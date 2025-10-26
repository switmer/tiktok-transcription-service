from typing import List, Optional, Dict, Any
import logging
from .base import TikTokAPIAdapter, APIResponse
from .rapidapi_adapter import RapidAPIAdapter
from .rapidapi_v2_adapter import RapidAPIV2Adapter
from .rapidapi_api6_adapter import RapidAPIAPI6Adapter
from .rapidapi_downloadvideo_adapter import RapidAPIDownloadVideoAdapter
from .tikwm_adapter import TikWMAdapter

logger = logging.getLogger(__name__)

class TikTokAPIManager:
    def __init__(self):
        self.adapters: List[TikTokAPIAdapter] = []
        self.current_adapter_index = 0
        self._failed_attempts = {}  # Track failed attempts per adapter
    
    def add_rapidapi_adapter(self, api_key: str, host: str = "tiktok-scraper7.p.rapidapi.com"):
        adapter = RapidAPIAdapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added RapidAPI adapter: {adapter.name}")
    
    def add_rapidapi_v2_adapter(self, api_key: str, host: str = "tiktok-scraper2.p.rapidapi.com"):
        adapter = RapidAPIV2Adapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added RapidAPI v2 adapter: {adapter.name}")
    
    def add_rapidapi_api6_adapter(self, api_key: str, host: str = "tiktok-api6.p.rapidapi.com"):
        adapter = RapidAPIAPI6Adapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added RapidAPI API6 adapter: {adapter.name}")
    
    def add_rapidapi_downloadvideo_adapter(self, api_key: str, host: str = "tiktok-download-video1.p.rapidapi.com"):
        adapter = RapidAPIDownloadVideoAdapter(api_key, host)
        self.adapters.append(adapter)
        logger.info(f"Added RapidAPI DownloadVideo adapter: {adapter.name}")
    
    def add_tikwm_adapter(self):
        adapter = TikWMAdapter()
        self.adapters.append(adapter)
        logger.info(f"Added TikWM adapter: {adapter.name}")
    
    def add_custom_adapter(self, adapter: TikTokAPIAdapter):
        self.adapters.append(adapter)
        logger.info(f"Added custom adapter: {adapter.name}")
    
    def get_available_adapters(self) -> List[TikTokAPIAdapter]:
        return [adapter for adapter in self.adapters if adapter.is_available()]
    
    def get_next_adapter(self) -> Optional[TikTokAPIAdapter]:
        available_adapters = self.get_available_adapters()
        
        if not available_adapters:
            logger.error("No available adapters")
            return None
        
        # Reset to first available adapter if current index is out of bounds
        if self.current_adapter_index >= len(available_adapters):
            self.current_adapter_index = 0
        
        adapter = available_adapters[self.current_adapter_index]
        logger.info(f"Using adapter: {adapter.name}")
        return adapter
    
    def failover_to_next_adapter(self):
        available_adapters = self.get_available_adapters()
        
        if len(available_adapters) <= 1:
            logger.warning("No other adapters available for failover")
            return
        
        self.current_adapter_index = (self.current_adapter_index + 1) % len(available_adapters)
        next_adapter = available_adapters[self.current_adapter_index]
        logger.info(f"Failed over to adapter: {next_adapter.name}")
    
    def get_video_info(self, video_url: str, max_retries: int = 3) -> APIResponse:
        if not self.adapters:
            return APIResponse(
                success=False,
                data=None,
                error="No adapters configured",
                rate_limit_info=None,
                status_code=None,
                headers=None
            )
        
        attempts = 0
        adapters_tried = set()
        
        while attempts < max_retries and len(adapters_tried) < len(self.adapters):
            adapter = self.get_next_adapter()
            
            if not adapter or adapter.name in adapters_tried:
                # If we've tried all adapters or no adapter available, break
                if len(adapters_tried) >= len(self.adapters):
                    break
                self.failover_to_next_adapter()
                continue
            
            adapters_tried.add(adapter.name)
            attempts += 1
            
            logger.info(f"Attempt {attempts}: Using {adapter.name} for video: {video_url}")
            
            try:
                response = adapter.get_video_info(video_url)
                
                if response.success:
                    logger.info(f"Successfully got video info using {adapter.name}")
                    return response
                
                # Handle different failure scenarios
                if response.status_code == 429 or (response.rate_limit_info and response.rate_limit_info.is_exhausted):
                    logger.warning(f"Rate limit hit for {adapter.name}, trying next adapter")
                    self.failover_to_next_adapter()
                    continue
                
                if response.status_code and response.status_code >= 500:
                    logger.warning(f"Server error from {adapter.name}, trying next adapter")
                    adapter.disable_temporarily(30)  # Disable for 30 minutes
                    self.failover_to_next_adapter()
                    continue
                
                # For 4xx errors (except 429), don't retry with other adapters
                if response.status_code and 400 <= response.status_code < 500 and response.status_code != 429:
                    logger.error(f"Client error from {adapter.name}: {response.error}")
                    return response
                
                # For other errors, try next adapter
                logger.warning(f"Error from {adapter.name}: {response.error}, trying next adapter")
                self.failover_to_next_adapter()
                
            except Exception as e:
                logger.error(f"Unexpected error with {adapter.name}: {str(e)}")
                adapter.disable_temporarily(15)  # Disable for 15 minutes
                self.failover_to_next_adapter()
        
        # If we've exhausted all adapters/retries
        return APIResponse(
            success=False,
            data=None,
            error=f"All adapters failed after {attempts} attempts",
            rate_limit_info=None,
            status_code=None,
            headers=None
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