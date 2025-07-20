import requests
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)

class TikWMAdapter(TikTokAPIAdapter):
    def __init__(self):
        super().__init__(
            name="TikWM",
            api_key="",  # No API key required
            base_url="https://www.tikwm.com/api/"
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_video_info(self, video_url: str) -> APIResponse:
        try:
            url = f"{self.base_url}"
            params = {
                "url": video_url,
                "hd": "1"
            }
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if the response indicates success
                if data.get('code') == 0 and data.get('data'):
                    return APIResponse(
                        success=True,
                        data=data,
                        error=None,
                        rate_limit_info=None,  # TikWM doesn't provide rate limit headers
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )
                else:
                    error_msg = data.get('msg', 'Unknown error from TikWM')
                    return APIResponse(
                        success=False,
                        data=None,
                        error=error_msg,
                        rate_limit_info=None,
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit for {self.name}")
                # TikWM doesn't provide specific rate limit info, so we estimate
                estimated_reset = datetime.now() + timedelta(minutes=15)
                rate_limit_info = RateLimitInfo(
                    limit=100,  # Estimated
                    remaining=0,
                    reset_time=estimated_reset,
                    is_exhausted=True
                )
                self.rate_limit_info = rate_limit_info
                
                return APIResponse(
                    success=False,
                    data=None,
                    error="Rate limit exceeded",
                    rate_limit_info=rate_limit_info,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return APIResponse(
                    success=False,
                    data=None,
                    error=f"HTTP {response.status_code}",
                    rate_limit_info=None,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
                
        except requests.exceptions.Timeout:
            return APIResponse(
                success=False,
                data=None,
                error="Request timeout",
                rate_limit_info=None,
                status_code=None,
                headers=None
            )
        except Exception as e:
            logger.error(f"Error with {self.name}: {str(e)}")
            return APIResponse(
                success=False,
                data=None,
                error=str(e),
                rate_limit_info=None,
                status_code=None,
                headers=None
            )
    
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        # TikWM doesn't provide rate limit headers
        return None