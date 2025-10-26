import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)

class RapidAPIV2Adapter(TikTokAPIAdapter):
    """
    Adapter for TikTok Scraper v2 API (tiktok-scraper2.p.rapidapi.com)
    Uses the /video/info_v2 endpoint with both video_url and video_id parameters.
    """
    
    def __init__(self, api_key: str, host: str = "tiktok-scraper2.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-V2-{host}",
            api_key=api_key,
            base_url=f"https://{host}"
        )
        self.host = host
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host
        }
    
    def extract_video_id(self, video_url: str) -> Optional[str]:
        """Extract video ID from TikTok URL for v2 API."""
        import re
        
        # Pattern to match TikTok video IDs from URLs
        patterns = [
            r'/video/(\d+)',
            r'@[^/]+/video/(\d+)',
            r'tiktok\.com/.*?video/(\d+)',
            r'v/(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                return match.group(1)
        
        return None
    
    def get_video_info(self, video_url: str) -> APIResponse:
        try:
            # Extract video ID for v2 API
            video_id = self.extract_video_id(video_url)
            
            url = f"{self.base_url}/video/info_v2"
            params = {
                "video_url": video_url
            }
            
            # Add video_id if we could extract it
            if video_id:
                params["video_id"] = video_id
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if the API returned a successful response
                # The v2 API uses status_code and statusCode fields
                status_code = data.get('status_code', data.get('statusCode', 0))
                
                if status_code == 0:  # Success
                    # Transform the response to a more standard format
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
                    error_msg = data.get('status_msg', f'API error: status_code {status_code}')
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
                    error_msg = error_data.get('message', error_data.get('status_msg', error_msg))
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
        """Transform v2 API response to a standardized format."""
        try:
            item_info = data.get('itemInfo', {})
            item_struct = item_info.get('itemStruct', {})
            
            # Extract key information in a standardized format
            transformed = {
                'id': item_struct.get('id'),
                'title': item_struct.get('desc', ''),
                'description': item_struct.get('desc', ''),
                'create_time': item_struct.get('createTime'),
                'duration': item_struct.get('video', {}).get('duration'),
                'author': {
                    'id': item_struct.get('author', {}).get('id'),
                    'unique_id': item_struct.get('author', {}).get('uniqueId'),
                    'nickname': item_struct.get('author', {}).get('nickname'),
                    'avatar_thumb': item_struct.get('author', {}).get('avatarThumb'),
                    'avatar_medium': item_struct.get('author', {}).get('avatarMedium'),
                    'avatar_larger': item_struct.get('author', {}).get('avatarLarger'),
                    'verified': item_struct.get('author', {}).get('verified', False),
                },
                'stats': item_struct.get('stats', {}),
                'video': {
                    'play_addr': item_struct.get('video', {}).get('playAddr'),
                    'download_addr': item_struct.get('video', {}).get('downloadAddr'),
                    'cover': item_struct.get('video', {}).get('cover'),
                    'origin_cover': item_struct.get('video', {}).get('originCover'),
                    'dynamic_cover': item_struct.get('video', {}).get('dynamicCover'),
                    'width': item_struct.get('video', {}).get('width'),
                    'height': item_struct.get('video', {}).get('height'),
                    'ratio': item_struct.get('video', {}).get('ratio'),
                    'duration': item_struct.get('video', {}).get('duration'),
                    'bitrate': item_struct.get('video', {}).get('bitrate'),
                    'format': item_struct.get('video', {}).get('format'),
                    'quality': item_struct.get('video', {}).get('definition'),
                    'bitrate_info': item_struct.get('video', {}).get('bitrateInfo', []),
                },
                'music': item_struct.get('music', {}),
                'challenges': item_struct.get('challenges', []),
                'text_extra': item_struct.get('textExtra', []),
                'share_meta': data.get('shareMeta', {}),
                
                # Include original data for backward compatibility
                'original_data': data
            }
            
            return transformed
            
        except Exception as e:
            logger.warning(f"Error transforming v2 response: {e}")
            # Return original data if transformation fails
            return data
    
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        """Parse rate limit headers from RapidAPI v2 response."""
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