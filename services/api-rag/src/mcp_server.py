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

from assistant import LegalAssistant
from engine import RetrievalEngine
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Initialize FastMCP server
mcp = FastMCP("Vessel Legal RAG MCP Server")

# Instantiate RetrievalEngine and LegalAssistant once at module load
engine = RetrievalEngine()
assistant = LegalAssistant()

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

if __name__ == "__main__":
    # Create middleware list
    middlewares = [Middleware(BearerAuthMiddleware)]
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8003,
        middleware=middlewares
    )
