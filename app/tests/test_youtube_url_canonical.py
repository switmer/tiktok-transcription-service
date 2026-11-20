"""YouTube URL canonicalization shared by app.py and transcriber.py.

Live, shorts, embed, youtu.be, m., and music. links must become
https://www.youtube.com/watch?v=ID before RapidAPI and yt-dlp, and the
job must be stored as platform youtube rather than the tiktok default.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.app import init_task, is_youtube_url
from app.transcriber import (
    canonical_youtube_url,
    clean_url_for_api,
    download_tiktok_ytdlp,
    download_youtube_rapidapi,
    extract_youtube_video_id,
    youtube_video_identity,
)

LIVE = "https://www.youtube.com/live/LzZ_FptHWqs?is=qIAcJzCrcYqh_KF9"
CANONICAL = "https://www.youtube.com/watch?v=LzZ_FptHWqs"
VIDEO_ID = "LzZ_FptHWqs"

YOUTUBE_FORMS = [
    LIVE,
    "https://www.youtube.com/watch?v=LzZ_FptHWqs",
    "https://www.youtube.com/watch?list=PLxxx&v=LzZ_FptHWqs",
    "https://youtube.com/watch?feature=share&v=LzZ_FptHWqs&t=43s",
    "https://youtu.be/LzZ_FptHWqs?si=abc&t=12",
    "https://www.youtube.com/shorts/LzZ_FptHWqs?pp=ygU",
    "https://www.youtube.com/embed/LzZ_FptHWqs",
    "https://www.youtube-nocookie.com/embed/LzZ_FptHWqs",
    "https://m.youtube.com/watch?v=LzZ_FptHWqs&pp=1&is=other",
    "https://music.youtube.com/watch?v=LzZ_FptHWqs&si=track",
    "https://youtube.com/live/LzZ_FptHWqs/",
    "https://youtu.be/LzZ_FptHWqs)",
]


@pytest.mark.parametrize("url", YOUTUBE_FORMS)
def test_every_form_canonicalizes_to_the_same_watch_url(url):
    assert youtube_video_identity(url) == (VIDEO_ID, CANONICAL)
    assert extract_youtube_video_id(url) == VIDEO_ID
    assert canonical_youtube_url(url) == CANONICAL
    assert is_youtube_url(url) is True


def test_share_param_is_not_the_video_id():
    assert extract_youtube_video_id(LIVE) == VIDEO_ID
    assert "qIAcJzCrcYqh_KF9" not in CANONICAL
    cleaned = clean_url_for_api(LIVE)
    assert "is=" not in cleaned
    assert "/live/LzZ_FptHWqs" in cleaned


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?is=qIAcJzCrcYqh_KF9",
    "https://youtu.be/short",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQZ",  # 12 chars
    "https://www.youtube.com/playlist?list=PLxxxx",
    "https://www.tiktok.com/@user/video/123",
    "https://example.com/live/LzZ_FptHWqs",
    "",
])
def test_non_video_urls_are_not_youtube(url):
    assert youtube_video_identity(url) is None
    assert is_youtube_url(url) is False


def test_rapidapi_gets_canonical_url_and_real_video_id(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        response = MagicMock()
        response.status_code = 500
        response.text = "rejected"
        return response

    monkeypatch.setattr("app.transcriber.requests.get", fake_get)
    assert download_youtube_rapidapi(LIVE) is None
    assert captured["params"]["video_id"] == VIDEO_ID
    assert captured["params"]["video_id"] != "unknown"
    assert captured["params"]["url"] == CANONICAL
    assert "is=" not in captured["params"]["url"]


def test_ytdlp_gets_canonical_watch_url(tmp_path, monkeypatch):
    seen = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            seen.append(url)
            return {"id": VIDEO_ID, "title": "Live"}

        def download(self, urls):
            seen.extend(urls)

    monkeypatch.setattr("app.transcriber.yt_dlp.YoutubeDL", FakeYDL)
    monkeypatch.setattr("app.transcriber.time.sleep", lambda *args, **kwargs: None)
    download_tiktok_ytdlp(LIVE, str(tmp_path))
    assert seen
    assert set(seen) == {CANONICAL}


@pytest.mark.asyncio
async def test_init_task_stores_youtube_platform_for_a_live_link():
    inserted = {}

    class Query:
        def insert(self, data):
            inserted.update(data)
            return self

        def execute(self):
            return SimpleNamespace(data=[inserted], error=None)

    fake = MagicMock()
    fake.table.return_value = Query()
    with patch("app.app.supabase", fake):
        result = await init_task(LIVE, user_phone="+15551234567")

    assert inserted["platform"] == "youtube"
    assert inserted["video_id"] == VIDEO_ID
    assert inserted["url"] == CANONICAL
    assert result["task_id"] == inserted["task_id"]
