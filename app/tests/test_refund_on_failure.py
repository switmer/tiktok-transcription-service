"""A failed transcription refunds the one credit taken when the job was accepted.

The refund is keyed by task id: a second failure path does not refund again,
and a task that was never charged (free retry) is not refunded.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.app import update_task_status
from app.core.credit_refund import (
    refund_failed_task_credit,
    refund_failed_task_with_retry,
)

TASK = "cb620adb-0000-4000-8000-000000000099"
PHONE = "+15551234567"
OTHER = "11111111-1111-4111-8111-111111111111"


class _Resp:
    def __init__(self, data):
        self.data = data
        self.error = None


class _Ready:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Resp(self._data)


class _MissingRefundRpc:
    def execute(self):
        raise Exception(
            "PGRST202 Could not find the function public.refund_failed_transcription"
            "(p_task_id) in the schema cache"
        )


class Ledger:
    """In-memory supabase stand-in for the pre-migration refund path."""

    def __init__(self, transactions, phone=PHONE):
        self.transactions = list(transactions)
        self.atomic_calls = []
        self.tasks = {TASK: {"task_id": TASK, "user_phone": phone, "status": "processing"}}

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        if name == "refund_failed_transcription":
            return _MissingRefundRpc()
        if name == "atomic_credit_transaction":
            self.atomic_calls.append(dict(params))
            self.transactions.append({
                "id": f"refund-{len(self.transactions) + 1}",
                "user_phone": params["user_phone_param"],
                "transaction_type": params["transaction_type"],
                "credit_change": params["credit_change"],
                "success": True,
                "metadata": dict(params["metadata"]),
            })
            return _Ready({"success": True, "transaction_type": "refund", "credit_change": 1, "new_balance": 4})
        raise AssertionError(name)


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = {}
        self.op = "select"
        self.payload = None

    def select(self, *args, **kwargs):
        self.op = "select"
        return self

    def update(self, data):
        self.op = "update"
        self.payload = data
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _n):
        return self

    def contains(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        if self.table == "transcriptions" and self.op == "update":
            row = self.db.tasks[self.filters["task_id"]]
            row.update(self.payload)
            return _Resp([dict(row)])
        if self.table == "transcriptions":
            row = self.db.tasks.get(self.filters.get("task_id"))
            return _Resp([row] if row else [])
        if self.table == "credit_transactions":
            phone = self.filters.get("user_phone")
            rows = [row for row in self.db.transactions if row["user_phone"] == phone]
            return _Resp(rows)
        raise AssertionError(self.table)


def _charge(task_id=TASK, phone=PHONE):
    return {
        "id": f"charge-{task_id}",
        "user_phone": phone,
        "transaction_type": "transcription",
        "credit_change": -1,
        "success": True,
        "metadata": {"task_id": task_id, "url": "https://www.youtube.com/watch?v=LzZ_FptHWqs"},
    }


def test_failure_refunds_once_and_a_second_failure_does_not():
    ledger = Ledger([_charge()])
    first = refund_failed_task_credit(ledger, TASK)
    second = refund_failed_task_credit(ledger, TASK)

    assert first["refunded"] is True
    assert first["reason"] == "refunded"
    assert second["refunded"] is False
    assert second["reason"] == "already_refunded"
    assert len(ledger.atomic_calls) == 1
    call = ledger.atomic_calls[0]
    assert call["credit_change"] == 1
    assert call["transaction_type"] == "refund"
    assert call["metadata"]["task_id"] == TASK
    assert call["user_phone_param"] == PHONE


def test_never_charged_task_is_not_refunded():
    ledger = Ledger([])
    result = refund_failed_task_credit(ledger, TASK)
    assert result == {"refunded": False, "reason": "never_charged"}
    assert ledger.atomic_calls == []


def test_charge_for_a_different_task_is_not_refunded():
    ledger = Ledger([_charge(task_id=OTHER)])
    result = refund_failed_task_credit(ledger, TASK)
    assert result["reason"] == "never_charged"
    assert ledger.atomic_calls == []


def test_db_function_result_is_used_when_the_migration_is_present():
    class Client:
        def __init__(self):
            self.atomic = 0

        def rpc(self, name, params):
            assert name == "refund_failed_transcription"
            assert params == {"p_task_id": TASK}
            return _Ready({"success": True, "refunded": False, "reason": "never_charged"})

    result = refund_failed_task_credit(Client(), TASK)
    assert result["refunded"] is False
    assert result["reason"] == "never_charged"


@pytest.mark.asyncio
async def test_retry_waits_for_the_charge_row_then_refunds_once():
    calls = {"n": 0}

    def fake_refund(_client, task_id):
        assert task_id == TASK
        calls["n"] += 1
        if calls["n"] == 1:
            return {"refunded": False, "reason": "never_charged"}
        return {"refunded": True, "reason": "refunded"}

    slept = []

    async def sleeper(delay):
        slept.append(delay)

    with patch("app.core.credit_refund.refund_failed_task_credit", fake_refund):
        result = await refund_failed_task_with_retry(
            object(), TASK, attempts=3, delay_s=0.4, sleeper=sleeper
        )

    assert result["refunded"] is True
    assert calls["n"] == 2
    assert slept == [0.4]


@pytest.mark.asyncio
async def test_update_task_status_failed_refunds_once_across_two_failure_paths():
    """Timeout and the exception handler both mark the task failed."""
    ledger = Ledger([_charge()])
    with patch("app.app.supabase", ledger):
        await update_task_status(TASK, "failed", "Failed to download video")
        await update_task_status(TASK, "failed", "Task timeout after 1800s")

    assert ledger.tasks[TASK]["status"] == "failed"
    assert len(ledger.atomic_calls) == 1
    assert ledger.atomic_calls[0]["metadata"]["task_id"] == TASK


@pytest.mark.asyncio
async def test_update_task_status_does_not_refund_a_free_retry(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    ledger = Ledger([])
    with patch("app.app.supabase", ledger):
        await update_task_status(TASK, "failed", "No video found on page")
    assert ledger.atomic_calls == []
    assert ledger.tasks[TASK]["status"] == "failed"
