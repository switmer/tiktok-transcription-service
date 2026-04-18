import os
from typing import List, Dict, Any
import logging
from .spotify_manager import SpotifyAPIManager

logger = logging.getLogger(__name__)


def create_spotify_api_manager() -> SpotifyAPIManager:
    """
    Create and configure a SpotifyAPIManager with adapters based on environment variables.

    Environment variables:
    - RAPIDAPI_SPOTIFY_KEYS: Comma-separated keys for Spotify adapters (optional)
    - RAPIDAPI_KEY: Fallback to primary RapidAPI key
    """
    manager = SpotifyAPIManager()

    primary_key = os.getenv("RAPIDAPI_KEY", "").strip()
    spotify_keys_env = os.getenv("RAPIDAPI_SPOTIFY_KEYS", "").strip()

    # Get Spotify-specific keys or fall back to primary
    if spotify_keys_env:
        keys = [k.strip() for k in spotify_keys_env.split(",") if k.strip()]
    elif primary_key:
        keys = [primary_key]
    else:
        keys = []

    if not keys:
        logger.warning("No Spotify API keys configured")
        return manager

    # Add primary adapter (spotify23) — the only one with working audio URLs
    try:
        manager.add_spotify_adapter(keys[0])
        logger.info("Added primary Spotify adapter (spotify23)")
    except Exception as e:
        logger.error(f"Failed to add Spotify adapter: {e}")

    # Add fallback adapters with same key (metadata fallback)
    if len(keys) > 1:
        try:
            manager.add_spotify_v2_adapter(keys[1] if len(keys) > 1 else keys[0])
            logger.info("Added Spotify V2 adapter (real-time scraper)")
        except Exception as e:
            logger.error(f"Failed to add Spotify V2 adapter: {e}")

    if len(keys) > 2:
        try:
            manager.add_spotify_v3_adapter(keys[2] if len(keys) > 2 else keys[0])
            logger.info("Added Spotify V3 adapter (web-api3)")
        except Exception as e:
            logger.error(f"Failed to add Spotify V3 adapter: {e}")

    logger.info(f"Spotify API Manager initialized with {len(manager.adapters)} adapters")
    return manager


def get_spotify_config_info() -> Dict[str, Any]:
    """Get information about Spotify adapter configuration."""
    primary_key = os.getenv("RAPIDAPI_KEY", "").strip()
    spotify_keys = os.getenv("RAPIDAPI_SPOTIFY_KEYS", "").strip()

    keys = []
    if spotify_keys:
        keys = [k.strip() for k in spotify_keys.split(",") if k.strip()]
    elif primary_key:
        keys = [primary_key]

    return {
        "spotify_keys_configured": len(keys),
        "configuration_method": (
            "SPOTIFY_SPECIFIC" if spotify_keys else
            "PRIMARY_KEY" if primary_key else
            "NONE"
        ),
        "environment_variables": {
            "RAPIDAPI_SPOTIFY_KEYS": "SET" if spotify_keys else "NOT_SET",
            "RAPIDAPI_KEY": "SET" if primary_key else "NOT_SET",
        }
    }
