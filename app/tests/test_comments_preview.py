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
from adapters.comments_adapter import TikTokCommentsAdapter  # noqa: E402
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
