import requests
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from urllib.parse import quote
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)


class RapidAPIInstagramAdapter(TikTokAPIAdapter):
    """
    Adapter for Instagram Reels Downloader API (instagram-reels-downloader-api.p.rapidapi.com)
    Uses the /download endpoint with url parameter.
    Provides video download URLs for Instagram Reels.
    """

    def __init__(self, api_key: str, host: str = "instagram-reels-downloader-api.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-Instagram-{host}",
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
            url = f"{self.base_url}/download"
            params = {
                "url": video_url
            }

            logger.info(f"Attempting Instagram RapidAPI download for: {video_url}")
            response = requests.get(url, headers=self.headers, params=params, timeout=30)

            # Update rate limit info from headers
            self.update_rate_limit_info(response.headers)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Instagram RapidAPI response: {data}")

                # Check if the API returned a successful response
                # The response structure may vary - check for video URL
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
                    logger.error(f"Instagram RapidAPI returned no video: {error_msg}")
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

                logger.error(f"Instagram RapidAPI request failed: {error_msg}")
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
        # Check common response structures
        if data.get('video_url') or data.get('videoUrl') or data.get('url'):
            return True
        if data.get('data', {}).get('video_url'):
            return True
        if data.get('result', {}).get('video_url'):
            return True
        # Check for media array
        if data.get('media') and isinstance(data['media'], list):
            for item in data['media']:
                if item.get('video_url') or item.get('url'):
                    return True
        return False

    def _transform_response(self, data: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        """Transform Instagram API response to a standardized format."""
        try:
            # Extract video URL from various possible response structures
            video_url = (
                data.get('video_url') or
                data.get('videoUrl') or
                data.get('url') or
                data.get('data', {}).get('video_url') or
                data.get('result', {}).get('video_url')
            )

            # Try to get from media array
            if not video_url and data.get('media'):
                for item in data['media']:
                    if item.get('video_url'):
                        video_url = item['video_url']
                        break
                    if item.get('url') and 'video' in item.get('type', ''):
                        video_url = item['url']
                        break

            # Extract metadata
            title = (
                data.get('title') or
                data.get('caption') or
                data.get('description') or
                data.get('data', {}).get('title') or
                'Instagram Reel'
            )

            # Extract thumbnail
            thumbnail = (
                data.get('thumbnail') or
                data.get('thumbnail_url') or
                data.get('cover') or
                data.get('data', {}).get('thumbnail')
            )

            # Extract author info
            author = data.get('author') or data.get('user') or data.get('owner') or {}
            if isinstance(author, str):
                author = {'username': author}

            transformed = {
                'id': data.get('id') or data.get('shortcode'),
                'title': title[:200] if title else 'Instagram Reel',
                'description': data.get('caption') or data.get('description') or '',
                'author': {
                    'id': author.get('id'),
                    'username': author.get('username') or author.get('name'),
                    'full_name': author.get('full_name'),
                    'avatar': author.get('profile_pic_url') or author.get('avatar'),
                },
                'stats': {
                    'play_count': data.get('play_count') or data.get('views'),
                    'like_count': data.get('like_count') or data.get('likes'),
                    'comment_count': data.get('comment_count') or data.get('comments'),
                },
                'video': {
                    'cover': thumbnail,
                    'play_url': video_url,
                    'duration': data.get('duration'),
                },
                'platform': 'instagram',
                'original_url': original_url,
                'original_data': data
            }

            return transformed

        except Exception as e:
            logger.warning(f"Error transforming Instagram response: {e}")
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
