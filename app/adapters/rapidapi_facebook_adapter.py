import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)


class RapidAPIFacebookAdapter(TikTokAPIAdapter):
    """
    Adapter for Facebook Video Downloader API.
    Uses RapidAPI services for downloading Facebook videos/reels.

    Supports multiple RapidAPI Facebook services - configure via host parameter:
    - facebook-reel-and-video-downloader.p.rapidapi.com (default)
    - Other Facebook downloader APIs as needed
    """

    def __init__(self, api_key: str, host: str = "facebook-reel-and-video-downloader.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-Facebook-{host}",
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
            # Different Facebook APIs may have different endpoints
            # Common patterns: /download, /api/download, /video
            url = f"{self.base_url}/download"
            params = {
                "url": video_url
            }

            logger.info(f"Attempting Facebook RapidAPI download for: {video_url}")
            response = requests.get(url, headers=self.headers, params=params, timeout=30)

            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Facebook RapidAPI response received")

                # Check if the API returned a successful response
                if self._has_video_url(data):
                    transformed_data = self._transform_response(data, video_url)

                    return APIResponse(
                        success=True,
                        data=transformed_data,
                        error=None,
                        rate_limit_info=self.rate_limit_info,
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )
                else:
                    error_msg = data.get('message', data.get('error', 'No video URL in response'))
                    logger.error(f"Facebook RapidAPI returned no video: {error_msg}")
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
                    error_msg = error_data.get('message', error_data.get('error', error_msg))
                except:
                    pass

                logger.error(f"Facebook RapidAPI request failed: {error_msg}")
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

    def _has_video_url(self, data: Dict[str, Any]) -> bool:
        """Check if the response contains a video URL."""
        if not data:
            return False
        # Check common response structures for Facebook APIs
        if data.get('video_url') or data.get('videoUrl') or data.get('url'):
            return True
        if data.get('hd') or data.get('sd'):  # HD/SD quality options
            return True
        if data.get('data', {}).get('video_url'):
            return True
        if data.get('result', {}).get('video_url'):
            return True
        if data.get('links') and isinstance(data['links'], list):
            return True
        return False

    def _transform_response(self, data: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        """Transform Facebook API response to a standardized format."""
        try:
            # Extract video URL - prefer HD, fallback to SD
            video_url = (
                data.get('hd') or
                data.get('sd') or
                data.get('video_url') or
                data.get('videoUrl') or
                data.get('url') or
                data.get('data', {}).get('video_url') or
                data.get('result', {}).get('video_url')
            )

            # Try to get from links array (some APIs return multiple quality options)
            if not video_url and data.get('links'):
                for link in data['links']:
                    if link.get('hd'):
                        video_url = link['hd']
                        break
                    if link.get('sd'):
                        video_url = link['sd']
                        break
                    if link.get('url'):
                        video_url = link['url']
                        break

            # Extract metadata
            title = (
                data.get('title') or
                data.get('caption') or
                data.get('description') or
                data.get('data', {}).get('title') or
                'Facebook Video'
            )

            # Extract thumbnail
            thumbnail = (
                data.get('thumbnail') or
                data.get('thumbnail_url') or
                data.get('cover') or
                data.get('data', {}).get('thumbnail')
            )

            transformed = {
                'id': data.get('id') or data.get('video_id'),
                'title': title[:200] if title else 'Facebook Video',
                'description': data.get('caption') or data.get('description') or '',
                'author': {
                    'id': data.get('author_id'),
                    'username': data.get('author') or data.get('username'),
                    'full_name': data.get('author_name'),
                },
                'stats': {
                    'play_count': data.get('views') or data.get('play_count'),
                    'like_count': data.get('likes') or data.get('like_count'),
                    'comment_count': data.get('comments') or data.get('comment_count'),
                    'share_count': data.get('shares') or data.get('share_count'),
                },
                'video': {
                    'cover': thumbnail,
                    'play_url': video_url,
                    'hd_url': data.get('hd'),
                    'sd_url': data.get('sd'),
                    'duration': data.get('duration'),
                },
                'platform': 'facebook',
                'original_url': original_url,
                'original_data': data
            }

            return transformed

        except Exception as e:
            logger.warning(f"Error transforming Facebook response: {e}")
            return data

    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        """Parse rate limit headers from RapidAPI response."""
        try:
            limit = None
            remaining = None
            reset_timestamp = None

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
