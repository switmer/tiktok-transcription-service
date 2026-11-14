"""Tests for fetch_youtube_captions (youtube-transcript-api). Network is mocked."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from youtube_transcript_api import IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled

from app.transcriber import fetch_youtube_captions

URL = "https://www.youtube.com/watch?v=tgwrCNzR6V0"


def _fetched(generated=False, lang="en"):
    snippets = [
        SimpleNamespace(text="Hello there", start=0.0, duration=1.5),
        SimpleNamespace(text="how are\nyou", start=1.5, duration=2.0),
    ]
    return SimpleNamespace(snippets=snippets, language_code=lang, is_generated=generated)


def _api(list_result=None, list_error=None):
    api = MagicMock()
    if list_error:
        api.list.side_effect = list_error
    else:
        api.list.return_value = list_result
    return api


def _transcript_list(fetched):
    tl = MagicMock()
    tl.find_transcript.return_value.fetch.return_value = fetched
    return tl


@patch("app.transcriber.requests.get")
@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_found_keeps_segments_language_and_flag(mock_cls, mock_get):
    mock_cls.return_value = _api(_transcript_list(_fetched(generated=True)))
    mock_get.return_value.json.return_value = {"title": "T", "author_name": "A"}

    out = fetch_youtube_captions(URL)

    assert out["status"] == "found"
    r = out["result"]
    assert r["transcript"] == "Hello there how are you"
    assert r["title"] == "T" and r["video_id"] == "tgwrCNzR6V0"
    caps = r["metadata"]["captions"]
    assert caps["language"] == "en" and caps["is_generated"] is True
    assert caps["segments"][1] == {"text": "how are\nyou", "start": 1.5, "duration": 2.0}
    assert r["duration"] == 3


@patch("app.transcriber.requests.get", side_effect=Exception("oembed down"))
@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_found_even_if_oembed_fails(mock_cls, _get):
    mock_cls.return_value = _api(_transcript_list(_fetched()))
    out = fetch_youtube_captions(URL)
    assert out["status"] == "found"
    assert out["result"]["title"] == "YouTube Video"


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_falls_back_to_any_language(mock_cls):
    tl = MagicMock()
    tl.find_transcript.side_effect = NoTranscriptFound("x", ["en"], tl)
    other = MagicMock()
    other.fetch.return_value = _fetched(lang="es")
    tl.__iter__.return_value = iter([other])
    mock_cls.return_value = _api(tl)
    with patch("app.transcriber.requests.get", side_effect=Exception):
        out = fetch_youtube_captions(URL)
    assert out["status"] == "found"
    assert out["result"]["metadata"]["captions"]["language"] == "es"


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_no_captions(mock_cls):
    mock_cls.return_value = _api(list_error=TranscriptsDisabled("tgwrCNzR6V0"))
    assert fetch_youtube_captions(URL)["status"] == "no_captions"


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_blocked_is_not_no_captions(mock_cls):
    for err in (IpBlocked("tgwrCNzR6V0"), RequestBlocked("tgwrCNzR6V0")):
        mock_cls.return_value = _api(list_error=err)
        assert fetch_youtube_captions(URL)["status"] == "blocked"


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_other_error(mock_cls):
    mock_cls.return_value = _api(list_error=RuntimeError("boom"))
    assert fetch_youtube_captions(URL)["status"] == "error"


def test_bad_url():
    assert fetch_youtube_captions("https://example.com/x")["status"] == "error"


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_proxy_is_passed_through(mock_cls):
    mock_cls.return_value = _api(list_error=TranscriptsDisabled("x"))
    fetch_youtube_captions(URL, "http://user:pw@proxy:8080")
    cfg = mock_cls.call_args.kwargs["proxy_config"]
    assert cfg.http_url == "http://user:pw@proxy:8080"
