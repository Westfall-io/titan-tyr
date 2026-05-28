"""`?created_by_actor=` filter on list endpoints (#111) + denormalized
`owner_actor` / `counterparty_actor` fields on contract list/search
responses (#112).

Both features paired in the same drop because they surfaced from the
same mimiron #79 work (agent-perspective graph views) and address the
same scaling concern: classifying parts/contracts by ownership boundary
without round-tripping through the part listing on the client side.
"""
from __future__ import annotations


async def _register_part(client, name, *, subtype="software", actor=None):
    headers = {"X-Actor": actor} if actor else {}
    r = await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": subtype,
            "repo_uri": "u",
            "markdown": f"# {name}\n\nbody.",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _register_contract(client, owner, counterparty, *, actor=None):
    headers = {"X-Actor": actor} if actor else {}
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": "interaction",
            "markdown": "m",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# #111 — ?created_by_actor= filter on list endpoints
# ============================================================


class TestPartsActorFilter:
    async def test_filters_to_named_actor(self, client):
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "bob-svc", actor="bob")
        await _register_part(client, "alice-img", subtype="image", actor="alice")

        r = await client.get("/parts?created_by_actor=alice")
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()["results"]}
        assert names == {"alice-svc", "alice-img"}

    async def test_unknown_actor_returns_empty(self, client):
        await _register_part(client, "svc", actor="alice")
        r = await client.get("/parts?created_by_actor=nonexistent")
        assert r.status_code == 200, r.text
        assert r.json()["results"] == []

    async def test_combines_with_subtype_filter(self, client):
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "alice-img", subtype="image", actor="alice")
        await _register_part(client, "bob-img", subtype="image", actor="bob")

        r = await client.get(
            "/parts?created_by_actor=alice&subtype=image"
        )
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()["results"]}
        assert names == {"alice-img"}

    async def test_anonymous_rows_excluded_when_filtering(self, client):
        # Filtering for an actor must NOT include anonymous-legacy rows
        # (created_by_actor IS NULL); they don't match any actor name.
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "anon-svc")  # no X-Actor
        r = await client.get("/parts?created_by_actor=alice")
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()["results"]}
        assert names == {"alice-svc"}


class TestContractsActorFilter:
    async def test_list_mode_filters_to_named_actor(self, client):
        await _register_part(client, "a", actor="alice")
        await _register_part(client, "b", actor="bob")
        await _register_part(client, "c", actor="alice")
        await _register_contract(client, "a", "b", actor="alice")
        await _register_contract(client, "b", "c", actor="bob")

        r = await client.get("/contracts?created_by_actor=alice")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert {results[0]["owner"], results[0]["counterparty"]} == {"a", "b"}
        assert results[0]["created_by_actor"] == "alice"

    async def test_search_mode_filters_to_named_actor(self, client):
        await _register_part(client, "a", actor="alice")
        await _register_part(client, "b", actor="bob")
        # Two contracts on the same pair, distinguished by actor and subtype
        # (interaction + binding can coexist on same pair).
        await _register_contract(client, "a", "b", actor="alice")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "b",
                "counterparty_part": "a",
                "subtype": "binding",
                "markdown": "m",
            },
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 201, r.text

        # Search with actor filter narrows to alice's row.
        r = await client.get(
            "/contracts?owner=a&counterparty=b&created_by_actor=alice"
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["created_by_actor"] == "alice"

    async def test_part_contracts_filter(self, client):
        await _register_part(client, "hub", actor="alice")
        await _register_part(client, "spoke-a", actor="alice")
        await _register_part(client, "spoke-b", actor="bob")
        await _register_contract(client, "hub", "spoke-a", actor="alice")
        await _register_contract(client, "hub", "spoke-b", actor="bob")

        r = await client.get(
            "/parts/hub/contracts?created_by_actor=alice"
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["created_by_actor"] == "alice"
        assert "spoke-a" in (results[0]["owner"], results[0]["counterparty"])


# ============================================================
# #112 — owner_actor / counterparty_actor denormalized on contract rows
# ============================================================


class TestContractListDenormalizedActors:
    async def test_list_mode_populates_endpoint_actors(self, client):
        await _register_part(client, "a", actor="alice")
        await _register_part(client, "b", actor="bob")
        await _register_contract(client, "a", "b", actor="alice")

        r = await client.get("/contracts")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        row = results[0]
        assert row["owner"] == "a"
        assert row["counterparty"] == "b"
        assert row["owner_actor"] == "alice"
        assert row["counterparty_actor"] == "bob"

    async def test_anonymous_endpoint_renders_null_actor(self, client):
        # Endpoint parts without X-Actor get created_by_actor=null;
        # the denormalized fields should mirror that.
        await _register_part(client, "anon-a")  # no actor
        await _register_part(client, "bob-b", actor="bob")
        await _register_contract(client, "anon-a", "bob-b", actor="alice")

        r = await client.get("/contracts")
        results = r.json()["results"]
        row = next(r for r in results if r["owner"] == "anon-a")
        assert row["owner_actor"] is None
        assert row["counterparty_actor"] == "bob"

    async def test_part_contracts_populates_endpoint_actors(self, client):
        await _register_part(client, "hub", actor="alice")
        await _register_part(client, "spoke", actor="bob")
        await _register_contract(client, "hub", "spoke", actor="alice")

        r = await client.get("/parts/hub/contracts")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["owner_actor"] == "alice"
        assert results[0]["counterparty_actor"] == "bob"

    async def test_search_mode_populates_endpoint_actors(self, client):
        await _register_part(client, "x", actor="alice")
        await _register_part(client, "y", actor="bob")
        await _register_contract(client, "x", "y", actor="alice")

        r = await client.get("/contracts?owner=x&counterparty=y")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["owner_actor"] == "alice"
        assert results[0]["counterparty_actor"] == "bob"
