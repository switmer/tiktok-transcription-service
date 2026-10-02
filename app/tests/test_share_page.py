"""Share links must render public transcripts on the deployed template API."""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest


app_module = importlib.import_module("app.app")
TASK_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "status", "text"),
    [
        ({"task_id": TASK_ID, "title": "Shared video", "transcript": "Shared words"}, 200, "Shared video"),
        (None, 404, "Transcript Not Found"),
    ],
)
async def test_share_page(monkeypatch, row, status, text):
    database = Mock()
    database.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        SimpleNamespace(data=row) if row else None
    )
    monkeypatch.setattr(app_module, "supabase", database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_module.app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v/{TASK_ID}")

    assert response.status_code == status
    assert text in response.text
