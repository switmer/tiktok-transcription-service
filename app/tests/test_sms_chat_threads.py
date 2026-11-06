import os
import sys

import pytest

# Repo root on sys.path so `from app ...` matches production `uvicorn app:app`
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from app import app as fastapi_app
from app.api import sms as sms_module
from app.models.schemas import SmsChatRequest
from app.sms import SMSHandler


class _Response:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent
        self.operations = []
        self.payload = None

    def select(self, *args, **kwargs):
        self.operations.append(("select", args, kwargs))
        return self

    def eq(self, *args, **kwargs):
        self.operations.append(("eq", args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self.operations.append(("order", args, kwargs))
        return self

    def limit(self, *args, **kwargs):
        self.operations.append(("limit", args, kwargs))
        return self

    def maybe_single(self):
        self.operations.append(("maybe_single",))
        return self

    def single(self):
        self.operations.append(("single",))
        return self

    def insert(self, payload):
        self.operations.append(("insert", payload))
        self.payload = payload
        return self

    def update(self, payload):
        self.operations.append(("update", payload))
        self.payload = payload
        return self

    def execute(self):
        return self.parent._execute(self.name, self.operations, self.payload)


class _FakeSupabase:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def table(self, name):
        return _FakeTable(name, self)

    def _execute(self, name, operations, payload):
        self.calls.append((name, operations, payload))
        if name not in self.responses or not self.responses[name]:
            return _Response([])
        return self.responses[name].pop(0)


def test_build_chat_context_includes_sections():
    context = SMSHandler._build_chat_context(
        title="Test Title",
        description="Test description",
        transcript_text="Transcript text",
        quote="Quote line",
        tldr_list=["Point 1", "Point 2"],
        conversation_summary="Summary text",
        message_history=[
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"}
        ]
    )
    assert "TITLE:" in context
    assert "DESCRIPTION:" in context
    assert "QUOTE:" in context
    assert "TLDR:" in context
    assert "CONVERSATION SUMMARY:" in context
    assert "RECENT MESSAGES:" in context
    assert "TRANSCRIPT:" in context


@pytest.mark.asyncio
async def test_generate_answer_fallback_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    answer = await SMSHandler.generate_answer(
        question="What is this about?",
        transcript_text="This transcript is about testing the fallback answer generation.",
        max_chars=40
    )
    assert answer


@pytest.mark.asyncio
async def test_sms_chat_creates_thread_and_returns_answer(monkeypatch):
    fake_responses = {
        "conversation_threads": [
            _Response([]),
            _Response({
                "id": "thread-1",
                "task_id": "task-1",
                "summary": None,
                "message_count": 0
            }),
            _Response([]),
        ],
        "transcriptions": [
            _Response([{"task_id": "task-1"}]),
            _Response({
                "status": "completed",
                "transcript": "Transcript content",
                "title": "Title",
                "description": "Description",
                "quote": "Quote",
                "tldr": "[]",
                "error": None
            }),
        ],
        "conversation_messages": [
            _Response([]),
            _Response([
                {"role": "user", "content": "Question", "created_at": "2025-01-01T00:00:00Z"}
            ]),
            _Response([]),
        ],
    }
    fake_supabase = _FakeSupabase(fake_responses)

    async def _mock_answer(*args, **kwargs):
        return "Short answer"

    async def _mock_summary(*args, **kwargs):
        return "Updated summary"

    monkeypatch.setattr(sms_module, "supabase", fake_supabase)
    monkeypatch.setattr(sms_module.sms.SMSHandler, "generate_answer", _mock_answer)
    monkeypatch.setattr(sms_module.sms.SMSHandler, "generate_chat_summary", _mock_summary)

    request = SmsChatRequest(phone="+15551234567", message="Question", max_chars=300)
    response = await sms_module.sms_chat(request)

    assert response.answer == "Short answer"
    assert response.task_id == "task-1"
    assert response.thread_id


@pytest.mark.asyncio
async def test_sms_chat_route_is_registered():
    """Production callers (sms-inbound /chat) POST /api/sms/chat — must not 404."""
    import httpx

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/definitely-not-a-route")
        assert missing.status_code == 404

        chat = await client.post(
            "/api/sms/chat",
            json={"phone": "+15551234567", "message": "What is this about?"},
        )
        assert chat.status_code != 404, chat.text

        reset = await client.post(
            "/api/sms/chat/reset",
            json={"phone": "+15551234567"},
        )
        assert reset.status_code != 404, reset.text
