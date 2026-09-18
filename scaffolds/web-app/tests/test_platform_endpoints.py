"""Every GET endpoint answers without crashing. Written by Poiesis, and read-only.

The platform's browser check once found GET /api/llm-overviews answering 500 in
the running app while every story test passed: the tests exercised a different
router, and the one the screen used had never been called. This calls every GET
route that takes no path parameters, on an empty test database, and a server
exception fails here with its own traceback — inside the build's repair loop,
where the Developer can read it, rather than in the browser after deploy.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.main import app

GET_ROUTES = sorted({
    route.path
    for route in app.routes
    if isinstance(route, APIRoute)
    and "GET" in route.methods
    and route.path.startswith("/api/")
    and "{" not in route.path
})


@pytest.mark.parametrize("path", GET_ROUTES)
def test_get_endpoint_does_not_crash(client, path):
    response = client.get(path)
    assert response.status_code < 500, f"GET {path} answered {response.status_code}: {response.text[:300]}"
