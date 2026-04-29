"""
Edge Hardware Input Simulator
Simulates the physical kiosk interface by accepting terminal input
and sending it to the backend chat endpoint
"""

import json
import logging
import requests
import sys
from datetime import datetime
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Edge Simulator - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = "http://localhost:8000"
CHAT_ENDPOINT = f"{BACKEND_URL}/api/chat"
HEALTH_ENDPOINT = f"{BACKEND_URL}/api/health"

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_banner():
    """Print welcome banner"""
    banner = f"""
{Colors.BOLD}{Colors.CYAN}
╔════════════════════════════════════════════════════════════╗
║      OFFLINE EDGE-AI ELECTION KIOSK - User Interface       ║
║           (Edge Hardware Input Simulator)                   ║
╚════════════════════════════════════════════════════════════╝
{Colors.END}

{Colors.YELLOW}System Status:{Colors.END} Initializing...
{Colors.YELLOW}Backend URL:{Colors.END} {BACKEND_URL}

Type your election questions below. Type 'quit' to exit.
Type 'help' for example questions.

{Colors.BOLD}{'='*60}{Colors.END}
"""
    print(banner)


def print_help():
    """Print example questions"""
    examples = [
        "When is the next election?",
        "How do I register to vote?",
        "What are the voting requirements?",
        "Where is my polling location?",
        "How do I vote by mail?"
    ]
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}Example Questions:{Colors.END}")
    for i, example in enumerate(examples, 1):
        print(f"  {Colors.BLUE}→ {example}{Colors.END}")
    print()


def check_backend_health() -> bool:
    """
    Check if backend is running and healthy
    
    Returns:
        True if backend is healthy, False otherwise
    """
    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=3)
        if response.status_code == 200:
            return True
    except Exception:
        pass
    return False


def send_query_to_backend(user_query: str) -> Dict[str, Any]:
    """
    Send user query to backend chat endpoint
    
    Args:
        user_query: The user's question
    
    Returns:
        Response dict from backend
    """
    try:
        logger.info(f"Sending query to backend: {user_query}")
        
        response = requests.post(
            CHAT_ENDPOINT,
            json={"query": user_query},
            timeout=120  # LLM inference can take time
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"Backend error: {response.status_code}",
                "response": "Unable to get response from backend"
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "error": "Connection failed",
            "response": f"Cannot connect to backend at {BACKEND_URL}"
        }
    except requests.exceptions.Timeout:
        return {
            "error": "Timeout",
            "response": "Backend took too long to respond. Please try again."
        }
    except Exception as e:
        return {
            "error": str(e),
            "response": "An unexpected error occurred"
        }


def display_response(response: Dict[str, Any]):
    """
    Display AI response in a formatted way
    
    Args:
        response: Response dict from backend
    """
    print(f"\n{Colors.BOLD}{Colors.GREEN}AI Response:{Colors.END}")
    print(f"{Colors.GREEN}{response.get('response', 'No response')}{Colors.END}")
    
    # Display context if available
    context_used = response.get("context_used", [])
    if context_used:
        print(f"\n{Colors.YELLOW}Context sources ({len(context_used)} documents):{Colors.END}")
        for i, context in enumerate(context_used, 1):
            # Truncate long context for display
            truncated = (context[:100] + "...") if len(context) > 100 else context
            print(f"  {Colors.BLUE}[{i}] {truncated}{Colors.END}")
    
    if response.get("error"):
        print(f"\n{Colors.RED}Error: {response['error']}{Colors.END}")
    
    print()


def main():
    """Main interaction loop"""
    print_banner()
    
    # Check backend health
    if not check_backend_health():
        print(f"{Colors.RED}✗ Backend is not running!{Colors.END}")
        print(f"{Colors.YELLOW}Please start the backend with: python backend.py{Colors.END}\n")
        sys.exit(1)
    
    print(f"{Colors.GREEN}✓ Backend is running and healthy{Colors.END}\n")
    
    try:
        while True:
            # Get user input
            try:
                user_input = input(f"{Colors.BOLD}{Colors.CYAN}Your Question:{Colors.END} ").strip()
            except EOFError:
                # Handle pipe/redirection input
                user_input = sys.stdin.readline().strip()
                if not user_input:
                    break
            
            # Handle special commands
            if user_input.lower() == "quit":
                print(f"\n{Colors.YELLOW}Thank you for using the Election Kiosk. Goodbye!{Colors.END}\n")
                break
            
            if user_input.lower() == "help":
                print_help()
                continue
            
            if not user_input:
                print(f"{Colors.YELLOW}Please enter a question.{Colors.END}\n")
                continue
            
            # Send to backend and display response
            print(f"\n{Colors.YELLOW}Processing...{Colors.END}")
            response = send_query_to_backend(user_input)
            display_response(response)
            
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Interrupted by user. Shutting down...{Colors.END}\n")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"{Colors.RED}An unexpected error occurred: {e}{Colors.END}\n")


if __name__ == "__main__":
    main()
