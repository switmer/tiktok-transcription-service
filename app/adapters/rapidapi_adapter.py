import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)

class RapidAPIAdapter(TikTokAPIAdapter):
    def __init__(self, api_key: str, host: str = "tiktok-scraper7.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-{host}",
            api_key=api_key,
            base_url=f"https://{host}"
        )
        self.host = host
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host
        }
    
    def get_video_info(self, video_url: str) -> APIResponse:
        try:
            url = f"{self.base_url}/video/info"
            params = {"url": video_url}
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)
            
            if response.status_code == 200:
                data = response.json()
                return APIResponse(
                    success=True,
                    data=data,
                    error=None,
                    rate_limit_info=self.rate_limit_info,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit for {self.name}")
                return APIResponse(
                    success=False,
                    data=None,
                    error="Rate limit exceeded",
                    rate_limit_info=self.rate_limit_info,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                error_msg = f"API error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_msg)
                except:
                    pass
                
                return APIResponse(
                    success=False,
                    data=None,
                    error=error_msg,
                    rate_limit_info=self.rate_limit_info,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
                
        except requests.exceptions.Timeout:
            return APIResponse(
                success=False,
                data=None,
                error="Request timeout",
                rate_limit_info=self.rate_limit_info,
                status_code=None,
                headers=None
            )
        except Exception as e:
            logger.error(f"Error with {self.name}: {str(e)}")
            return APIResponse(
                success=False,
                data=None,
                error=str(e),
                rate_limit_info=self.rate_limit_info,
                status_code=None,
                headers=None
            )
    
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        try:
            # RapidAPI typically uses these headers
            limit = None
            remaining = None
            reset_timestamp = None
            
            # Try different header formats
            for header_name in headers:
                header_lower = header_name.lower()
                if 'ratelimit' in header_lower and 'limit' in header_lower and 'remaining' not in header_lower:
                    limit = int(headers[header_name])
                elif 'ratelimit' in header_lower and 'remaining' in header_lower:
                    remaining = int(headers[header_name])
                elif 'ratelimit' in header_lower and 'reset' in header_lower:
                    reset_timestamp = int(headers[header_name])
            
            if limit is not None and remaining is not None:
                reset_time = datetime.now()
                if reset_timestamp:
                    reset_time = datetime.fromtimestamp(reset_timestamp)
                
                return RateLimitInfo(
                    limit=limit,
                    remaining=remaining,
                    reset_time=reset_time,
                    is_exhausted=remaining <= 5
                )
        except (ValueError, KeyError) as e:
            logger.debug(f"Could not parse rate limit headers for {self.name}: {e}")
        
        return None