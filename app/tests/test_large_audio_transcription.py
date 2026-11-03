"""
Tests for large audio transcription handling.

Tests the re-encoding and chunking logic for audio files that exceed
OpenAI Whisper's 25MB limit.
"""
import pytest
import os
import tempfile
import subprocess
from unittest.mock import Mock, patch, MagicMock
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcriber import (
    WHISPER_MAX_SIZE_BYTES,
    WHISPER_REENCODE_THRESHOLD,
    CHUNK_DURATION_SECONDS,
    _get_audio_duration,
    _prepare_audio_for_whisper,
    _split_audio_into_chunks,
    _transcribe_single_chunk,
    _stitch_transcriptions,
)


class TestAudioDurationDetection:
    """Test audio duration detection via ffprobe."""

    def test_get_duration_nonexistent_file(self):
        """Should return 0.0 for nonexistent file."""
        duration = _get_audio_duration("/nonexistent/file.mp3")
        assert duration == 0.0

    @patch('transcriber.subprocess.run')
    def test_get_duration_success(self, mock_run):
        """Should parse ffprobe output correctly."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="125.5\n",
            stderr=""
        )
        duration = _get_audio_duration("/some/file.mp3")
        assert duration == 125.5

    @patch('transcriber.subprocess.run')
    def test_get_duration_ffprobe_failure(self, mock_run):
        """Should return 0.0 when ffprobe fails."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error"
        )
        duration = _get_audio_duration("/some/file.mp3")
        assert duration == 0.0


class TestAudioPreparation:
    """Test audio re-encoding for Whisper size limit."""

    def test_threshold_constants(self):
        """Verify size thresholds are set correctly."""
        assert WHISPER_MAX_SIZE_BYTES == 25 * 1024 * 1024
        assert WHISPER_REENCODE_THRESHOLD == 24 * 1024 * 1024
        assert WHISPER_REENCODE_THRESHOLD < WHISPER_MAX_SIZE_BYTES

    def test_small_file_not_reencoded(self):
        """Files under threshold should not be re-encoded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a small test file
            small_file = os.path.join(tmpdir, "small.mp3")
            with open(small_file, 'wb') as f:
                f.write(b'\x00' * 1000)  # 1KB file
            
            result = _prepare_audio_for_whisper(small_file, tmpdir, "test_video")
            # Should return original file path since it's under threshold
            assert result == small_file

    def test_nonexistent_file_returns_path(self):
        """Nonexistent file should return original path."""
        result = _prepare_audio_for_whisper("/nonexistent.mp3", "/tmp", "test")
        assert result == "/nonexistent.mp3"

    @patch('transcriber.subprocess.run')
    @patch('transcriber.os.path.getsize')
    @patch('transcriber.os.path.exists')
    def test_large_file_reencoded(self, mock_exists, mock_getsize, mock_run):
        """Files over threshold should be re-encoded to 64kbps mono 16kHz."""
        mock_exists.return_value = True
        # First call: original file is 30MB, second call: re-encoded is 5MB
        mock_getsize.side_effect = [30 * 1024 * 1024, 5 * 1024 * 1024]
        mock_run.return_value = Mock(returncode=0, stderr=b"")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _prepare_audio_for_whisper("/large/file.mp3", tmpdir, "test_video")
            
            # Check ffmpeg was called with correct parameters
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert 'ffmpeg' in call_args
            assert '-ab' in call_args
            assert '64k' in call_args
            assert '-ar' in call_args
            assert '16000' in call_args
            assert '-ac' in call_args
            assert '1' in call_args


class TestAudioChunking:
    """Test audio splitting into chunks."""

    def test_chunk_duration_constant(self):
        """Verify chunk duration is 10 minutes."""
        assert CHUNK_DURATION_SECONDS == 600

    @patch('transcriber._get_audio_duration')
    def test_short_audio_no_split(self, mock_duration):
        """Audio shorter than chunk duration should not be split."""
        mock_duration.return_value = 300.0  # 5 minutes
        
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "short.mp3")
            with open(test_file, 'wb') as f:
                f.write(b'\x00' * 1000)
            
            chunks = _split_audio_into_chunks(test_file, tmpdir, "test_video")
            
            # Should return single chunk (original file)
            assert len(chunks) == 1
            assert chunks[0][0] == test_file
            assert chunks[0][1] == 0.0

    @patch('transcriber._get_audio_duration')
    def test_zero_duration_fallback(self, mock_duration):
        """Should return original file if duration cannot be determined."""
        mock_duration.return_value = 0.0
        
        chunks = _split_audio_into_chunks("/some/file.mp3", "/tmp", "test")
        
        assert len(chunks) == 1
        assert chunks[0][0] == "/some/file.mp3"
        assert chunks[0][1] == 0.0


class TestTranscriptionStitching:
    """Test combining multiple chunk transcriptions."""

    def test_stitch_empty_list(self):
        """Empty list should return None."""
        result = _stitch_transcriptions([])
        assert result is None

    def test_stitch_single_response(self):
        """Single response should be returned as-is."""
        response = {'text': 'Hello', 'segments': [], 'duration': 10}
        result = _stitch_transcriptions([response])
        assert result == response

    def test_stitch_multiple_responses(self):
        """Multiple responses should be combined correctly."""
        responses = [
            {'text': 'Hello', 'segments': [{'start': 0, 'end': 5, 'text': 'Hello'}], 'duration': 10},
            {'text': 'World', 'segments': [{'start': 10, 'end': 15, 'text': 'World'}], 'duration': 10},
        ]
        
        result = _stitch_transcriptions(responses)
        
        assert result is not None
        assert 'Hello' in result['text']
        assert 'World' in result['text']
        assert len(result['segments']) == 2
        assert result['duration'] == 20

    def test_stitch_skips_none_responses(self):
        """None responses should be skipped."""
        responses = [
            {'text': 'Hello', 'segments': [], 'duration': 10},
            None,
            {'text': 'World', 'segments': [], 'duration': 10},
        ]
        
        result = _stitch_transcriptions(responses)
        
        assert result is not None
        assert 'Hello' in result['text']
        assert 'World' in result['text']


class TestPlatformDetectionIntegration:
    """Test that platform detection is correctly used in app.py context."""

    def test_x_twitter_detected_as_twitter(self):
        """X.com URLs should be detected as 'twitter' platform."""
        from transcriber import _detect_platform
        
        x_urls = [
            "https://x.com/neeraj_here15/status/2117203284910104609/video/1",
            "https://x.com/user/status/123456789",
            "https://twitter.com/user/status/987654321",
        ]
        
        for url in x_urls:
            platform = _detect_platform(url)
            assert platform == "twitter", f"URL {url} should be 'twitter', got '{platform}'"

    def test_tiktok_detected_correctly(self):
        """TikTok URLs should be detected as 'tiktok'."""
        from transcriber import _detect_platform
        
        tiktok_urls = [
            "https://www.tiktok.com/@user/video/123456",
            "https://vm.tiktok.com/abc123/",
        ]
        
        for url in tiktok_urls:
            platform = _detect_platform(url)
            assert platform == "tiktok", f"URL {url} should be 'tiktok', got '{platform}'"

    def test_new_platforms_detected(self):
        """Reddit, Vimeo, Twitch, Threads, Loom should be detected."""
        from transcriber import _detect_platform
        
        test_cases = [
            ("https://www.reddit.com/r/videos/comments/abc123/title/", "reddit"),
            ("https://vimeo.com/123456789", "vimeo"),
            ("https://clips.twitch.tv/AwesomeClip", "twitch"),
            ("https://www.threads.net/@user/post/Cxxxxxxxxxx", "threads"),
            ("https://www.loom.com/share/abc123", "loom"),
        ]
        
        for url, expected_platform in test_cases:
            platform = _detect_platform(url)
            assert platform == expected_platform, f"URL {url} should be '{expected_platform}', got '{platform}'"

    def test_unknown_url_returns_unknown(self):
        """Unknown URLs should return 'unknown'."""
        from transcriber import _detect_platform
        
        unknown_urls = [
            "https://example.com/video",
            "https://random-site.org/content",
            "",
            None,
        ]
        
        for url in unknown_urls:
            platform = _detect_platform(url)
            assert platform == "unknown", f"URL {url} should be 'unknown', got '{platform}'"
