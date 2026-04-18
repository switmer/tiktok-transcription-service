from typing import List, Optional, Dict, Any
import logging
from .base import TikTokAPIAdapter, APIResponse
from .rapidapi_spotify_adapter import RapidAPISpotifyAdapter
from .rapidapi_spotify_v2_adapter import RapidAPISpotifyV2Adapter
from .rapidapi_spotify_v3_adapter import RapidAPISpotifyV3Adapter

logger = logging.getLogger(__name__)


class SpotifyAPIManager:
    """Manager for Spotify API adapters with failover support."""

    def __init__(self):
        self.adapters: List[TikTokAPIAdapter] = []
        self.current_adapter_index = 0

    def add_spotify_adapter(self, api_key: str, host: str = "spotify23.p.rapidapi.com"):
        adapter = RapidAPISpotifyAdapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added Spotify adapter: {adapter.name}")

    def add_spotify_v2_adapter(self, api_key: str, host: str = "real-time-spotify-data-scraper.p.rapidapi.com"):
        adapter = RapidAPISpotifyV2Adapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added Spotify V2 adapter: {adapter.name}")

    def add_spotify_v3_adapter(self, api_key: str, host: str = "spotify-web-api3.p.rapidapi.com"):
        adapter = RapidAPISpotifyV3Adapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added Spotify V3 adapter: {adapter.name}")

    def get_available_adapters(self) -> List[TikTokAPIAdapter]:
        return [adapter for adapter in self.adapters if adapter.is_available()]

    def get_next_adapter(self) -> Optional[TikTokAPIAdapter]:
        available = self.get_available_adapters()
        if not available:
            return None
        if self.current_adapter_index >= len(available):
            self.current_adapter_index = 0
        adapter = available[self.current_adapter_index]
        logger.info(f"Using Spotify adapter: {adapter.name}")
        return adapter

    def failover_to_next_adapter(self):
        available = self.get_available_adapters()
        if len(available) <= 1:
            logger.warning("No other Spotify adapters available for failover")
            return
        self.current_adapter_index = (self.current_adapter_index + 1) % len(available)
        logger.info(f"Failed over to Spotify adapter: {available[self.current_adapter_index].name}")

    def get_video_info(self, video_url: str, max_retries: int = 3) -> APIResponse:
        if not self.adapters:
            return APIResponse(
                success=False, data=None,
                error="No Spotify adapters configured",
                rate_limit_info=None, status_code=None, headers=None
            )

        attempts = 0
        adapters_tried = set()

        while attempts < max_retries and len(adapters_tried) < len(self.adapters):
            adapter = self.get_next_adapter()

            if not adapter or adapter.name in adapters_tried:
                if len(adapters_tried) >= len(self.adapters):
                    break
                self.failover_to_next_adapter()
                continue

            adapters_tried.add(adapter.name)
            attempts += 1

            logger.info(f"Spotify attempt {attempts}: Using {adapter.name} for: {video_url}")

            try:
                response = adapter.get_video_info(video_url)

                if response.success:
                    logger.info(f"Successfully got episode info using {adapter.name}")
                    return response

                if response.status_code == 429 or (response.rate_limit_info and response.rate_limit_info.is_exhausted):
                    logger.warning(f"Rate limit hit for {adapter.name}, trying next")
                    self.failover_to_next_adapter()
                    continue

                if response.status_code and response.status_code >= 500:
                    logger.warning(f"Server error from {adapter.name}, trying next")
                    adapter.disable_temporarily(30)
                    self.failover_to_next_adapter()
                    continue

                if response.status_code and 400 <= response.status_code < 500 and response.status_code != 429:
                    logger.error(f"Client error from {adapter.name}: {response.error}")
                    return response

                logger.warning(f"Error from {adapter.name}: {response.error}, trying next")
                self.failover_to_next_adapter()

            except Exception as e:
                logger.error(f"Unexpected error with {adapter.name}: {str(e)}")
                adapter.disable_temporarily(15)
                self.failover_to_next_adapter()

        return APIResponse(
            success=False, data=None,
            error=f"All Spotify adapters failed after {attempts} attempts",
            rate_limit_info=None, status_code=None, headers=None
        )

    def get_status(self) -> Dict[str, Any]:
        status = {
            "total_adapters": len(self.adapters),
            "available_adapters": len(self.get_available_adapters()),
            "current_adapter": None,
            "adapters": []
        }
        current = self.get_next_adapter()
        if current:
            status["current_adapter"] = current.name
        for adapter in self.adapters:
            adapter_status = {
                "name": adapter.name,
                "available": adapter.is_available(),
                "rate_limit_info": None
            }
            if adapter.rate_limit_info:
                adapter_status["rate_limit_info"] = {
                    "limit": adapter.rate_limit_info.limit,
                    "remaining": adapter.rate_limit_info.remaining,
                    "reset_time": adapter.rate_limit_info.reset_time.isoformat(),
                    "is_exhausted": adapter.rate_limit_info.is_exhausted
                }
            status["adapters"].append(adapter_status)
        return status
