import os
import time
import datetime
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psutil
from dotenv import load_dotenv

try:
    import google.genai as genai
except Exception:
    genai = None

try:
    import chromadb
    from chromadb.utils import embedding_functions
except Exception:
    chromadb = None
    embedding_functions = None

try:
    import firebase_admin
    from firebase_admin import db as firebase_db
except Exception:
    firebase_admin = None
    firebase_db = None

try:
    from google.cloud import logging as cloud_logging
except Exception:
    cloud_logging = None

load_dotenv()

app = FastAPI(title="Election Kiosk Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers for all responses
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Global state
gemini_client: Optional[Any] = None
chroma_collection: Optional[Any] = None
firebase_initialized = False
cloud_logger: Optional[Any] = None
cloud_logging_logger: Optional[Any] = None

kiosk_stats: Dict[str, Any] = {
    "total_queries": 0,
    "total_lora_updates": 0,
    "startup_time": datetime.datetime.utcnow().isoformat() + "Z",
    "model_used": "gemini-2.0-flash",
}


def log_cloud(payload: Dict[str, Any], severity: str = "INFO"):
    global cloud_logger, cloud_logging_logger
    if cloud_logger is None or cloud_logging_logger is None:
        return
    try:
        cloud_logging_logger.log_struct(payload, severity=severity)
    except Exception:
        pass


def chunk_text(text: str, size: int = 400, overlap: int = 80) -> List[str]:
    words = text.split()
    chunks: List[str] = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return chunks


def load_election_data(collection: Any) -> None:
    data_dir = os.getenv("ELECTION_DATA_PATH", "election_data")
    if not os.path.isdir(data_dir):
        print(f"[warning] election data directory not found: {data_dir}")
        return

    documents: List[str] = []
    metadatas: List[Dict[str, str]] = []
    ids: List[str] = []

    for filename in sorted(os.listdir(data_dir)):
        if not filename.endswith(".txt"):
            continue
        path = os.path.join(data_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read().strip()
        except Exception:
            continue

        if not text:
            continue

        for idx, chunk in enumerate(chunk_text(text, size=400, overlap=80)):
            documents.append(chunk)
            metadatas.append({"source": filename})
            ids.append(f"{filename}_{idx}")

    if documents:
        try:
            collection.add(documents=documents, metadatas=metadatas, ids=ids)
            print(f"[info] loaded {len(documents)} election text chunks into ChromaDB")
        except Exception as exc:
            print(f"[warning] failed to load election data into ChromaDB: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cloud_logger, cloud_logging_logger, gemini_client, chroma_collection, firebase_initialized

    # Initialize Google Cloud Logging
    if cloud_logging is not None:
        try:
            cloud_logger = cloud_logging.Client()
            cloud_logging_logger = cloud_logger.logger("election_kiosk")
            log_cloud({"message": "startup", "service": "cloud_logging"}, severity="INFO")
        except Exception as exc:
            print(f"[warning] google cloud logging unavailable: {exc}")
    else:
        print("[warning] google-cloud-logging package not installed")

    # Initialize Gemini client
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if gemini_api_key and genai is not None:
        try:
            gemini_client = genai.Client(api_key=gemini_api_key)
        except Exception as exc:
            print(f"[warning] failed to initialize Gemini client: {exc}")
            gemini_client = None
    else:
        if not gemini_api_key:
            print("[warning] GEMINI_API_KEY not set; Gemini will run in fallback mode")
        else:
            print("[warning] google-genai package not installed; Gemini disabled")

    # Initialize ChromaDB
    if chromadb is not None and embedding_functions is not None:
        try:
            chroma_path = os.getenv("CHROMA_PATH", "./chroma_db")
            chroma_client = chromadb.PersistentClient(path=chroma_path)
            embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            chroma_collection = chroma_client.get_or_create_collection(
                name="election_kb",
                metadata={"hnsw:space": "cosine"},
                embedding_function=embedding_fn,
            )
            if chroma_collection.count() == 0:
                load_election_data(chroma_collection)
        except Exception as exc:
            print(f"[warning] failed to initialize ChromaDB: {exc}")
            chroma_collection = None
    else:
        print("[warning] chromadb or sentence-transformers not installed; RAG disabled")

    # Initialize Firebase Admin
    if firebase_admin is not None:
        try:
            firebase_url = os.getenv(
                "FIREBASE_DATABASE_URL",
                "https://election-kiosk-default-rtdb.firebaseio.com",
            )
            if not firebase_admin._apps:
                firebase_admin.initialize_app(options={"databaseURL": firebase_url})
            firebase_initialized = True
        except Exception as exc:
            print(f"[warning] firebase admin initialization failed: {exc}")
            firebase_initialized = False
    else:
        print("[warning] firebase-admin package not installed; realtime sync disabled")

    yield

    try:
        log_cloud({"message": "shutdown", "service": "backend"}, severity="INFO")
    except Exception:
        pass


def retrieve_context(query: str, n: int = 4) -> str:
    if chroma_collection is None:
        return ""

    try:
        results = chroma_collection.query(
            query_texts=[query],
            n_results=n,
            include=["documents", "metadatas"],
        )
    except Exception:
        return ""

    documents = []
    metadatas = []
    if isinstance(results, dict):
        documents = results.get("documents", [[]])[0] if results.get("documents") else []
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []

    formatted: List[str] = []
    for idx, doc in enumerate(documents):
        source = "unknown"
        if idx < len(metadatas) and isinstance(metadatas[idx], dict):
            source = metadatas[idx].get("source", "unknown")
        formatted.append(f"[Source: {source}]\n{doc.strip()}")

    return "\n\n".join(formatted)


def query_gemini(prompt: str) -> str:
    if gemini_client is None:
        return "Gemini unavailable. I cannot answer your question at this time."

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        if isinstance(response, dict):
            return str(response.get("content", response.get("output", ""))).strip()
        return str(response).strip()
    except Exception as exc:
        return f"Gemini query failed: {exc}"


def build_rag_prompt(question: str, context: str) -> str:
    return (
        "You are an offline election kiosk assistant. Answer ONLY from the provided context. "
        "If the answer is not contained in the context, say 'I don't have that in my database.' "
        "Keep the answer under 4 sentences.\n\n"
        "CONTEXT:\n"
        f"{context}\n\n"
        "QUESTION:\n"
        f"{question}\n\n"
        "ANSWER:"
    )


class QueryPayload(BaseModel):
    question: str
    source: str = "text"


class LoraUpdatePayload(BaseModel):
    update_type: str
    message: str
    timestamp: str


@app.post("/api/query")
async def api_query(payload: QueryPayload):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question must not be empty")

    start_time = time.perf_counter()
    context = retrieve_context(question)
    prompt = build_rag_prompt(question, context)
    answer = query_gemini(prompt)
    latency_seconds = round(time.perf_counter() - start_time, 4)
    rag_chunks_used = context.count("[Source:") if context else 0

    log_cloud(
        {
            "message": "voter_query",
            "question": question,
            "source": payload.source,
            "latency_seconds": latency_seconds,
            "rag_chunks": rag_chunks_used,
        },
        severity="INFO",
    )

    if firebase_initialized and firebase_db is not None:
        try:
            firebase_db.reference("/kiosk/last_query").push(
                {
                    "question": question,
                    "answer": answer,
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                }
            )
        except Exception:
            pass

    kiosk_stats["total_queries"] += 1

    return {
        "question": question,
        "answer": answer,
        "latency_seconds": latency_seconds,
        "model": kiosk_stats["model_used"],
        "rag_chunks_used": rag_chunks_used,
        "grounded": True,
        "source": payload.source,
    }


@app.post("/api/lora-update")
async def api_lora_update(payload: LoraUpdatePayload):
    entry = {
        "update_type": payload.update_type,
        "message": payload.message,
        "timestamp": payload.timestamp,
    }

    severity = "WARNING" if payload.update_type == "alert" else "INFO"
    log_cloud({"message": "lora_update", **entry}, severity=severity)

    if firebase_initialized and firebase_db is not None:
        try:
            firebase_db.reference("/kiosk/lora_updates").push(entry)
        except Exception:
            pass

    kiosk_stats["total_lora_updates"] += 1

    return {"status": "received", "entry": entry}


@app.get("/api/status")
async def api_status():
    rag_chunks_loaded = 0
    try:
        rag_chunks_loaded = chroma_collection.count() if chroma_collection is not None else 0
    except Exception:
        rag_chunks_loaded = 0

    memory = psutil.virtual_memory()

    return {
        "total_queries": kiosk_stats["total_queries"],
        "total_lora_updates": kiosk_stats["total_lora_updates"],
        "startup_time": kiosk_stats["startup_time"],
        "model_used": kiosk_stats["model_used"],
        "rag_chunks_loaded": rag_chunks_loaded,
        "gemini_available": gemini_client is not None,
        "firebase_connected": firebase_initialized,
        "cloud_logging_active": cloud_logger is not None,
        "memory_used_mb": memory.used // (1024 * 1024),
        "memory_percent": memory.percent,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "services": {
            "gemini": gemini_client is not None,
            "chromadb": chroma_collection is not None,
            "firebase": firebase_initialized,
            "cloud_logging": cloud_logger is not None,
        },
    }


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return FileResponse("index.html")




if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend:app", host="0.0.0.0", port=port, reload=False)
