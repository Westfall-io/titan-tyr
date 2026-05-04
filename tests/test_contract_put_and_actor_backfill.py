"""PUT /contracts/{id}, X-Actor first-write-wins backfill, and per-version
actor on contract history (#52, #53, #54)."""
from __future__ import annotations


# ---------- helpers ----------


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


async def _register_contract(client, owner, counterparty, *, actor=None, project=None):
    body = {
        "owner_part": owner,
        "counterparty_part": counterparty,
        "subtype": "interaction",
        "markdown": "contract body",
    }
    if project is not None:
        body["project"] = project
    headers = {"X-Actor": actor} if actor else {}
    r = await client.post("/contracts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# PUT /contracts/{id} — soft metadata (closes #53, #52 Gap 1)
# ============================================================


class TestPutContractProject:
    async def test_set_project_on_existing_contract(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        await client.post("/projects", json={"name": "alpha"})
        r = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": "alpha"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["project"] == "alpha"
        # Verify via GET
        d = await client.get(f"/contracts/{c['contract_id']}")
        assert d.json()["project"] == "alpha"

    async def test_clear_project(self, client):
        await client.post("/projects", json={"name": "alpha"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b", project="alpha")
        r = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": None}
        )
        assert r.status_code == 200
        assert r.json()["project"] is None

    async def test_omitted_project_unchanged(self, client):
        await client.post("/projects", json={"name": "alpha"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b", project="alpha")
        # Empty body — touch nothing
        r = await client.put(f"/contracts/{c['contract_id']}", json={})
        assert r.status_code == 200
        assert r.json()["project"] == "alpha"

    async def test_unknown_project_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": "ghost"}
        )
        assert r.status_code == 422

    async def test_invalid_project_slug_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": "Bad.Slug"}
        )
        assert r.status_code == 422

    async def test_unknown_contract_404(self, client):
        r = await client.put(
            "/contracts/00000000-0000-0000-0000-000000000000",
            json={"project": None},
        )
        assert r.status_code == 404

    async def test_response_matches_followup_get(self, client):
        await client.post("/projects", json={"name": "alpha"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        put = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": "alpha"}
        )
        get = await client.get(f"/contracts/{c['contract_id']}")
        assert put.status_code == 200
        assert put.json() == get.json()

    async def test_put_does_not_bump_version(self, client):
        await client.post("/projects", json={"name": "alpha"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        before = (await client.get(f"/contracts/{c['contract_id']}")).json()["version"]
        r = await client.put(
            f"/contracts/{c['contract_id']}", json={"project": "alpha"}
        )
        assert r.status_code == 200
        assert r.json()["version"] == before


# ============================================================
# X-Actor first-write-wins backfill on PUT (closes #54, #52 Gap 2)
# ============================================================


class TestPartCreatedByActorBackfill:
    async def test_backfill_when_currently_null(self, client):
        # Register without X-Actor → created_by_actor: null.
        await _register_part(client, "legacy")
        # PUT with X-Actor backfills.
        r = await client.put(
            "/parts/legacy",
            json={"version": "1.1.0", "markdown": "v2"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "alice"
        # GET confirms persistence.
        d = await client.get("/parts/legacy")
        assert d.json()["created_by_actor"] == "alice"

    async def test_does_not_overwrite_existing(self, client):
        # Registered with bob → created_by_actor: 'bob'.
        await _register_part(client, "claimed", actor="bob")
        # Some other actor PUTs — backfill should NOT fire.
        r = await client.put(
            "/parts/claimed",
            json={"version": "1.1.0", "markdown": "v2"},
            headers={"X-Actor": "carol"},
        )
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "bob"

    async def test_no_x_actor_leaves_null(self, client):
        await _register_part(client, "anon")
        r = await client.put(
            "/parts/anon",
            json={"version": "1.1.0", "markdown": "v2"},
        )
        assert r.status_code == 200
        assert r.json()["created_by_actor"] is None


class TestContractCreatedByActorBackfill:
    async def test_backfill_when_currently_null(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        # PUT with X-Actor and an empty payload — pure backfill.
        r = await client.put(
            f"/contracts/{c['contract_id']}",
            json={},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "alice"

    async def test_does_not_overwrite_existing(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b", actor="bob")
        r = await client.put(
            f"/contracts/{c['contract_id']}",
            json={},
            headers={"X-Actor": "carol"},
        )
        assert r.status_code == 200
        assert r.json()["created_by_actor"] == "bob"

    async def test_backfill_combined_with_project_set(self, client):
        # One PUT can claim attribution AND tag the project.
        await client.post("/projects", json={"name": "alpha"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.put(
            f"/contracts/{c['contract_id']}",
            json={"project": "alpha"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["created_by_actor"] == "alice"
        assert body["project"] == "alpha"


# ============================================================
# Per-version actor on /contracts/{id}/history (closes #54 third bullet)
# ============================================================


class TestContractHistoryActor:
    async def test_body_bump_carries_actor(self, client):
        # Register, then propose + accept a new body version. The
        # accepted contract_versions row carries proposer/acceptor.
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b", actor="alice")
        # Initial version is propose-less (created via POST), so the
        # accepted row has no proposer/acceptor — confirm it surfaces
        # as None on history.
        r = await client.get(f"/contracts/{c['contract_id']}/history")
        assert r.status_code == 200
        rows = r.json()["results"]
        assert len(rows) >= 1
        # The initial 1.0.0 version has no proposer/acceptor recorded.
        v100 = next(r for r in rows if r["version"] == "1.0.0")
        assert v100["kind"] == "body_bump"
        assert v100["proposer_actor"] is None
        assert v100["acceptor_actor"] is None
        assert v100["single_operator_override"] is False

        # Propose + accept a new version with attributed actors.
        prop = await client.post(
            f"/contracts/{c['contract_id']}/proposals",
            json={"version": "1.1.0", "markdown": "v2 body"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        accept = await client.post(
            f"/contracts/{c['contract_id']}/proposals/1.1.0/accept",
            headers={"X-Actor": "bob"},
        )
        assert accept.status_code == 200, accept.text

        r = await client.get(f"/contracts/{c['contract_id']}/history")
        rows = r.json()["results"]
        v110 = next(r for r in rows if r["version"] == "1.1.0")
        assert v110["proposer_actor"] == "alice"
        assert v110["acceptor_actor"] == "bob"
        assert v110["single_operator_override"] is False

    async def test_subtype_shift_carries_actor(self, client):
        await _register_part(client, "a", actor="alice")
        await _register_part(client, "b", actor="alice")
        c = await _register_contract(client, "a", "b")
        prop = await client.post(
            f"/contracts/{c['contract_id']}/subtype-proposals",
            json={
                "new_subtype": "interaction",
                "rationale": "no real change",
            },
            headers={"X-Actor": "alice"},
        )
        # That's a no-op (same subtype) — get a real shift instead.
        # Use endpoint-shift since two parts make a no-op subtype awkward.
        await _register_part(client, "a2", actor="alice")
        prop = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_owner": "a2", "rationale": "owner moved"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        proposal_id = prop.json()["proposal_id"]
        accept = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/{proposal_id}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accept.status_code == 200, accept.text

        r = await client.get(f"/contracts/{c['contract_id']}/history")
        rows = r.json()["results"]
        shift = next(r for r in rows if r["kind"] == "endpoint_shift")
        assert shift["proposer_actor"] == "alice"
        assert shift["acceptor_actor"] == "bob"

    async def test_single_operator_override_surfaces(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        # Propose + accept under same actor with single_operator override.
        await client.post(
            f"/contracts/{c['contract_id']}/proposals",
            json={"version": "1.1.0", "markdown": "v2"},
            headers={"X-Actor": "alice"},
        )
        accept = await client.post(
            f"/contracts/{c['contract_id']}/proposals/1.1.0/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert accept.status_code == 200, accept.text

        r = await client.get(f"/contracts/{c['contract_id']}/history")
        v110 = next(r for r in r.json()["results"] if r["version"] == "1.1.0")
        assert v110["single_operator_override"] is True
        assert v110["proposer_actor"] == "alice"
        assert v110["acceptor_actor"] == "alice"
