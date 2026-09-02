import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up paths so we can import engine and assistant
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists("/app"):
    project_root = "/app"
else:
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))

# Ensure services/processor/src is in sys.path (needed by engine.py)
sys.path.append(os.path.join(project_root, 'services', 'processor', 'src'))
sys.path.append(current_dir)

from assistant import LegalAssistant, GeneralAssistant
from engine import RetrievalEngine
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Initialize FastMCP server
mcp = FastMCP("Vessel Legal RAG MCP Server")

# Instantiate RetrievalEngines and Assistants once at module load
engine = RetrievalEngine()
assistant = LegalAssistant()

general_engine = RetrievalEngine(table_name="general_chunks")
general_assistant = GeneralAssistant()

# Import the general ingestor function
try:
    from services.processor.src.general_ingestor import ingest_general_pdf
except ImportError:
    from general_ingestor import ingest_general_pdf  # type: ignore

# Custom Starlette Middleware for Bearer Token Auth
class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # We only check authorization for paths starting with /mcp
        if request.url.path.startswith("/mcp"):
            token = os.getenv("MCP_AUTH_TOKEN")
            if token:
                auth_header = request.headers.get("Authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    return JSONResponse(
                        {"detail": "Unauthorized: Missing Bearer Token"}, 
                        status_code=401
                    )
                
                req_token = auth_header.split(" ")[1]
                if req_token != token:
                    return JSONResponse(
                        {"detail": "Unauthorized: Invalid Bearer Token"}, 
                        status_code=401
                    )

        response = await call_next(request)
        return response

# Expose search_legal_rag tool
@mcp.tool()
def search_legal_rag(query: str, jurisdiction: str | None = None) -> str:
    """
    Search the legal RAG pipeline and generate a contextual legal answer using GEMINI.
    
    Args:
        query: The search/legal question query.
        jurisdiction: Optional jurisdiction filter (e.g. State name or central/state authorities).
    """
    try:
        # 1. Search the LanceDB database
        search_results = engine.search(
            search_query=query,
            limit=5,
            jurisdiction=jurisdiction
        )
        
        if not search_results:
            return "I couldn't find any specific legal documents matching your query in the database."
            
        # 2. Extract the text chunks for the Legal Assistant
        context_chunks = [result["text"] for result in search_results]
        
        # 3. Get professional answer from Legal Assistant / Gemini
        answer = assistant.ask_legal_question(query, context_chunks) or ""
        
        # 4. Extract citations / sources
        sources = []
        for result in search_results:
            title = result.get("title") or result.get("act_name") or "Unknown Source"
            source_url = result.get("source_url")
            authority = result.get("authority")
            state = result.get("state")
            
            citation = f"- **{title}**"
            extra_info = []
            if authority:
                extra_info.append(f"Authority: {authority}")
            if state:
                extra_info.append(f"State: {state}")
            if source_url:
                extra_info.append(f"URL: {source_url}")
                
            if extra_info:
                citation += f" ({', '.join(extra_info)})"
            
            if citation not in sources:
                sources.append(citation)
                
        if sources:
            sources_text = "\n".join(sources)
            answer = f"{answer}\n\n### Sources & Citations:\n{sources_text}"
            
        return answer
        
    except Exception as e:
        return f"An error occurred while executing the legal RAG search: {e!s}"

# Expose search_general tool
@mcp.tool()
def search_general(query: str, user_id: str) -> str:
    """
    Search the general-purpose RAG pipeline and generate a contextual answer using GEMINI.
    The search is scoped and restricted only to the specified user's uploaded files.
    
    Args:
        query: The search/question query.
        user_id: The ID of the user whose files should be searched.
    """
    try:
        # 1. Search general_chunks with user_id filter
        search_results = general_engine.search(
            search_query=query,
            limit=5,
            user_id=user_id
        )
        
        if not search_results:
            return f"I couldn't find any documents indexed for user '{user_id}' that match your query."
            
        # 2. Extract text chunks
        context_chunks = [result["text"] for result in search_results]
        
        # 3. Get answer from GeneralAssistant / Gemini
        answer = general_assistant.ask_general_question(query, context_chunks) or ""
        
        # 4. Extract unique sources / document titles
        sources = []
        for result in search_results:
            title = result.get("title") or "Unknown Document"
            citation = f"- **{title}**"
            if citation not in sources:
                sources.append(citation)
                
        if sources:
            sources_text = "\n".join(sources)
            answer = f"{answer}\n\n### Sources:\n{sources_text}"
            
        return answer
    except Exception as e:
        return f"An error occurred while executing the general search: {e!s}"

# Expose ingest_pdf tool
@mcp.tool()
async def ingest_pdf(file_base64: str, filename: str, user_id: str) -> str:
    """
    Upload and index a general-purpose PDF file. The file is scoped to the specified user.
    
    Args:
        file_base64: The base64-encoded string representation of the PDF file's bytes.
        filename: The original filename of the PDF.
        user_id: The ID of the user uploading the file.
    """
    import base64
    import tempfile
    
    temp_file_path = None
    try:
        # Decode base64 string
        file_bytes = base64.b64decode(file_base64)
        
        # Write to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file.write(file_bytes)
            temp_file_path = temp_file.name
            
        # Ingest general PDF
        success = await ingest_general_pdf(temp_file_path, user_id, filename)
        
        if success:
            return f"Successfully processed and indexed '{filename}' for user '{user_id}'."
        else:
            return f"Failed to index '{filename}' for user '{user_id}'."
    except Exception as e:
        return f"An error occurred while ingesting the PDF: {e!s}"
    finally:
        # Always clean up the temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

if __name__ == "__main__":
    # Create middleware list
    middlewares = [Middleware(BearerAuthMiddleware)]
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8003,
        middleware=middlewares
    )
