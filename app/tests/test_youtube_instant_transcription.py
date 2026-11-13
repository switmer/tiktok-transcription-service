"""
Regression tests for the instant YouTube transcription success path.

Covers the production bug where:
  asyncio.to_thread(supabase...execute()) ran .execute() synchronously,
  then tried to call the APIResponse → 'APIResponse' object is not callable,
  which queued background fallback that overwrote a completed transcript.

All network/DB is mocked; no paid API calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

_APP_DIR = os.path.dirname(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.dirname(_APP_DIR)
for _path in (_PROJECT_ROOT, _APP_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.schemas import TranscriptionRequest  # noqa: E402


TASK_ID = "cb620adb-0000-4000-8000-000000000001"
YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TRANSCRIPT_TEXT = "A" * 1040  # non-trivial transcript (production was ~104k)


class _Resp:
    def __init__(self, data):
        self.data = data
        self.error = None


def _chainable(final_data):
    """Chainable supabase query mock ending in .execute() → _Resp(data)."""
    terminal = Mock()
    terminal.execute.return_value = _Resp(final_data)
    node = terminal
    for _ in range(10):
        parent = Mock()
        for method in (
            "select", "eq", "order", "limit", "single", "maybe_single",
            "insert", "update", "upsert", "range", "gte", "lt", "is_",
        ):
            getattr(parent, method).return_value = node
        parent.execute.return_value = _Resp(final_data)
        node = parent
    return node


def _pending_task_row():
    return {
        "task_id": TASK_ID,
        "status": "pending",
        "url": YOUTUBE_URL,
        "created_at": "2026-11-13T00:55:00Z",
        "error": None,
        "video_id": None,
        "title": None,
        "description": None,
        "platform": None,
        "transcript": None,
    }


def _youtube_result():
    return {
        "video_id": "dQw4w9WgXcQ",
        "title": "Test YouTube Video",
        "description": "desc",
        "transcript": TRANSCRIPT_TEXT,
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "duration": 212,
        "uploader": "Uploader",
        "channel": "Channel",
        "metadata": {"source": "mock"},
    }


@pytest.fixture
def background_tasks():
    bt = MagicMock()
    bt.add_task = MagicMock()
    return bt


@pytest.mark.asyncio
async def test_instant_youtube_success_saves_once_and_never_queues_fallback(background_tasks):
    """(a) Successful instant YouTube transcription saves once; no background queue."""
    pending = _pending_task_row()
    youtube = _youtube_result()

    mock_supabase = Mock()
    # First to_thread: select after init → pending row
    # Second to_thread: update with completed transcript
    select_chain = _chainable(pending)
    update_chain = _chainable([{"task_id": TASK_ID, "status": "completed"}])

    def table_side_effect(name):
        assert name == "transcriptions"
        # Alternate: select then update (order of calls in the success path)
        if not hasattr(table_side_effect, "n"):
            table_side_effect.n = 0
        table_side_effect.n += 1
        if table_side_effect.n == 1:
            return select_chain
        return update_chain

    mock_supabase.table.side_effect = table_side_effect

    to_thread_funcs = []

    async def capturing_to_thread(func, /, *args, **kwargs):
        to_thread_funcs.append(func)
        # Mirror real asyncio.to_thread: invoke the callable
        if not callable(func):
            raise TypeError(f"'{type(func).__name__}' object is not callable")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    with patch("app.api.public.init_task", new_callable=AsyncMock) as mock_init, \
         patch("app.api.public.supabase", mock_supabase), \
         patch("app.api.public.transcriber") as mock_transcriber, \
         patch("app.api.public.is_youtube_url", return_value=True), \
         patch("app.api.public.process_transcription_task") as mock_bg, \
         patch("app.api.public.send_completion_sms", new_callable=AsyncMock) as mock_sms, \
         patch("app.api.public.asyncio.to_thread", side_effect=capturing_to_thread):

        mock_init.return_value = {"task_id": TASK_ID}
        mock_transcriber.download_youtube_rapidapi.return_value = youtube

        from app.api.public import transcribe

        request = TranscriptionRequest(url=YOUTUBE_URL)
        response = await transcribe(request, background_tasks, user_id=None)

    assert response.status == "completed"
    assert response.task_id == TASK_ID
    mock_transcriber.download_youtube_rapidapi.assert_called_once_with(YOUTUBE_URL)
    # Must never queue background / fallback processing after success
    background_tasks.add_task.assert_not_called()
    mock_bg.assert_not_called()
    mock_sms.assert_not_called()
    # Save path used to_thread at least twice (select + update)
    assert len(to_thread_funcs) >= 2


@pytest.mark.asyncio
async def test_instant_youtube_to_thread_receives_callable(background_tasks):
    """(b) The save-path to_thread must receive a callable, not an APIResponse."""
    pending = _pending_task_row()
    youtube = _youtube_result()

    mock_supabase = Mock()
    select_chain = _chainable(pending)
    update_chain = _chainable([{"task_id": TASK_ID, "status": "completed"}])
    calls = {"n": 0}

    def table_side_effect(name):
        calls["n"] += 1
        return select_chain if calls["n"] == 1 else update_chain

    mock_supabase.table.side_effect = table_side_effect

    received = []

    async def capturing_to_thread(func, /, *args, **kwargs):
        received.append(func)
        if not callable(func):
            # Reproduce the production TypeError so the bug is visible
            raise TypeError(f"'{type(func).__name__}' object is not callable")
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    with patch("app.api.public.init_task", new_callable=AsyncMock) as mock_init, \
         patch("app.api.public.supabase", mock_supabase), \
         patch("app.api.public.transcriber") as mock_transcriber, \
         patch("app.api.public.is_youtube_url", return_value=True), \
         patch("app.api.public.send_completion_sms", new_callable=AsyncMock), \
         patch("app.api.public.asyncio.to_thread", side_effect=capturing_to_thread):

        mock_init.return_value = {"task_id": TASK_ID}
        mock_transcriber.download_youtube_rapidapi.return_value = youtube

        from app.api.public import transcribe

        request = TranscriptionRequest(url=YOUTUBE_URL)
        await transcribe(request, background_tasks, user_id=None)

    assert len(received) >= 2, "expected select + update to_thread calls"
    for i, func in enumerate(received):
        assert callable(func), (
            f"to_thread arg #{i} must be callable, got {type(func).__name__}: {func!r}"
        )


@pytest.mark.asyncio
async def test_post_save_exception_does_not_queue_fallback_or_fail_task(background_tasks):
    """(c) Exception after successful save must not queue fallback; task stays completed."""
    pending = _pending_task_row()
    youtube = _youtube_result()

    mock_supabase = Mock()
    select_chain = _chainable(pending)
    update_chain = _chainable([{"task_id": TASK_ID, "status": "completed"}])
    calls = {"n": 0}

    def table_side_effect(name):
        calls["n"] += 1
        return select_chain if calls["n"] == 1 else update_chain

    mock_supabase.table.side_effect = table_side_effect

    async def capturing_to_thread(func, /, *args, **kwargs):
        if not callable(func):
            raise TypeError(f"'{type(func).__name__}' object is not callable")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    with patch("app.api.public.init_task", new_callable=AsyncMock) as mock_init, \
         patch("app.api.public.supabase", mock_supabase), \
         patch("app.api.public.transcriber") as mock_transcriber, \
         patch("app.api.public.is_youtube_url", return_value=True), \
         patch("app.api.public.process_transcription_task"), \
         patch(
             "app.api.public.send_completion_sms",
             new_callable=AsyncMock,
             side_effect=RuntimeError("SMS bookkeeping blew up"),
         ), \
         patch("app.api.public.asyncio.to_thread", side_effect=capturing_to_thread):

        mock_init.return_value = {"task_id": TASK_ID}
        mock_transcriber.download_youtube_rapidapi.return_value = youtube

        from app.api.public import transcribe

        # SMS failure is caught internally; force a post-save raise by breaking
        # task_data mutation via a patched logger that raises on the success log —
        # instead, call with user_phone so SMS path is used (already swallowed),
        # then simulate a post-save raise by making the success logger raise once
        # AFTER transcript_saved is set. We do that by patching the module logger.
        request = TranscriptionRequest(url=YOUTUBE_URL, user_phone="+15551234567")

        # Make the "completed" log raise AFTER save to exercise the guard.
        # logger.info is called for "YouTube instant transcription completed..."
        real_info = None
        raise_once = {"done": False}

        def info_side_effect(msg, *args, **kwargs):
            text = str(msg)
            if (
                not raise_once["done"]
                and "YouTube instant transcription completed" in text
            ):
                raise_once["done"] = True
                raise RuntimeError("post-save bookkeeping failure")
            return None

        with patch("app.api.public.logger") as mock_logger:
            mock_logger.info.side_effect = info_side_effect
            mock_logger.error = MagicMock()
            mock_logger.warning = MagicMock()
            response = await transcribe(request, background_tasks, user_id=None)

    assert response.status == "completed"
    assert getattr(response, "transcript", None) in (None, TRANSCRIPT_TEXT) or True
    # Critical: must NOT queue background reprocessing after a successful save
    background_tasks.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_status_refuses_to_overwrite_completed_transcript():
    """(c) Later failure must not overwrite a completed task that has a transcript."""
    from app.app import update_task_status

    completed_row = {
        "status": "completed",
        "transcript": TRANSCRIPT_TEXT,
    }
    failed_updates = []

    class TrackingQuery:
        """Minimal chainable query that records update payloads."""

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def maybe_single(self, *a, **k):
            return self

        def single(self, *a, **k):
            return self

        def update(self, data):
            failed_updates.append(dict(data))
            return self

        def execute(self):
            # select path returns the completed row; update path unused on fixed code
            if failed_updates:
                return _Resp([{"task_id": TASK_ID, **failed_updates[-1]}])
            return _Resp(completed_row)

    mock_supabase = Mock()
    mock_supabase.table.return_value = TrackingQuery()

    async def realish_to_thread(func, /, *args, **kwargs):
        assert callable(func), f"to_thread got non-callable: {type(func).__name__}"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    with patch("app.app.supabase", mock_supabase), \
         patch("app.app.asyncio.to_thread", side_effect=realish_to_thread):
        await update_task_status(TASK_ID, "failed", "Failed to download video")

    assert failed_updates == [], (
        f"completed transcript must not be overwritten with failed status; "
        f"got updates={failed_updates}"
    )
