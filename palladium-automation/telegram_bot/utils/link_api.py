import requests
from link_service.core.config import LINK_SERVICE_URL
import logging

logger = logging.getLogger(__name__)

def check_api_health() -> bool:
    """
    Checks if the Link Service API is reachable and healthy.
    Returns True if healthy, False otherwise.
    """
    try:
        response = requests.get(f"{LINK_SERVICE_URL}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "ok":
                return True
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Link API health check failed: {e}")
        return False

def add_links(user_id: str, links: list) -> bool:
    """
    Sends links to the Link Service API for storage.
    """
    try:
        payload = {
            "user_id": str(user_id),
            "links": links
        }
        response = requests.post(f"{LINK_SERVICE_URL}/links/add", json=payload, timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Link API add_links failed: {e}")
        return False

def get_active_links(user_id: str) -> list:
    """
    Retrieves active links for a user from the Link Service API.
    """
    try:
        response = requests.get(f"{LINK_SERVICE_URL}/links/active/{user_id}", timeout=5)
        if response.status_code == 200:
            return response.json().get("links", [])
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Link API get_active_links failed: {e}")
        return []

def get_next_link(user_id: str) -> dict:
    """
    Retrieves the next available active link for a user.
    Returns dict like {"url": "http...", "message": ...}
    """
    try:
        response = requests.get(f"{LINK_SERVICE_URL}/links/next/{user_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return {}
    except requests.exceptions.RequestException as e:
        logger.error(f"Link API get_next_link failed: {e}")
        return {}