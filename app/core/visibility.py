"""Visibility for transcription rows.

The `visibility` column already exists (`public`, `private`, `unlisted`, or null).
Null is legacy and stays listable. API-key creates default to private.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

ALLOWED_VISIBILITY = ("public", "private", "unlisted")

# PostgREST `or` filter: listed pages include explicit public rows and legacy nulls.
PUBLIC_LISTING_FILTER = "visibility.eq.public,visibility.is.null"


def resolve_visibility(requested: Optional[str], *, from_api_key: bool) -> str:
    """Pick the visibility stored at task creation.

    An explicit public/private/unlisted value wins. Otherwise API-key creates
    are private and every other create (SMS, public transcribe, webhook) is public.
    """
    if requested is None or str(requested).strip() == "":
        return "private" if from_api_key else "public"
    value = str(requested).strip().lower()
    if value not in ALLOWED_VISIBILITY:
        raise ValueError(value)
    return value


def row_is_publicly_listed(visibility: Optional[str]) -> bool:
    """True for discovery, sitemaps, and other browse surfaces."""
    return visibility is None or visibility == "public"


def row_is_publicly_readable(visibility: Optional[str]) -> bool:
    """True for by-id public reads. Private rows stay behind the API key."""
    return visibility != "private"


def apply_public_listing_filter(query):
    """Restrict a transcriptions query to rows that may appear in public listings."""
    return query.or_(PUBLIC_LISTING_FILTER)


async def exclude_hidden_from_listing(client, rows):
    """Drop private and unlisted hits from a search RPC result.

    Fails closed: a visibility lookup error returns no rows rather than the
    unfiltered RPC payload.
    """
    if not rows:
        return rows
    if client is None:
        return []

    ids = []
    for row in rows:
        if isinstance(row, dict) and row.get("task_id"):
            ids.append(row["task_id"])
    if not ids:
        return []

    try:
        response = await asyncio.to_thread(
            lambda: client.table("transcriptions")
            .select("task_id, visibility")
            .in_("task_id", ids)
            .execute()
        )
    except Exception:
        logger.warning("visibility lookup failed; hiding search hits", exc_info=True)
        return []

    listed = {
        row.get("task_id")
        for row in (getattr(response, "data", None) or [])
        if row_is_publicly_listed(row.get("visibility"))
    }
    return [row for row in rows if isinstance(row, dict) and row.get("task_id") in listed]
