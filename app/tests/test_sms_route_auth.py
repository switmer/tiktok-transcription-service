"""Auth checks for SMS routes that read or change a user's data.

`verify_api_key` returns 401 (AUTH_REQUIRED / AUTH_INVALID), not 403.
A valid key is a raw `X-API-Key` value present in the `API_KEYS` env list.
"""

import os
import re
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.api import sms as sms_module
from app.app import app as fastapi_app

VALID_KEY = "test-render-api-key"
OTHER_KEY = "another-service-key"
# Previously committed in sms-inbound as a fallback. It must not authenticate.
LEAKED_FALLBACK_KEY = "f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b"
PHONE = "+15551234567"

PROTECTED_ROUTES = [
    ("/api/sms/summary", {"phone": PHONE}),
    ("/api/sms/chat", {"phone": PHONE, "message": "What happened?"}),
    ("/api/sms/chat/reset", {"phone": PHONE}),
    ("/api/link-sms-account", {"phone": PHONE}),
]


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def insert(self, payload):
        return self

    def update(self, payload):
        return self

    def execute(self):
        queue = self.parent.queues.get(self.name) or []
        if not queue:
            raise AssertionError(f"unexpected query on {self.name}")
        return queue.pop(0)


class _ScriptedSupabase:
    def __init__(self, queues):
        self.queues = queues

    def table(self, name):
        return _Query(name, self)


class _AuthUser:
    id = "auth-user-1"


class _AuthResult:
    user = _AuthUser()


class _AuthAdmin:
    def create_user(self, payload):
        return _AuthResult()

    def delete_user(self, user_id):
        return None


class _Auth:
    def __init__(self):
        self.admin = _AuthAdmin()


class _SmsUsersTable:
    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        return _Row(None)


class _LinkSupabase:
    def __init__(self):
        self.auth = _Auth()
        self.rpc_calls = []

    def table(self, name):
        assert name == "sms_users"
        return _SmsUsersTable()

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        if fn == "get_sms_user_stats":
            return _Row([{"total_transcriptions": 4}])
        if fn == "link_sms_user_to_auth":
            return _Row([{"linked_transcriptions": 4}])
        raise AssertionError(fn)


@pytest.fixture(autouse=True)
def configured_api_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", f"{OTHER_KEY},{VALID_KEY}")


@pytest_asyncio.fixture
async def api_client():
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _auth_header(key=VALID_KEY):
    return {"X-API-Key": key}


def _assert_unauthorized(response, message_part):
    """verify_api_key raises ApiError(401). The running app returns that as 401.

    The body is FastAPI's {"detail": "..."} when the registered ApiError handler
    is a different imported class than the one the route raises. Accept the
    structured {"error": {"code", "message"}} shape too.
    """
    assert response.status_code == 401, response.text
    body = response.json()
    if isinstance(body.get("detail"), str):
        assert message_part in body["detail"]
        return
    error = body["error"]
    assert error["code"] in {"AUTH_REQUIRED", "AUTH_INVALID"}
    assert message_part in error["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", PROTECTED_ROUTES)
async def test_protected_sms_routes_require_api_key(api_client, path, payload):
    response = await api_client.post(path, json=payload)
    _assert_unauthorized(response, "X-API-Key")


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", PROTECTED_ROUTES)
async def test_protected_sms_routes_reject_invalid_key(api_client, path, payload):
    response = await api_client.post(path, json=payload, headers=_auth_header("not-a-valid-key"))
    _assert_unauthorized(response, "Invalid API Key")


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", PROTECTED_ROUTES)
async def test_leaked_fallback_key_does_not_authenticate(api_client, path, payload):
    response = await api_client.post(path, json=payload, headers=_auth_header(LEAKED_FALLBACK_KEY))
    _assert_unauthorized(response, "Invalid API Key")


@pytest.mark.asyncio
async def test_summary_succeeds_with_valid_key(api_client, monkeypatch):
    seen = {}

    async def _summary(phone):
        seen["phone"] = phone
        return "Short TLDR"

    monkeypatch.setattr(sms_module.sms.SMSHandler, "handle_summary_command", _summary)

    response = await api_client.post(
        "/api/sms/summary",
        json={"phone": PHONE},
        headers=_auth_header(),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"summary": "Short TLDR"}
    assert seen["phone"] == PHONE


@pytest.mark.asyncio
async def test_summary_accepts_lowercase_x_api_key_header(api_client, monkeypatch):
    async def _summary(phone):
        return "Short TLDR"

    monkeypatch.setattr(sms_module.sms.SMSHandler, "handle_summary_command", _summary)
    response = await api_client.post(
        "/api/sms/summary",
        json={"phone": PHONE},
        headers={"x-api-key": VALID_KEY},
    )
    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "Short TLDR"


@pytest.mark.asyncio
async def test_chat_succeeds_with_valid_key(api_client, monkeypatch):
    fake = _ScriptedSupabase({
        "conversation_threads": [
            _Row([]),
            _Row([{
                "id": "thread-1",
                "task_id": "task-1",
                "summary": None,
                "message_count": 0,
            }]),
            _Row([{"id": "thread-1"}]),
        ],
        "transcriptions": [
            _Row([{"task_id": "task-1"}]),
            _Row({
                "status": "completed",
                "transcript": "Transcript content about testing.",
                "title": "Title",
                "description": "Description",
                "quote": "Quote",
                "tldr": None,
                "error": None,
            }),
        ],
        "conversation_messages": [
            _Row([{"id": "user-msg"}]),
            _Row([{
                "role": "user",
                "content": "What happened?",
                "created_at": "2025-01-01T00:00:00Z",
            }]),
            _Row([{"id": "assistant-msg"}]),
        ],
    })

    async def _answer(*args, **kwargs):
        return "Short answer"

    async def _chat_summary(*args, **kwargs):
        return "Updated summary"

    monkeypatch.setattr(sms_module, "supabase", fake)
    monkeypatch.setattr(sms_module.sms.SMSHandler, "generate_answer", _answer)
    monkeypatch.setattr(sms_module.sms.SMSHandler, "generate_chat_summary", _chat_summary)

    response = await api_client.post(
        "/api/sms/chat",
        json={"phone": PHONE, "message": "What happened?"},
        headers=_auth_header(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Short answer"
    assert body["task_id"] == "task-1"
    assert body["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_chat_reset_succeeds_with_valid_key(api_client, monkeypatch):
    fake = _ScriptedSupabase({
        "conversation_threads": [
            _Row([{"id": "thread-1"}, {"id": "thread-2"}]),
        ],
    })
    monkeypatch.setattr(sms_module, "supabase", fake)

    response = await api_client.post(
        "/api/sms/chat/reset",
        json={"phone": PHONE},
        headers=_auth_header(),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "closed_threads": 2}


@pytest.mark.asyncio
async def test_link_sms_account_succeeds_with_valid_key(api_client, monkeypatch):
    fake = _LinkSupabase()
    monkeypatch.setattr(sms_module, "supabase", fake)

    response = await api_client.post(
        "/api/link-sms-account",
        json={"phone": PHONE},
        headers=_auth_header(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["auth_user_id"] == "auth-user-1"
    assert body["linked_transcriptions"] == 4
    assert body["phone"] == PHONE
    assert [name for name, _params in fake.rpc_calls] == [
        "get_sms_user_stats",
        "link_sms_user_to_auth",
    ]


def test_sms_inbound_has_no_hardcoded_render_key():
    source = Path(REPO_ROOT, "app", "supabase", "functions", "sms-inbound", "index.ts").read_text()
    assert LEAKED_FALLBACK_KEY not in source
    # Empty-string fallback is fine; a quoted key in source is not.
    assert not re.search(r"RENDER_API_KEY'\)\s*\|\|\s*'[^']+", source)
    assert "function getRenderApiKey" in source
    assert "'X-API-Key': apiKey" in source
    for path in (
        "/api/sms/summary",
        "/api/sms/chat",
        "/api/sms/chat/reset",
        "/api/link-sms-account",
    ):
        assert f"postAuthenticatedRender('{path}'" in source
