"""
Tests for language detection in transcription.

Tests the language detection logic that ensures:
1. Language from metadata is used when available
2. Language is detected once from a sample (not per chunk)
3. Fallback to default language (TRANSCRIBE_DEFAULT_LANGUAGE) works
4. Language hint is passed to every Whisper call consistently
"""
import pytest
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcriber import (
    DEFAULT_LANGUAGE,
    WHISPER_SUPPORTED_LANGUAGES,
    LANGUAGE_DETECTION_MIN_CONFIDENCE,
    _extract_language_from_metadata,
    _extract_audio_sample,
    _detect_language_from_sample,
    _get_language_for_transcription,
    _transcribe_single_chunk,
    _stitch_transcriptions,
    transcribe_audio,
)


class TestLanguageConstants:
    """Test language detection constants are properly configured."""

    def test_default_language_is_english(self):
        """Default language should be 'en' unless overridden by env var."""
        assert DEFAULT_LANGUAGE == os.environ.get("TRANSCRIBE_DEFAULT_LANGUAGE", "en")

    def test_supported_languages_includes_common(self):
        """Supported languages should include common languages."""
        common = {'en', 'es', 'fr', 'de', 'zh', 'ja', 'ko', 'pt', 'ru', 'ar'}
        assert common.issubset(WHISPER_SUPPORTED_LANGUAGES)

    def test_welsh_is_supported(self):
        """Welsh (cy) should be in supported languages (it was the misdetected language)."""
        assert 'cy' in WHISPER_SUPPORTED_LANGUAGES

    def test_confidence_threshold_is_reasonable(self):
        """Confidence threshold should be between 0 and 1."""
        assert 0 < LANGUAGE_DETECTION_MIN_CONFIDENCE < 1


class TestExtractLanguageFromMetadata:
    """Test extracting language from various metadata formats."""

    def test_no_metadata_file_returns_none(self):
        """Should return None when no metadata file exists."""
        assert _extract_language_from_metadata(None) is None
        assert _extract_language_from_metadata("/nonexistent/file.json") is None

    def test_ytdlp_metadata_language_field(self):
        """Should extract language from yt-dlp format metadata."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"language": "en"}, f)
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result == "en"
            finally:
                os.unlink(f.name)

    def test_spotify_languages_array(self):
        """Should extract language from Spotify format with languages array."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "data": {
                    "languages": ["es", "en"]
                }
            }, f)
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result == "es"
            finally:
                os.unlink(f.name)

    def test_rapidapi_lang_field(self):
        """Should extract language from RapidAPI lang field."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"lang": "fr"}, f)
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result == "fr"
            finally:
                os.unlink(f.name)

    def test_nested_data_language(self):
        """Should extract language from nested data.language field."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "data": {
                    "language": "de"
                }
            }, f)
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result == "de"
            finally:
                os.unlink(f.name)

    def test_unsupported_language_returns_none(self):
        """Should return None for unsupported language codes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"language": "xyz"}, f)
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result is None
            finally:
                os.unlink(f.name)

    def test_invalid_json_returns_none(self):
        """Should return None for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json")
            f.flush()
            try:
                result = _extract_language_from_metadata(f.name)
                assert result is None
            finally:
                os.unlink(f.name)


class TestDetectLanguageFromSample:
    """Test language detection from audio samples."""

    @patch('transcriber.client')
    @patch('transcriber._extract_audio_sample')
    def test_detection_with_high_confidence(self, mock_extract, mock_client):
        """Should return language when detection succeeds with high confidence."""
        mock_extract.return_value = "/tmp/sample.mp3"
        
        mock_response = Mock()
        mock_response.language = "en"
        mock_response.text = "This is a long enough transcript with many words to be confident about the language detection results."
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy file for the test
            sample_path = os.path.join(tmpdir, "sample.mp3")
            with open(sample_path, 'wb') as f:
                f.write(b'\x00' * 1000)
            mock_extract.return_value = sample_path
            
            lang, confidence = _detect_language_from_sample("/audio.mp3", tmpdir, "test_video")
            
            assert lang == "en"
            assert confidence >= LANGUAGE_DETECTION_MIN_CONFIDENCE

    @patch('transcriber.client')
    @patch('transcriber._extract_audio_sample')
    def test_detection_with_low_confidence_short_text(self, mock_extract, mock_client):
        """Should return low confidence for very short transcripts."""
        mock_extract.return_value = "/tmp/sample.mp3"
        
        mock_response = Mock()
        mock_response.language = "en"
        mock_response.text = "Short"  # Very short text
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_path = os.path.join(tmpdir, "sample.mp3")
            with open(sample_path, 'wb') as f:
                f.write(b'\x00' * 1000)
            mock_extract.return_value = sample_path
            
            lang, confidence = _detect_language_from_sample("/audio.mp3", tmpdir, "test_video")
            
            assert lang == "en"
            assert confidence < LANGUAGE_DETECTION_MIN_CONFIDENCE  # Low confidence

    @patch('transcriber.client', None)
    def test_detection_fails_without_client(self):
        """Should return None when OpenAI client is not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lang, confidence = _detect_language_from_sample("/audio.mp3", tmpdir, "test_video")
            
            assert lang is None
            assert confidence == 0.0


class TestGetLanguageForTranscription:
    """Test the main language selection function."""

    @patch('transcriber._detect_language_from_sample')
    @patch('transcriber._extract_language_from_metadata')
    def test_metadata_language_wins(self, mock_metadata, mock_detect):
        """Metadata language should be used when available."""
        mock_metadata.return_value = "es"
        mock_detect.return_value = ("en", 1.0)  # Would return English if called
        
        result = _get_language_for_transcription(
            "/audio.mp3", "/tmp", "test", "/metadata.json"
        )
        
        assert result == "es"
        mock_detect.assert_not_called()  # Should not try to detect

    @patch('transcriber._detect_language_from_sample')
    @patch('transcriber._extract_language_from_metadata')
    def test_detection_used_when_no_metadata(self, mock_metadata, mock_detect):
        """Detection should be used when metadata has no language."""
        mock_metadata.return_value = None
        mock_detect.return_value = ("fr", 0.9)
        
        result = _get_language_for_transcription(
            "/audio.mp3", "/tmp", "test", None
        )
        
        assert result == "fr"
        mock_detect.assert_called_once()

    @patch('transcriber._detect_language_from_sample')
    @patch('transcriber._extract_language_from_metadata')
    def test_fallback_to_default_on_low_confidence(self, mock_metadata, mock_detect):
        """Should fall back to default when detection confidence is low."""
        mock_metadata.return_value = None
        mock_detect.return_value = ("cy", 0.3)  # Welsh with low confidence
        
        result = _get_language_for_transcription(
            "/audio.mp3", "/tmp", "test", None
        )
        
        assert result == DEFAULT_LANGUAGE

    @patch('transcriber._detect_language_from_sample')
    @patch('transcriber._extract_language_from_metadata')
    def test_fallback_to_default_on_detection_failure(self, mock_metadata, mock_detect):
        """Should fall back to default when detection fails."""
        mock_metadata.return_value = None
        mock_detect.return_value = (None, 0.0)
        
        result = _get_language_for_transcription(
            "/audio.mp3", "/tmp", "test", None
        )
        
        assert result == DEFAULT_LANGUAGE


class TestTranscribeSingleChunkWithLanguage:
    """Test that language is passed to Whisper for chunk transcription."""

    @patch('transcriber.client')
    def test_language_passed_to_whisper(self, mock_client):
        """Language should be passed to Whisper API when provided."""
        mock_response = Mock()
        mock_response.duration = 60
        mock_response.segments = []
        mock_response.text = "Test transcript"
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(b'\x00' * 1000)
            f.flush()
            try:
                _transcribe_single_chunk(f.name, time_offset=0.0, language="es")
                
                # Verify language was passed
                call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
                assert call_kwargs.get('language') == "es"
            finally:
                os.unlink(f.name)

    @patch('transcriber.client')
    def test_no_language_param_when_none(self, mock_client):
        """Should not pass language parameter when None."""
        mock_response = Mock()
        mock_response.duration = 60
        mock_response.segments = []
        mock_response.text = "Test"
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(b'\x00' * 1000)
            f.flush()
            try:
                _transcribe_single_chunk(f.name, time_offset=0.0, language=None)
                
                call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
                assert 'language' not in call_kwargs
            finally:
                os.unlink(f.name)


class TestStitchTranscriptionsWithLanguage:
    """Test that language is correctly handled in stitched responses."""

    def test_language_passed_through(self):
        """Language should be included in stitched response."""
        responses = [
            {'text': 'Hello', 'segments': [], 'duration': 10},
            {'text': 'World', 'segments': [], 'duration': 10},
        ]
        
        result = _stitch_transcriptions(responses, language="de")
        
        assert result['language'] == "de"

    def test_default_language_when_not_provided(self):
        """Should use default language when not provided."""
        responses = [
            {'text': 'Test', 'segments': [], 'duration': 10},
        ]
        
        result = _stitch_transcriptions(responses, language=None)
        
        assert result['language'] == DEFAULT_LANGUAGE

    def test_single_response_gets_language(self):
        """Single response should also get language set."""
        response = {'text': 'Single', 'segments': [], 'duration': 10}
        
        result = _stitch_transcriptions([response], language="ja")
        
        assert result.get('language') == "ja"


class TestTranscribeAudioWithLanguage:
    """Integration tests for transcribe_audio with language detection."""

    @patch('transcriber.client')
    @patch('transcriber._get_language_for_transcription')
    @patch('transcriber._validate_audio')
    @patch('transcriber.os.path.getsize')
    @patch('transcriber.os.path.exists')
    def test_language_detection_happens_once(
        self, mock_exists, mock_getsize, mock_validate, 
        mock_get_lang, mock_client
    ):
        """Language detection should happen once before any transcription."""
        mock_exists.return_value = True
        mock_getsize.return_value = 1000  # Small file, no chunking needed
        mock_validate.return_value = (True, "valid audio")
        mock_get_lang.return_value = "fr"
        
        mock_response = Mock()
        mock_response.duration = 60
        mock_response.text = "Test"
        mock_response.language = "fr"
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = os.path.join(tmpdir, "test.mp3")
            with open(audio_file, 'wb') as f:
                f.write(b'\x00' * 1000)
            
            result, _ = transcribe_audio(audio_file, tmpdir, "test_video")
            
            # Language detection should be called exactly once
            mock_get_lang.assert_called_once()

    @patch('transcriber.client')
    @patch('transcriber._get_language_for_transcription')
    @patch('transcriber._validate_audio')
    @patch('transcriber.os.path.getsize')
    @patch('transcriber.os.path.exists')
    def test_language_passed_to_single_transcription(
        self, mock_exists, mock_getsize, mock_validate,
        mock_get_lang, mock_client
    ):
        """Language should be passed to Whisper for single-file transcription."""
        mock_exists.return_value = True
        mock_getsize.return_value = 1000
        mock_validate.return_value = (True, "valid")
        mock_get_lang.return_value = "es"
        
        mock_response = Mock()
        mock_response.duration = 60
        mock_response.text = "Test"
        mock_response.language = "es"
        mock_client.audio.transcriptions.create.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = os.path.join(tmpdir, "test.mp3")
            with open(audio_file, 'wb') as f:
                f.write(b'\x00' * 1000)
            
            transcribe_audio(audio_file, tmpdir, "test_video")
            
            # Verify language was passed to Whisper
            call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
            assert call_kwargs.get('language') == "es"

    @patch('transcriber.client')
    @patch('transcriber._get_language_for_transcription')
    @patch('transcriber._validate_audio')
    @patch('transcriber._split_audio_into_chunks')
    @patch('transcriber._prepare_audio_for_whisper')
    @patch('transcriber.os.path.getsize')
    @patch('transcriber.os.path.exists')
    def test_same_language_for_all_chunks(
        self, mock_exists, mock_getsize, mock_prepare,
        mock_split, mock_validate, mock_get_lang, mock_client
    ):
        """Same language should be used for all chunks."""
        mock_exists.return_value = True
        mock_getsize.side_effect = [30 * 1024 * 1024, 30 * 1024 * 1024, 5000, 5000, 5000]
        mock_validate.return_value = (True, "valid")
        mock_get_lang.return_value = "de"
        mock_prepare.return_value = "/prepared.mp3"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk1 = os.path.join(tmpdir, "chunk1.mp3")
            chunk2 = os.path.join(tmpdir, "chunk2.mp3")
            chunk3 = os.path.join(tmpdir, "chunk3.mp3")
            for p in [chunk1, chunk2, chunk3]:
                with open(p, 'wb') as f:
                    f.write(b'\x00' * 1000)
            
            mock_split.return_value = [(chunk1, 0.0), (chunk2, 600.0), (chunk3, 1200.0)]
            
            mock_response = Mock()
            mock_response.duration = 600
            mock_response.text = "Test"
            mock_response.segments = []
            mock_client.audio.transcriptions.create.return_value = mock_response
            
            audio_file = os.path.join(tmpdir, "test.mp3")
            with open(audio_file, 'wb') as f:
                f.write(b'\x00' * 1000)
            
            transcribe_audio(audio_file, tmpdir, "test_video")
            
            # Verify all calls used same language
            calls = mock_client.audio.transcriptions.create.call_args_list
            for call in calls:
                kwargs = call[1]
                assert kwargs.get('language') == "de", \
                    f"Expected language='de', got {kwargs.get('language')}"


class TestDefaultLanguageEnvVar:
    """Test TRANSCRIBE_DEFAULT_LANGUAGE environment variable."""

    def test_env_var_overrides_default(self):
        """Environment variable should override default 'en'."""
        import importlib
        
        original_env = os.environ.get("TRANSCRIBE_DEFAULT_LANGUAGE")
        try:
            os.environ["TRANSCRIBE_DEFAULT_LANGUAGE"] = "es"
            
            # Re-import to pick up new env var
            import transcriber
            importlib.reload(transcriber)
            
            assert transcriber.DEFAULT_LANGUAGE == "es"
        finally:
            # Restore original
            if original_env is not None:
                os.environ["TRANSCRIBE_DEFAULT_LANGUAGE"] = original_env
            elif "TRANSCRIBE_DEFAULT_LANGUAGE" in os.environ:
                del os.environ["TRANSCRIBE_DEFAULT_LANGUAGE"]
            
            # Reload to restore original default
            import transcriber
            importlib.reload(transcriber)
