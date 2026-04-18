import requests
import re
from typing import Dict, Optional, Any
from datetime import datetime
import logging
from .base import TikTokAPIAdapter, APIResponse, RateLimitInfo

logger = logging.getLogger(__name__)


class RapidAPISpotifyAdapter(TikTokAPIAdapter):
    """
    Primary Spotify adapter using spotify23.p.rapidapi.com.
    Uses Episode Sound endpoint for audio URLs (passthroughUrl + scdn.co)
    and Episodes endpoint for metadata.
    """

    def __init__(self, api_key: str, host: str = "spotify23.p.rapidapi.com"):
        super().__init__(
            name=f"RapidAPI-Spotify-{host}",
            api_key=api_key,
            base_url=f"https://{host}"
        )
        self.host = host
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host
        }

    @staticmethod
    def extract_episode_id(url: str) -> Optional[str]:
        """Extract Spotify episode ID from URL."""
        match = re.search(r'open\.spotify\.com/episode/([a-zA-Z0-9]+)', url)
        return match.group(1) if match else None

    def get_video_info(self, video_url: str) -> APIResponse:
        """Get Spotify episode audio URLs and metadata."""
        try:
            episode_id = self.extract_episode_id(video_url)
            if not episode_id:
                return APIResponse(
                    success=False, data=None,
                    error="Could not extract episode ID from URL",
                    rate_limit_info=self.rate_limit_info,
                    status_code=None, headers=None
                )

            # Get audio URLs via Episode Sound endpoint
            logger.info(f"Fetching Spotify episode sound for: {episode_id}")
            sound_resp = requests.get(
                f"{self.base_url}/episode_sound/",
                headers=self.headers,
                params={"id": episode_id},
                timeout=30
            )
            self.update_rate_limit_info(sound_resp.headers)

            if sound_resp.status_code == 429:
                return APIResponse(
                    success=False, data=None, error="Rate limit exceeded",
                    rate_limit_info=self.rate_limit_info,
                    status_code=429, headers=dict(sound_resp.headers)
                )

            if sound_resp.status_code != 200:
                error_msg = f"Episode Sound HTTP {sound_resp.status_code}"
                try:
                    error_msg = sound_resp.json().get('message', error_msg)
                except:
                    pass
                return APIResponse(
                    success=False, data=None, error=error_msg,
                    rate_limit_info=self.rate_limit_info,
                    status_code=sound_resp.status_code,
                    headers=dict(sound_resp.headers)
                )

            sound_data = sound_resp.json()

            # Get metadata via Episode endpoint
            logger.info(f"Fetching Spotify episode metadata for: {episode_id}")
            meta_resp = requests.get(
                f"{self.base_url}/episode/",
                headers=self.headers,
                params={"id": episode_id},
                timeout=30
            )

            meta_data = None
            if meta_resp.status_code == 200:
                meta_json = meta_resp.json()
                # Response wraps in data.episodeUnionV2 or may be flat
                if isinstance(meta_json, dict):
                    episode_union = meta_json.get('data', {}).get('episodeUnionV2')
                    if episode_union:
                        meta_data = self._extract_meta_from_union(episode_union)
                    elif meta_json.get('id') == episode_id:
                        meta_data = meta_json
                    else:
                        meta_data = meta_json
            else:
                logger.warning(f"Metadata fetch failed (HTTP {meta_resp.status_code}), continuing with sound data only")

            transformed = self._transform_response(sound_data, meta_data, video_url, episode_id)

            if not transformed.get('audio', {}).get('play_url'):
                return APIResponse(
                    success=False, data=None,
                    error="No playable audio URL found",
                    rate_limit_info=self.rate_limit_info,
                    status_code=200, headers=dict(sound_resp.headers)
                )

            return APIResponse(
                success=True, data=transformed, error=None,
                rate_limit_info=self.rate_limit_info,
                status_code=200, headers=dict(sound_resp.headers)
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

    @staticmethod
    def _extract_meta_from_union(episode: Dict) -> Dict:
        """Convert episodeUnionV2 format to flat metadata dict."""
        cover_sources = episode.get('coverArt', {}).get('sources', [])
        cover_url = max(cover_sources, key=lambda s: s.get('width', 0)).get('url') if cover_sources else None
        podcast = episode.get('podcastV2', {}).get('data', {})
        show_uri = podcast.get('uri', '')
        return {
            'id': episode.get('id'),
            'name': episode.get('name'),
            'description': episode.get('description', ''),
            'duration_ms': episode.get('duration', {}).get('totalMilliseconds', 0),
            'release_date': episode.get('releaseDate', {}).get('isoString', ''),
            'explicit': episode.get('contentRating', {}).get('label') == 'EXPLICIT',
            'language': (episode.get('languages', ['en']) or ['en'])[0] if isinstance(episode.get('languages'), list) else 'en',
            'images': [{'url': cover_url, 'height': 640}] if cover_url else [],
            'show': {
                'name': podcast.get('name', ''),
                'id': show_uri.split(':')[-1] if show_uri else '',
                'publisher': podcast.get('name', ''),
            }
        }

    def _transform_response(self, sound_data: Dict, meta_data: Optional[Dict],
                            original_url: str, episode_id: str) -> Dict[str, Any]:
        """Transform Spotify API responses to standardized format."""
        try:
            # Extract best audio URL: prefer passthroughUrl, then scdn.co URLs
            passthrough_url = sound_data.get('passthroughUrl')
            scdn_urls = sound_data.get('url', [])
            if isinstance(scdn_urls, str):
                scdn_urls = [scdn_urls]

            play_url = passthrough_url
            audio_format = 'mp3' if passthrough_url else None

            if not play_url and scdn_urls:
                play_url = scdn_urls[0]
                audio_format = sound_data.get('format', 'mp4').lower()

            # Extract metadata
            title = 'Spotify Episode'
            description = ''
            show_name = ''
            show_id = ''
            publisher = ''
            cover_url = None
            duration_ms = 0
            release_date = ''
            explicit = False
            language = 'en'

            if meta_data:
                title = meta_data.get('name', title)
                description = meta_data.get('description', '')
                duration_ms = meta_data.get('duration_ms', 0)
                release_date = meta_data.get('release_date', '')
                explicit = meta_data.get('explicit', False)
                language = meta_data.get('language', 'en')

                images = meta_data.get('images', [])
                if images:
                    # Prefer largest image
                    cover_url = max(images, key=lambda i: i.get('height', 0)).get('url')

                show = meta_data.get('show', {})
                if show:
                    show_name = show.get('name', '')
                    show_id = show.get('id', '')
                    publisher = show.get('publisher', '')

            return {
                'id': episode_id,
                'title': title[:200] if title else 'Spotify Episode',
                'description': description,
                'author': {
                    'id': show_id,
                    'username': show_name,
                    'full_name': publisher,
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
                    'passthrough_url': passthrough_url,
                    'scdn_urls': scdn_urls,
                    'duration': duration_ms / 1000 if duration_ms else None,
                    'format': audio_format,
                },
                'podcast': {
                    'show_name': show_name,
                    'show_id': show_id,
                    'publisher': publisher,
                    'release_date': release_date,
                    'explicit': explicit,
                    'language': language,
                },
                'platform': 'spotify',
                'original_url': original_url,
                'original_data': {
                    'sound': sound_data,
                    'metadata': meta_data,
                }
            }

        except Exception as e:
            logger.warning(f"Error transforming Spotify response: {e}")
            return {
                'id': episode_id,
                'title': 'Spotify Episode',
                'audio': {'play_url': sound_data.get('passthroughUrl')},
                'platform': 'spotify',
                'original_url': original_url,
                'original_data': sound_data,
            }

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
