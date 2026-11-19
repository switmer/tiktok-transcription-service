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


# is_global on some Python versions misses these ranges: they can wrap or tunnel to private IPv4
# addresses, or (fec0::/10, deprecated site-local) reach internal networks.
_BLOCKED_NETS = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "::/96", "::ffff:0:0:0/96", "fec0::/10")]


def _is_public(ip) -> bool:
    return ip.is_global and not ip.is_multicast and not any(ip in net for net in _BLOCKED_NETS)


def resolve_safe_callback(callback_url: str) -> Optional[Tuple[str, str]]:
    """Return (url_with_checked_ip, hostname, host_header), or None if the URL is not safe."""
    try:
        parts = urlsplit(callback_url)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            return None
        host = host.encode("idna").decode("ascii")  # non-ASCII names must be sent as ASCII
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not infos:
            return None
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    except (ValueError, OSError, UnicodeError):
        return None
    # Every address must be public: a host with one private record is refused.
    if not all(_is_public(ip) for ip in ips):
        return None
    ip = ips[0]
    ip_text = f"[{ip}]" if ip.version == 6 else str(ip)
    netloc = f"{ip_text}:{port}"
    default_port = 443 if parts.scheme == "https" else 80
    host_text = f"[{host}]" if ":" in host else host
    host_header = host_text if port == default_port else f"{host_text}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host, host_header


async def send_task_callback(callback_url: Optional[str], payload: Dict[str, Any]) -> None:
    """POST payload to callback_url. Never raises: a callback failure must not fail the task."""
    if not callback_url:
        return
    try:
        target = await asyncio.wait_for(asyncio.to_thread(resolve_safe_callback, callback_url), timeout=5)
        if target is None:
            logger.warning(f"Refused unsafe callback_url for task {payload.get('task_id')}")
            return
        url, host, host_header = target
        # Do not read the reply body (a hostile server could send endless data), and cap total time.
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async def post():
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"Host": host_header},
                    extensions={"sni_hostname": host},
                ):
                    pass
            await asyncio.wait_for(post(), timeout=15)
    except Exception as e:
        logger.error(f"Callback failed for task {payload.get('task_id')}: {e}")
