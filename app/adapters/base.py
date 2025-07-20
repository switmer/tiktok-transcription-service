from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

@dataclass
class RateLimitInfo:
    limit: int
    remaining: int
    reset_time: datetime
    is_exhausted: bool = False

@dataclass
class APIResponse:
    success: bool
    data: Optional[Dict[str, Any]]
    error: Optional[str]
    rate_limit_info: Optional[RateLimitInfo]
    status_code: Optional[int]
    headers: Optional[Dict[str, str]]

class TikTokAPIAdapter(ABC):
    def __init__(self, name: str, api_key: str, base_url: str):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.rate_limit_info: Optional[RateLimitInfo] = None
        self._is_disabled = False
        self._disable_until: Optional[datetime] = None
        
    @abstractmethod
    def get_video_info(self, video_url: str) -> APIResponse:
        pass
    
    @abstractmethod
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        pass
    
    def is_available(self) -> bool:
        if self._is_disabled and self._disable_until:
            if datetime.now() < self._disable_until:
                return False
            else:
                self._is_disabled = False
                self._disable_until = None
                logger.info(f"Re-enabling {self.name} adapter")
        
        if self.rate_limit_info and self.rate_limit_info.is_exhausted:
            if datetime.now() < self.rate_limit_info.reset_time:
                return False
            else:
                self.rate_limit_info.is_exhausted = False
                logger.info(f"Rate limit reset for {self.name}")
        
        return not self._is_disabled
    
    def disable_temporarily(self, duration_minutes: int = 60):
        self._is_disabled = True
        self._disable_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.warning(f"Disabling {self.name} adapter for {duration_minutes} minutes")
    
    def update_rate_limit_info(self, headers: Dict[str, str]):
        rate_limit_info = self.parse_rate_limit_headers(headers)
        if rate_limit_info:
            self.rate_limit_info = rate_limit_info
            if rate_limit_info.remaining <= 5:  # Consider exhausted when <= 5 requests remaining
                rate_limit_info.is_exhausted = True
                logger.warning(f"Rate limit nearly exhausted for {self.name}: {rate_limit_info.remaining} remaining")