"""Read and write normalized transcript segments.

`segments` is a nullable jsonb column added by
`20261120210000_add_transcript_segments.sql`. Reads fall back when that
migration has not been applied yet. Writes are best-effort so a missing
column cannot fail the transcript text update.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_WITH_SEGMENTS = "task_id, status, transcript, error, visibility, segments"
_WITHOUT_SEGMENTS = "task_id, status, transcript, error, visibility"


def transcript_payload(task_id: str, row: dict) -> dict:
    """JSON body shared by the public and private transcript routes.

    Existing `task_id` and `transcript` fields stay. `segments` is null when
    timings were not stored.
    """
    segments = row.get("segments") if isinstance(row, dict) else None
    if not isinstance(segments, list):
        segments = None
    transcript = ""
    if isinstance(row, dict) and row.get("transcript"):
        transcript = row["transcript"]
    return {
        "task_id": task_id,
        "transcript": transcript,
        "segments": segments,
    }


def _select_transcript(client, task_id: str, columns: str):
    return (
        client.table("transcriptions")
        .select(columns)
        .eq("task_id", task_id)
        .maybe_single()
        .execute()
    )


def _missing_segments_column(exc: Exception) -> bool:
    text = str(exc).lower()
    return "segments" in text and (
        "column" in text or "schema" in text or "does not exist" in text or "pgrst" in text
    )


async def fetch_transcript_row(client, task_id: str):
    """Load one transcript row, retrying without `segments` if the column is absent."""
    last_exc = None
    for columns in (_WITH_SEGMENTS, _WITHOUT_SEGMENTS):
        try:
            return await asyncio.to_thread(_select_transcript, client, task_id, columns)
        except Exception as exc:
            last_exc = exc
            if columns == _WITHOUT_SEGMENTS or not _missing_segments_column(exc):
                raise
            logger.warning(
                "segments column unavailable; reading transcript %s without it",
                task_id,
            )
    raise last_exc


def persist_transcript_segments(client, task_id: str, segments) -> None:
    """Store normalized segments after the transcript text is saved.

    A missing column or a PostgREST error is logged and ignored. The completion
    update must not depend on this migration.
    """
    if client is None or not segments:
        return
    try:
        client.table("transcriptions").update({"segments": segments}).eq("task_id", task_id).execute()
    except Exception as exc:
        logger.warning("Could not persist segments for task %s: %s", task_id, exc)
