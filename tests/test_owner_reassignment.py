"""PUT /parts/{name}/owner + PUT /contracts/{id}/owner — mutable
ownership reassignment (#119).

Replaces the first-write-wins backfill semantic of legacy
`created_by_actor`. Single-write reassignment; no two-party rule.
Overwrite allowed (no first-write-wins).
"""
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
# Parts
# ============================================================


class TestPartOwnerReassignment:
    async def test_reassign_overwrites_existing_owner(self, client):
        await _register_part(client, "svc", actor="alice")
        r = await client.put(
            "/parts/svc/owner",
            json={"new_owner_actor": "bob", "rationale": "handoff to bob"},
            headers={"X-Actor": "carol"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_owner_actor"] == "alice"
        assert body["new_owner_actor"] == "bob"
        assert body["reassigned_by_actor"] == "carol"
        assert body["rationale"] == "handoff to bob"
        # GET reflects the new owner.
        detail = await client.get("/parts/svc")
        assert detail.json()["owner_actor"] == "bob"

    async def test_reassign_fills_null_owner(self, client):
        # Anonymous registration → NULL owner. Reassignment populates.
        await _register_part(client, "anon-svc")  # no X-Actor
        r = await client.put(
            "/parts/anon-svc/owner",
            json={"new_owner_actor": "alice", "rationale": "claiming legacy row"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["previous_owner_actor"] is None
        assert r.json()["new_owner_actor"] == "alice"

    async def test_reassign_unknown_part_404(self, client):
        r = await client.put(
            "/parts/nonexistent/owner",
            json={"new_owner_actor": "bob", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 404

    async def test_reassign_missing_rationale_422(self, client):
        await _register_part(client, "svc", actor="alice")
        r = await client.put(
            "/parts/svc/owner",
            json={"new_owner_actor": "bob"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 422

    async def test_reassign_does_not_bump_part_version(self, client):
        # Ownership shifts don't bump the body version (parallel to
        # subtype/name/endpoint shifts).
        await _register_part(client, "svc", actor="alice")
        before = (await client.get("/parts/svc")).json()["version"]
        await client.put(
            "/parts/svc/owner",
            json={"new_owner_actor": "bob", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        after = (await client.get("/parts/svc")).json()["version"]
        assert before == after


# ============================================================
# Contracts
# ============================================================


class TestContractOwnerReassignment:
    async def test_reassign_overwrites_existing_owner(self, client):
        await _register_part(client, "a", actor="alice")
        await _register_part(client, "b", actor="bob")
        c = await _register_contract(client, "a", "b", actor="alice")
        cid = c["contract_id"]

        r = await client.put(
            f"/contracts/{cid}/owner",
            json={"new_owner_actor": "tyr", "rationale": "moving to tyr"},
            headers={"X-Actor": "carol"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_owner_actor"] == "alice"
        assert body["new_owner_actor"] == "tyr"
        assert body["reassigned_by_actor"] == "carol"

        detail = await client.get(f"/contracts/{cid}")
        assert detail.json()["owner_actor"] == "tyr"

    async def test_reassign_unknown_contract_404(self, client):
        # Well-formed UUID that doesn't exist.
        r = await client.put(
            "/contracts/00000000-0000-0000-0000-000000000000/owner",
            json={"new_owner_actor": "tyr", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 404

    async def test_reassign_then_filter_by_new_owner(self, client):
        # After reassignment, ?owner_actor= filter narrows to the
        # new owner — confirms the field is fully mutable end-to-end.
        await _register_part(client, "x", actor="alice")
        await _register_part(client, "y", actor="bob")
        c = await _register_contract(client, "x", "y", actor="alice")
        await client.put(
            f"/contracts/{c['contract_id']}/owner",
            json={"new_owner_actor": "tyr", "rationale": "shift"},
            headers={"X-Actor": "alice"},
        )
        r = await client.get("/contracts?owner_actor=tyr")
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["contract_id"] == c["contract_id"]
