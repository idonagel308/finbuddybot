import logging
from google.cloud import firestore

# Configure logging
logger = logging.getLogger(__name__)

import os

# Initialize Firestore client (AsyncClient)
# ADC (Application Default Credentials) will be used automatically in Cloud Run
# Explicitly setting project ID and database to ensure connection sanity
project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "finbuddy-etl")
# In many newer projects, the default database is literally named "default" not "(default)"
database_id = os.getenv("FIRESTORE_DATABASE", "default")

db = firestore.AsyncClient(
    project=project_id,
    database=database_id
)

__all__ = ["db", "logger"]
