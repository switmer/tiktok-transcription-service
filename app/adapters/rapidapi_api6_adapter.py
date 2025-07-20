import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)

class RapidAPIAPI6Adapter(TikTokAPIAdapter):
    """
    Adapter for TikTok API6 (tiktok-api6.p.rapidapi.com)
    Uses the /video/details endpoint with video_id parameter.
    Provides very detailed video information including statistics and subtitles.
    """
    
    def __init__(self, api_key: str, host: str = "tiktok-api6.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-API6-{host}",
            api_key=api_key,
            base_url=f"https://{host}"
        )
        self.host = host
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host
        }
    
    def extract_video_id(self, video_url: str) -> Optional[str]:
        """Extract video ID from TikTok URL for API6."""
        import re
        
        # Pattern to match TikTok video IDs from URLs
        patterns = [
            r'/video/(\d+)',
            r'@[^/]+/video/(\d+)',
            r'tiktok\.com/.*?video/(\d+)',
            r'v/(\d+)',
            r'(\d{19})',  # Direct video ID (19 digits)
        ]
        
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                return match.group(1)
        
        return None
    
    def get_video_info(self, video_url: str) -> APIResponse:
        try:
            # Extract video ID for API6
            video_id = self.extract_video_id(video_url)
            
            if not video_id:
                return APIResponse(
                    success=False,
                    data=None,
                    error="Could not extract video ID from URL",
                    rate_limit_info=self.rate_limit_info,
                    status_code=None,
                    headers=None
                )
            
            url = f"{self.base_url}/video/details"
            params = {
                "video_id": video_id
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)
            
            if response.status_code == 200:
                data = response.json()
                
                # Transform the response to a standardized format
                transformed_data = self._transform_response(data)
                
                return APIResponse(
                    success=True,
                    data=transformed_data,
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
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_data.get('msg', error_msg))
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
    
    def _transform_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform API6 response to a standardized format."""
        try:
            # API6 has video_id at root and details object
            video_id = data.get('video_id')
            details = data.get('details', {})
            
            # Extract key information in a standardized format
            transformed = {
                'id': video_id,
                'title': details.get('description', ''),
                'description': details.get('description', ''),
                'create_time': details.get('create_time'),
                'duration': details.get('duration'),
                'author': {
                    'id': details.get('author_id'),
                    'unique_id': details.get('author', {}).get('uniqueId'),
                    'nickname': details.get('author_name') or details.get('author', {}).get('nickname'),
                    'avatar_thumb': details.get('avatar_thumb') or details.get('author', {}).get('avatarThumb'),
                    'avatar_medium': details.get('author', {}).get('avatarMedium'),
                    'avatar_larger': details.get('author', {}).get('avatarLarger'),
                    'verified': details.get('author', {}).get('verified', False),
                    'signature': details.get('author', {}).get('signature'),
                },
                'stats': {
                    'play_count': details.get('statistics', {}).get('number_of_plays'),
                    'digg_count': details.get('statistics', {}).get('number_of_hearts'),
                    'comment_count': details.get('statistics', {}).get('number_of_comments'),
                    'share_count': details.get('statistics', {}).get('number_of_reposts'),
                },
                'video': {
                    'cover': details.get('cover'),
                    'download_url': details.get('download_url'),
                    'unwatermarked_download_url': details.get('unwatermarked_download_url'),
                    'duration': details.get('duration'),
                    'bitrate': details.get('bitrate'),
                    'definition': details.get('video_definition'),
                    'format': details.get('format'),
                },
                'subtitles': details.get('subtitles', []),
                'cookies': details.get('cookies'),
                'type': data.get('type'),
                
                # Include original data for backward compatibility
                'original_data': data
            }
            
            return transformed
            
        except Exception as e:
            logger.warning(f"Error transforming API6 response: {e}")
            # Return original data if transformation fails
            return data
    
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        """Parse rate limit headers from RapidAPI API6 response."""
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