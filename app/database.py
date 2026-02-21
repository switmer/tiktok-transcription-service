import logging
import os
from typing import Any

try:
    from supabase import Client, ClientOptions, create_client
except Exception as exc:
    create_client = None
    Client = Any
    ClientOptions = None
    logging.getLogger(__name__).error(
        "Supabase client import failed; database operations disabled: %s",
        exc,
    )

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase: Client = None

DEFAULT_POSTGREST_TIMEOUT_SECONDS = 10.0


def _load_postgrest_timeout() -> float:
    raw_timeout = (
        os.environ.get("SUPABASE_POSTGREST_TIMEOUT_SECONDS")
        or os.getenv("SUPABASE_POSTGREST_TIMEOUT_SECONDS")
        or os.environ.get("SUPABASE_TIMEOUT_SECONDS")
        or os.getenv("SUPABASE_TIMEOUT_SECONDS")
    )
    if not raw_timeout:
        return DEFAULT_POSTGREST_TIMEOUT_SECONDS

    try:
        timeout_value = float(raw_timeout)
        if timeout_value <= 0:
            raise ValueError("timeout must be positive")
        return timeout_value
    except ValueError:
        logger.warning(
            "Invalid SUPABASE_POSTGREST_TIMEOUT_SECONDS=%s; using %.1fs",
            raw_timeout,
            DEFAULT_POSTGREST_TIMEOUT_SECONDS,
        )
        return DEFAULT_POSTGREST_TIMEOUT_SECONDS


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

        options = None
        if ClientOptions is not None:
            timeout_seconds = _load_postgrest_timeout()
            options = ClientOptions(postgrest_client_timeout=timeout_seconds)
            logger.info("Supabase PostgREST timeout set to %.1fs", timeout_seconds)

        supabase = create_client(supabase_url, supabase_key, options=options)
        logger.info("Supabase client initialized successfully")
        return supabase
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        return None

# Initialize the client when this module is imported
init_supabase() 
