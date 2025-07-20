import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)

class RapidAPIDownloadVideoAdapter(TikTokAPIAdapter):
    """
    Adapter for TikTok Download Video1 API (tiktok-download-video1.p.rapidapi.com)
    Uses the /getVideo endpoint with url parameter and optional hd parameter.
    Provides video download URLs and comprehensive metadata.
    """
    
    def __init__(self, api_key: str, host: str = "tiktok-download-video1.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-DownloadVideo-{host}",
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
            url = f"{self.base_url}/getVideo"
            params = {
                "url": video_url,
                "hd": "1"  # Request HD quality
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if the API returned a successful response
                # The download video API uses code field for status
                code = data.get('code', -1)
                
                if code == 0:  # Success
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
                else:
                    # API returned an error
                    error_msg = data.get('msg', f'API error: code {code}')
                    return APIResponse(
                        success=False,
                        data=None,
                        error=error_msg,
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
        """Transform download video API response to a standardized format."""
        try:
            # Download Video API has data object with video info
            video_data = data.get('data', {})
            
            # Extract key information in a standardized format
            transformed = {
                'id': video_data.get('id'),
                'aweme_id': video_data.get('aweme_id'),
                'title': video_data.get('title', ''),
                'description': video_data.get('title', ''),
                'create_time': video_data.get('create_time'),
                'duration': video_data.get('duration'),
                'region': video_data.get('region'),
                'author': {
                    'id': video_data.get('author', {}).get('id'),
                    'unique_id': video_data.get('author', {}).get('unique_id'),
                    'nickname': video_data.get('author', {}).get('nickname'),
                    'avatar': video_data.get('author', {}).get('avatar'),
                },
                'stats': {
                    'play_count': video_data.get('play_count'),
                    'digg_count': video_data.get('digg_count'),
                    'comment_count': video_data.get('comment_count'),
                    'share_count': video_data.get('share_count'),
                    'download_count': video_data.get('download_count'),
                },
                'video': {
                    'cover': video_data.get('cover'),
                    'origin_cover': video_data.get('origin_cover'),
                    'duration': video_data.get('duration'),
                    'play_url': video_data.get('play'),
                    'wmplay_url': video_data.get('wmplay'),  # Watermarked
                    'hdplay_url': video_data.get('hdplay'),  # HD version
                    'size': video_data.get('size'),
                    'wm_size': video_data.get('wm_size'),
                    'hd_size': video_data.get('hd_size'),
                },
                'music': {
                    'id': video_data.get('music_info', {}).get('id'),
                    'title': video_data.get('music_info', {}).get('title'),
                    'play_url': video_data.get('music'),
                    'cover': video_data.get('music_info', {}).get('cover'),
                    'author': video_data.get('music_info', {}).get('author'),
                    'original': video_data.get('music_info', {}).get('original'),
                    'duration': video_data.get('music_info', {}).get('duration'),
                    'album': video_data.get('music_info', {}).get('album'),
                },
                'processed_time': data.get('processed_time'),
                
                # Include original data for backward compatibility
                'original_data': data
            }
            
            return transformed
            
        except Exception as e:
            logger.warning(f"Error transforming download video response: {e}")
            # Return original data if transformation fails
            return data
    
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        """Parse rate limit headers from RapidAPI download video response."""
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