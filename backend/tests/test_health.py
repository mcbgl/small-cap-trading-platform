"""
Smoke test — verify the health endpoint returns 200 and expected fields.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "small-cap-trading-platform"
    assert body["version"] == "0.1.0"
    assert "paper_mode" in body
    assert "shadow_mode" in body
