"""Find video links on a public web page without downloading media.

This module implements video discovery for generic web pages (not known platforms).
It uses yt-dlp first, then falls back to parsing page HTML for video embeds.

SSRF Protection:
- Only http/https schemes allowed
- Resolves hostnames and blocks private/loopback/link-local IPs
- Limits redirects, timeouts, and response size
"""

from __future__ import annotations

import ipaddress
import json
import logging
import shutil
import socket
import subprocess
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB
REQUEST_TIMEOUT = 15
MAX_REDIRECTS = 5

_VIDEO_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com",
    "wistia.com", "wistia.net", "loom.com", "x.com", "twitter.com",
    "instagram.com", "tiktok.com", "dailymotion.com", "player.vimeo.com",
    "fast.wistia.net",
)

_MEDIA_EXTENSIONS = (".mp4", ".webm", ".mov", ".m3u8", ".mpd", ".ogg", ".ogv")

_SCORES = {
    "yt_dlp": 100,
    "og:video": 90,
    "twitter:player": 88,
    "json_ld": 85,
    "video_tag": 80,
    "iframe": 70,
    "media_link": 55,
    "platform_link": 40,
}


class SSRFError(ValueError):
    """Raised when a URL would cause a server-side request forgery."""
    pass


def _resolve_and_check_ip(hostname: str) -> None:
    """Resolve hostname to IP and check it's not private/loopback/link-local."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"Cannot resolve hostname: {hostname}") from e

    for family, _, _, _, sockaddr in results:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise SSRFError(f"Private/loopback/link-local IP not allowed: {ip_str}")
        if ip.is_multicast:
            raise SSRFError(f"Multicast IP not allowed: {ip_str}")


def _validate_url(url: str) -> str:
    """Validate URL is safe to fetch (SSRF protection)."""
    url = url.strip()
    parsed = urlsplit(url)
    host = parsed.hostname or ""

    if parsed.scheme not in ("http", "https"):
        raise SSRFError("Only http:// and https:// URLs are allowed")
    if not host:
        raise SSRFError("URL must have a hostname")
    if parsed.username or parsed.password:
        raise SSRFError("URLs with credentials are not allowed")

    host_lower = host.lower()
    if host_lower in ("localhost", "127.0.0.1", "::1"):
        raise SSRFError("Localhost URLs are not allowed")
    if host_lower.endswith((".localhost", ".local", ".internal", ".localdomain")):
        raise SSRFError("Local domain URLs are not allowed")

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise SSRFError(f"Non-global IP not allowed: {host}")
    except ValueError:
        _resolve_and_check_ip(host)

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _video_host(host: str) -> bool:
    """Check if host is a known video platform."""
    host = host.lower()
    return any(host == domain or host.endswith("." + domain) for domain in _VIDEO_HOSTS)


def _platform_video_page(url: str) -> bool:
    """Check if URL is a video page on a known platform."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()

    if host == "youtu.be" or host.endswith(".youtu.be"):
        return bool(path.strip("/"))
    if host == "youtube.com" or host.endswith(".youtube.com"):
        return path.startswith(("/watch", "/shorts/", "/live/", "/embed/"))
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        parts = path.strip("/").split("/")
        return len(parts) > 0 and parts[0].isdigit()
    if "player.vimeo.com" in host:
        return "/video/" in path
    if host == "loom.com" or host.endswith(".loom.com"):
        return path.startswith(("/share/", "/embed/"))
    if host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com")):
        return "/status/" in path
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return any(p in path for p in ("/reel/", "/p/", "/tv/", "/reels/"))
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "/video/" in path or "@" in path
    if host.endswith(("wistia.com", "wistia.net")):
        return "/medias/" in path or "/embed/" in path
    if host == "dailymotion.com" or host.endswith(".dailymotion.com"):
        return "/video/" in path
    return False


def _yt_dlp_video(url: str) -> dict | None:
    """Try to extract video info using yt-dlp (without downloading)."""
    executable = shutil.which("yt-dlp")
    if not executable:
        logger.debug("yt-dlp not found in PATH")
        return None

    try:
        result = subprocess.run(
            [executable, "--ignore-config", "--dump-single-json", "--skip-download",
             "--no-playlist", "--no-warnings", "--quiet", url],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            logger.debug(f"yt-dlp failed for {url}: {result.stderr[:200]}")
            return None

        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            return None
        if data.get("_type") == "playlist":
            return None
        if not any(data.get(key) for key in ("id", "url", "formats", "webpage_url")):
            return None

        return {
            "url": data.get("webpage_url") or url,
            "source": "yt_dlp",
            "score": _SCORES["yt_dlp"],
            "reason": "yt-dlp recognized this page",
            "title": data.get("title"),
        }
    except subprocess.TimeoutExpired:
        logger.debug(f"yt-dlp timed out for {url}")
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"yt-dlp error for {url}: {e}")
        return None


def _json_ld_videos(value) -> list[str]:
    """Extract video URLs from JSON-LD structured data."""
    results = []

    if isinstance(value, list):
        for item in value:
            results.extend(_json_ld_videos(item))
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(str(t).rsplit("/", 1)[-1] == "VideoObject" for t in types):
            for key in ("contentUrl", "embedUrl", "url"):
                link = value.get(key)
                if isinstance(link, str) and link.strip():
                    results.append(link.strip())
        for key in ("@graph", "mainEntity", "itemListElement", "video"):
            if key in value:
                results.extend(_json_ld_videos(value[key]))

    return results


def _fetch_page(url: str) -> tuple[str | None, str | None, int | None]:
    """Fetch page HTML with SSRF protection. Returns (html, final_url, status_code)."""
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = session.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )

        final_url = response.url
        try:
            _validate_url(final_url)
        except SSRFError as e:
            logger.warning(f"Redirect to unsafe URL blocked: {e}")
            return None, None, None

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "xml" not in content_type:
            logger.debug(f"Non-HTML content type: {content_type}")
            return None, final_url, response.status_code

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_SIZE:
            logger.warning(f"Response too large: {content_length} bytes")
            return None, final_url, response.status_code

        chunks = []
        total_size = 0
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
            total_size += len(chunk)
            if total_size > MAX_RESPONSE_SIZE:
                logger.warning("Response exceeded size limit during download")
                return None, final_url, response.status_code
            chunks.append(chunk)

        html = b"".join(chunks).decode("utf-8", errors="replace")
        return html, final_url, response.status_code

    except requests.exceptions.TooManyRedirects:
        logger.warning(f"Too many redirects for {url}")
        return None, None, None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request failed for {url}: {e}")
        return None, None, None


def _parse_candidates(html: str, page_url: str) -> list[dict]:
    """Parse HTML for video candidates and return them ranked by score."""
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, dict] = {}

    def add(raw: str | None, source: str, *, in_main: bool = False) -> None:
        if not raw:
            return
        link = urljoin(page_url, raw.strip())
        try:
            link = _validate_url(link)
        except SSRFError:
            return

        score = _SCORES[source] + (5 if in_main else 0)
        candidate = {
            "url": link,
            "source": source,
            "score": score,
            "reason": source.replace("_", " ") + (" in main content" if in_main else ""),
        }
        if link not in found or score > found[link]["score"]:
            found[link] = candidate

    for tag in soup.select("meta[property], meta[name]"):
        name = (tag.get("property") or tag.get("name") or "").lower()
        if name in ("og:video", "og:video:url", "og:video:secure_url"):
            add(tag.get("content"), "og:video")
        elif name in ("twitter:player", "twitter:player:stream"):
            add(tag.get("content"), "twitter:player")

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            text = script.string or script.get_text()
            if text:
                for link in _json_ld_videos(json.loads(text)):
                    add(link, "json_ld")
        except (ValueError, TypeError):
            continue

    for tag in soup.select("video[src], video source[src]"):
        in_main = bool(tag.find_parent("main") or tag.find_parent("article"))
        add(tag.get("src"), "video_tag", in_main=in_main)

    for tag in soup.select("iframe[src]"):
        src = tag.get("src", "")
        if not src:
            continue
        link = urljoin(page_url, src)
        parsed = urlsplit(link)
        if _video_host(parsed.hostname or ""):
            in_main = bool(tag.find_parent("main") or tag.find_parent("article"))
            add(src, "iframe", in_main=in_main)

    for tag in soup.select("a[href]"):
        href = tag.get("href", "")
        if not href:
            continue
        link = urljoin(page_url, href)
        parsed = urlsplit(link)
        path_lower = parsed.path.lower()

        if any(path_lower.endswith(ext) for ext in _MEDIA_EXTENSIONS):
            in_main = bool(tag.find_parent("main") or tag.find_parent("article"))
            add(href, "media_link", in_main=in_main)
        elif _platform_video_page(link):
            in_main = bool(tag.find_parent("main") or tag.find_parent("article"))
            add(href, "platform_link", in_main=in_main)

    return sorted(found.values(), key=lambda item: -item["score"])


def find_videos(url: str, *, try_yt_dlp: bool = True) -> dict:
    """Find the best video link and alternatives for a web page.

    Args:
        url: The web page URL to scan for videos
        try_yt_dlp: Whether to try yt-dlp first (default True)

    Returns:
        dict with keys:
            - page_url: The original URL
            - status: "found", "not_found", or "unavailable"
            - top: The best video candidate (dict with url, source, score, reason) or None
            - alternates: List of other video candidates
            - checked: List of methods checked
            - message: Human-readable status message (optional)
    """
    try:
        url = _validate_url(url)
    except SSRFError as e:
        return {
            "page_url": url,
            "status": "unavailable",
            "top": None,
            "alternates": [],
            "checked": [],
            "message": str(e),
        }

    checked: list[str] = []

    if try_yt_dlp:
        checked.append("yt-dlp")
        match = _yt_dlp_video(url)
        if match:
            logger.info(f"yt-dlp found video on {url}")
            return {
                "page_url": url,
                "status": "found",
                "top": match,
                "alternates": [],
                "checked": checked,
            }

    parsed = urlsplit(url)
    if parsed.path.lower().endswith(_MEDIA_EXTENSIONS):
        match = {
            "url": url,
            "source": "media_link",
            "score": _SCORES["media_link"],
            "reason": "direct media URL",
        }
        return {
            "page_url": url,
            "status": "found",
            "top": match,
            "alternates": [],
            "checked": checked,
        }

    checked.append("page HTML")
    html, final_url, status_code = _fetch_page(url)

    if html is None or status_code != 200:
        return {
            "page_url": url,
            "status": "unavailable",
            "top": None,
            "alternates": [],
            "checked": checked,
            "message": "The page could not be fetched",
        }

    candidates = _parse_candidates(html, final_url or url)

    if not candidates:
        return {
            "page_url": url,
            "status": "not_found",
            "top": None,
            "alternates": [],
            "checked": checked,
            "message": "No video found in page metadata or HTML",
        }

    logger.info(f"Found {len(candidates)} video candidate(s) on {url}")

    return {
        "page_url": url,
        "status": "found",
        "top": candidates[0],
        "alternates": candidates[1:],
        "checked": checked,
    }
