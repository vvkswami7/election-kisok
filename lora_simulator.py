"""
LoRa Mesh Network Simulator
Simulates periodic offline radio network syncs by sending dummy updates
to the backend every 30 seconds
"""

import time
import logging
import os
import requests
from datetime import datetime, timezone
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - LoRa Simulator - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
MESH_UPDATE_ENDPOINT = f"{BACKEND_URL}/api/mesh-update"
UPDATE_INTERVAL_SECONDS = 30  # Send update every 30 seconds

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

# Simulated LoRa network states
LORA_STATES = [
    {
        "status": "Network Sync OK",
        "rssi": -75,  # Signal strength
        "messages_queued": 0,
        "last_sync": utc_now_iso()
    },
    {
        "status": "Sync in progress",
        "rssi": -82,
        "messages_queued": 3,
        "last_sync": utc_now_iso()
    },
    {
        "status": "Network Sync Complete",
        "rssi": -70,
        "messages_queued": 0,
        "new_elections": ["Local Referendum 2026", "District Vote 2026"],
        "last_sync": utc_now_iso()
    }
]

# Counter for cycling through states
STATE_COUNTER = 0


def generate_mesh_update() -> Dict[str, Any]:
    """
    Generate a simulated LoRa mesh network update payload
    
    In a real system, this would contain actual radio network data:
    - Signal strength (RSSI)
    - Messages queued for transmission
    - New data synced from other nodes
    - Network topology info
    
    Returns:
        Dict with mesh update data
    """
    global STATE_COUNTER
    
    # Cycle through different network states
    update = LORA_STATES[STATE_COUNTER % len(LORA_STATES)].copy()
    STATE_COUNTER += 1
    
    # Update timestamp to current time
    update["last_sync"] = utc_now_iso()
    
    return update


def send_mesh_update(update: Dict[str, Any]) -> bool:
    """
    Send the mesh update to the backend
    
    Args:
        update: The mesh update payload
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Sending mesh update: {update['status']}")
        
        response = requests.post(
            MESH_UPDATE_ENDPOINT,
            json=update,
            timeout=5
        )
        
        if response.status_code == 200:
            logger.info(f"✓ Mesh update sent successfully")
            return True
        else:
            logger.warning(f"✗ Backend returned status {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        logger.error("✗ Cannot connect to backend. Is it running on localhost:8000?")
        return False
    except requests.exceptions.Timeout:
        logger.error("✗ Request to backend timed out")
        return False
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error(f"✗ Error sending mesh update: {exc}")
        return False


def main() -> None:
    """
    Main loop: Generate and send mesh updates every UPDATE_INTERVAL_SECONDS
    """
    logger.info("="*60)
    logger.info("LoRa Mesh Network Simulator Started")
    logger.info(f"Backend URL: {BACKEND_URL}")
    logger.info(f"Update interval: {UPDATE_INTERVAL_SECONDS} seconds")
    logger.info("Press Ctrl+C to stop")
    logger.info("="*60)
    
    try:
        while True:
            # Generate a new mesh update
            mesh_update = generate_mesh_update()
            
            # Send to backend
            send_mesh_update(mesh_update)
            
            # Wait before next update
            logger.info(f"Waiting {UPDATE_INTERVAL_SECONDS}s until next mesh sync...")
            time.sleep(UPDATE_INTERVAL_SECONDS)
            
    except KeyboardInterrupt:
        logger.info("\nLoRa simulator shutting down...")
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error(f"Unexpected error in main loop: {exc}", exc_info=True)


if __name__ == "__main__":
    main()
