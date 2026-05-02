import os
import json
import logging
import re
import time
import datetime
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Deque, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psutil
from dotenv import load_dotenv

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

try:
    import google.genai as genai
except (ImportError, ModuleNotFoundError):
    genai = None

try:
    import chromadb
    from chromadb.utils import embedding_functions
except (ImportError, ModuleNotFoundError):
    chromadb = None
    embedding_functions = None

try:
    import firebase_admin
    from firebase_admin import credentials as firebase_credentials
    from firebase_admin import db as firebase_db
except (ImportError, ModuleNotFoundError):
    firebase_admin = None
    firebase_credentials = None
    firebase_db = None

try:
    from google.cloud import logging as cloud_logging
except (ImportError, ModuleNotFoundError):
    cloud_logging = None

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_COLLECTION_NAME = "election_kb"
GOOGLE_LOGGER_NAME = "election_kiosk"

def int_env(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(minimum, value)

RATE_LIMIT_WINDOW_SECONDS = int_env("RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1)
RATE_LIMIT_MAX_REQUESTS = int_env("RATE_LIMIT_MAX_REQUESTS", 20, minimum=0)

def csv_env(name: str, default: List[str]) -> List[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    return values or default

ALLOWED_ORIGINS = csv_env(
    "ALLOWED_ORIGINS",
    [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
    ],
)
ALLOW_CREDENTIALS = "*" not in ALLOWED_ORIGINS

def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

def validate_iso_timestamp(value: str) -> str:
    timestamp = value.strip()
    if not timestamp:
        raise ValueError("timestamp must not be empty")
    try:
        datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601 formatted") from exc
    return timestamp

# Global state
gemini_client: Optional[Any] = None
chroma_collection: Optional[Any] = None
firebase_initialized = False
cloud_logger: Optional[Any] = None
cloud_logging_logger: Optional[Any] = None
rate_limit_hits: Dict[str, Deque[float]] = {}

kiosk_stats: Dict[str, Any] = {
    "total_queries": 0,
    "total_lora_updates": 0,
    "startup_time": utc_now_iso(),
    "model_used": GEMINI_MODEL,
}

def log_cloud(payload: Dict[str, Any], severity: str = "INFO") -> None:
    global cloud_logger, cloud_logging_logger
    if cloud_logger is None or cloud_logging_logger is None:
        return
    try:
        cloud_logging_logger.log_struct(payload, severity=severity)
    except (RuntimeError, AttributeError, TypeError):
        pass

def chunk_text(text: str, size: int = 400, overlap: int = 80) -> List[str]:
    words = text.split()
    chunks: List[str] = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return chunks

def upsert_documents(
    collection: Any,
    documents: List[str],
    metadatas: List[Dict[str, str]],
    ids: List[str],
) -> None:
    if hasattr(collection, "upsert"):
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)
    else:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

def load_election_data(collection: Any) -> None:
    data_dir = os.getenv("ELECTION_DATA_PATH", "election_data")
    if not os.path.isdir(data_dir):
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
        except (OSError, IOError, FileNotFoundError, UnicodeDecodeError):
            continue

        if not text:
            continue

        for idx, chunk in enumerate(chunk_text(text, size=400, overlap=80)):
            documents.append(chunk)
            metadatas.append({"source": filename})
            ids.append(f"{filename}_{idx}")

    if documents:
        try:
            upsert_documents(collection, documents, metadatas, ids)
        except (RuntimeError, ValueError, TypeError) as exc:
            log_cloud(
                {
                    "message": "election_data_load_failed",
                    "error": str(exc)[:500],
                },
                severity="WARNING",
            )

def google_services_status() -> Dict[str, Any]:
    firebase_database_url = os.getenv("FIREBASE_DATABASE_URL", "")
    active_services = sum([
        gemini_client is not None,
        chroma_collection is not None,
        firebase_initialized,
        cloud_logger is not None,
    ])
    return {
        "gemini": {
            "available": gemini_client is not None,
            "configured": bool(os.getenv("GEMINI_API_KEY")),
            "sdk_installed": genai is not None,
            "model": GEMINI_MODEL,
            "description": "Google Generative AI for advanced question answering",
        },
        "firebase": {
            "available": firebase_initialized,
            "configured": bool(firebase_database_url),
            "connected": firebase_initialized,
            "sdk_installed": firebase_admin is not None,
            "database_url_configured": bool(firebase_database_url),
            "description": "Firebase Realtime Database for query logging",
        },
        "cloud_logging": {
            "available": cloud_logger is not None,
            "configured": cloud_logging is not None,
            "active": cloud_logger is not None,
            "sdk_installed": cloud_logging is not None,
            "logger_name": GOOGLE_LOGGER_NAME,
            "description": "Google Cloud Logging for centralized logging",
        },
        "chromadb": {
            "available": chroma_collection is not None,
            "configured": chromadb is not None,
            "sdk_installed": chromadb is not None,
            "description": "ChromaDB for RAG knowledge base storage",
        },
        "total_active": active_services,
        "timestamp": utc_now_iso(),
    }

def chroma_client_settings() -> Optional[Any]:
    if chromadb is None:
        return None
    try:
        return chromadb.config.Settings(anonymized_telemetry=False)
    except (RuntimeError, ValueError, AttributeError):
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cloud_logger, cloud_logging_logger, gemini_client, chroma_collection, firebase_initialized

    if cloud_logging is not None:
        try:
            cloud_logger = cloud_logging.Client()
            cloud_logging_logger = cloud_logger.logger(GOOGLE_LOGGER_NAME)
            log_cloud({"message": "startup", "service": "cloud_logging"}, severity="INFO")
        except (RuntimeError, ValueError, AttributeError):
            pass

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if gemini_api_key and genai is not None:
        try:
            gemini_client = genai.Client(api_key=gemini_api_key)
        except (RuntimeError, ValueError, TypeError):
            gemini_client = None

    if chromadb is not None and embedding_functions is not None:
        try:
            chroma_path = os.getenv("CHROMA_PATH", "./chroma_db")
            chroma_settings = chroma_client_settings()
            if chroma_settings is None:
                chroma_client = chromadb.PersistentClient(path=chroma_path)
            else:
                chroma_client = chromadb.PersistentClient(
                    path=chroma_path,
                    settings=chroma_settings,
                )
            embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
            chroma_collection = chroma_client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
                embedding_function=embedding_fn,
            )
            if chroma_collection.count() == 0:
                load_election_data(chroma_collection)
        except (RuntimeError, ValueError, AttributeError, OSError):
            chroma_collection = None

    firebase_url = os.getenv("FIREBASE_DATABASE_URL", "")
    if firebase_admin is not None and firebase_url:
        try:
            firebase_credential = None
            firebase_service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            firebase_credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if firebase_credentials is not None and firebase_service_account_json:
                firebase_credential = firebase_credentials.Certificate(
                    json.loads(firebase_service_account_json)
                )
            elif firebase_credentials is not None and firebase_credentials_path:
                firebase_credential = firebase_credentials.Certificate(firebase_credentials_path)

            if not firebase_admin._apps:
                if firebase_credential is not None:
                    firebase_admin.initialize_app(
                        firebase_credential,
                        {"databaseURL": firebase_url},
                    )
                else:
                    firebase_admin.initialize_app(options={"databaseURL": firebase_url})
            firebase_initialized = True
        except (RuntimeError, ValueError, json.JSONDecodeError, OSError):
            firebase_initialized = False

    yield

    try:
        log_cloud({"message": "shutdown", "service": "backend"}, severity="INFO")
    except (RuntimeError, AttributeError, TypeError):
        pass


app = FastAPI(title="Election Kiosk Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "localhost",
        "127.0.0.1",
        "*.localhost",
        "*.hf.space",
        "*.onrender.com",
        "*.render.com",
        "*",
    ],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
        "https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

def enforce_rate_limit(request: Request) -> None:
    if RATE_LIMIT_MAX_REQUESTS <= 0:
        return

    client_host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    recent_hits = rate_limit_hits.setdefault(client_host, deque())
    while recent_hits and recent_hits[0] < window_start:
        recent_hits.popleft()

    if len(recent_hits) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before asking again.",
        )

    recent_hits.append(now)

def check_rate_limit(client_ip: str) -> bool:
    """
    Check if a client IP is within the rate limit without raising an exception.
    Returns True if the request is allowed, False if rate limited.
    Does not record a new hit; only checks the current state.
    """
    if RATE_LIMIT_MAX_REQUESTS <= 0:
        return True

    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    recent_hits = rate_limit_hits.get(client_ip, deque())
    
    # Clean old hits outside the window
    while recent_hits and recent_hits[0] < window_start:
        recent_hits.popleft()
    
    return len(recent_hits) < RATE_LIMIT_MAX_REQUESTS

def retrieve_context(query: str, n: int = 4) -> str:
    if chroma_collection is None:
        return ""
    try:
        results = chroma_collection.query(
            query_texts=[query],
            n_results=n,
            include=["documents", "metadatas"],
        )
    except RuntimeError:
        return ""

    documents = results.get("documents", [[]])[0] if results.get("documents") else []
    metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []

    formatted: List[str] = []
    for idx, doc in enumerate(documents):
        source = "unknown"
        if idx < len(metadatas) and isinstance(metadatas[idx], dict):
            source = metadatas[idx].get("source", "unknown")
        formatted.append(f"[Source: {source}]\n{doc.strip()}")

    return "\n\n".join(formatted)

def extract_context_sources(context: str) -> List[str]:
    sources: List[str] = []
    for source in re.findall(r"\[Source: ([^\]]+)\]", context):
        if source not in sources:
            sources.append(source)
    return sources

def local_context_answer(context: str) -> str:
    if not context:
        return "I don't have that in my database."

    context_without_sources = re.sub(r"\[Source: [^\]]+\]\s*", "", context).strip()
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", context_without_sources)
        if sentence.strip()
    ]
    answer = " ".join(sentences[:3]).strip()
    return answer if answer else "I don't have that in my database."

def query_gemini(prompt: str) -> Optional[str]:
    if gemini_client is None:
        return None
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        answer = response.text if hasattr(response, "text") else str(response)
        answer = answer.strip()
        return answer or None
    except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
        error_text = str(exc)
        log_cloud(
            {
                "message": "gemini_query_failed",
                "error": error_text[:500],
            },
            severity="WARNING",
        )
        return None

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

class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

class QueryPayload(StrictPayload):
    question: str = Field(..., min_length=1, max_length=500)
    source: Literal["text", "voice", "web"] = "text"

class ChatPayload(StrictPayload):
    query: str = Field(..., min_length=1, max_length=500)

class LoraUpdatePayload(StrictPayload):
    update_type: str = Field(..., min_length=1, max_length=60, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(..., min_length=1, max_length=500)
    timestamp: str = Field(..., min_length=1, max_length=80)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        from datetime import datetime
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ", 
            "%Y-%m-%dT%H:%M:%S+00:00",
        ):
            try:
                datetime.strptime(v, fmt)
                return v
            except ValueError:
                continue
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            raise ValueError(
                f"timestamp must be a valid ISO 8601 datetime, got: {v!r}"
            )

class MeshUpdatePayload(StrictPayload):
    status: str = Field(..., min_length=1, max_length=120)
    rssi: Optional[int] = None
    messages_queued: Optional[int] = None
    last_sync: str = Field(..., min_length=1, max_length=80)
    new_elections: Optional[List[str]] = None

    @field_validator("last_sync")
    @classmethod
    def last_sync_must_be_iso8601(cls, value: str) -> str:
        return validate_iso_timestamp(value)

class QueryResponse(BaseModel):
    question: str
    answer: str
    latency_seconds: float
    model: str
    rag_chunks_used: int
    grounded: bool
    source: str
    context_used: List[str] = Field(default_factory=list)

class ChatResponse(QueryResponse):
    response: str

class LoraEntry(BaseModel):
    update_type: str
    message: str
    timestamp: str

class LoraUpdateResponse(BaseModel):
    status: str
    entry: LoraEntry

class StatusResponse(BaseModel):
    total_queries: int
    total_lora_updates: int
    startup_time: str
    model_used: str
    rag_chunks_loaded: int
    gemini_available: bool
    firebase_connected: bool
    cloud_logging_active: bool
    google_services: Dict[str, Dict[str, Any]]
    memory_used_mb: int
    memory_percent: float
    cpu_percent: float

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, bool]

class GoogleServicesResponse(BaseModel):
    services: Dict[str, Dict[str, Any]]

def answer_question(question: str, source: str) -> Dict[str, Any]:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question must not be empty")

    start_time = time.perf_counter()
    context = retrieve_context(question)
    prompt = build_rag_prompt(question, context)
    answer = query_gemini(prompt)
    model_used = kiosk_stats["model_used"]
    if answer is None:
        answer = local_context_answer(context)
        model_used = "local-rag-fallback"
    latency_seconds = round(time.perf_counter() - start_time, 4)
    rag_chunks_used = context.count("[Source:") if context else 0
    context_sources = extract_context_sources(context)

    log_cloud(
        {
            "message": "voter_query",
            "question": question,
            "source": source,
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
                    "source": source,
                    "model": model_used,
                    "rag_chunks_used": rag_chunks_used,
                    "timestamp": utc_now_iso(),
                }
            )
        except RuntimeError:
            pass

    kiosk_stats["total_queries"] += 1

    return {
        "question": question,
        "answer": answer,
        "latency_seconds": latency_seconds,
        "model": model_used,
        "rag_chunks_used": rag_chunks_used,
        "grounded": bool(context_sources),
        "source": source,
        "context_used": context_sources,
    }

@app.post("/api/query", response_model=QueryResponse)
async def api_query(payload: QueryPayload, request: Request):
    enforce_rate_limit(request)
    return answer_question(payload.question, payload.source)

@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(payload: ChatPayload, request: Request):
    enforce_rate_limit(request)
    result = answer_question(payload.query, "edge")
    return {
        **result,
        "response": result["answer"],
    }

@app.post("/api/lora-update", response_model=LoraUpdateResponse)
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
        except RuntimeError:
            pass

    kiosk_stats["total_lora_updates"] += 1

    return {"status": "received", "entry": entry}

@app.post("/api/mesh-update", response_model=LoraUpdateResponse)
async def api_mesh_update(payload: MeshUpdatePayload):
    details = [
        f"status={payload.status}",
        f"last_sync={payload.last_sync}",
    ]
    if payload.rssi is not None:
        details.append(f"rssi={payload.rssi}")
    if payload.messages_queued is not None:
        details.append(f"messages_queued={payload.messages_queued}")
    if payload.new_elections:
        details.append(f"new_elections={', '.join(payload.new_elections)}")

    lora_payload = LoraUpdatePayload(
        update_type="mesh_update",
        message="; ".join(details),
        timestamp=payload.last_sync,
    )
    return await api_lora_update(lora_payload)

@app.get("/api/status", response_model=StatusResponse)
async def api_status():
    rag_chunks_loaded = 0
    try:
        rag_chunks_loaded = chroma_collection.count() if chroma_collection is not None else 0
    except RuntimeError:
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
        "google_services": google_services_status(),
        "memory_used_mb": memory.used // (1024 * 1024),
        "memory_percent": memory.percent,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "healthy",
        "timestamp": utc_now_iso(),
        "services": {
            "gemini": gemini_client is not None,
            "chromadb": chroma_collection is not None,
            "firebase": firebase_initialized,
            "cloud_logging": cloud_logger is not None,
        },
    }

@app.get("/api/google-services", response_model=GoogleServicesResponse)
async def api_google_services():
    return {"services": google_services_status()}

@app.api_route("/", methods=["GET", "HEAD"])
async def root() -> FileResponse:
    response = FileResponse("index.html")
    response.headers["Cache-Control"] = "no-store"
    return response
