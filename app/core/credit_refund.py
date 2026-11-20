"""Refund one SMS credit when a transcription task fails.

The sms-inbound edge function deducts 1 credit as soon as Render accepts
the job, and stores ``task_id`` on that ``transcription`` ledger row.
Failure paths call :func:`refund_failed_task_with_retry`.

Rules:
- At most one successful refund per task id.
- Never refund a task that has no successful ``transcription`` charge
  for that same task id (free retries, web tasks, charge not written).
- Prefer the ``refund_failed_transcription`` SQL function when the
  migration has been applied. Until then, use the existing
  ``atomic_credit_transaction`` RPC with the same checks in this module.

Option A (charge only after success) is not used. The SMS credit check
is only a pre-check, so delaying the charge would let one credit enqueue
many jobs. See the pull request for that tradeoff.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

REFUND_DESCRIPTION = "Refund for failed transcription"

def _rpc_missing(exc: BaseException) -> bool:
    """True only when refund_failed_transcription is not installed yet."""
    code = str(getattr(exc, "code", "") or "").lower()
    if code == "pgrst202":
        return True
    text = f"{exc} {getattr(exc, 'message', '')}".lower()
    if "pgrst202" in text or "could not find the function" in text or "schema cache" in text:
        return True
    return "refund_failed_transcription" in text and "does not exist" in text


def _rows(result: Any) -> list:
    data = getattr(result, "data", None)
    if data is None and isinstance(result, dict):
        data = result.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _metadata(row: dict) -> dict:
    meta = row.get("metadata") or {}
    if isinstance(meta, dict):
        return meta
    return {}


def _task_id_of(row: dict) -> Optional[str]:
    task_id = _metadata(row).get("task_id")
    if task_id is None or task_id == "":
        return None
    return str(task_id)


def _normalize_rpc_payload(data: Any) -> dict:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {"refunded": False, "reason": "rpc_error", "error": "unexpected rpc payload"}
    if "refunded" not in data:
        refunded = bool(data.get("success")) and data.get("transaction_type") == "refund"
        data = {**data, "refunded": refunded, "reason": data.get("reason") or ("refunded" if refunded else "unknown")}
    return data


def _refund_via_atomic(client: Any, task_id: str) -> dict:
    """App-level guard used until the SQL function is installed.

    Sequential double-failure is safe. Concurrent refunds need the unique
    index in the migration.
    """
    try:
        task_result = (
            client.table("transcriptions")
            .select("task_id,user_phone")
            .eq("task_id", task_id)
            .limit(1)
            .execute()
        )
        task_rows = _rows(task_result)
        phone = task_rows[0].get("user_phone") if task_rows else None

        tx_query = client.table("credit_transactions").select(
            "id,user_phone,transaction_type,credit_change,success,metadata"
        )
        if phone:
            tx_query = tx_query.eq("user_phone", phone)
        else:
            tx_query = tx_query.contains("metadata", {"task_id": task_id})
        transactions = _rows(tx_query.limit(200).execute())
    except Exception as exc:
        logger.error("Refund lookup failed for task %s: %s", task_id, exc)
        return {"refunded": False, "reason": "lookup_error", "error": str(exc)}

    charged = None
    for row in transactions:
        if _task_id_of(row) != task_id:
            continue
        if row.get("success") is False:
            continue
        change = int(row.get("credit_change") or 0)
        kind = row.get("transaction_type")
        if kind == "refund" and change > 0:
            return {
                "refunded": False,
                "reason": "already_refunded",
                "transaction_id": row.get("id"),
            }
        if kind == "transcription" and change < 0:
            charged = row
            phone = phone or row.get("user_phone")

    if charged is None:
        return {"refunded": False, "reason": "never_charged"}
    if not phone:
        return {"refunded": False, "reason": "no_phone"}

    params = {
        "user_phone_param": phone,
        "credit_change": 1,
        "transaction_type": "refund",
        "description": REFUND_DESCRIPTION,
        "metadata": {"task_id": task_id, "charge_id": str(charged.get("id")) if charged.get("id") else None},
    }
    try:
        result = client.rpc("atomic_credit_transaction", params).execute()
    except Exception as exc:
        text = str(exc).lower()
        if "duplicate" in text or "unique" in text:
            return {"refunded": False, "reason": "already_refunded"}
        logger.error("atomic refund failed for task %s: %s", task_id, exc)
        return {"refunded": False, "reason": "rpc_error", "error": str(exc)}

    payload = _normalize_rpc_payload(getattr(result, "data", None))
    if payload.get("success") is False:
        return {"refunded": False, "reason": "rpc_rejected", "result": payload}
    return {"refunded": True, "reason": "refunded", "result": payload}


def refund_failed_task_credit(client: Any, task_id: str) -> dict:
    """Refund one credit for ``task_id``, or explain why no refund was issued."""
    if client is None or not task_id or task_id == "unknown":
        return {"refunded": False, "reason": "missing_task_id"}

    try:
        response = client.rpc(
            "refund_failed_transcription",
            {"p_task_id": task_id},
        ).execute()
    except Exception as exc:
        if _rpc_missing(exc):
            return _refund_via_atomic(client, task_id)
        logger.error("refund_failed_transcription failed for %s: %s", task_id, exc)
        return {"refunded": False, "reason": "rpc_error", "error": str(exc)}

    return _normalize_rpc_payload(getattr(response, "data", None))


def _default_attempts() -> int:
    # CI and unit tests set TESTING so a fast failure does not sleep.
    flag = os.environ.get("TESTING", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return 1
    return 3


async def refund_failed_task_with_retry(
    client: Any,
    task_id: str,
    *,
    attempts: Optional[int] = None,
    delay_s: float = 0.4,
    sleeper: Optional[Callable] = None,
) -> dict:
    """Retry a few times when the charge row has not landed yet.

    The edge function writes the charge after Render's HTTP response, and
    the background task starts at the same moment. A very fast failure can
    look up the ledger before that insert. Free retries never write a
    charge, so the retries expire and return ``never_charged``.
    """
    if attempts is None:
        attempts = _default_attempts()
    if sleeper is None:
        sleeper = asyncio.sleep

    last = {"refunded": False, "reason": "missing_task_id"}
    total = max(1, attempts)
    for attempt in range(total):
        last = await asyncio.to_thread(refund_failed_task_credit, client, task_id)
        if last.get("reason") != "never_charged" or attempt >= total - 1:
            return last
        await sleeper(delay_s)
    return last
