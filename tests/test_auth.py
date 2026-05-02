import pytest


class TestAuth:
    async def test_missing_bearer_rejected(self, client):
        client.headers.pop("Authorization", None)
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_wrong_bearer_rejected(self, client):
        client.headers["Authorization"] = "Bearer wrong"
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_correct_bearer_accepted(self, client):
        r = await client.get("/templates/software")
        assert r.status_code == 200

    @pytest.mark.parametrize("path", [
        "/templates/software",
        "/templates/contract",
        "/software/anything",
    ])
    async def test_auth_required_on_get_endpoints(self, client, path):
        client.headers.pop("Authorization", None)
        r = await client.get(path)
        assert r.status_code == 401

    async def test_auth_required_on_post(self, client):
        client.headers.pop("Authorization", None)
        r = await client.post("/software", json={"name": "n", "repo_uri": "u", "markdown": "m"})
        assert r.status_code == 401
