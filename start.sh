#!/bin/bash

###############################################################################
# Start Script for Offline Edge-AI Election Kiosk
#
# This script orchestrates the startup of all components:
# 1. Backend (FastAPI) on port 8000
# 2. LoRa Simulator (sends mesh updates every 30s)
# 3. Edge Simulator (user interface)
#
# Kill all processes on exit (Ctrl+C)
###############################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to print colored output
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Function to cleanup on exit
cleanup() {
    echo ""
    log_warn "Shutting down all services..."
    
    # Kill all background jobs
    jobs -p | xargs kill 2>/dev/null || true
    
    log_info "All services stopped"
    exit 0
}

# Set trap to cleanup on Ctrl+C
trap cleanup SIGINT SIGTERM

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    log_success "Virtual environment activated"
else
    log_error "Virtual environment not found! Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# ===================================================================
# VALIDATION
# ===================================================================

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   OFFLINE EDGE-AI ELECTION KIOSK - Startup Script          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check required files
log_info "Checking required files..."

required_files=("backend.py" "lora_simulator.py" "edge_simulator.py" "index.html")

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        log_success "$file found"
    else
        log_error "$file not found!"
        exit 1
    fi
done

# Check Python is available
if ! command -v python3 &> /dev/null; then
    log_error "Python3 is not installed!"
    exit 1
fi

log_success "Python3 is available"

# Check for required Python packages
log_info "Checking Python dependencies..."

packages=("fastapi" "uvicorn" "chromadb" "google.genai" "firebase_admin" "psutil" "requests")

for package in "${packages[@]}"; do
    if python3 -c "import ${package}" 2>/dev/null; then
        log_success "$package installed"
    else
        log_warn "$package is not installed"
        log_info "Install with: pip install $package"
    fi
done

echo ""

# ===================================================================
# STARTUP SEQUENCE
# ===================================================================

log_info "Starting up all services..."
echo ""

# Start Backend
log_info "Starting Backend (FastAPI)..."
python3 -m uvicorn backend:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
log_success "Backend started (PID: $BACKEND_PID)"

# Wait for backend to be ready
sleep 3

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    log_error "Backend failed to start!"
    exit 1
fi

# Check if backend is accepting connections
log_info "Waiting for backend to accept connections..."
for i in {1..10}; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        log_success "Backend is ready"
        break
    fi
    if [ $i -eq 10 ]; then
        log_error "Backend did not become ready"
        exit 1
    fi
    sleep 1
done

echo ""

# Start LoRa Simulator in background
log_info "Starting LoRa Simulator..."
python3 lora_simulator.py &
LORA_PID=$!
log_success "LoRa Simulator started (PID: $LORA_PID)"

echo ""

# Start Edge Simulator (foreground, user interaction)
log_info "Starting Edge Simulator (User Interface)..."
log_info "Press Ctrl+C to stop all services"
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
echo ""

python3 edge_simulator.py

# If edge_simulator exits normally, shutdown
cleanup
