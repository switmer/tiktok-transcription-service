"""Timed YouTube segments, API-key privacy, and maintenance-route auth.

No network and no live database. Supabase is replaced with in-memory fakes.
"""

import importlib
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.api import public as public_module
from app.core.transcripts import fetch_transcript_row
from app.core.visibility import (
    PUBLIC_LISTING_FILTER,
    exclude_hidden_from_listing,
    resolve_visibility,
)
from app.transcriber import (
    WHISPER_REENCODE_TIMEOUT_SECONDS,
    YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS,
    extract_timed_segments,
    normalize_timed_segments,
    segments_from_whisper_response,
)

# `import app.app` returns the FastAPI instance (package attribute shadowing).
# importlib returns the module the routes actually close over. app.py's import
# fallback binds `discovery` to that same module object.
app_module = importlib.import_module("app.app")
fastapi_app = app_module.app

TASK_ID = "550e8400-e29b-41d4-a716-446655440000"
VALID_KEY = "test-render-api-key"
APP_PY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


class _Chain:
    """Records query calls and returns a canned execute() payload."""

    def __init__(self, data=None, fail_selects=None):
        self.data = data
        self.fail_selects = fail_selects or set()
        self.calls = []
        self.or_expr = None
        self._columns = ""

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, columns, *args, **kwargs):
        self._columns = columns
        self.calls.append(("select", columns))
        return self

    def eq(self, *args, **kwargs):
        self.calls.append(("eq", args))
        return self

    def or_(self, expr):
        self.or_expr = expr
        self.calls.append(("or", expr))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def single(self):
        return self

    def in_(self, *args, **kwargs):
        self.calls.append(("in", args))
        return self

    def execute(self):
        if self._columns in self.fail_selects:
            raise Exception(f"column transcriptions.{self._columns} does not exist")
        return SimpleNamespace(data=self.data, error=None)


def _row(**overrides):
    base = {
        "task_id": TASK_ID,
        "status": "completed",
        "transcript": "The motion carries.",
        "error": None,
        "visibility": "public",
        "segments": [
            {"start": 12.0, "end": 18.5, "text": "The motion carries."},
        ],
        "title": "City council",
        "description": None,
        "created_at": "2026-01-01T00:00:00Z",
        "video_id": "abc123def45",
        "thumbnail_url": None,
        "thumbnail_local_path": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def api_client():
    transport = httpx.ASGITransport(app=fastapi_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client


@pytest.fixture(autouse=True)
def _clear_overrides():
    fastapi_app.dependency_overrides.clear()
    yield
    fastapi_app.dependency_overrides.clear()


def test_normalize_timestamp_pair_duration_and_next_start():
    chunks = [
        {"text": "Call to order", "timestamp": [0, 4.25]},
        {"text": "Roll call", "start": 4.25, "duration": 3},
        {"text": "Minutes", "start": 10},
        {"text": "Adjourned", "start": 22},
    ]
    assert normalize_timed_segments(chunks) == [
        {"start": 0.0, "end": 4.25, "text": "Call to order"},
        {"start": 4.25, "end": 7.25, "text": "Roll call"},
        {"start": 10.0, "end": 22.0, "text": "Minutes"},
        {"start": 22.0, "end": 22.0, "text": "Adjourned"},
    ]


def test_normalize_treats_large_values_as_milliseconds_once_per_list():
    raw = [
        {"text": "Open", "start": 0, "end": 1500},
        {"text": "Close", "start": 120000, "duration": 2000},
    ]
    assert normalize_timed_segments(raw) == [
        {"start": 0.0, "end": 1.5, "text": "Open"},
        {"start": 120.0, "end": 122.0, "text": "Close"},
    ]


def test_normalize_missing_provider_payload_is_null():
    assert normalize_timed_segments(None) is None
    assert extract_timed_segments({"transcript": "plain text only"}) is None
    assert extract_timed_segments({"data": {"text": "plain", "chunks": []}}) is None


def test_whisper_objects_become_segments():
    class _Segment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    class _Response:
        segments = [_Segment(0, 5.5, " Hello "), _Segment(5.5, 9, "there")]

    assert segments_from_whisper_response(_Response()) == [
        {"start": 0.0, "end": 5.5, "text": "Hello"},
        {"start": 5.5, "end": 9.0, "text": "there"},
    ]
    assert segments_from_whisper_response({"text": "no timings"}) is None


@patch.dict(os.environ, {"RAPIDAPI_KEY": "test-key"})
@patch("app.transcriber.requests.get")
def test_rapidapi_youtube_keeps_timed_chunks(mock_get):
    from app.transcriber import download_youtube_rapidapi

    api_response = MagicMock()
    api_response.status_code = 200
    api_response.json.return_value = {
        "data": {
            "text": "The fire board approved the budget.",
            "chunks": [
                {"text": "The fire board", "timestamp": [65.0, 68.2]},
                {"text": "approved the budget.", "start": 68.2, "duration": 2.8},
            ],
        },
        "status": "success",
        "title": "Fire board",
    }
    mock_get.return_value = api_response

    result = download_youtube_rapidapi("https://www.youtube.com/watch?v=abc123def45")

    assert result["transcript"] == "The fire board approved the budget."
    assert result["segments"] == [
        {"start": 65.0, "end": 68.2, "text": "The fire board"},
        {"start": 68.2, "end": 71.0, "text": "approved the budget."},
    ]
    assert mock_get.call_args.kwargs["timeout"] == YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS


def test_long_video_timeouts_cover_a_multi_hour_reencode():
    assert YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS >= 120
    assert WHISPER_REENCODE_TIMEOUT_SECONDS == 1800


def test_visibility_defaults():
    assert resolve_visibility(None, from_api_key=True) == "private"
    assert resolve_visibility("  ", from_api_key=True) == "private"
    assert resolve_visibility(None, from_api_key=False) == "public"
    assert resolve_visibility("Unlisted", from_api_key=True) == "unlisted"
    with pytest.raises(ValueError):
        resolve_visibility("secret", from_api_key=True)


def test_completion_updates_do_not_force_public_visibility():
    source = open(APP_PY, encoding="utf-8").read()
    assert "'visibility': 'public'" not in source
    assert '"visibility": "public"' not in source


@pytest.mark.asyncio
async def test_hidden_rows_are_removed_from_search_hits():
    chain = _Chain(data=[
        {"task_id": "pub", "visibility": "public"},
        {"task_id": "old", "visibility": None},
        {"task_id": "priv", "visibility": "private"},
        {"task_id": "unlist", "visibility": "unlisted"},
    ])
    rows = [
        {"task_id": "pub", "title": "Public"},
        {"task_id": "old", "title": "Legacy"},
        {"task_id": "priv", "title": "Private"},
        {"task_id": "unlist", "title": "Unlisted"},
        {"task_id": "missing", "title": "Unknown"},
    ]
    kept = await exclude_hidden_from_listing(chain, rows)
    assert [row["task_id"] for row in kept] == ["pub", "old"]


@pytest.mark.asyncio
async def test_public_transcript_json_includes_segments(api_client, monkeypatch):
    monkeypatch.setattr(public_module, "supabase", _Chain(data=_row()))
    async with api_client as client:
        response = await client.get(f"/api/public/transcript/{TASK_ID}?format=json")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == TASK_ID
    assert body["transcript"] == "The motion carries."
    assert body["segments"] == [
        {"start": 12.0, "end": 18.5, "text": "The motion carries."},
    ]


@pytest.mark.asyncio
async def test_public_transcript_segments_null_when_column_missing(api_client, monkeypatch):
    chain = _Chain(
        data=_row(segments=None),
        fail_selects={"task_id, status, transcript, error, visibility, segments"},
    )
    monkeypatch.setattr(public_module, "supabase", chain)
    async with api_client as client:
        response = await client.get(f"/api/public/transcript/{TASK_ID}?format=json")
    assert response.status_code == 200, response.text
    assert response.json()["segments"] is None
    assert response.json()["transcript"] == "The motion carries."


@pytest.mark.asyncio
async def test_public_transcript_hides_private_tasks(api_client, monkeypatch):
    monkeypatch.setattr(public_module, "supabase", _Chain(data=_row(visibility="private")))
    async with api_client as client:
        json_response = await client.get(f"/api/public/transcript/{TASK_ID}?format=json")
        text_response = await client.get(f"/api/public/transcript/{TASK_ID}?format=text")
    assert json_response.status_code == 404
    assert text_response.status_code == 404


@pytest.mark.asyncio
async def test_private_transcript_requires_key_and_returns_segments(api_client, monkeypatch):
    monkeypatch.setenv("API_KEYS", VALID_KEY)
    monkeypatch.setattr(app_module, "supabase", _Chain(data=_row(visibility="private")))
    async with api_client as client:
        missing = await client.get(f"/api/transcript/{TASK_ID}")
        ok = await client.get(
            f"/api/transcript/{TASK_ID}",
            headers={"X-API-Key": VALID_KEY},
        )
    assert missing.status_code == 401
    # verify_api_key raises during dependency injection. FastAPI's HTTPException
    # handler returns `detail` for that path.
    assert "X-API-Key" in missing.json().get("detail", "")
    assert ok.status_code == 200, ok.text
    assert ok.json()["segments"][0]["start"] == 12.0
    assert ok.json()["transcript"] == "The motion carries."


@pytest.mark.asyncio
async def test_api_key_create_defaults_private_and_can_opt_in(api_client, monkeypatch):
    seen = {}

    async def fake_init(url, user_id=None, user_phone=None, visibility=None):
        seen["visibility"] = visibility
        return {"task_id": TASK_ID}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(app_module, "supabase", object())
    monkeypatch.setattr(app_module, "init_task", fake_init)
    monkeypatch.setattr(app_module, "process_transcription_task", noop)
    fastapi_app.dependency_overrides[app_module.validate_api_key] = lambda: "key-user"

    async with api_client as client:
        default = await client.post(
            "/api/tasks",
            json={"url": "https://www.youtube.com/watch?v=abc123def45"},
        )
        assert default.status_code == 201, default.text
        assert seen["visibility"] == "private"

        explicit = await client.post(
            "/api/tasks",
            json={
                "url": "https://www.youtube.com/watch?v=abc123def45",
                "visibility": "public",
            },
        )
        assert explicit.status_code == 201, explicit.text
        assert seen["visibility"] == "public"

        invalid = await client.post(
            "/api/tasks",
            json={
                "url": "https://www.youtube.com/watch?v=abc123def45",
                "visibility": "secret",
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_public_create_stays_public(api_client, monkeypatch):
    seen = {}

    async def fake_init(url, user_id=None, user_phone=None, visibility=None):
        seen["visibility"] = visibility
        return {"task_id": TASK_ID}

    completed = _row()
    monkeypatch.setattr(public_module, "init_task", fake_init)
    monkeypatch.setattr(public_module, "supabase", _Chain(data=completed))

    async with api_client as client:
        response = await client.post(
            "/api/public/transcribe",
            json={"url": "https://example.com/meeting"},
        )
    assert response.status_code == 200, response.text
    assert seen["visibility"] == "public"


@pytest.mark.asyncio
async def test_public_task_list_excludes_private_and_unlisted(api_client, monkeypatch):
    chain = _Chain(data=[])
    monkeypatch.setattr(public_module, "supabase", chain)
    async with api_client as client:
        response = await client.get("/api/public/tasks")
    assert response.status_code == 200, response.text
    assert response.json()["tasks"] == []
    assert chain.or_expr == PUBLIC_LISTING_FILTER


@pytest.mark.asyncio
async def test_recent_discovery_uses_the_public_listing_filter(api_client, monkeypatch):
    discovery_module = app_module.discovery
    discovery_module._DISCOVERY_CACHE.clear()
    chain = _Chain(data=[])
    monkeypatch.setattr(discovery_module, "supabase", chain)
    async with api_client as client:
        response = await client.get("/api/public/discover/recent")
    assert response.status_code == 200, response.text
    assert response.json() == []
    assert chain.or_expr == PUBLIC_LISTING_FILTER
    discovery_module._DISCOVERY_CACHE.clear()


@pytest.mark.asyncio
async def test_share_page_404_for_private_row(api_client, monkeypatch):
    monkeypatch.setattr(app_module, "supabase", _Chain(data=_row(visibility="private", title="Hidden")))
    async with api_client as client:
        response = await client.get(f"/v/{TASK_ID}")
    assert response.status_code == 404
    assert "Transcript Not Found" in response.text


@pytest.mark.asyncio
async def test_maintenance_aliases_require_api_key(api_client, monkeypatch):
    monkeypatch.setenv("API_KEYS", VALID_KEY)
    monkeypatch.setattr(app_module, "supabase", _Chain(data=[]))
    paths = ("/api/public/cleanup-stuck-tasks", "/api/public/reprocess-sms-jobs")
    async with api_client as client:
        for path in paths:
            open_call = await client.post(path)
            assert open_call.status_code == 401, path
            assert "X-API-Key" in open_call.json().get("detail", "")
            bad = await client.post(path, headers={"X-API-Key": "nope"})
            assert bad.status_code == 401, path
            ok = await client.post(path, headers={"X-API-Key": VALID_KEY})
            assert ok.status_code == 200, ok.text


def test_fetch_transcript_row_is_used_by_both_readers():
    """Guard against the private route drifting back to a text-only select."""
    source = open(APP_PY, encoding="utf-8").read()
    public_source = open(public_module.__file__, encoding="utf-8").read()
    assert "fetch_transcript_row" in source
    assert "fetch_transcript_row" in public_source
    assert fetch_transcript_row.__name__ == "fetch_transcript_row"
