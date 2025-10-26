import logging
from typing import Optional, Dict, Any
from adapters.config import create_tiktok_api_manager
from adapters.manager import TikTokAPIManager

logger = logging.getLogger(__name__)

class TikTokService:
    """Service class for TikTok video information retrieval with automatic API failover."""
    
    def __init__(self):
        self.api_manager: Optional[TikTokAPIManager] = None
        self._initialize_manager()
    
    def _initialize_manager(self):
        """Initialize the API manager with configured adapters."""
        try:
            self.api_manager = create_tiktok_api_manager()
            if not self.api_manager.adapters:
                logger.warning("TikTokService initialized without any API adapters")
        except Exception as e:
            logger.error(f"Failed to initialize TikTok API manager: {e}")
            self.api_manager = None
    
    def get_video_info(self, video_url: str) -> Dict[str, Any]:
        """
        Get video information from TikTok URL with automatic failover between APIs.
        
        Args:
            video_url: TikTok video URL
            
        Returns:
            Dictionary containing video information or error details
        """
        if not self.api_manager:
            return {
                "success": False,
                "error": "TikTok API manager not initialized",
                "data": None
            }
        
        if not self.api_manager.adapters:
            return {
                "success": False,
                "error": "No TikTok API adapters configured",
                "data": None
            }
        
        try:
            response = self.api_manager.get_video_info(video_url)
            
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
            logger.error(f"Unexpected error in TikTokService.get_video_info: {e}")
            return {
                "success": False,
                "error": f"Service error: {str(e)}",
                "data": None
            }
    
    def get_adapters_status(self) -> Dict[str, Any]:
        """Get status of all configured adapters."""
        if not self.api_manager:
            return {
                "error": "TikTok API manager not initialized",
                "total_adapters": 0,
                "available_adapters": 0,
                "adapters": []
            }
        
        return self.api_manager.get_status()
    
    def refresh_manager(self):
        """Reinitialize the API manager (useful for config changes)."""
        self._initialize_manager()

# Global instance
tiktok_service = TikTokService()