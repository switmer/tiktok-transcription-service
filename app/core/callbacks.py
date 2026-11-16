"""Send the task-finished webhook to a caller-supplied callback_url.

callback_url comes from a public endpoint, so the server must not be tricked into
calling internal addresses. We allow only http(s) and refuse private, loopback and
link-local targets. We connect to the IP we checked (not a second DNS lookup) and
never follow redirects.
"""
import asyncio
import ipaddress
import logging
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


def resolve_safe_callback(callback_url: str) -> Optional[Tuple[str, str]]:
    """Return (url_with_checked_ip, hostname), or None if the URL is not safe."""
    try:
        parts = urlsplit(callback_url)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            return None
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not infos:
            return None
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    except (ValueError, OSError):
        return None
    # Every address must be public: a host with one private record is refused.
    if not all(ip.is_global for ip in ips):
        return None
    ip = ips[0]
    ip_text = f"[{ip}]" if ip.version == 6 else str(ip)
    netloc = f"{ip_text}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host


async def send_task_callback(callback_url: Optional[str], payload: Dict[str, Any]) -> None:
    """POST payload to callback_url. Never raises: a callback failure must not fail the task."""
    if not callback_url:
        return
    try:
        target = await asyncio.to_thread(resolve_safe_callback, callback_url)
        if target is None:
            logger.warning(f"Refused unsafe callback_url for task {payload.get('task_id')}")
            return
        url, host = target
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            await client.post(
                url,
                json=payload,
                headers={"Host": host},
                extensions={"sni_hostname": host},
            )
    except Exception as e:
        logger.error(f"Callback failed for task {payload.get('task_id')}: {e}")
