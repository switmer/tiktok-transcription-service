"""Unit tests for video_finder module.

Tests video discovery on web pages without making network requests.
Uses saved HTML fixtures for various scenarios.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from video_finder import (
    find_videos,
    _validate_url,
    _parse_candidates,
    _video_host,
    _platform_video_page,
    SSRFError,
)


# HTML Fixtures

HTML_YOUTUBE_EMBED = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:title" content="Product with YouTube Video">
</head>
<body>
    <article>
        <h1>Product with Custom Video</h1>
        <iframe width="560" height="315" 
            src="https://www.youtube.com/embed/dQw4w9WgXcQ" 
            frameborder="0" allowfullscreen></iframe>
    </article>
</body>
</html>
"""

HTML_OG_VIDEO = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:video" content="https://example.com/videos/main.mp4">
    <meta property="og:video:secure_url" content="https://example.com/videos/main.mp4">
    <meta property="og:title" content="Article with Video">
</head>
<body>
    <article>
        <p>This is an article with a video.</p>
    </article>
</body>
</html>
"""

HTML_VIDEO_TAG = """
<!DOCTYPE html>
<html>
<head><title>HTML5 Video Example</title></head>
<body>
    <main>
        <h1>Video Tutorial</h1>
        <video width="640" height="360" controls>
            <source src="/videos/tutorial.mp4" type="video/mp4">
            <source src="/videos/tutorial.webm" type="video/webm">
        </video>
    </main>
</body>
</html>
"""

HTML_MULTIPLE_VIDEOS = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:video" content="https://example.com/main-video.mp4">
</head>
<body>
    <main>
        <iframe src="https://www.youtube.com/embed/abc123" width="560" height="315"></iframe>
        <video src="/videos/secondary.mp4" controls></video>
        <a href="https://vimeo.com/123456789">Watch on Vimeo</a>
        <a href="/files/bonus.mp4">Download bonus video</a>
    </main>
</body>
</html>
"""

HTML_NO_VIDEO = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:title" content="Text Article">
    <meta property="og:type" content="article">
</head>
<body>
    <article>
        <h1>This is a text-only article</h1>
        <p>No videos here, just text content.</p>
        <img src="/images/photo.jpg" alt="Just an image">
    </article>
</body>
</html>
"""

HTML_JSON_LD_VIDEO = """
<!DOCTYPE html>
<html>
<head>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": "Product Demo",
        "contentUrl": "https://cdn.example.com/videos/demo.mp4",
        "embedUrl": "https://example.com/embed/demo",
        "thumbnailUrl": "https://example.com/thumb.jpg"
    }
    </script>
</head>
<body>
    <h1>Product Demo Page</h1>
</body>
</html>
"""

HTML_WISTIA_EMBED = """
<!DOCTYPE html>
<html>
<head><title>Loom and Wistia Examples</title></head>
<body>
    <main>
        <iframe src="https://fast.wistia.net/embed/iframe/abc123xyz" allowfullscreen></iframe>
        <a href="https://www.loom.com/share/123456abcdef">Watch the Loom recording</a>
    </main>
</body>
</html>
"""


class TestSSRFProtection:
    """Test SSRF protection in URL validation."""

    def test_validates_https_url(self):
        """Valid HTTPS URLs should pass."""
        result = _validate_url("https://example.com/page")
        assert result == "https://example.com/page"

    def test_validates_http_url(self):
        """Valid HTTP URLs should pass."""
        result = _validate_url("http://example.com/page")
        assert result == "http://example.com/page"

    def test_rejects_file_scheme(self):
        """file:// URLs should be rejected."""
        with pytest.raises(SSRFError, match="http:// and https://"):
            _validate_url("file:///etc/passwd")

    def test_rejects_ftp_scheme(self):
        """ftp:// URLs should be rejected."""
        with pytest.raises(SSRFError, match="http:// and https://"):
            _validate_url("ftp://example.com/file")

    def test_rejects_localhost(self):
        """localhost URLs should be rejected."""
        with pytest.raises(SSRFError, match="Localhost"):
            _validate_url("http://localhost/admin")

    def test_rejects_127_0_0_1(self):
        """127.0.0.1 URLs should be rejected."""
        with pytest.raises(SSRFError, match="Localhost"):
            _validate_url("http://127.0.0.1/admin")

    def test_rejects_local_domain(self):
        """.local domain URLs should be rejected."""
        with pytest.raises(SSRFError, match="Local domain"):
            _validate_url("http://server.local/admin")

    def test_rejects_internal_domain(self):
        """.internal domain URLs should be rejected."""
        with pytest.raises(SSRFError, match="Local domain"):
            _validate_url("http://api.internal/secret")

    def test_rejects_private_ip(self):
        """Private IP addresses should be rejected."""
        with pytest.raises(SSRFError):
            _validate_url("http://192.168.1.1/admin")

    def test_rejects_link_local_ip(self):
        """Link-local IP addresses should be rejected."""
        with pytest.raises(SSRFError):
            _validate_url("http://169.254.1.1/metadata")

    def test_rejects_credentials_in_url(self):
        """URLs with credentials should be rejected."""
        with pytest.raises(SSRFError, match="credentials"):
            _validate_url("http://user:pass@example.com/page")

    def test_strips_fragments(self):
        """URL fragments should be stripped."""
        result = _validate_url("https://example.com/page#section")
        assert result == "https://example.com/page"

    def test_preserves_query_strings(self):
        """Query strings should be preserved."""
        result = _validate_url("https://example.com/page?id=123")
        assert result == "https://example.com/page?id=123"


class TestVideoHostDetection:
    """Test video host recognition."""

    def test_recognizes_youtube(self):
        assert _video_host("youtube.com")
        assert _video_host("www.youtube.com")
        assert _video_host("youtube-nocookie.com")

    def test_recognizes_vimeo(self):
        assert _video_host("vimeo.com")
        assert _video_host("player.vimeo.com")

    def test_recognizes_wistia(self):
        assert _video_host("wistia.com")
        assert _video_host("fast.wistia.net")

    def test_recognizes_loom(self):
        assert _video_host("loom.com")
        assert _video_host("www.loom.com")

    def test_rejects_non_video_host(self):
        assert not _video_host("example.com")
        assert not _video_host("google.com")


class TestPlatformVideoPage:
    """Test platform video page detection."""

    def test_youtube_watch(self):
        assert _platform_video_page("https://www.youtube.com/watch?v=abc123")

    def test_youtube_shorts(self):
        assert _platform_video_page("https://youtube.com/shorts/abc123")

    def test_youtu_be(self):
        assert _platform_video_page("https://youtu.be/abc123")

    def test_vimeo_video(self):
        assert _platform_video_page("https://vimeo.com/123456789")

    def test_loom_share(self):
        assert _platform_video_page("https://loom.com/share/abc123")

    def test_non_video_page(self):
        assert not _platform_video_page("https://example.com/blog")


class TestParseYouTubeEmbed:
    """Test parsing YouTube embed from HTML."""

    def test_finds_youtube_iframe(self):
        candidates = _parse_candidates(HTML_YOUTUBE_EMBED, "https://example.com/product")
        assert len(candidates) >= 1
        
        youtube_candidate = next(
            (c for c in candidates if "youtube.com" in c["url"]), None
        )
        assert youtube_candidate is not None
        assert "iframe" in youtube_candidate["source"]

    def test_youtube_has_high_score(self):
        candidates = _parse_candidates(HTML_YOUTUBE_EMBED, "https://example.com/product")
        youtube_candidate = next(
            (c for c in candidates if "youtube.com" in c["url"]), None
        )
        assert youtube_candidate["score"] >= 70


class TestParseOGVideo:
    """Test parsing og:video meta tags."""

    def test_finds_og_video(self):
        candidates = _parse_candidates(HTML_OG_VIDEO, "https://example.com/article")
        assert len(candidates) >= 1
        
        og_candidate = next(
            (c for c in candidates if "og:video" in c["source"]), None
        )
        assert og_candidate is not None
        assert og_candidate["url"] == "https://example.com/videos/main.mp4"

    def test_og_video_has_high_score(self):
        candidates = _parse_candidates(HTML_OG_VIDEO, "https://example.com/article")
        og_candidate = candidates[0]
        assert og_candidate["score"] >= 90


class TestParseVideoTag:
    """Test parsing HTML5 video tags."""

    def test_finds_video_source(self):
        candidates = _parse_candidates(HTML_VIDEO_TAG, "https://example.com/tutorial")
        assert len(candidates) >= 1
        
        video_candidate = next(
            (c for c in candidates if "video_tag" in c["source"]), None
        )
        assert video_candidate is not None

    def test_resolves_relative_url(self):
        candidates = _parse_candidates(HTML_VIDEO_TAG, "https://example.com/tutorial")
        video_urls = [c["url"] for c in candidates]
        assert any("https://example.com/videos/tutorial" in url for url in video_urls)

    def test_main_content_bonus(self):
        """Videos in main/article tags get bonus score."""
        candidates = _parse_candidates(HTML_VIDEO_TAG, "https://example.com/tutorial")
        video_candidate = next(
            (c for c in candidates if "video_tag" in c["source"]), None
        )
        assert "in main content" in video_candidate["reason"]


class TestParseMultipleVideos:
    """Test ranking when multiple videos are present."""

    def test_finds_all_videos(self):
        candidates = _parse_candidates(HTML_MULTIPLE_VIDEOS, "https://example.com/page")
        assert len(candidates) >= 3

    def test_ranks_by_score(self):
        candidates = _parse_candidates(HTML_MULTIPLE_VIDEOS, "https://example.com/page")
        scores = [c["score"] for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_og_video_ranked_first(self):
        candidates = _parse_candidates(HTML_MULTIPLE_VIDEOS, "https://example.com/page")
        top = candidates[0]
        assert "og:video" in top["source"] or top["score"] >= 90


class TestParseNoVideo:
    """Test behavior when no video is present."""

    def test_returns_empty_list(self):
        candidates = _parse_candidates(HTML_NO_VIDEO, "https://example.com/article")
        assert candidates == []


class TestParseJSONLD:
    """Test parsing JSON-LD VideoObject."""

    def test_finds_json_ld_video(self):
        candidates = _parse_candidates(HTML_JSON_LD_VIDEO, "https://example.com/demo")
        assert len(candidates) >= 1
        
        json_ld_candidate = next(
            (c for c in candidates if "json_ld" in c["source"]), None
        )
        assert json_ld_candidate is not None
        # JSON-LD VideoObject can have contentUrl, embedUrl, or url - any is valid
        assert "example.com" in json_ld_candidate["url"]


class TestParseWistiaLoom:
    """Test parsing Wistia and Loom embeds."""

    def test_finds_wistia_embed(self):
        candidates = _parse_candidates(HTML_WISTIA_EMBED, "https://example.com/training")
        wistia_candidate = next(
            (c for c in candidates if "wistia" in c["url"].lower()), None
        )
        assert wistia_candidate is not None

    def test_finds_loom_link(self):
        candidates = _parse_candidates(HTML_WISTIA_EMBED, "https://example.com/training")
        loom_candidate = next(
            (c for c in candidates if "loom.com" in c["url"]), None
        )
        assert loom_candidate is not None


class TestFindVideosIntegration:
    """Integration tests for find_videos function."""

    @patch("video_finder._fetch_page")
    def test_returns_found_status_with_video(self, mock_fetch):
        mock_fetch.return_value = (HTML_YOUTUBE_EMBED, "https://example.com/product", 200)
        
        result = find_videos("https://example.com/product", try_yt_dlp=False)
        
        assert result["status"] == "found"
        assert result["top"] is not None
        assert "youtube.com" in result["top"]["url"]

    @patch("video_finder._fetch_page")
    def test_returns_not_found_status_without_video(self, mock_fetch):
        mock_fetch.return_value = (HTML_NO_VIDEO, "https://example.com/article", 200)
        
        result = find_videos("https://example.com/article", try_yt_dlp=False)
        
        assert result["status"] == "not_found"
        assert result["top"] is None
        assert "No video found" in result.get("message", "")

    @patch("video_finder._fetch_page")
    def test_returns_alternates(self, mock_fetch):
        mock_fetch.return_value = (HTML_MULTIPLE_VIDEOS, "https://example.com/page", 200)
        
        result = find_videos("https://example.com/page", try_yt_dlp=False)
        
        assert result["status"] == "found"
        assert len(result["alternates"]) >= 2

    @patch("video_finder._fetch_page")
    def test_returns_unavailable_on_fetch_error(self, mock_fetch):
        mock_fetch.return_value = (None, None, None)
        
        result = find_videos("https://example.com/page", try_yt_dlp=False)
        
        assert result["status"] == "unavailable"
        assert "could not be fetched" in result.get("message", "")

    def test_ssrf_blocked_private_ip(self):
        """SSRF protection blocks private IPs without making requests."""
        result = find_videos("http://192.168.1.1/admin")
        
        assert result["status"] == "unavailable"
        assert result["checked"] == []  # No methods checked due to SSRF block

    def test_ssrf_blocked_localhost(self):
        """SSRF protection blocks localhost without making requests."""
        result = find_videos("http://localhost:8080/internal")
        
        assert result["status"] == "unavailable"
        assert "Localhost" in result.get("message", "")

    @patch("video_finder._resolve_and_check_ip")
    @patch("video_finder._fetch_page")
    def test_direct_mp4_url_found(self, mock_fetch, mock_resolve):
        """Direct media URLs are recognized immediately (no page fetch needed)."""
        mock_resolve.return_value = None  # Don't actually resolve DNS
        
        result = find_videos("https://cdn.example.com/video.mp4", try_yt_dlp=False)
        
        assert result["status"] == "found"
        assert result["top"]["source"] == "media_link"
        mock_fetch.assert_not_called()
