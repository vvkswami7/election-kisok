---
title: Election Kiosk
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---
# Offline Edge-AI Election Kiosk

A fully self-contained election information system designed for remote areas with limited connectivity. This project uses **Gemini 1.5 Flash** for high-reasoning responses and **ChromaDB** for Retrieval-Augmented Generation (RAG), hosted on Hugging Face Spaces.

## 🚀 Deployment Status
- **Backend:** FastAPI
- **Database:** Firebase Realtime Database (Singapore Region)
- **Vector Store:** ChromaDB (Local)
- **AI Model:** Gemini 1.5 Flash via Google AI Studio

## 🛠️ Components

### 1. **backend.py** - FastAPI Server
The central hub for all requests. 
- **RAG-powered chat:** Uses semantic search to find election rules before answering.
- **Firebase Integration:** Syncs logs and updates to the cloud.
- **WebSocket support:** Provides real-time status updates to the dashboard.

### 2. **index.html** - Web Dashboard
The user-facing interface for monitoring the system health and interacting with the AI.

### 3. **Environment Configuration**
This Space requires the following variables to be set in **Settings > Variables and Secrets**:
- `GEMINI_API_KEY` (Secret)
- `FIREBASE_SERVICE_ACCOUNT_JSON` (Secret)
- `FIREBASE_DATABASE_URL` (Variable)
- `ELECTION_DATA_PATH` (Variable)

## 📖 Architecture Overview

1. **User Query:** Submitted via the frontend or Edge Simulator.
2. **Context Retrieval:** ChromaDB searches the `election_data` folder for relevant PDFs/text.
3. **Augmentation:** The retrieved text is added to the prompt to prevent AI hallucinations.
4. **Generation:** Gemini processes the context and query to provide a factual answer.
5. **Persistence:** The interaction is logged to Firebase.

## 🏗️ Local Development

If you want to run this locally on your Ubuntu machine:
```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn backend:app --reload