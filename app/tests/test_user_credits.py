"""
Unit tests for credit balance resolution (SMS + email users).

Uses mocked Supabase responses only — no network / production DB.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.core.user_credits import (
    identity_from_auth_user,
    normalize_phone,
    resolve_sms_user_credits,
)


class MockResponse:
    def __init__(self, data):
        self.data = data


class TrackingClient:
    """Minimal supabase table mock that records eq() filters."""

    def __init__(self, rows_by_key):
        # rows_by_key: {(column, value): credits_remaining or None for miss}
        self.rows_by_key = rows_by_key
        self.queries = []

    def table(self, name):
        assert name == "sms_users"
        return _Query(self)


class _Query:
    def __init__(self, client: TrackingClient):
        self.client = client
        self._column = None
        self._value = None
        self._raise = None

    def select(self, *a, **kw):
        return self

    def eq(self, column, value):
        self._column = column
        self._value = value
        return self

    def limit(self, n):
        return self

    def execute(self):
        key = (self._column, self._value)
        self.client.queries.append(key)
        if key in self.client.rows_by_key:
            credits = self.client.rows_by_key[key]
            if isinstance(credits, Exception):
                raise credits
            return MockResponse([{"credits_remaining": credits}])
        # Simulate PostgREST unknown-column for email when configured
        if self._column == "email" and self.client.rows_by_key.get(("__no_email_column__",)) is True:
            raise Exception("column sms_users.email does not exist")
        return MockResponse([])


class TestNormalizePhone:
    def test_ten_digit(self):
        assert normalize_phone("5551234567") == "+15551234567"

    def test_already_e164(self):
        assert normalize_phone("+15551234567") == "+15551234567"

    def test_none(self):
        assert normalize_phone(None) is None


class TestIdentityFromAuthUser:
    def test_phone_only_sms_user(self):
        user = SimpleNamespace(
            id="user-1",
            email=None,
            phone="+15551234567",
            user_metadata={},
        )
        identity = identity_from_auth_user(user)
        assert identity["auth_user_id"] == "user-1"
        assert identity["phone"] == "+15551234567"
        assert identity["email"] is None

    def test_email_user(self):
        user = SimpleNamespace(
            id="user-2",
            email="person@example.com",
            phone=None,
            user_metadata={},
        )
        identity = identity_from_auth_user(user)
        assert identity["email"] == "person@example.com"
        assert identity["phone"] is None


class TestResolveSmsUserCredits:
    def test_lookup_by_phone_for_sms_user(self):
        client = TrackingClient({
            ("phone_number", "+15551234567"): 7,
        })
        result = resolve_sms_user_credits(
            client,
            phone="+15551234567",
            email=None,
            auth_user_id=None,
        )
        assert result == 7
        assert ("phone_number", "+15551234567") in client.queries

    def test_lookup_by_auth_user_id(self):
        client = TrackingClient({
            ("auth_user_id", "uuid-abc"): 3,
        })
        result = resolve_sms_user_credits(
            client,
            auth_user_id="uuid-abc",
            phone=None,
            email=None,
        )
        assert result == 3

    def test_lookup_by_session_token(self):
        client = TrackingClient({
            ("session_token", "sess-1"): 11,
        })
        result = resolve_sms_user_credits(
            client,
            session_token="sess-1",
            phone="+15550001111",  # should not be needed
        )
        assert result == 11
        assert client.queries[0] == ("session_token", "sess-1")

    def test_email_user_still_works(self):
        client = TrackingClient({
            ("email", "person@example.com"): 4,
        })
        result = resolve_sms_user_credits(
            client,
            email="person@example.com",
        )
        assert result == 4

    def test_prefers_phone_over_email(self):
        client = TrackingClient({
            ("phone_number", "+15551234567"): 9,
            ("email", "person@example.com"): 1,
        })
        result = resolve_sms_user_credits(
            client,
            phone="+15551234567",
            email="person@example.com",
        )
        assert result == 9
        assert ("email", "person@example.com") not in client.queries

    def test_genuine_zero_balance(self):
        client = TrackingClient({
            ("phone_number", "+15551234567"): 0,
        })
        result = resolve_sms_user_credits(client, phone="+15551234567")
        assert result == 0

    def test_unknown_when_unauthenticated(self):
        client = TrackingClient({})
        result = resolve_sms_user_credits(client)
        assert result is None

    def test_unknown_when_no_matching_row(self):
        client = TrackingClient({})
        result = resolve_sms_user_credits(
            client,
            phone="+15559999999",
            email="missing@example.com",
            auth_user_id="no-such-user",
        )
        assert result is None

    def test_missing_email_column_does_not_become_zero(self):
        client = TrackingClient({("__no_email_column__",): True})
        result = resolve_sms_user_credits(
            client,
            email="person@example.com",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_credits_endpoint_phone_auth_sms_user(self):
        """Endpoint resolves SMS phone-auth users without requiring email."""
        from unittest.mock import patch
        from fastapi import Request
        from app.app import get_user_credits

        mock_user = SimpleNamespace(
            id="auth-sms-1",
            email=None,
            phone="+15551234567",
            user_metadata={"auth_type": "phone_only"},
        )
        mock_auth = MagicMock()
        mock_auth.get_user.return_value = SimpleNamespace(user=mock_user)

        mock_supabase = MagicMock()
        mock_supabase.auth = mock_auth

        chain = MagicMock()
        mock_supabase.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MockResponse([{"credits_remaining": 5}])

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/users/credits",
            "headers": [(b"authorization", b"Bearer fake-token")],
        }
        request = Request(scope)

        with patch("app.app.supabase", mock_supabase):
            result = await get_user_credits(
                request=request,
                x_session_token=None,
            )

        assert result == {"credits": 5}
        mock_supabase.table.assert_called_with("sms_users")
        eq_calls = [c[0] for c in chain.eq.call_args_list if c[0]]
        assert eq_calls, "expected at least one sms_users.eq filter"
        assert not any(c[0] == "email" for c in eq_calls)
        assert any(c[0] in ("auth_user_id", "phone_number") for c in eq_calls)

    @pytest.mark.asyncio
    async def test_get_user_credits_endpoint_returns_null_when_unknown(self):
        from unittest.mock import patch
        from fastapi import Request
        from app.app import get_user_credits

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/users/credits",
            "headers": [],
        }
        request = Request(scope)

        with patch("app.app.supabase", MagicMock()):
            result = await get_user_credits(
                request=request,
                x_session_token=None,
            )

        assert result == {"credits": None}
