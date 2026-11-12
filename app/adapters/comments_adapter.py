"""
TikTok Comments Adapter - Pro Feature
Fetches comments and replies from TikTok videos using multiple API providers.
"""

import os
import requests
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process preview cache + per-provider 429 cooldown
# ---------------------------------------------------------------------------

DEFAULT_PREVIEW_SUCCESS_TTL_SECONDS = 300  # 5 minutes
DEFAULT_PREVIEW_NEGATIVE_TTL_SECONDS = 60  # 1 minute
DEFAULT_PROVIDER_COOLDOWN_SECONDS = 6 * 3600  # 6 hours after 429

_PREVIEW_CACHE: Dict[str, Dict[str, Any]] = {}
_PROVIDER_COOLDOWN_UNTIL: Dict[str, float] = {}
_CACHE_LOCK = Lock()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def clear_comments_caches() -> None:
    """Test helper: reset preview cache and provider cooldowns."""
    with _CACHE_LOCK:
        _PREVIEW_CACHE.clear()
        _PROVIDER_COOLDOWN_UNTIL.clear()


class UnusableCommentsResponse(ValueError):
    """Raised when a provider returns HTTP 200 with a body we cannot use."""


@dataclass
class Comment:
    """Normalized comment structure across all providers"""
    comment_id: str
    text: str
    author_name: str
    author_username: str
    author_avatar: Optional[str]
    created_at: str
    likes: int
    reply_count: int
    parent_comment_id: Optional[str] = None
    video_id: Optional[str] = None
    raw_data: Optional[Dict] = None


def _as_dict(value: Any) -> Dict:
    return value if isinstance(value, dict) else {}


def _first_url(url_list: Any) -> Optional[str]:
    if not isinstance(url_list, list) or not url_list:
        return None
    first = url_list[0]
    return first if isinstance(first, str) and first else None


def _avatar_from_user(user: Any, *nested_keys: str) -> Optional[str]:
    """Safely extract an avatar URL from nested TikTok user blobs."""
    user = _as_dict(user)
    if not user:
        return None

    # Plain string avatar fields (download-video1)
    for key in ("avatar", "avatar_url"):
        value = user.get(key)
        if isinstance(value, str) and value:
            return value

    for key in nested_keys:
        blob = user.get(key)
        if blob is None:
            continue
        if isinstance(blob, str) and blob:
            return blob
        if isinstance(blob, dict):
            url = _first_url(blob.get("url_list"))
            if url:
                return url
    return None


def _comments_list_at(data: Any, *path: str) -> Tuple[Optional[List], bool]:
    """
    Walk path into data.

    Returns (list_or_none, key_was_present).
    - key missing → (None, False)
    - key present and list → (list, True)
    - key present and null/non-list → raises UnusableCommentsResponse
    """
    current = data
    for i, key in enumerate(path):
        if not isinstance(current, dict) or key not in current:
            return None, False
        current = current[key]
        if i < len(path) - 1:
            if current is None:
                raise UnusableCommentsResponse(
                    f"Unusable response: {'/'.join(path[:i+1])} is null"
                )
            if not isinstance(current, dict):
                raise UnusableCommentsResponse(
                    f"Unusable response: {'/'.join(path[:i+1])} is not an object"
                )

    if current is None:
        raise UnusableCommentsResponse(
            f"Unusable response: {'/'.join(path)} is null"
        )
    if not isinstance(current, list):
        raise UnusableCommentsResponse(
            f"Unusable response: {'/'.join(path)} is not a list"
        )
    return current, True


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


class TikTokCommentsAdapter:
    """
    Multi-provider comments adapter with automatic fallback.
    Supports: tiktok-api23, tiktok-download-video1, tiktok-scraper2

    Note: tiktok-api6 is used elsewhere for video metadata only — it is not a
    comments provider and is intentionally not listed here. Each RapidAPI host
    requires its own marketplace subscription on the same RAPIDAPI_KEY.
    """

    def __init__(self, api_keys: List[str]):
        """
        Initialize with list of RapidAPI keys.
        Keys will be tried in rotation for rate limit management.
        """
        self.api_keys = api_keys if isinstance(api_keys, list) else [api_keys]
        self.current_key_index = 0
        self.preview_success_ttl = _env_int(
            "COMMENTS_PREVIEW_SUCCESS_TTL_SECONDS",
            DEFAULT_PREVIEW_SUCCESS_TTL_SECONDS,
        )
        self.preview_negative_ttl = _env_int(
            "COMMENTS_PREVIEW_NEGATIVE_TTL_SECONDS",
            DEFAULT_PREVIEW_NEGATIVE_TTL_SECONDS,
        )
        self.provider_cooldown_seconds = _env_int(
            "COMMENTS_PROVIDER_COOLDOWN_SECONDS",
            DEFAULT_PROVIDER_COOLDOWN_SECONDS,
        )

        # Provider configurations
        self.providers = [
            {
                'name': 'tiktok-api23',
                'host': 'tiktok-api23.p.rapidapi.com',
                'endpoint': '/api/post/comments',
                'replies_endpoint': '/api/post/comment/replies',
                'parser': self._parse_api23
            },
            {
                'name': 'tiktok-download-video1',
                'host': 'tiktok-download-video1.p.rapidapi.com',
                'endpoint': '/commentList',
                'replies_endpoint': '/commentReply',
                'parser': self._parse_downloadvideo1
            },
            {
                'name': 'tiktok-scraper2',
                'host': 'tiktok-scraper2.p.rapidapi.com',
                'endpoint': '/video/comments',
                'replies_endpoint': None,  # No dedicated replies endpoint in adapter
                'parser': self._parse_scraper2
            }
        ]

    def get_api_key(self) -> str:
        """Get current API key with rotation"""
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    # ------------------------------------------------------------------
    # Cache / cooldown helpers
    # ------------------------------------------------------------------

    def _preview_cache_get(self, video_id: str) -> Optional[Dict[str, Any]]:
        with _CACHE_LOCK:
            entry = _PREVIEW_CACHE.get(video_id)
            if not entry:
                return None
            if time.time() >= entry["expires_at"]:
                _PREVIEW_CACHE.pop(video_id, None)
                return None
            return entry["result"]

    def _preview_cache_set(
        self, video_id: str, result: Dict[str, Any], *, success: bool
    ) -> None:
        ttl = self.preview_success_ttl if success else self.preview_negative_ttl
        with _CACHE_LOCK:
            _PREVIEW_CACHE[video_id] = {
                "expires_at": time.time() + ttl,
                "success": success,
                "result": result,
            }

    def _provider_in_cooldown(self, provider_name: str) -> bool:
        with _CACHE_LOCK:
            until = _PROVIDER_COOLDOWN_UNTIL.get(provider_name)
            if until is None:
                return False
            if time.time() >= until:
                _PROVIDER_COOLDOWN_UNTIL.pop(provider_name, None)
                return False
            return True

    def _mark_provider_cooldown(
        self, provider_name: str, retry_after: Optional[int] = None
    ) -> None:
        seconds = retry_after if retry_after and retry_after > 0 else self.provider_cooldown_seconds
        with _CACHE_LOCK:
            _PROVIDER_COOLDOWN_UNTIL[provider_name] = time.time() + seconds
        logger.warning(
            "Provider %s cooling down for %ss after rate limit",
            provider_name,
            seconds,
        )

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> Optional[int]:
        header = response.headers.get("Retry-After") or response.headers.get("retry-after")
        if not header:
            return None
        try:
            return int(header)
        except ValueError:
            return None

    def fetch_comments(
        self,
        video_id: str,
        count: int = 30,
        cursor: str = None,
        max_retries: int = 3,
        get_all: bool = False,
        preview: bool = False,
    ) -> Dict[str, Any]:
        """
        Fetch comments for a video with automatic provider fallback.

        Args:
            video_id: TikTok video ID
            count: Number of comments per page (ignored if get_all=True)
            cursor: Pagination cursor (ignored if get_all=True)
            max_retries: Maximum retry attempts per provider
            get_all: If True, fetch ALL comments with pagination
            preview: If True, one attempt per provider, fail-fast on 5xx, no backoff sleeps

        Returns:
            {
                'comments': List[Comment],
                'cursor': str,
                'has_more': bool,
                'provider': str,
                'error': Optional[str],
                'pages_fetched': int (if get_all=True)
            }
        """
        if get_all:
            return self._fetch_all_comments_with_pagination(video_id, max_retries)
        else:
            effective_retries = 1 if preview else max_retries
            return self._fetch_single_page(
                video_id, count, cursor, effective_retries, preview=preview
            )

    def _fetch_single_page(
        self,
        video_id: str,
        count: int = 30,
        cursor: str = None,
        max_retries: int = 3,
        preview: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a single page of comments (original behavior)"""
        # Preview-only cache: avoid re-hitting providers for the same video_id
        if preview and not cursor:
            cached = self._preview_cache_get(video_id)
            if cached is not None:
                logger.info("Returning cached comment preview for video %s", video_id)
                return cached

        provider_errors: List[str] = []

        for provider in self.providers:
            if self._provider_in_cooldown(provider["name"]):
                msg = f"{provider['name']}: skipped (rate-limit cooldown)"
                provider_errors.append(msg)
                logger.warning(msg)
                continue

            for attempt in range(max_retries):
                try:
                    result = self._fetch_from_provider(
                        provider, video_id, count, cursor, max_retries, preview=preview
                    )
                    # Successful provider response — including genuine zero comments
                    logger.info(
                        f"Successfully fetched {len(result.get('comments') or [])} comments "
                        f"from {provider['name']} for video {video_id}"
                    )
                    if preview and not cursor:
                        self._preview_cache_set(video_id, result, success=True)
                    return result
                except Exception as e:
                    err = f"{provider['name']}: {e}"
                    provider_errors.append(err)
                    logger.warning(
                        f"Provider {provider['name']} attempt {attempt + 1} failed: {e}"
                    )
                    if preview or attempt >= max_retries - 1:
                        break  # next provider; no backoff sleep on preview
                    time.sleep(1)  # Brief delay before retry
                    continue

        # All providers failed
        logger.error(f"All comment providers failed for video {video_id}")
        result = {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'All providers failed',
            'provider_errors': provider_errors,
        }
        if preview and not cursor:
            self._preview_cache_set(video_id, result, success=False)
        return result

    def _fetch_all_comments_with_pagination(
        self,
        video_id: str,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch ALL comments using pagination with retry logic"""
        logger.info(f"Starting pagination fetch for video {video_id}")

        for provider in self.providers:
            if self._provider_in_cooldown(provider["name"]):
                logger.warning(
                    "Skipping provider %s (rate-limit cooldown)", provider["name"]
                )
                continue
            try:
                logger.info(f"Trying provider: {provider['name']}")
                result = self._fetch_all_from_provider(provider, video_id, max_retries)
                if result.get('comments'):
                    logger.info(
                        f"Successfully fetched {len(result['comments'])} comments "
                        f"across {result.get('pages_fetched', 1)} pages "
                        f"from {provider['name']} for video {video_id}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"Provider {provider['name']} failed: {e}")
                continue

        # All providers failed
        logger.error(f"All comment providers failed for video {video_id}")
        return {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'All providers failed',
            'pages_fetched': 0
        }

    def _fetch_all_from_provider(
        self,
        provider: Dict,
        video_id: str,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch all comments from a specific provider with pagination"""
        all_comments = []
        cursor = 0
        page_count = 0
        max_pages = 100  # Safety limit to prevent infinite loops

        while page_count < max_pages:
            logger.info(f"Fetching page {page_count + 1} with cursor {cursor}")

            # Retry logic for each page
            page_success = False
            for attempt in range(max_retries):
                try:
                    result = self._fetch_from_provider(provider, video_id, 50, cursor, max_retries)

                    if result.get('comments'):
                        page_comments = result['comments']
                        all_comments.extend(page_comments)
                        page_count += 1
                        page_success = True

                        logger.info(
                            f"Page {page_count}: Got {len(page_comments)} comments "
                            f"(total: {len(all_comments)})"
                        )

                        # Check if there are more comments
                        has_more = self._has_more_comments(result.get('data', {}), provider['name'])
                        if not has_more:
                            logger.info("No more comments available")
                            break

                        # Update cursor for next page
                        cursor = self._get_next_cursor(result.get('data', {}), provider['name'], cursor)
                        if cursor is None:
                            logger.info("No next cursor available")
                            break

                        # Rate limiting between pages
                        time.sleep(1)  # 1 second delay between pages
                        break
                    else:
                        logger.warning(f"Page {page_count + 1}: No comments returned")
                        break

                except Exception as e:
                    logger.warning(f"Page {page_count + 1} attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        logger.error(f"Page {page_count + 1} failed after {max_retries} attempts")
                        break

            if not page_success:
                logger.warning(f"Failed to fetch page {page_count + 1}, stopping pagination")
                break

        return {
            'comments': all_comments,
            'count': len(all_comments),
            'provider': provider['name'],
            'pages_fetched': page_count,
            'error': None
        }

    def fetch_comment_replies(
        self,
        video_id: str,
        comment_id: str,
        count: int = 20,
        cursor: str = None
    ) -> Dict[str, Any]:
        """Fetch replies to a specific comment"""
        for provider in self.providers:
            if not provider['replies_endpoint']:
                continue  # Skip providers without reply support
            if self._provider_in_cooldown(provider["name"]):
                continue

            try:
                api_key = self.get_api_key()
                headers = {
                    'X-RapidAPI-Key': api_key,
                    'X-RapidAPI-Host': provider['host']
                }

                base_url = f"https://{provider['host']}{provider['replies_endpoint']}"

                # Build params based on provider
                if provider['name'] == 'tiktok-api23':
                    params = {
                        'videoId': video_id,
                        'commentId': comment_id,
                        'count': count
                    }
                elif provider['name'] == 'tiktok-download-video1':
                    params = {
                        'comment_id': comment_id,
                        'video_id': video_id,
                        'count': count
                    }
                else:
                    continue

                if cursor:
                    params['cursor'] = cursor

                response = requests.get(base_url, headers=headers, params=params, timeout=30)

                if response.status_code == 429:
                    self._mark_provider_cooldown(
                        provider["name"], self._parse_retry_after(response)
                    )
                    continue

                if response.status_code == 200:
                    data = response.json()
                    comments = provider['parser'](data, parent_id=comment_id)

                    return {
                        'comments': comments,
                        'cursor': self._extract_cursor(data, provider['name']),
                        'has_more': self._extract_has_more(data, provider['name']),
                        'provider': provider['name'],
                        'error': None
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch replies from {provider['name']}: {e}")
                continue

        return {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'No provider supports replies or all failed'
        }

    def _validate_provider_payload(self, provider: Dict, data: Any) -> None:
        """Raise UnusableCommentsResponse for known-bad 200 bodies."""
        if not isinstance(data, dict):
            raise UnusableCommentsResponse(
                f"Unusable response from {provider['name']}: body is not a JSON object"
            )

        name = provider["name"]
        if name == "tiktok-download-video1":
            code = data.get("code")
            if code is not None and code != 0:
                raise UnusableCommentsResponse(
                    f"Provider {name} error code={code}: {data.get('msg') or data.get('message')}"
                )
            # Prefer nested data.comments; fall through to raise if explicitly null
            _comments_list_at(data, "data", "comments")
            return

        if name == "tiktok-api23":
            # Accept top-level comments or nested data.comments
            comments, present = _comments_list_at(data, "comments")
            if present:
                return
            nested, nested_present = _comments_list_at(data, "data", "comments")
            if nested_present:
                return
            # Missing comments array with no nested data — treat as empty usable body
            return

        if name == "tiktok-scraper2":
            comments, present = _comments_list_at(data, "comments")
            if present:
                return
            nested, nested_present = _comments_list_at(data, "data", "comments")
            if nested_present:
                return
            return

    def _fetch_from_provider(
        self,
        provider: Dict,
        video_id: str,
        count: int,
        cursor: Optional[str],
        max_retries: int = 3,
        preview: bool = False,
    ) -> Dict[str, Any]:
        """Fetch comments from a specific provider with enhanced error handling"""
        api_key = self.get_api_key()
        headers = {
            'X-RapidAPI-Key': api_key,
            'X-RapidAPI-Host': provider['host']
        }

        base_url = f"https://{provider['host']}{provider['endpoint']}"

        # Build params based on provider
        if provider['name'] == 'tiktok-api23':
            params = {'videoId': video_id, 'count': count}
        elif provider['name'] == 'tiktok-download-video1':
            # Needs full URL, but we have video_id - construct it
            params = {
                'url': f'https://www.tiktok.com/@x/video/{video_id}',
                'count': count
            }
        elif provider['name'] == 'tiktok-scraper2':
            params = {
                'video_url': f'https://www.tiktok.com/@x/video/{video_id}',
                'count': count
            }
        else:
            params = {'video_id': video_id, 'count': count}

        if cursor:
            params['cursor'] = cursor

        # Preview: single attempt, fail-fast on 5xx, no retry backoff sleeps
        attempts = 1 if preview else max_retries

        for attempt in range(attempts):
            try:
                response = requests.get(base_url, headers=headers, params=params, timeout=30)

                # Preview path: fail fast on any 5xx (no retries / sleeps)
                if preview and response.status_code >= 500:
                    raise requests.exceptions.RequestException(
                        f"Provider {provider['name']} returned {response.status_code}"
                    )

                # Handle specific HTTP errors (full fetch only)
                if response.status_code == 504:
                    logger.warning(f"Gateway timeout (504) on attempt {attempt + 1}, retrying...")
                    if attempt < attempts - 1:
                        time.sleep(5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Gateway timeout after {attempts} attempts")

                if response.status_code == 429:
                    self._mark_provider_cooldown(
                        provider["name"], self._parse_retry_after(response)
                    )
                    logger.warning(f"Rate limit (429) on attempt {attempt + 1}")
                    raise requests.exceptions.RequestException(
                        f"Rate limit exceeded for {provider['name']}"
                    )

                # Not subscribed / forbidden — common when fallback hosts share one key
                if response.status_code in (401, 403):
                    detail = ""
                    try:
                        detail = response.json().get("message") or ""
                    except Exception:
                        detail = (response.text or "")[:200]
                    raise requests.exceptions.RequestException(
                        f"HTTP {response.status_code} from {provider['name']}"
                        + (f": {detail}" if detail else "")
                    )

                response.raise_for_status()
                data = response.json()
                self._validate_provider_payload(provider, data)
                comments = provider['parser'](data)

                return {
                    'comments': comments,
                    'cursor': self._extract_cursor(data, provider['name']),
                    'has_more': self._extract_has_more(data, provider['name']),
                    'provider': provider['name'],
                    'error': None,
                    'data': data  # Include raw data for pagination helpers
                }

            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout on attempt {attempt + 1}, retrying...")
                if attempt < attempts - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error on attempt {attempt + 1}, retrying...")
                if attempt < attempts - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
            except (UnusableCommentsResponse, requests.exceptions.RequestException) as e:
                logger.error(f"Request/body error on attempt {attempt + 1}: {e}")
                if preview or attempt >= attempts - 1:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if preview or attempt >= attempts - 1:
                    raise
                time.sleep(5 * (attempt + 1))
                continue

        # This should never be reached due to the raise statements above
        raise Exception(f"Failed to fetch comments after {attempts} attempts")

    def _parse_api23(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-api23 response format"""
        comments = []

        comments_data, present = _comments_list_at(data, "comments")
        if not present:
            comments_data, present = _comments_list_at(data, "data", "comments")
        if not present:
            comments_data = []

        for item in comments_data:
            try:
                item = _as_dict(item)
                user = _as_dict(item.get('user'))
                comments.append(Comment(
                    comment_id=str(item.get('cid', '')),
                    text=item.get('text', '') or '',
                    author_name=user.get('nickname', 'Unknown') or 'Unknown',
                    author_username=user.get('unique_id', '') or '',
                    author_avatar=_avatar_from_user(
                        user, 'avatar_thumb', 'avatar_medium', 'avatar_larger'
                    ),
                    created_at=str(item.get('create_time', '')),
                    likes=int(item.get('digg_count') or 0),
                    reply_count=int(item.get('reply_comment_total') or 0),
                    parent_comment_id=parent_id,
                    video_id=str(item.get('aweme_id', '') or ''),
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue

        return comments

    def _parse_downloadvideo1(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-download-video1 response format"""
        comments = []

        comments_data, present = _comments_list_at(data, "data", "comments")
        if not present:
            comments_data, present = _comments_list_at(data, "comments")
        if not present:
            comments_data = []

        for item in comments_data:
            try:
                item = _as_dict(item)
                user = _as_dict(item.get('user'))
                comments.append(Comment(
                    comment_id=str(item.get('id', '') or item.get('cid', '')),
                    text=item.get('text', '') or '',
                    author_name=user.get('nickname', 'Unknown') or 'Unknown',
                    author_username=user.get('unique_id', '') or '',
                    author_avatar=_avatar_from_user(user, 'avatar_thumb'),
                    created_at=str(item.get('create_time', '')),
                    likes=int(item.get('digg_count') or 0),
                    reply_count=int(item.get('reply_total') or item.get('reply_comment_total') or 0),
                    parent_comment_id=parent_id,
                    video_id=str(item.get('video_id') or '') or None,
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue

        return comments

    def _parse_scraper2(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-scraper2 response format"""
        comments = []

        comments_data, present = _comments_list_at(data, "comments")
        if not present:
            comments_data, present = _comments_list_at(data, "data", "comments")
        if not present:
            comments_data = []

        for item in comments_data:
            try:
                item = _as_dict(item)
                user = _as_dict(item.get('user'))
                comments.append(Comment(
                    comment_id=str(item.get('cid', '') or item.get('id', '')),
                    text=item.get('text', '') or '',
                    author_name=user.get('nickname', 'Unknown') or 'Unknown',
                    author_username=user.get('unique_id', '') or user.get('uniqueId', '') or '',
                    author_avatar=_avatar_from_user(
                        user, 'avatar_larger', 'avatar_thumb', 'avatar_medium', 'avatarLarger', 'avatarThumb'
                    ),
                    created_at=str(item.get('create_time', '') or item.get('createTime', '')),
                    likes=int(item.get('digg_count') or item.get('diggCount') or 0),
                    reply_count=int(
                        item.get('reply_comment_total')
                        or item.get('replyCommentTotal')
                        or item.get('reply_total')
                        or 0
                    ),
                    parent_comment_id=parent_id,
                    video_id=str(item.get('aweme_id', '') or item.get('awemeId', '') or ''),
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue

        return comments

    def _extract_cursor(self, data: Dict, provider_name: str) -> Optional[str]:
        """Extract pagination cursor from response"""
        data = _as_dict(data)
        nested = _as_dict(data.get("data"))

        def pick(*values):
            for value in values:
                if value is not None and value != "":
                    return value
            return None

        if provider_name == 'tiktok-api23':
            return pick(data.get('cursor'), nested.get('cursor'))
        elif provider_name == 'tiktok-download-video1':
            return pick(nested.get('cursor'), data.get('cursor'), nested.get('next_cursor'))
        elif provider_name == 'tiktok-scraper2':
            return pick(
                data.get('cursor'),
                data.get('min_time'),
                nested.get('cursor'),
                nested.get('min_time'),
            )
        return None

    def _extract_has_more(self, data: Dict, provider_name: str) -> bool:
        """Extract has_more flag from response (supports has_more / hasMore)."""
        data = _as_dict(data)
        nested = _as_dict(data.get("data"))

        def pick_flag(*values) -> bool:
            for value in values:
                if value is not None:
                    return _truthy_flag(value)
            return False

        if provider_name == 'tiktok-api23':
            return pick_flag(
                data.get('has_more'), data.get('hasMore'),
                nested.get('has_more'), nested.get('hasMore'),
            )
        elif provider_name == 'tiktok-download-video1':
            return pick_flag(
                nested.get('has_more'), nested.get('hasMore'),
                data.get('has_more'), data.get('hasMore'),
            )
        elif provider_name == 'tiktok-scraper2':
            return pick_flag(
                data.get('has_more'), data.get('hasMore'),
                nested.get('has_more'), nested.get('hasMore'),
            )
        return False

    def _has_more_comments(self, data: Dict, provider_name: str) -> bool:
        """Check if there are more comments available for pagination"""
        data = _as_dict(data)
        # Prefer explicit flags when present
        if self._extract_has_more(data, provider_name):
            return True
        if provider_name == 'tiktok-api23':
            comments = data.get('comments')
            return isinstance(comments, list) and len(comments) > 0
        elif provider_name == 'tiktok-download-video1':
            return data.get('next_cursor') is not None
        elif provider_name == 'tiktok-scraper2':
            return data.get('next_cursor') is not None or data.get('min_time') is not None
        else:
            comments = data.get('comments')
            return isinstance(comments, list) and len(comments) > 0

    def _get_next_cursor(self, data: Dict, provider_name: str, current_cursor: int) -> Optional[int]:
        """Get the next cursor value for pagination"""
        data = _as_dict(data)
        extracted = self._extract_cursor(data, provider_name)
        if extracted is not None:
            try:
                return int(extracted)
            except (TypeError, ValueError):
                return extracted  # type: ignore[return-value]

        if provider_name == 'tiktok-api23':
            comments = data.get('comments')
            if isinstance(comments, list) and len(comments) > 0:
                return current_cursor + len(comments)
            return None
        else:
            comments = data.get('comments')
            if isinstance(comments, list) and len(comments) > 0:
                return current_cursor + len(comments)
            return None
