"""Checks for task statuses and the callback_url webhook. No network, no live DB."""
import ipaddress
import os
import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
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


def test_extension_poll_loop_only_checks_backend_statuses():
    js_path = os.path.join(_root, "chrome-extension", "sidepanel.js")
    js = open(js_path, encoding="utf-8").read()
    used = set(re.findall(r"task\.status === '([a-z_]+)'", js))
    assert used == ALLOWED, f"extension checks statuses the backend never sends: {used - ALLOWED}"


@pytest.mark.parametrize("url", [
    "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "http://", "not a url",
    "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/x", "http://192.168.1.1/x",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/x", "http://0.0.0.0/x",
    "http://[64:ff9b::7f00:1]/x", "http://[64:ff9b::a9fe:a9fe]/x", "http://[2002:7f00:1::]/x",
    "http://[::127.0.0.1]/x", "http://[::ffff:127.0.0.1]/x", "http://224.0.0.1/x",
    "http://[::ffff:0:7f00:1]/x", "http://[::ffff:0:a9fe:a9fe]/x", "http://[fec0::1]/x",
    "http://2130706433/x", "http://0x7f.1/x", "http://127.0.0.1:80@example.com.invalid/x",
])
def test_unsafe_callback_urls_refused(url):
    def resolve(host, port, **kwargs):
        # Keep this suite offline, including platform-specific numeric host forms.
        aliases = {"localhost": "127.0.0.1", "2130706433": "127.0.0.1", "0x7f.1": "127.0.0.1"}
        try:
            address = str(ipaddress.ip_address(aliases.get(host, host)))
        except ValueError:
            raise OSError("test hostname has no records")
        return _public(address)

    with patch.object(callbacks.socket, "getaddrinfo", side_effect=resolve):
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
        url, host, host_header = callbacks.resolve_safe_callback("https://example.com/hook?a=1")
    assert url == "https://93.184.216.34:443/hook?a=1" and host == "example.com" and host_header == "example.com"


def test_host_header_brackets_ipv6_literal():
    _, _, h = callbacks.resolve_safe_callback("http://[2606:4700::1111]:8080/x")
    assert h == "[2606:4700::1111]:8080"


def test_host_header_keeps_non_default_port():
    with patch.object(callbacks.socket, "getaddrinfo", return_value=_public("93.184.216.34")):
        _, _, host_header = callbacks.resolve_safe_callback("https://example.com:8443/hook")
    assert host_header == "example.com:8443"


@pytest.mark.asyncio
async def test_send_callback_posts_to_checked_ip_without_redirects():
    client = MagicMock()
    client.stream.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False))
    ctx = MagicMock(__aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock(return_value=False))
    with patch.object(callbacks.socket, "getaddrinfo", return_value=_public("93.184.216.34")), \
         patch.object(callbacks.httpx, "AsyncClient", return_value=ctx) as cls:
        await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t", "status": "completed"})
    assert cls.call_args.kwargs["follow_redirects"] is False
    assert client.stream.call_args.args[:2] == ("POST", "https://93.184.216.34:443/hook")
    assert client.stream.call_args.kwargs["headers"] == {"Host": "example.com"}
    assert client.stream.call_args.kwargs["extensions"] == {"sni_hostname": "example.com"}


@pytest.mark.asyncio
async def test_send_callback_skips_unsafe_url():
    with patch.object(callbacks.httpx, "AsyncClient") as cls:
        await callbacks.send_task_callback("http://127.0.0.1/x", {"task_id": "t"})
    cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_callback_failure_does_not_raise():
    with patch.object(callbacks.socket, "getaddrinfo", side_effect=OSError("dns down")):
        await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t"})
    with patch.object(callbacks, "resolve_safe_callback", return_value=("https://1.1.1.1:443/", "x", "x")), \
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


@pytest.mark.asyncio
async def test_callback_refuses_new_lookups_while_all_dns_slots_are_busy():
    import threading
    from app.core import callbacks
    release = threading.Event()

    def stuck_lookup(url):
        release.wait(5)
        return None

    posted = []
    with patch.object(callbacks, "resolve_safe_callback", stuck_lookup), \
         patch.object(callbacks, "_DNS_WORKERS", 2), \
         patch.object(callbacks.asyncio, "wait_for", side_effect=asyncio.TimeoutError):
        for _ in range(3):
            await callbacks.send_task_callback("https://example.com/hook", {"task_id": "t"})
        assert callbacks._dns_in_flight == 2  # third call was refused, not queued
        release.set()
        for _ in range(50):
            if callbacks._dns_in_flight == 0:
                break
            await asyncio.sleep(0.02)
        assert callbacks._dns_in_flight == 0
