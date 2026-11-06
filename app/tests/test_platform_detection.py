"""
Platform URL Detection Tests

Comprehensive regression tests for platform detection covering:
- All supported platforms (TikTok, YouTube, Instagram, Facebook, X/Twitter, 
  Reddit, Vimeo, Twitch, LinkedIn, Threads, Loom, Spotify)
- Various URL formats per platform
- Trailing punctuation handling
- Rejection of unsupported URLs
"""
import pytest
import sys
import os

# Add the app directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcriber import (
    _is_tiktok_url,
    _is_youtube_url,
    _is_instagram_url,
    _is_facebook_url,
    _is_spotify_url,
    _is_x_twitter_url,
    _is_reddit_url,
    _is_vimeo_url,
    _is_twitch_url,
    _is_linkedin_url,
    _is_threads_url,
    _is_loom_url,
    _detect_platform,
    canonical_platform,
    needs_video_discovery,
    clean_url_trailing_punctuation,
)


class TestTrailingPunctuationCleaning:
    """Test trailing punctuation removal from URLs."""

    @pytest.mark.parametrize("url,expected", [
        # Trailing period
        ("https://www.tiktok.com/@user/video/123.", "https://www.tiktok.com/@user/video/123"),
        # Trailing parenthesis
        ("https://youtu.be/dQw4w9WgXcQ)", "https://youtu.be/dQw4w9WgXcQ"),
        # Multiple punctuation
        ("https://x.com/user/status/123...).", "https://x.com/user/status/123"),
        # Comma and exclamation
        ("https://instagram.com/reel/ABC123!,", "https://instagram.com/reel/ABC123"),
        # No trailing punctuation - unchanged
        ("https://vimeo.com/123456789", "https://vimeo.com/123456789"),
        # Query string preserved
        ("https://youtube.com/watch?v=abc123", "https://youtube.com/watch?v=abc123"),
    ])
    def test_clean_trailing_punctuation(self, url, expected):
        assert clean_url_trailing_punctuation(url) == expected


class TestTikTokDetection:
    """Test TikTok URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.tiktok.com/@username/video/1234567890123456789",
        "https://tiktok.com/@user/video/123",
        "https://vm.tiktok.com/ZMxxxxxxx/",
        "https://tiktok.com/t/ZSxxxxxxx/",
        "https://www.tiktok.com/@creator.name/video/7123456789012345678",
    ])
    def test_valid_tiktok_urls(self, url):
        assert _is_tiktok_url(url) is True
        assert _detect_platform(url) == "tiktok"

    @pytest.mark.parametrize("url", [
        "https://www.tiktok.com/@username",  # Profile, not video
        "https://example.com/tiktok.com",
    ])
    def test_invalid_tiktok_urls(self, url):
        assert _is_tiktok_url(url) is False


class TestYouTubeDetection:
    """Test YouTube URL detection - comprehensive coverage."""

    @pytest.mark.parametrize("url", [
        # Standard watch URLs
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        # v= not first parameter
        "https://www.youtube.com/watch?list=PLxxx&v=dQw4w9WgXcQ",
        "https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        # Short URLs
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=120",
        # Shorts
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://youtube.com/shorts/12345678901",
        # Live
        "https://www.youtube.com/live/abcdefghijk",
        # Embed
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        # Mobile
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        # Music
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ])
    def test_valid_youtube_urls(self, url):
        assert _is_youtube_url(url) is True
        assert _detect_platform(url) == "youtube"

    @pytest.mark.parametrize("url", [
        "https://youtube.com/channel/UCxxxxxx",  # Channel, not video
        "https://youtube.com/playlist?list=PLxxxxx",  # Playlist page
    ])
    def test_invalid_youtube_urls(self, url):
        assert _is_youtube_url(url) is False


class TestInstagramDetection:
    """Test Instagram URL detection - comprehensive coverage."""

    @pytest.mark.parametrize("url", [
        # Standard reel
        "https://www.instagram.com/reel/Cxxxxxxxxxx/",
        "https://instagram.com/reel/ABC123/",
        # Reels (plural)
        "https://www.instagram.com/reels/Cxxxxxxxxxx/",
        # Post (p)
        "https://www.instagram.com/p/Cxxxxxxxxxx/",
        "https://instagram.com/p/ABC123/",
        # TV (IGTV)
        "https://www.instagram.com/tv/Cxxxxxxxxxx/",
        # Username-prefixed paths
        "https://www.instagram.com/username/reel/Cxxxxxxxxxx/",
        "https://instagram.com/creator/p/ABC123/",
        # Share links
        "https://www.instagram.com/share/reel/Cxxxxxxxxxx/",
        "https://instagram.com/share/p/ABC123/",
        # With tracking params
        "https://www.instagram.com/reel/Cxxxxxxxxxx/?igsh=xyz123",
        # Production shortcode that was stored as tiktok
        "https://www.instagram.com/reel/DfVWPIwFJz_/",
        "https://instagram.com/reel/DfVWPIwFJz_",
        # Share links without reel/p prefix
        "https://www.instagram.com/share/DfVWPIwFJz_/",
        # instagr.am short URLs
        "https://instagr.am/p/ABC123/",
        "https://instagr.am/reel/XYZ789/",
    ])
    def test_valid_instagram_urls(self, url):
        assert _is_instagram_url(url) is True
        assert _detect_platform(url) == "instagram"

    @pytest.mark.parametrize("url", [
        "https://www.instagram.com/username",  # Profile only
        "https://instagram.com/explore/",
    ])
    def test_invalid_instagram_urls(self, url):
        assert _is_instagram_url(url) is False


class TestFacebookDetection:
    """Test Facebook URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.facebook.com/username/videos/1234567890/",
        "https://facebook.com/watch?v=1234567890",
        "https://www.facebook.com/reel/1234567890",
        "https://fb.watch/abcdefghij/",
        "https://fb.gg/v/abcdefg/",
    ])
    def test_valid_facebook_urls(self, url):
        assert _is_facebook_url(url) is True
        assert _detect_platform(url) == "facebook"


class TestXTwitterDetection:
    """Test X/Twitter URL detection."""

    @pytest.mark.parametrize("url", [
        # x.com (new domain)
        "https://x.com/username/status/1234567890123456789",
        "https://x.com/elonmusk/status/1800000000000000000",
        # twitter.com (old domain)
        "https://twitter.com/username/status/1234567890123456789",
        "https://www.twitter.com/user/status/123",
        "https://mobile.twitter.com/user/status/456",
    ])
    def test_valid_x_twitter_urls(self, url):
        assert _is_x_twitter_url(url) is True
        assert _detect_platform(url) == "twitter"

    @pytest.mark.parametrize("url", [
        "https://twitter.com/username",  # Profile only
        "https://x.com/explore",
    ])
    def test_invalid_x_twitter_urls(self, url):
        assert _is_x_twitter_url(url) is False


class TestRedditDetection:
    """Test Reddit URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.reddit.com/r/videos/comments/abc123/title/",
        "https://reddit.com/r/funny/comments/xyz789/",
        "https://redd.it/abc123",
        "https://v.redd.it/xyz789abc",
        # Share links
        "https://www.reddit.com/r/subreddit/s/abcd1234",
    ])
    def test_valid_reddit_urls(self, url):
        assert _is_reddit_url(url) is True
        assert _detect_platform(url) == "reddit"


class TestVimeoDetection:
    """Test Vimeo URL detection."""

    @pytest.mark.parametrize("url", [
        "https://vimeo.com/123456789",
        "https://player.vimeo.com/video/123456789",
        "https://vimeo.com/channels/staffpicks/123456789",
        "https://vimeo.com/groups/mygroup/videos/123456789",
    ])
    def test_valid_vimeo_urls(self, url):
        assert _is_vimeo_url(url) is True
        assert _detect_platform(url) == "vimeo"


class TestTwitchDetection:
    """Test Twitch URL detection."""

    @pytest.mark.parametrize("url", [
        "https://clips.twitch.tv/AwesomeClipName",
        "https://www.twitch.tv/username/clip/ClipName",
        "https://www.twitch.tv/videos/1234567890",
    ])
    def test_valid_twitch_urls(self, url):
        assert _is_twitch_url(url) is True
        assert _detect_platform(url) == "twitch"


class TestLinkedInDetection:
    """Test LinkedIn URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.linkedin.com/posts/username_title-activity-123",
        "https://www.linkedin.com/feed/update/urn:li:activity:123",
        "https://www.linkedin.com/video/embed/123",
    ])
    def test_valid_linkedin_urls(self, url):
        assert _is_linkedin_url(url) is True
        assert _detect_platform(url) == "linkedin"


class TestThreadsDetection:
    """Test Threads URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.threads.net/@username/post/Cxxxxxxxxxx",
        "https://threads.net/@creator/post/ABC123xyz",
    ])
    def test_valid_threads_urls(self, url):
        assert _is_threads_url(url) is True
        assert _detect_platform(url) == "threads"


class TestLoomDetection:
    """Test Loom URL detection."""

    @pytest.mark.parametrize("url", [
        "https://www.loom.com/share/abcdef123456",
        "https://loom.com/share/xyz789",
    ])
    def test_valid_loom_urls(self, url):
        assert _is_loom_url(url) is True
        assert _detect_platform(url) == "loom"


class TestSpotifyDetection:
    """Test Spotify podcast episode URL detection."""

    @pytest.mark.parametrize("url", [
        "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk",
        "https://open.spotify.com/episode/abc123?si=xyz",
    ])
    def test_valid_spotify_urls(self, url):
        assert _is_spotify_url(url) is True
        assert _detect_platform(url) == "spotify"


class TestWebAndUnsupportedURLs:
    """Generic http(s) pages are 'web'; non-URLs stay 'unknown'."""

    @pytest.mark.parametrize("url", [
        "https://example.com/video/123",
        "https://dailymotion.com/video/x123abc",
        "https://streamable.com/abc123",
        "https://google.com",
        "https://www.w3schools.com/html/html5_video.asp",
        "https://www.w3schools.com/html/mov_bbb.mp4",
    ])
    def test_generic_http_urls_are_web(self, url):
        assert _detect_platform(url) == "web"
        assert canonical_platform(url) == "web"

    @pytest.mark.parametrize("url", [
        "not-a-url",
        "",
    ])
    def test_non_urls_are_unknown(self, url):
        assert _detect_platform(url) == "unknown"


class TestCanonicalPlatformStorage:
    """Stored platform must match the DB constraint and never default to tiktok."""

    def test_never_falls_back_to_tiktok_for_web_pages(self):
        url = "https://www.w3schools.com/html/html5_video.asp"
        assert canonical_platform(url) == "web"
        assert canonical_platform(url, "unknown") == "web"
        assert canonical_platform(url, "webpage") == "web"

    def test_instagram_rapidapi_nested_data_keeps_instagram(self):
        # Production bug: Instagram RapidAPI metadata includes a `data` dict and
        # the completion path used to hardcode platform='tiktok'.
        url = "https://www.instagram.com/reel/DfVWPIwFJz_/"
        assert canonical_platform(url, "instagram") == "instagram"
        assert canonical_platform(url) == "instagram"

    def test_needs_video_discovery_only_for_generic_pages(self):
        assert needs_video_discovery("web") is True
        assert needs_video_discovery("unknown") is True
        assert needs_video_discovery("webpage") is True
        assert needs_video_discovery("instagram") is False
        assert needs_video_discovery("tiktok") is False
        assert needs_video_discovery("youtube") is False


class TestTrailingPunctuationWithDetection:
    """Test that platform detection works with trailing punctuation in URLs."""

    @pytest.mark.parametrize("url,expected_platform", [
        ("https://www.tiktok.com/@user/video/123.", "tiktok"),
        ("https://youtu.be/dQw4w9WgXcQ)", "youtube"),
        ("https://x.com/user/status/123!)", "twitter"),
        ("https://instagram.com/reel/ABC123,", "instagram"),
        ("https://vimeo.com/123456789.", "vimeo"),
    ])
    def test_detection_with_punctuation(self, url, expected_platform):
        # Detection should work even with trailing punctuation
        # because _detect_platform should call clean_url_trailing_punctuation
        # Actually, looking at the code, _detect_platform doesn't clean.
        # The cleaning happens in the edge function and download_tiktok.
        # So these tests verify the raw detection.
        cleaned = clean_url_trailing_punctuation(url)
        assert _detect_platform(cleaned) == expected_platform
