# # front door for the frontend
# # the frontend will use this file to ask questions and get answers from the RAG pipeline.
# # it will call the RetrievalEngine to get relevant legal snippets from the database,
# # and then pass those snippets to the LegalAssistant to generate a human-readable answer.

# # connects the retrieval engine and the legal assistant, orchestrating the entire RAG process for the API.

# # FastAPI automatically generates a testing page at http://localhost:8000/docs
# # where you can test your 100GB RAG without writing a single line of frontend code.

# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from engine import RetrievalEngine
# from assistant import LegalAssistant
# from typing import Optional

# app = FastAPI(title="Vessel Legal RAG API")

# # initialise core components
# engine = RetrievalEngine()
# assistant = LegalAssistant()

# class QueryRequest(BaseModel):
#     question: str
#     jurisdiction: Optional[str] = None
#     limit: int = 5

# @app.post("/ask")
# async def ask_legal_bot(request: QueryRequest):
#     try:
#         # 1. Search the 100GB LanceDB for relevant law snippets
#         search_results = engine.search(
#             query=request.question, 
#             limit=request.limit, 
#             jurisdiction=request.jurisdiction
#         )

#         if not search_results:
#             return {"answer": "I couldn't find any specific legal documents matching your query in the database.", "sources": []}

#         # 2. Extract the text chunks for the AI
#         context_chunks = [result["text"] for result in search_results]
#         sources = [{"metadata": result.get("metadata")} for result in search_results]

#         # 3. Get the professional answer from Gemini
#         answer = assistant.ask_legal_question(request.question, context_chunks)

#         return {
#             "answer": answer,
#             "sources": sources
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)