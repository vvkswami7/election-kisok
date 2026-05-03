---
title: Election Kiosk
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# Offline Edge-AI Election Kiosk

Election Kiosk is a FastAPI-based voter information assistant for low-connectivity election help desks. It combines local retrieval from `election_data`, ChromaDB semantic search, Gemini 1.5 Flash generation, Firebase Realtime Database logging, and a browser dashboard designed for kiosk use.

## Project Highlights

- RAG answers grounded in local election text files.
- Gemini 1.5 Flash integration with a local RAG fallback when quota is exhausted.
- Firebase Realtime Database persistence for voter queries and mesh updates.
- Google Cloud Logging integration for structured backend events.
- `/api/google-services` and `/api/status` summaries for Gemini, Firebase, Cloud Logging, ChromaDB, active service counts, and timestamps.
- Accessible web UI with semantic landmarks, live regions, keyboard form submission, and reduced-motion support.
- Security headers, stricter request validation, CORS hardening, API cache control, and basic request rate limiting.
- Compatibility endpoints for the edge simulator (`/api/chat`) and LoRa mesh simulator (`/api/mesh-update`).

## Architecture

1. A voter asks a question through the dashboard or edge simulator.
2. ChromaDB retrieves relevant chunks from `election_data`.
3. Gemini receives a context-grounded prompt and returns a concise answer.
4. If Gemini is unavailable or quota-limited, the backend returns a local context answer.
5. Query metadata and LoRa/mesh updates are stored in Firebase when Firebase is configured.
6. Health, status, Google-service readiness, and structured logs expose operational state for deployment checks.

## Services

- Backend: FastAPI + Uvicorn
- AI: Gemini 1.5 Flash through Google AI Studio
- Vector store: ChromaDB with `all-MiniLM-L6-v2`
- Persistence: Firebase Realtime Database
- Observability: Google Cloud Logging
- Frontend: Static `index.html` served by FastAPI

## API Endpoints

- `POST /api/query` - primary kiosk question endpoint with grounded RAG metadata.
- `POST /api/chat` - edge simulator compatibility endpoint.
- `POST /api/lora-update` - stores mesh/radio updates.
- `POST /api/mesh-update` - LoRa simulator compatibility endpoint.
- `GET /api/status` - runtime counters, resource usage, RAG status, and Google-service readiness.
- `GET /api/google-services` - Gemini, Firebase, Cloud Logging, and ChromaDB readiness with descriptions, active count, and timestamp.
- `GET /api/health` - lightweight health probe for deployment checks.

## Environment Variables

Use `.env.example` as a safe template for local setup.

Required:

```text
GEMINI_API_KEY=your_google_ai_studio_key
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.region.firebasedatabase.app
FIREBASE_SERVICE_ACCOUNT_JSON=
GOOGLE_APPLICATION_CREDENTIALS=/secure/path/to/service-account.json
ELECTION_DATA_PATH=election_data
CHROMA_PATH=./chroma_db
```

Recommended:

```text
GEMINI_MODEL=gemini-1.5-flash
EMBEDDING_MODEL=all-MiniLM-L6-v2
ANONYMIZED_TELEMETRY=False
ALLOWED_ORIGINS=https://your-deployed-domain.example
ALLOWED_HOSTS=your-deployed-domain.example,localhost,127.0.0.1
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_MAX_REQUESTS=20
```

Do not commit `.env` files or Firebase service account JSON files. They are ignored by `.gitignore` and should be set only in the hosting platform's secret manager.

## Deployment Commands

For a native Python deployment:

```bash
pip install -r requirements.txt && python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

```bash
uvicorn backend:app --host 0.0.0.0 --port $PORT
```

For Docker-based hosting, the included `Dockerfile` runs as a non-root user and honors the platform-provided `PORT` value, defaulting to `7860` for Hugging Face Spaces.

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn backend:app --reload --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000`.

## Tests

```bash
python3 -m pytest
```

The tests cover health/status APIs, Google-service readiness reporting, security headers, request validation, local Gemini fallback behavior, source grounding, timestamp validation, and simulator compatibility endpoints.
