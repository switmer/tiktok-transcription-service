import logging
from typing import Optional, Dict, Any
from adapters.spotify_config import create_spotify_api_manager
from adapters.spotify_manager import SpotifyAPIManager

logger = logging.getLogger(__name__)


class SpotifyService:
    """Service class for Spotify episode information retrieval with automatic API failover."""

    def __init__(self):
        self.api_manager: Optional[SpotifyAPIManager] = None
        self._initialize_manager()

    def _initialize_manager(self):
        try:
            self.api_manager = create_spotify_api_manager()
            if not self.api_manager.adapters:
                logger.warning("SpotifyService initialized without any API adapters")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify API manager: {e}")
            self.api_manager = None

    def get_episode_info(self, episode_url: str) -> Dict[str, Any]:
        """
        Get episode information from Spotify URL with automatic failover.

        Returns:
            Dictionary containing episode information or error details
        """
        if not self.api_manager:
            return {
                "success": False,
                "error": "Spotify API manager not initialized",
                "data": None
            }

        if not self.api_manager.adapters:
            return {
                "success": False,
                "error": "No Spotify API adapters configured",
                "data": None
            }

        try:
            response = self.api_manager.get_video_info(episode_url)

            return {
                "success": response.success,
                "data": response.data,
                "error": response.error,
                "status_code": response.status_code,
                "rate_limit_info": {
                    "limit": response.rate_limit_info.limit if response.rate_limit_info else None,
                    "remaining": response.rate_limit_info.remaining if response.rate_limit_info else None,
                    "reset_time": response.rate_limit_info.reset_time.isoformat() if response.rate_limit_info else None
                } if response.rate_limit_info else None
            }

        except Exception as e:
            logger.error(f"Unexpected error in SpotifyService.get_episode_info: {e}")
            return {
                "success": False,
                "error": f"Service error: {str(e)}",
                "data": None
            }

    def get_adapters_status(self) -> Dict[str, Any]:
        if not self.api_manager:
            return {
                "error": "Spotify API manager not initialized",
                "total_adapters": 0,
                "available_adapters": 0,
                "adapters": []
            }
        return self.api_manager.get_status()

    def refresh_manager(self):
        self._initialize_manager()


# Global instance
spotify_service = SpotifyService()
