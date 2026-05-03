"""CORS middleware behaviour, per #14 / contract proposal 1.1.0-rc1.

Allow-list is restricted to digitalforge.app (+ subdomains) and localhost
on any port. Other origins get no Access-Control-Allow-Origin header back
and the browser blocks the response.
"""
import pytest


class TestPreflight:
    @pytest.mark.parametrize("origin", [
        "http://localhost:8765",
        "https://localhost:8443",
        "https://digitalforge.app",
        "https://app.digitalforge.app",
    ])
    async def test_options_preflight_for_allowed_origin(self, client, origin):
        r = await client.options(
            "/parts",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert r.status_code in (200, 204), r.text
        assert r.headers.get("access-control-allow-origin") == origin
        allow_methods = (r.headers.get("access-control-allow-methods") or "").upper()
        for method in ("GET", "POST", "PUT"):
            assert method in allow_methods
        allow_headers = (r.headers.get("access-control-allow-headers") or "").lower()
        assert "authorization" in allow_headers
        assert "content-type" in allow_headers

    @pytest.mark.parametrize("origin", [
        "https://evil.com",
        "https://digitalforge.app.evil.com",  # suffix attack
        "http://digitalforge.app",            # http on the production host
        "https://otherhost",
    ])
    async def test_options_preflight_for_disallowed_origin(self, client, origin):
        r = await client.options(
            "/parts",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        # Either the preflight is rejected outright or it returns no
        # allow-origin header — both forms cause the browser to block.
        assert r.headers.get("access-control-allow-origin") in (None, "")


class TestActualRequest:
    async def test_get_with_allowed_origin_returns_allow_origin_header(self, client):
        r = await client.get(
            "/parts", headers={"Origin": "http://localhost:8765"}
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:8765"

    async def test_post_with_allowed_origin_returns_allow_origin_header(self, client):
        r = await client.post(
            "/parts",
            headers={"Origin": "https://digitalforge.app"},
            json={"name": "cors-test", "subtype": "software", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201
        assert r.headers.get("access-control-allow-origin") == "https://digitalforge.app"

    async def test_health_with_allowed_origin_returns_allow_origin_header(self, client):
        # /health is unauthed but should still be CORS-eligible.
        r = await client.get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    async def test_get_with_disallowed_origin_omits_allow_origin_header(self, client):
        r = await client.get("/parts", headers={"Origin": "https://evil.com"})
        # The endpoint still serves a 200 — CORS is enforced by the browser,
        # not the server. The server just declines to advertise the origin.
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers


class TestNonCorsUnaffected:
    async def test_request_without_origin_has_no_cors_headers(self, client):
        r = await client.get("/parts")
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers
