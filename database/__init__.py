import logging
from google.cloud import firestore

# Configure logging
logger = logging.getLogger(__name__)

import os

# Initialize Firestore client (AsyncClient)
project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "finbuddy-etl")
database_id = os.getenv("FIRESTORE_DATABASE", "default")

# If the database is the literal "default", omit the parameter to let the library
# use its canonical discovery for the primary instance (avoiding "(default)" 404s).
if database_id == "default":
    db = firestore.AsyncClient(project=project_id)
else:
    db = firestore.AsyncClient(project=project_id, database=database_id)

__all__ = ["db", "logger"]
