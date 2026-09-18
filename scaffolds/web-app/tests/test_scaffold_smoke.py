"""Scaffold smoke tests.

These prove the application is wired together before any feature code exists, so
a run that produces nothing useful still fails honestly rather than reporting a
green suite over an empty repository.

Do not delete these. Feature tests go in their own files alongside them.
"""
def test_health_returns_ok(client):
    """The archetype's definition of deployable depends on this endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_router_is_mounted(client):
    """/api must exist even before a story adds endpoints to it."""
    schema = client.get("/openapi.json").json()
    assert any(path.startswith("/api") for path in schema["paths"])


def test_database_is_reachable_under_test(client):
    """The `client` fixture provisions a real in-memory database.

    If this fails, tests are talking to the production DATABASE_URL and every
    database-backed test will fail with 'connection refused'.
    """
    assert client.get("/api/status").json() == {"database": "connected"}
