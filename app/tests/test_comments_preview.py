"""
Tests for TikTok-only, non-blocking comment preview/fetch APIs.

Covers:
- Unsupported platforms → HTTP 422 (adapter not called)
- Preview timeout → HTTP 504
- All providers 5xx → HTTP 503 (not 200 with zero estimates)
- Preview uses a single attempt per provider (no retry backoff)
- Genuine TikTok video with zero comments → HTTP 200

All network is mocked; fixtures contain no real user data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

# Project root + app/ so `app` package and `adapters` absolute imports both work
_APP_DIR = os.path.dirname(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.dirname(_APP_DIR)
for _path in (_PROJECT_ROOT, _APP_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import importlib  # noqa: E402

from app.app import app as fastapi_app  # noqa: E402
from adapters.comments_adapter import (  # noqa: E402
    TikTokCommentsAdapter,
    UnusableCommentsResponse,
    clear_comments_caches,
)
_app_mod = importlib.import_module("app.app")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data):
        self.data = data


def _chain(final_data):
    """Build a chainable supabase table mock that ends in .execute() → data."""
    terminal = Mock()
    terminal.execute.return_value = _Resp(final_data)
    # Every chaining method returns something that can continue chaining
    # and ultimately execute.
    node = terminal
    for _ in range(8):
        parent = Mock()
        for method in (
            "select", "eq", "order", "limit", "single", "maybe_single",
            "insert", "update", "upsert", "range",
        ):
            getattr(parent, method).return_value = node
        parent.execute.return_value = _Resp(final_data)
        node = parent
    return node


def _http_resp(status_code=200, payload=None, headers=None):
    resp = Mock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = ""
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status = Mock()
    resp.json.return_value = payload if payload is not None else {}
    return resp


@pytest.fixture(autouse=True)
def _clear_comment_caches():
    clear_comments_caches()
    yield
    clear_comments_caches()


@pytest.fixture
def client():
    return TestClient(fastapi_app)


def _task(
    *,
    platform="tiktok",
    video_id="1234567890123456789",
    url="https://www.tiktok.com/@demo/video/1234567890123456789",
    comments_fetched=False,
    comment_count=0,
):
    return {
        "task_id": "00000000-0000-4000-8000-000000000001",
        "video_id": video_id,
        "video_url": url,
        "url": url,
        "platform": platform,
        "comments_fetched": comments_fetched,
        "comment_count": comment_count,
        "user_phone": None,
    }


# ---------------------------------------------------------------------------
# Endpoint: unsupported platform → 422, adapter never called
# ---------------------------------------------------------------------------

class TestUnsupportedPlatform:
    def test_preview_non_tiktok_returns_422_and_skips_adapter(self, client):
        task = _task(
            platform="youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_id="dQw4w9WgXcQ",
        )
        mock_sb = Mock()
        mock_sb.table.return_value = _chain(task)

        with patch("app.app.supabase", mock_sb), \
             patch("adapters.comments_adapter.TikTokCommentsAdapter") as MockAdapter:
            response = client.get(
                "/api/public/comments/preview/00000000-0000-4000-8000-000000000001"
            )

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "unsupported_platform"
        assert body["platform"] == "youtube"
        assert body["message"] == "Comment research is TikTok-only for now."
        MockAdapter.assert_not_called()

    def test_fetch_non_tiktok_returns_422_and_skips_adapter(self, client):
        task = _task(
            platform="instagram",
            url="https://www.instagram.com/reel/ABC123/",
            video_id="ABC123",
        )
        mock_sb = Mock()
        mock_sb.table.return_value = _chain([task])

        fastapi_app.dependency_overrides[_app_mod.verify_api_key] = lambda: "test-key"
        try:
            with patch("app.app.supabase", mock_sb), \
                 patch("adapters.comments_adapter.TikTokCommentsAdapter") as MockAdapter:
                response = client.post(
                    "/api/pro/comments/fetch",
                    json={"task_id": task["task_id"], "get_all": False},
                )
            assert response.status_code == 422
            body = response.json()
            assert body["error"] == "unsupported_platform"
            assert body["platform"] == "instagram"
            assert "TikTok-only" in body["message"]
            MockAdapter.assert_not_called()
        finally:
            fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Endpoint: preview timeout → 504
# ---------------------------------------------------------------------------

class TestPreviewTimeout:
    def test_preview_timeout_returns_504(self, client):
        task = _task()
        mock_sb = Mock()
        mock_sb.table.return_value = _chain(task)

        mock_adapter = MagicMock()
        # Never called if wait_for raises first; still provide a safe stub
        mock_adapter.fetch_comments.return_value = {
            "comments": [], "error": None, "has_more": False, "provider": None
        }

        async def _timeout(awaitable, *args, **kwargs):
            # Close the pending to_thread awaitable to avoid "never awaited" warnings
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError()

        with patch("app.app.supabase", mock_sb), \
             patch.dict(os.environ, {"RAPIDAPI_KEY": "test-key"}), \
             patch("adapters.comments_adapter.TikTokCommentsAdapter", return_value=mock_adapter), \
             patch("app.app.asyncio.wait_for", side_effect=_timeout):
            response = client.get(
                "/api/public/comments/preview/00000000-0000-4000-8000-000000000001"
            )

        assert response.status_code == 504
        body = response.json()
        assert body["error"] == "preview_timeout"


# ---------------------------------------------------------------------------
# Endpoint: provider failures → 503; zero comments → 200
# ---------------------------------------------------------------------------

class TestPreviewProviderErrors:
    def test_all_providers_failed_returns_503(self, client):
        task = _task()
        mock_sb = Mock()
        mock_sb.table.return_value = _chain(task)

        mock_adapter = MagicMock()
        mock_adapter.fetch_comments.return_value = {
            "comments": [],
            "cursor": None,
            "has_more": False,
            "provider": None,
            "error": "All providers failed",
        }

        with patch("app.app.supabase", mock_sb), \
             patch.dict(os.environ, {"RAPIDAPI_KEY": "test-key"}), \
             patch("adapters.comments_adapter.TikTokCommentsAdapter", return_value=mock_adapter):
            response = client.get(
                "/api/public/comments/preview/00000000-0000-4000-8000-000000000001"
            )

        assert response.status_code == 503
        body = response.json()
        assert body["error"] == "All providers failed"
        assert "estimated_total" not in body
        assert "credits_needed" not in body

    def test_genuine_zero_comments_returns_200(self, client):
        task = _task(comment_count=0)
        mock_sb = Mock()
        mock_sb.table.return_value = _chain(task)

        mock_adapter = MagicMock()
        mock_adapter.fetch_comments.return_value = {
            "comments": [],
            "cursor": None,
            "has_more": False,
            "provider": "tiktok-api23",
            "error": None,
        }

        with patch("app.app.supabase", mock_sb), \
             patch.dict(os.environ, {"RAPIDAPI_KEY": "test-key"}), \
             patch("adapters.comments_adapter.TikTokCommentsAdapter", return_value=mock_adapter):
            response = client.get(
                "/api/public/comments/preview/00000000-0000-4000-8000-000000000001"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["preview_comments"] == []
        assert body["estimated_total"] == 0
        assert body["credits_needed"] == 0


# ---------------------------------------------------------------------------
# Adapter: preview = one attempt per provider, fail-fast on 5xx, no sleeps
# ---------------------------------------------------------------------------

class TestAdapterPreviewFailFast:
    def test_preview_single_attempt_per_provider_on_5xx(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        call_hosts = []

        def fake_get(url, headers=None, params=None, timeout=None):
            host = headers.get("X-RapidAPI-Host")
            call_hosts.append(host)
            resp = Mock()
            resp.status_code = 503
            resp.raise_for_status.side_effect = Exception("should not retry raise_for_status")
            resp.json.return_value = {}
            return resp

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get), \
             patch("adapters.comments_adapter.time.sleep") as mock_sleep:
            result = adapter.fetch_comments(
                "1234567890123456789", count=20, get_all=False, preview=True
            )

        assert result.get("error") == "All providers failed"
        # Exactly one HTTP call per configured provider
        assert len(call_hosts) == len(adapter.providers)
        assert len(call_hosts) == len(set(call_hosts))
        mock_sleep.assert_not_called()

    def test_preview_success_with_empty_comments_is_not_error(self):
        adapter = TikTokCommentsAdapter(["test-key"])

        def fake_get(url, headers=None, params=None, timeout=None):
            resp = Mock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            # Empty comments list — genuine zero-comment video
            resp.json.return_value = {"comments": [], "has_more": False, "cursor": None}
            return resp

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get), \
             patch("adapters.comments_adapter.time.sleep") as mock_sleep:
            result = adapter.fetch_comments(
                "1234567890123456789", count=20, get_all=False, preview=True
            )

        assert result.get("error") is None
        assert result.get("comments") == []
        assert result.get("provider") == "tiktok-api23"
        # Only first provider should be hit on success
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Adapter: parsing robustness + hasMore camelCase
# ---------------------------------------------------------------------------

class TestCommentParsers:
    def test_api23_null_comments_is_unusable_not_crash(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        with pytest.raises(UnusableCommentsResponse, match="comments is null"):
            adapter._parse_api23({"comments": None, "hasMore": 0})

    def test_api23_null_avatar_still_parses_comment(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        comments = adapter._parse_api23({
            "comments": [{
                "cid": "1",
                "text": "hello",
                "user": {
                    "nickname": "Ada",
                    "unique_id": "ada",
                    "avatar_thumb": None,
                },
                "create_time": 1,
                "digg_count": 2,
                "reply_comment_total": 0,
                "aweme_id": "vid",
            }],
            "hasMore": 1,
        })
        assert len(comments) == 1
        assert comments[0].text == "hello"
        assert comments[0].author_avatar is None
        assert adapter._extract_has_more({"hasMore": 1}, "tiktok-api23") is True

    def test_downloadvideo1_null_data_is_unusable(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        with pytest.raises(UnusableCommentsResponse):
            adapter._validate_provider_payload(
                adapter.providers[1],
                {"code": -1, "msg": "fail", "data": None},
            )

    def test_downloadvideo1_parses_hasMore_and_comments(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        payload = {
            "code": 0,
            "msg": "success",
            "data": {
                "comments": [{
                    "id": "9",
                    "text": "nice",
                    "user": {"nickname": "Bob", "unique_id": "bob", "avatar": "https://x"},
                    "create_time": 11,
                    "digg_count": 3,
                    "reply_total": 1,
                }],
                "cursor": 10,
                "hasMore": True,
            },
        }
        comments = adapter._parse_downloadvideo1(payload)
        assert len(comments) == 1
        assert comments[0].author_avatar == "https://x"
        assert adapter._extract_has_more(payload, "tiktok-download-video1") is True
        assert adapter._extract_cursor(payload, "tiktok-download-video1") == 10

    def test_preview_unusable_body_falls_through_providers(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            host = headers.get("X-RapidAPI-Host")
            calls.append(host)
            if host == "tiktok-api23.p.rapidapi.com":
                # Exact production failure mode: HTTP 200 + comments:null
                return _http_resp(200, {"comments": None, "hasMore": 0})
            if host == "tiktok-download-video1.p.rapidapi.com":
                return _http_resp(403, {"message": "You are not subscribed to this API."})
            return _http_resp(403, {"message": "You are not subscribed to this API."})

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get), \
             patch("adapters.comments_adapter.time.sleep") as mock_sleep:
            result = adapter.fetch_comments("123", count=20, preview=True)

        assert result["error"] == "All providers failed"
        assert len(calls) == 3
        assert any("null" in (e or "") for e in result.get("provider_errors") or [])
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Adapter: preview cache + 429 cooldown
# ---------------------------------------------------------------------------

class TestPreviewCacheAndCooldown:
    def test_preview_success_cached_skips_http_on_second_call(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(headers.get("X-RapidAPI-Host"))
            return _http_resp(200, {
                "comments": [{
                    "cid": "1",
                    "text": "cached",
                    "user": {"nickname": "N", "unique_id": "n"},
                    "create_time": 1,
                    "digg_count": 0,
                    "reply_comment_total": 0,
                    "aweme_id": "v",
                }],
                "hasMore": 0,
            })

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get):
            first = adapter.fetch_comments("vid-cache-1", count=20, preview=True)
            second = adapter.fetch_comments("vid-cache-1", count=20, preview=True)

        assert first["error"] is None
        assert second["error"] is None
        assert len(first["comments"]) == 1
        assert len(second["comments"]) == 1
        assert len(calls) == 1  # second call served from cache

    def test_preview_negative_cache_skips_providers(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(headers.get("X-RapidAPI-Host"))
            return _http_resp(503, {})

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get):
            first = adapter.fetch_comments("vid-neg-1", count=20, preview=True)
            second = adapter.fetch_comments("vid-neg-1", count=20, preview=True)

        assert first["error"] == "All providers failed"
        assert second["error"] == "All providers failed"
        assert len(calls) == len(adapter.providers)
        assert second.get("provider_errors") == first.get("provider_errors")

    def test_429_sets_cooldown_and_skips_provider_next_request(self):
        adapter = TikTokCommentsAdapter(["test-key"])
        adapter.provider_cooldown_seconds = 3600
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            host = headers.get("X-RapidAPI-Host")
            calls.append(host)
            if host == "tiktok-api23.p.rapidapi.com":
                return _http_resp(429, {"message": "Too many requests"}, headers={"Retry-After": "120"})
            # Fallback succeeds
            return _http_resp(200, {
                "code": 0,
                "data": {
                    "comments": [{
                        "id": "2",
                        "text": "from-fallback",
                        "user": {"nickname": "F", "unique_id": "f", "avatar": ""},
                        "create_time": 1,
                        "digg_count": 0,
                        "reply_total": 0,
                    }],
                    "hasMore": False,
                },
            })

        with patch("adapters.comments_adapter.requests.get", side_effect=fake_get):
            first = adapter.fetch_comments("vid-429-a", count=20, preview=True)
            # Different video so preview cache does not short-circuit
            second = adapter.fetch_comments("vid-429-b", count=20, preview=True)

        assert first["error"] is None
        assert first["provider"] == "tiktok-download-video1"
        assert second["provider"] == "tiktok-download-video1"
        # First request: api23 429 + downloadvideo1 success
        # Second request: api23 skipped via cooldown, only downloadvideo1
        assert calls.count("tiktok-api23.p.rapidapi.com") == 1
        assert calls.count("tiktok-download-video1.p.rapidapi.com") == 2
