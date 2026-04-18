import requests
import re
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)


class RapidAPISpotifyV3Adapter(TikTokAPIAdapter):
    """
    Fallback Spotify adapter using spotify-web-api3.p.rapidapi.com.
    POST endpoint returns full metadata + audio.items[].
    Note: p.scdn.co/mp3-preview URLs may 404 — this adapter works best as metadata fallback.
    """

    def __init__(self, api_key: str, host: str = "spotify-web-api3.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-SpotifyV3-{host}",
            api_key=api_key,
            base_url=f"https://{host}"
        )
        self.host = host
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host,
            "Content-Type": "application/json"
        }

    @staticmethod
    def extract_episode_id(url: str) -> Optional[str]:
        match = re.search(r'open\.spotify\.com/episode/([a-zA-Z0-9]+)', url)
        return match.group(1) if match else None

    def get_video_info(self, video_url: str) -> APIResponse:
        try:
            episode_id = self.extract_episode_id(video_url)
            if not episode_id:
                return APIResponse(
                    success=False, data=None,
                    error="Could not extract episode ID from URL",
                    rate_limit_info=self.rate_limit_info,
                    status_code=None, headers=None
                )

            logger.info(f"Fetching Spotify episode via web-api3: {episode_id}")
            resp = requests.post(
                f"{self.base_url}/v1/social/spotify/getepisode",
                headers=self.headers,
                json={"id": episode_id},
                timeout=30
            )
            self.update_rate_limit_info(resp.headers)

            if resp.status_code == 429:
                return APIResponse(
                    success=False, data=None, error="Rate limit exceeded",
                    rate_limit_info=self.rate_limit_info,
                    status_code=429, headers=dict(resp.headers)
                )

            if resp.status_code != 200:
                error_msg = f"HTTP {resp.status_code}"
                try:
                    error_msg = resp.json().get('message', error_msg)
                except:
                    pass
                return APIResponse(
                    success=False, data=None, error=error_msg,
                    rate_limit_info=self.rate_limit_info,
                    status_code=resp.status_code, headers=dict(resp.headers)
                )

            data = resp.json()
            episode = data.get('data', {}).get('episodeUnionV2', {})
            if not episode:
                return APIResponse(
                    success=False, data=None, error="No episode data in response",
                    rate_limit_info=self.rate_limit_info,
                    status_code=200, headers=dict(resp.headers)
                )

            transformed = self._transform_response(episode, video_url, episode_id)

            if not transformed.get('audio', {}).get('play_url'):
                return APIResponse(
                    success=False, data=None,
                    error="No playable audio URL found",
                    rate_limit_info=self.rate_limit_info,
                    status_code=200, headers=dict(resp.headers)
                )

            return APIResponse(
                success=True, data=transformed, error=None,
                rate_limit_info=self.rate_limit_info,
                status_code=200, headers=dict(resp.headers)
            )

        except requests.exceptions.Timeout:
            return APIResponse(
                success=False, data=None, error="Request timeout",
                rate_limit_info=self.rate_limit_info,
                status_code=None, headers=None
            )
        except Exception as e:
            logger.error(f"Error with {self.name}: {str(e)}")
            return APIResponse(
                success=False, data=None, error=str(e),
                rate_limit_info=self.rate_limit_info,
                status_code=None, headers=None
            )

    def _transform_response(self, episode: Dict, original_url: str, episode_id: str) -> Dict[str, Any]:
        """Same response structure as V2 adapter (episodeUnionV2 format)."""
        try:
            audio_items = episode.get('audio', {}).get('items', [])
            play_url = None
            audio_format = None
            for item in audio_items:
                if item.get('format') == 'MP4_128' and item.get('url'):
                    play_url = item['url']
                    audio_format = 'mp4'
                    break
            if not play_url and audio_items:
                play_url = audio_items[0].get('url')
                audio_format = audio_items[0].get('format', '').lower()

            title = episode.get('name', 'Spotify Episode')
            description = episode.get('contents', {}).get('description', '') or episode.get('description', '')
            duration_ms = episode.get('duration', {}).get('totalMilliseconds', 0)
            release_date = episode.get('releaseDate', {}).get('isoString', '')

            cover_sources = episode.get('coverArt', {}).get('sources', [])
            cover_url = max(cover_sources, key=lambda s: s.get('width', 0)).get('url') if cover_sources else None

            podcast = episode.get('podcastV2', {}).get('data', {})
            show_name = podcast.get('name', '')
            show_uri = podcast.get('uri', '')
            show_id = show_uri.split(':')[-1] if show_uri else ''

            return {
                'id': episode_id,
                'title': title[:200],
                'description': description,
                'author': {
                    'id': show_id,
                    'username': show_name,
                    'full_name': show_name,
                    'avatar': None,
                },
                'stats': {
                    'play_count': None,
                    'like_count': None,
                    'comment_count': None,
                },
                'audio': {
                    'cover': cover_url,
                    'play_url': play_url,
                    'passthrough_url': None,
                    'scdn_urls': [i.get('url') for i in audio_items if i.get('url')],
                    'duration': duration_ms / 1000 if duration_ms else None,
                    'format': audio_format,
                },
                'podcast': {
                    'show_name': show_name,
                    'show_id': show_id,
                    'publisher': show_name,
                    'release_date': release_date,
                    'explicit': episode.get('contentRating', {}).get('label') == 'EXPLICIT',
                    'language': 'en',
                },
                'platform': 'spotify',
                'original_url': original_url,
                'original_data': episode,
            }
        except Exception as e:
            logger.warning(f"Error transforming SpotifyV3 response: {e}")
            return {
                'id': episode_id,
                'title': 'Spotify Episode',
                'audio': {'play_url': None},
                'platform': 'spotify',
                'original_url': original_url,
                'original_data': episode,
            }

    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
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
                    limit=limit, remaining=remaining,
                    reset_time=reset_time, is_exhausted=remaining <= 5
                )
        except (ValueError, KeyError) as e:
            logger.debug(f"Could not parse rate limit headers for {self.name}: {e}")
        return None
