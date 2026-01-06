import logging
import os
from typing import Any

try:
    from supabase.client import create_client, Client
except Exception as exc:
    create_client = None
    Client = Any
    logging.getLogger(__name__).error(
        "Supabase client import failed; database operations disabled: %s",
        exc,
    )

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase: Client = None

def init_supabase():
    global supabase
    try:
        if create_client is None:
            logger.error("Supabase client library unavailable; skipping initialization")
            return None
        # Get credentials from environment
        supabase_url = os.environ.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
        
        if not supabase_url or not supabase_key:
            logger.error("Supabase credentials not found in environment variables")
            return None
        
        logger.info(f"Initializing Supabase client with URL: {supabase_url[:20]}... (truncated)")
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully")
        return supabase
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        return None

# Initialize the client when this module is imported
init_supabase() 
