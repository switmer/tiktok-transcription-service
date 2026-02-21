import asyncio
import logging
import os

from fastapi import Depends, Header, HTTPException
from fastapi.security import APIKeyHeader

from ..core.errors import ApiError, AUTH_REQUIRED, AUTH_INVALID, SERVICE_UNAVAILABLE, INTERNAL_ERROR
from ..database import supabase

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def validate_api_key(api_key: str = Depends(api_key_header)) -> str:
    """Validate the API key against the Supabase api_keys table and return user_id."""
    logger.info(f"Validating API key: {api_key[:4]}... (first 4 chars only for security)")

    if not api_key:
        logger.warning("API key validation failed: Header X-API-Key is missing.")
        raise ApiError(401, AUTH_REQUIRED, "Missing API Key Header")

    if supabase is None:
        logger.error("Cannot validate API key: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "API key validation service unavailable")

    try:
        query = supabase.table('api_keys')
        query = query.select('id')
        query = query.eq('api_key', api_key)
        query = query.eq('is_active', True)
        query = query.limit(1)

        response = await asyncio.to_thread(query.execute)

        if response and response.data and len(response.data) > 0:
            if 'id' in response.data[0]:
                api_key_id = response.data[0]['id']
                logger.info(f"API key validated successfully, using key id as user_id: {api_key_id}")
                return str(api_key_id)

            logger.warning("API key validated but id missing in response data.")
            return "default_user"

        logger.warning("API key validation failed: Invalid or inactive API key.")
        raise ApiError(401, AUTH_INVALID, "Invalid or inactive API key")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating API key: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Error validating API key")


def verify_api_key(x_api_key: str = Header(None)):
    """Dependency for API key validation using environment variable fallback"""
    if x_api_key is None:
        logger.warning("API key validation failed: X-API-Key header missing.")
        raise ApiError(401, AUTH_REQUIRED, "X-API-Key header required")

    api_keys_env = (os.getenv("API_KEYS") or "").strip()
    if api_keys_env:
        valid_keys = [key.strip() for key in api_keys_env.split(",") if key.strip()]
        if x_api_key not in valid_keys:
            logger.warning("API key validation failed: Invalid API key provided.")
            raise ApiError(401, AUTH_INVALID, "Invalid API Key")
    else:
        raise ApiError(500, SERVICE_UNAVAILABLE, "API key validation not configured")

    return x_api_key
