"""`?owner_actor=` filter on list endpoints (#111, renamed from
created_by_actor in #119).

The denormalized `owner_actor` / `counterparty_actor` fields on
contract responses (#112) were removed in #119 — keeping
denormalized copies of a mutable field was a staleness footgun.
Consumers needing ownership-boundary classification join client-side
through `parts[name].owner_actor`.
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
# #111 — ?owner_actor= filter on list endpoints
# ============================================================


class TestPartsActorFilter:
    async def test_filters_to_named_actor(self, client):
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "bob-svc", actor="bob")
        await _register_part(client, "alice-img", subtype="image", actor="alice")

        r = await client.get("/parts?owner_actor=alice")
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()["results"]}
        assert names == {"alice-svc", "alice-img"}

    async def test_unknown_actor_returns_empty(self, client):
        await _register_part(client, "svc", actor="alice")
        r = await client.get("/parts?owner_actor=nonexistent")
        assert r.status_code == 200, r.text
        assert r.json()["results"] == []

    async def test_combines_with_subtype_filter(self, client):
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "alice-img", subtype="image", actor="alice")
        await _register_part(client, "bob-img", subtype="image", actor="bob")

        r = await client.get(
            "/parts?owner_actor=alice&subtype=image"
        )
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()["results"]}
        assert names == {"alice-img"}

    async def test_anonymous_rows_excluded_when_filtering(self, client):
        # Filtering for an actor must NOT include anonymous-legacy rows
        # (owner_actor IS NULL); they don't match any actor name.
        await _register_part(client, "alice-svc", actor="alice")
        await _register_part(client, "anon-svc")  # no X-Actor
        r = await client.get("/parts?owner_actor=alice")
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

        r = await client.get("/contracts?owner_actor=alice")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert {results[0]["owner"], results[0]["counterparty"]} == {"a", "b"}
        assert results[0]["owner_actor"] == "alice"

    async def test_search_mode_filters_to_named_actor(self, client):
        await _register_part(client, "a", actor="alice")  # software (default)
        # `b` must be container or pod for the binding row below to satisfy
        # the binding source/target rule (container/pod → software).
        await _register_part(client, "b", subtype="container", actor="bob")
        # Two contracts on the (a, b) pair, distinguished by actor and
        # subtype: interaction (a → b) by alice + binding (b → a) by bob.
        # Search mode walks both directions of the (owner, counterparty)
        # pair, so the actor filter narrowing the result to alice's row
        # is the assertion.
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
            "/contracts?owner=a&counterparty=b&owner_actor=alice"
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["owner_actor"] == "alice"

    async def test_part_contracts_filter(self, client):
        await _register_part(client, "hub", actor="alice")
        await _register_part(client, "spoke-a", actor="alice")
        await _register_part(client, "spoke-b", actor="bob")
        await _register_contract(client, "hub", "spoke-a", actor="alice")
        await _register_contract(client, "hub", "spoke-b", actor="bob")

        r = await client.get(
            "/parts/hub/contracts?owner_actor=alice"
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["owner_actor"] == "alice"
        assert "spoke-a" in (results[0]["owner"], results[0]["counterparty"])

