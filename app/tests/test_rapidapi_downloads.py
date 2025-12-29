"""
Tests for platform-specific RapidAPI download functions.

Tests cover:
- URL detection for TikTok, Instagram, Facebook
- Instagram RapidAPI response parsing
- Facebook RapidAPI response parsing (primary and backup)
- Download flow with platform routing
"""

import pytest
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcriber import (
    _is_tiktok_url,
    _is_instagram_url,
    _is_facebook_url,
    clean_url_for_api,
    download_instagram_rapidapi,
    download_facebook_rapidapi,
    download_tiktok,
)


class TestURLDetection:
    """Test platform URL detection functions."""

    def test_tiktok_url_standard(self):
        """Test standard TikTok URLs."""
        assert _is_tiktok_url("https://www.tiktok.com/@user/video/1234567890")
        assert _is_tiktok_url("https://tiktok.com/@username/video/123")
        assert _is_tiktok_url("http://tiktok.com/@test/video/456")

    def test_tiktok_url_short(self):
        """Test short TikTok URLs."""
        assert _is_tiktok_url("https://vm.tiktok.com/ZMxxxxxx/")
        assert _is_tiktok_url("http://vm.tiktok.com/abc123")

    def test_tiktok_url_negative(self):
        """Test non-TikTok URLs return False."""
        assert not _is_tiktok_url("https://www.instagram.com/reel/ABC123")
        assert not _is_tiktok_url("https://www.youtube.com/watch?v=123")
        assert not _is_tiktok_url("https://facebook.com/video/123")
        assert not _is_tiktok_url("")

    def test_instagram_url_reel(self):
        """Test Instagram Reel URLs."""
        assert _is_instagram_url("https://www.instagram.com/reel/DJg8Hc_zkot/")
        assert _is_instagram_url("https://instagram.com/reel/ABC123/?igsh=xxx")
        assert _is_instagram_url("http://www.instagram.com/reel/test123")

    def test_instagram_url_post(self):
        """Test Instagram post URLs."""
        assert _is_instagram_url("https://www.instagram.com/p/ABC123/")
        assert _is_instagram_url("https://instagram.com/p/xyz789")

    def test_instagram_url_tv(self):
        """Test Instagram TV URLs."""
        assert _is_instagram_url("https://www.instagram.com/tv/ABC123/")

    def test_instagram_url_negative(self):
        """Test non-Instagram URLs return False."""
        assert not _is_instagram_url("https://www.tiktok.com/@user/video/123")
        assert not _is_instagram_url("https://www.instagram.com/username/")  # Profile, not video
        assert not _is_instagram_url("https://facebook.com/reel/123")
        assert not _is_instagram_url("")

    def test_facebook_url_video(self):
        """Test Facebook video URLs."""
        assert _is_facebook_url("https://www.facebook.com/user/videos/1234567890")
        assert _is_facebook_url("https://facebook.com/page/videos/123")

    def test_facebook_url_reel(self):
        """Test Facebook Reel URLs."""
        assert _is_facebook_url("https://www.facebook.com/reel/1234567890")
        assert _is_facebook_url("https://facebook.com/reel/123")

    def test_facebook_url_watch(self):
        """Test Facebook Watch URLs (fb.watch)."""
        assert _is_facebook_url("https://fb.watch/abc123/")
        assert _is_facebook_url("http://fb.watch/xyz")

    def test_facebook_url_negative(self):
        """Test non-Facebook URLs return False."""
        assert not _is_facebook_url("https://www.tiktok.com/@user/video/123")
        assert not _is_facebook_url("https://www.instagram.com/reel/123")
        assert not _is_facebook_url("https://www.facebook.com/username")  # Profile
        assert not _is_facebook_url("")


class TestURLCleaning:
    """Test URL cleaning function."""

    def test_clean_instagram_igsh(self):
        """Test removing igsh tracking param from Instagram URLs."""
        dirty = "https://www.instagram.com/reel/DJg8Hc_zkot/?igsh=MXFvaDhueHozZjQ2bQ=="
        clean = clean_url_for_api(dirty)
        assert "igsh" not in clean
        assert "instagram.com/reel/DJg8Hc_zkot" in clean

    def test_clean_utm_params(self):
        """Test removing UTM tracking params."""
        dirty = "https://www.tiktok.com/@user/video/123?utm_source=copy&utm_medium=social"
        clean = clean_url_for_api(dirty)
        assert "utm_source" not in clean
        assert "utm_medium" not in clean

    def test_clean_facebook_fbclid(self):
        """Test removing fbclid from Facebook URLs."""
        dirty = "https://www.facebook.com/reel/123?fbclid=abc123xyz"
        clean = clean_url_for_api(dirty)
        assert "fbclid" not in clean

    def test_clean_preserves_important_params(self):
        """Test that important params like video ID are preserved."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=tracking123"
        clean = clean_url_for_api(url)
        assert "v=dQw4w9WgXcQ" in clean
        assert "si=" not in clean

    def test_clean_url_no_params(self):
        """Test URL without params passes through unchanged."""
        url = "https://www.instagram.com/reel/ABC123/"
        clean = clean_url_for_api(url)
        assert clean == url


class TestInstagramRapidAPIResponse:
    """Test Instagram RapidAPI response parsing."""

    @pytest.fixture
    def sample_instagram_response(self):
        """Sample successful Instagram API response."""
        return {
            "success": True,
            "message": "success",
            "data": {
                "url": "https://www.instagram.com/reel/DJg8Hc_zkot/",
                "source": "instagram",
                "title": "Playing with the fish\n#sealife #diving",
                "author": "Oskar Dusik",
                "shortcode": "DJg8Hc_zkot",
                "view_count": 0,
                "like_count": 18864465,
                "thumbnail": "https://instagram.com/thumbnail.jpg",
                "duration": 42.98,
                "owner": {
                    "id": "72847438554",
                    "username": "oskidives",
                    "full_name": "Oskar Dusik"
                },
                "medias": [
                    {
                        "id": "3630165694622878253",
                        "url": "https://instagram.com/video.mp4",
                        "quality": "640-1136p",
                        "type": "video",
                        "extension": "mp4"
                    },
                    {
                        "id": "1680768932798817ad",
                        "type": "audio",
                        "url": "https://instagram.com/audio.m4a",
                        "quality": "audio",
                        "extension": "m4a"
                    }
                ],
                "type": "multiple",
                "error": False
            }
        }

    @patch('transcriber.requests.get')
    @patch('transcriber.subprocess.run')
    def test_instagram_download_success(self, mock_subprocess, mock_get, sample_instagram_response):
        """Test successful Instagram download."""
        # Mock API response
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = sample_instagram_response

        # Mock video download
        video_response = MagicMock()
        video_response.status_code = 200
        video_response.content = b"fake video content"

        mock_get.side_effect = [api_response, video_response]
        mock_subprocess.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_instagram_rapidapi(
                    "https://www.instagram.com/reel/DJg8Hc_zkot/",
                    tmpdir
                )

        assert result is not None
        assert result["platform"] == "instagram"
        assert result["video_id"] == "DJg8Hc_zkot"
        assert "Playing with the fish" in result["title"]

    @patch('transcriber.requests.get')
    def test_instagram_download_api_error(self, mock_get):
        """Test Instagram download with API error."""
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = {
            "success": False,
            "message": "Video not found",
            "error": True
        }
        mock_get.return_value = api_response

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_instagram_rapidapi(
                    "https://www.instagram.com/reel/invalid/",
                    tmpdir
                )

        assert result is None

    @patch('transcriber.requests.get')
    def test_instagram_download_rate_limit(self, mock_get):
        """Test Instagram download with rate limit."""
        api_response = MagicMock()
        api_response.status_code = 429
        mock_get.return_value = api_response

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_instagram_rapidapi(
                    "https://www.instagram.com/reel/test/",
                    tmpdir
                )

        assert result is None

    def test_instagram_download_no_api_key(self):
        """Test Instagram download without API key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {}, clear=True):
                # Remove RAPIDAPI_KEY if it exists
                os.environ.pop("RAPIDAPI_KEY", None)
                result = download_instagram_rapidapi(
                    "https://www.instagram.com/reel/test/",
                    tmpdir
                )

        assert result is None


class TestFacebookRapidAPIResponse:
    """Test Facebook RapidAPI response parsing."""

    @pytest.fixture
    def sample_facebook_primary_response(self):
        """Sample successful Facebook primary API response."""
        return {
            "status": "success",
            "message": "Video information retrieved successfully",
            "data": {
                "video": {
                    "id": "UYpdwuh4B9Q8DRrX",
                    "title": "Amazing Video",
                    "description": None,
                    "type": "Video",
                    "duration_ms": 419383,
                    "thumbnail_url": "https://facebook.com/thumbnail.jpg"
                },
                "download": {
                    "sd": {
                        "url": "https://facebook.com/video_sd.mp4",
                        "quality": "SD"
                    },
                    "hd": {
                        "url": "https://facebook.com/video_hd.mp4",
                        "quality": "HD"
                    }
                }
            }
        }

    @pytest.fixture
    def sample_facebook_backup_response(self):
        """Sample successful Facebook backup API response."""
        return {
            "status": "ok",
            "video": {
                "video_id": "723196289891905",
                "thumbnail_url": "https://facebook.com/thumb.jpg",
                "sd_video_url": "https://facebook.com/sd.mp4",
                "hd_video_url": "https://facebook.com/hd.mp4"
            }
        }

    @patch('transcriber.requests.get')
    @patch('transcriber.subprocess.run')
    def test_facebook_download_primary_success(self, mock_subprocess, mock_get, sample_facebook_primary_response):
        """Test successful Facebook download with primary API."""
        # Mock API response
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = sample_facebook_primary_response

        # Mock video download
        video_response = MagicMock()
        video_response.status_code = 200
        video_response.content = b"fake video content"

        mock_get.side_effect = [api_response, video_response]
        mock_subprocess.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_facebook_rapidapi(
                    "https://www.facebook.com/reel/123456",
                    tmpdir
                )

        assert result is not None
        assert result["platform"] == "facebook"
        assert result["title"] == "Amazing Video"

    @patch('transcriber.requests.get')
    @patch('transcriber.subprocess.run')
    def test_facebook_download_backup_fallback(self, mock_subprocess, mock_get, sample_facebook_backup_response):
        """Test Facebook download falling back to backup API."""
        # Primary API fails
        primary_response = MagicMock()
        primary_response.status_code = 200
        primary_response.json.return_value = {"status": "error", "message": "Not found"}

        # Backup API succeeds
        backup_response = MagicMock()
        backup_response.status_code = 200
        backup_response.json.return_value = sample_facebook_backup_response

        # Video download
        video_response = MagicMock()
        video_response.status_code = 200
        video_response.content = b"fake video content"

        mock_get.side_effect = [primary_response, backup_response, video_response]
        mock_subprocess.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_facebook_rapidapi(
                    "https://www.facebook.com/reel/123456",
                    tmpdir
                )

        assert result is not None
        assert result["platform"] == "facebook"

    @patch('transcriber.requests.get')
    def test_facebook_download_both_apis_fail(self, mock_get):
        """Test Facebook download when both APIs fail."""
        # Both APIs return errors
        error_response = MagicMock()
        error_response.status_code = 200
        error_response.json.return_value = {"status": "error"}

        mock_get.return_value = error_response

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAPIDAPI_KEY": "test_key"}):
                result = download_facebook_rapidapi(
                    "https://www.facebook.com/reel/invalid",
                    tmpdir
                )

        assert result is None


class TestDownloadFlowRouting:
    """Test that download_tiktok routes to correct platform API."""

    @patch('transcriber.download_tiktok_rapidapi')
    @patch('transcriber.download_tiktok_ytdlp')
    def test_tiktok_url_routes_to_tiktok_api(self, mock_ytdlp, mock_tiktok_api):
        """Test TikTok URLs are routed to TikTok API."""
        mock_tiktok_api.return_value = {"video_id": "123", "platform": "tiktok"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_tiktok(
                "https://www.tiktok.com/@user/video/123",
                tmpdir
            )

        mock_tiktok_api.assert_called_once()
        mock_ytdlp.assert_not_called()
        assert result["platform"] == "tiktok"

    @patch('transcriber.download_instagram_rapidapi')
    @patch('transcriber.download_tiktok_ytdlp')
    def test_instagram_url_routes_to_instagram_api(self, mock_ytdlp, mock_instagram_api):
        """Test Instagram URLs are routed to Instagram API."""
        mock_instagram_api.return_value = {"video_id": "ABC", "platform": "instagram"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_tiktok(
                "https://www.instagram.com/reel/ABC123/",
                tmpdir
            )

        mock_instagram_api.assert_called_once()
        mock_ytdlp.assert_not_called()
        assert result["platform"] == "instagram"

    @patch('transcriber.download_facebook_rapidapi')
    @patch('transcriber.download_tiktok_ytdlp')
    def test_facebook_url_routes_to_facebook_api(self, mock_ytdlp, mock_facebook_api):
        """Test Facebook URLs are routed to Facebook API."""
        mock_facebook_api.return_value = {"video_id": "456", "platform": "facebook"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_tiktok(
                "https://www.facebook.com/reel/123456",
                tmpdir
            )

        mock_facebook_api.assert_called_once()
        mock_ytdlp.assert_not_called()
        assert result["platform"] == "facebook"

    @patch('transcriber.download_instagram_rapidapi')
    @patch('transcriber.download_tiktok_ytdlp')
    def test_instagram_fallback_to_ytdlp(self, mock_ytdlp, mock_instagram_api):
        """Test Instagram falls back to yt-dlp when API fails."""
        mock_instagram_api.return_value = None
        mock_ytdlp.return_value = ("/path/to/audio.mp3", "video_id", "Title")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_tiktok(
                "https://www.instagram.com/reel/ABC123/",
                tmpdir
            )

        mock_instagram_api.assert_called_once()
        mock_ytdlp.assert_called_once()
        assert result is not None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_url(self):
        """Test empty URL handling."""
        assert not _is_tiktok_url("")
        assert not _is_instagram_url("")
        assert not _is_facebook_url("")

    def test_none_url(self):
        """Test None URL handling in clean function."""
        result = clean_url_for_api("")
        assert result == ""

    def test_malformed_url(self):
        """Test malformed URL handling."""
        # Should not crash, just return False
        assert not _is_tiktok_url("not a url")
        assert not _is_instagram_url("http://")
        assert not _is_facebook_url("ftp://facebook.com")

    def test_case_insensitive_detection(self):
        """Test URL detection is case insensitive."""
        assert _is_tiktok_url("https://WWW.TIKTOK.COM/@user/video/123")
        assert _is_instagram_url("https://INSTAGRAM.COM/reel/ABC/")
        assert _is_facebook_url("https://FB.WATCH/abc123/")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
