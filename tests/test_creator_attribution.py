"""Initial-creation attribution on POST /parts and POST /contracts (#39)."""
from __future__ import annotations


async def _register_part(client, name, *, actor=None):
    headers = {"X-Actor": actor} if actor else {}
    r = await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": "software",
            "repo_uri": "u",
            "markdown": f"# {name}\n\nbody.",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestPartCreatorAttribution:
    async def test_post_parts_records_x_actor(self, client):
        await _register_part(client, "svc", actor="alice")
        r = await client.get("/parts/svc")
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "alice"

    async def test_post_parts_anonymous_records_null(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc")
        assert r.json()["created_by_actor"] is None

    async def test_listing_includes_creator(self, client):
        await _register_part(client, "svc1", actor="alice")
        await _register_part(client, "svc2")
        r = await client.get("/parts?limit=10")
        assert r.status_code == 200
        by_name = {p["name"]: p["created_by_actor"] for p in r.json()["results"]}
        assert by_name["svc1"] == "alice"
        assert by_name["svc2"] is None


class TestContractCreatorAttribution:
    async def test_post_contracts_records_x_actor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "body",
            },
            headers={"X-Actor": "carol"},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["contract_id"]

        r = await client.get(f"/contracts/{cid}")
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "carol"

    async def test_post_contracts_anonymous_records_null(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "body",
            },
        )
        cid = r.json()["contract_id"]
        r = await client.get(f"/contracts/{cid}")
        assert r.json()["created_by_actor"] is None

    async def test_part_touching_listing_includes_creator(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "body",
            },
            headers={"X-Actor": "carol"},
        )
        r = await client.get("/parts/a/contracts")
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["created_by_actor"] == "carol"
