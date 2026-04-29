# Offline Edge-AI Election Kiosk

A fully self-contained, offline election information system for remote areas with limited connectivity. Powered by local LLMs (Ollama) and ChromaDB for Retrieval-Augmented Generation (RAG).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ELECTION KIOSK SYSTEM                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐       ┌──────────────────┐           │
│  │  Edge Simulator  │       │  LoRa Simulator  │           │
│  │  (User Input)    │       │  (Mesh Network)  │           │
│  └────────┬─────────┘       └────────┬─────────┘           │
│           │ /api/chat                │ /api/mesh-update     │
│           └────────────┬─────────────┘                       │
│                        ↓                                      │
│          ┌──────────────────────────┐                       │
│          │    FastAPI Backend       │                       │
│          │  (backend.py - :8000)    │                       │
│          └────────────┬─────────────┘                       │
│                       │                                      │
│          ┌────────────┴─────────────┐                       │
│          ↓                          ↓                        │
│    ┌──────────────┐          ┌─────────────┐               │
│    │  ChromaDB    │          │   Ollama    │               │
│    │  (RAG Store) │          │  (Llama 3)  │               │
│    └──────────────┘          └─────────────┘               │
│                                                               │
│  ┌──────────────────┐                                       │
│  │   index.html     │ ← WebSocket /ws/status               │
│  │  (Dashboard)     │                                       │
│  └──────────────────┘                                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. **backend.py** - FastAPI Server
- **Port:** 8000
- **Role:** Central hub for all requests and communication
- **Key Features:**
  - RAG-powered chat endpoint `/api/chat`
  - WebSocket endpoint `/ws/status` for real-time updates
  - Mesh network update endpoint `/api/mesh-update`
  - Health check endpoint `/api/health`
  - Integrates ChromaDB for document retrieval
  - Connects to Ollama for LLM inference

**Key Endpoints:**
- `POST /api/chat` - Submit election questions
- `WS /ws/status` - Real-time system status updates
- `POST /api/mesh-update` - Receive offline network updates
- `GET /api/health` - Health check

### 2. **lora_simulator.py** - Mesh Network Simulator
- **Role:** Simulates a LoRa radio receiver
- **Behavior:**
  - Sends dummy mesh network updates every 30 seconds
  - Simulates varying network states (sync OK, in progress, complete)
  - Posts to `/api/mesh-update` endpoint
  - Demonstrates offline data sync capability

**Use Case:** In production, replace with actual LoRa hardware that sends radio packets over the mesh network

### 3. **edge_simulator.py** - Hardware Input Simulator
- **Role:** Simulates the physical kiosk interface
- **Behavior:**
  - Terminal-based user interface (can be replaced with actual voice/touchscreen)
  - Takes user questions as input
  - Sends to backend `/api/chat` endpoint
  - Displays AI responses with context sources
  - Colored terminal output for readability

**Use Case:** In production, replace with actual hardware input (voice transcription, touchscreen, etc.)

### 4. **index.html** - Web Dashboard
- **Role:** Real-time monitoring and chat interface
- **Features:**
  - Real-time status display (backend, ChromaDB, WebSocket)
  - Network update feed
  - Chat interface for questions
  - Tailwind CSS styling
  - Responsive design
  - WebSocket connection to backend

**Access:** Open in browser at `http://localhost:8000/` or serve separately

### 5. **start.sh** - Boot Script
- **Role:** Orchestrates startup of all services
- **Features:**
  - Validates all required files
  - Checks Python dependencies
  - Starts backend server
  - Starts LoRa simulator in background
  - Launches edge simulator (foreground)
  - Graceful shutdown on Ctrl+C

## Getting Started

### Prerequisites

```bash
# Python 3.8+ with dependencies
pip install -r requirements.txt

# Ollama with Llama 3 model
ollama pull llama3

# Embedded election data and ChromaDB
# (Should already exist from rag_loader.py)
```

### Quick Start

```bash
# Make script executable (if not already)
chmod +x start.sh

# Run the entire system
./start.sh
```

This will:
1. Start the FastAPI backend on `localhost:8000`
2. Start the LoRa simulator (background)
3. Launch the edge simulator (terminal UI)

### Manual Startup (Advanced)

```bash
# Terminal 1: Backend
python backend.py

# Terminal 2: LoRa Simulator
python lora_simulator.py

# Terminal 3: Edge Simulator
python edge_simulator.py

# Browser: Dashboard
# Open http://localhost:8000/index.html
```

## Usage

### Terminal Interface (edge_simulator.py)
```
Your Question: How do I register to vote?

Processing...

AI Response:
To register to vote in [your location], you must be...

Context sources (2 documents):
  [1] Voter registration requirements and procedures...
  [2] State-specific registration deadlines and methods...
```

### Web Dashboard (index.html)
- Shows real-time system health
- Displays incoming mesh network updates
- Chat interface for questions
- Response with context sources

### Commands in Edge Simulator
- `quit` - Exit the interface
- `help` - Show example questions
- Type questions and press Enter to send

## Data Flow

### Chat Request Flow
```
User Input
    ↓
edge_simulator.py → POST /api/chat
    ↓
backend.py
    ├→ ChromaDB: Search for top 2 relevant documents
    ├→ Construct RAG prompt with context
    ├→ Ollama: Query Llama 3 with prompt
    ├→ Broadcast to WebSocket clients
    └→ Return response
    ↓
Display AI response + context sources
```

### Mesh Network Update Flow
```
lora_simulator.py → POST /api/mesh-update every 30s
    ↓
backend.py
    ├→ Log update
    ├→ Broadcast to WebSocket clients
    └→ Return confirmation
    ↓
index.html receives update and displays
```

## Key Design Decisions

### 1. RAG (Retrieval-Augmented Generation)
- **Why:** Ensures responses are grounded in election data, reducing hallucinations
- **How:** ChromaDB searches for top 2 documents; included in LLM prompt
- **Result:** Factual, verifiable responses

### 2. Local LLM (Ollama + Llama 3)
- **Why:** 100% offline, no internet required, no API costs
- **How:** Uses all-MiniLM-L6-v2 embeddings for semantic search
- **Trade-off:** Slower than cloud APIs but truly offline

### 3. WebSocket for Real-Time Updates
- **Why:** Dashboard stays synchronized with backend events
- **Clients:** Browser dashboard, can extend to mobile apps
- **Broadcast:** All connected clients receive system updates

### 4. Mesh Network Simulation
- **Why:** Demonstrates how actual LoRa hardware would integrate
- **Extensible:** Replace lora_simulator.py with actual radio hardware logic
- **Pattern:** POST updates every 30 seconds (configurable)

## Configuration

### Environment Variables
None required (uses defaults). To customize:

```bash
# In backend.py
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000
CHROMA_PATH = "./chroma_db"

# In lora_simulator.py
UPDATE_INTERVAL_SECONDS = 30
BACKEND_URL = "http://localhost:8000"

# In edge_simulator.py
BACKEND_URL = "http://localhost:8000"
```

### Tuning Parameters

**backend.py - RAG Query:**
```python
# Change number of retrieved documents
search_results = collection.query(
    query_texts=[user_query],
    n_results=2  # ← Increase/decrease here
)
```

**lora_simulator.py - Update Frequency:**
```python
UPDATE_INTERVAL_SECONDS = 30  # ← Change here
```

## Testing Checklist

- [ ] Backend starts and connects to ChromaDB
- [ ] LoRa simulator sends updates every 30s
- [ ] Edge simulator accepts input and gets responses
- [ ] Dashboard shows real-time updates
- [ ] WebSocket connections are maintained
- [ ] Chat responses include context sources
- [ ] All services stop gracefully on Ctrl+C

## Deployment Notes

### For Remote Kiosks
1. **Install** on Linux device (Raspberry Pi 4+, EdgeAI device, etc.)
2. **Configure** for local network only (no internet required)
3. **Run** `./start.sh` at boot
4. **Monitor** via dashboard in browser on local network

### For Production
- Add authentication to endpoints
- Implement rate limiting
- Add monitoring/logging to disk
- Use persistent WebSocket reconnection
- Add request validation
- Consider containerization (Docker)

## Troubleshooting

### Backend won't start
```bash
# Check if port 8000 is in use
lsof -i :8000

# Verify ChromaDB exists
ls -la ./chroma_db

# Check Ollama is running
ollama serve
```

### Ollama not responding
```bash
# Pull the model if missing
ollama pull llama3

# Start Ollama service
ollama serve
```

### Edge simulator can't connect
```bash
# Verify backend is healthy
curl http://localhost:8000/api/health

# Check network connectivity
ping localhost
```

### WebSocket connection fails
```bash
# Check browser console for errors
# Verify backend is running with WebSocket support
# Try reloading the page
```

## Extension Ideas

1. **Voice Input** - Replace terminal input with speech-to-text
2. **SMS Support** - Add SMS endpoint for SMS-based queries
3. **Touchscreen UI** - Build native mobile/touchscreen interface
4. **Multi-Language** - Support multiple languages with LLM
5. **Offline Persistence** - Store Q&A locally for offline access
6. **Analytics** - Track common questions and response effectiveness
7. **Admin Interface** - Update election data without restart
8. **LoRa Hardware** - Replace simulator with actual radio module

## License

[Your License Here]

## Support

For issues or questions, refer to the inline code comments which explain each component in detail.
