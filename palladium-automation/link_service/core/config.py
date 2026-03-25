import os
from dotenv import load_dotenv

# Load environment variables from the root .env file
load_dotenv()

LINK_SERVICE_URL = os.getenv("LINK_SERVICE_URL", "http://localhost:8000")
