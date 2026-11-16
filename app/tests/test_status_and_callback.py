"""Checks for task statuses and the callback_url webhook. No network, no live DB."""
import os
import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.core import callbacks
from app.models.schemas import TranscriptionResponse

ALLOWED = {"pending", "processing", "completed", "failed"}
APP_PY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


def _public(host_ip):
    return [(2, 1, 6, "", (host_ip, 443))]


def test_backend_only_writes_allowed_statuses():
    src = open(APP_PY, encoding="utf-8").read()
    written = set(re.findall(r'update_task_status\(\s*task_id,\s*"([a-z_]+)"', src))
    assert written <= ALLOWED, f"unsupported statuses written: {written - ALLOWED}"


def test_response_model_matches_allowed_statuses():
    for status in ALLOWED:
        TranscriptionResponse(task_id="t", status=status, created_at="2025-01-01T00:00:00Z")
    with pytest.raises(Exception):
        TranscriptionResponse(task_id="t", status="transcribing", created_at="2025-01-01T00:00:00Z")


@pytest.mark.parametrize("url", [
    "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "http://", "not a url",
    "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/x", "http://192.168.1.1/x",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/x", "http://0.0.0.0/x",
])
def test_unsafe_callback_urls_refused(url):
    assert callbacks.resolve_safe_callback(url) is None


def test_hostname_resolving_to_private_ip_refused():
    with patch.object(callbacks.socket, "getaddrinfo", return_value=_public("10.1.2.3")):
        assert callbacks.resolve_safe_callback("https://evil.example.com/hook") is None


def test_mixed_public_and_private_records_refused():
    infos = _public("8.8.8.8") + _public("127.0.0.1")
    with patch.object(callbacks.socket, "getaddrinfo", return_value=infos):
        assert callbacks.resolve_safe_callback("https://evil.example.com/hook") is None


def test_public_url_pins_checked_ip():
    with patch.object(callbacks.socket, "getaddrinfo", return_value=_public("93.184.216.34")):
        url, host = callbacks.resolve_safe_callback("https://example.com/hook?a=1")
    assert url == "https://93.184.216.34:443/hook?a=1" and host == "example.com"


@pytest.mark.asyncio
async def test_send_callback_posts_to_checked_ip_without_redirects():
    client = MagicMock()
    client.post = AsyncMock()
    ctx = MagicMock(__aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock(return_value=False))
    with patch.object(callbacks.socket, "getaddrinfo", return_value=_public("93.184.216.34")), \
         patch.object(callbacks.httpx, "AsyncClient", return_value=ctx) as cls:
        await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t", "status": "completed"})
    assert cls.call_args.kwargs["follow_redirects"] is False
    assert client.post.call_args.args[0] == "https://93.184.216.34:443/hook"
    assert client.post.call_args.kwargs["headers"] == {"Host": "example.com"}


@pytest.mark.asyncio
async def test_send_callback_skips_unsafe_url():
    with patch.object(callbacks.httpx, "AsyncClient") as cls:
        await callbacks.send_task_callback("http://127.0.0.1/x", {"task_id": "t"})
    cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_callback_failure_does_not_raise():
    with patch.object(callbacks.socket, "getaddrinfo", side_effect=OSError("dns down")):
        await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t"})
    with patch.object(callbacks, "resolve_safe_callback", return_value=("https://1.1.1.1:443/", "x")), \
         patch.object(callbacks.httpx, "AsyncClient", side_effect=RuntimeError("boom")):
        await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t"})


@pytest.mark.parametrize("final_status", ["completed", "failed", "pending"])
@pytest.mark.asyncio
async def test_pipeline_posts_callback_on_final_status(final_status):
    import importlib
    app_module = importlib.import_module("app.app")
    row = MagicMock(data={"status": final_status, "error": None, "video_id": "v", "title": "T", "thumbnail_url": None})
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = row
    with patch.object(app_module, "supabase", sb), \
         patch.object(app_module, "_run_transcription_task", new=AsyncMock()), \
         patch.object(app_module, "send_task_callback", new=AsyncMock()) as send:
        await app_module.process_transcription_task("tid", "u", "https://example.com/hook", None)
    if final_status == "pending":
        send.assert_not_called()
    else:
        send.assert_awaited_once()
        assert send.call_args.args[1]["status"] == final_status
