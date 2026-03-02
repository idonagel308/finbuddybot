import logging
from google.cloud import firestore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firestore client (AsyncClient)
# ADC (Application Default Credentials) will be used automatically in Cloud Run
db = firestore.AsyncClient()

__all__ = ["db", "logger"]
