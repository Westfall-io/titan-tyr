"""Contract deletion via two-party proposal flow (#69)."""
from __future__ import annotations


# ---------- helpers ----------


async def _register_part(client, name, subtype="software"):
    r = await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": subtype,
            "repo_uri": "u",
            "markdown": f"# {name}\n\nbody.",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _register_contract(
    client,
    owner,
    counterparty,
    subtype="interaction",
    connection_type=None,
    markdown=None,
):
    body = {
        "owner_part": owner,
        "counterparty_part": counterparty,
        "subtype": subtype,
        "markdown": markdown if markdown is not None else f"# {owner}->{counterparty}",
    }
    if connection_type is not None:
        body["connection_type"] = connection_type
    r = await client.post("/contracts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _propose_deletion(client, contract_id, rationale="retire", actor="alice"):
    r = await client.post(
        f"/contracts/{contract_id}/deletion-proposals",
        json={"rationale": rationale},
        headers={"X-Actor": actor} if actor else {},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# Propose
# ============================================================


class TestProposeContractDeletion:
    async def test_creates_proposal(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals",
            json={"rationale": "registered against the wrong endpoint"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["contract_id"] == c["contract_id"]
        assert body["rationale"] == "registered against the wrong endpoint"
        assert body["proposer_actor"] == "alice"
        assert body["status"] == "proposal"
        assert "proposal_id" in body
        assert "impact" in body

    async def test_rationale_required(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals",
            json={"rationale": ""},
        )
        assert r.status_code == 422

    async def test_unknown_contract_404(self, client):
        r = await client.post(
            "/contracts/00000000-0000-0000-0000-000000000000/deletion-proposals",
            json={"rationale": "x"},
        )
        assert r.status_code == 404

    async def test_already_deleted_contract_404(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals",
            json={"rationale": "second attempt"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 404


# ============================================================
# Impact block
# ============================================================


class TestImpactBlock:
    async def test_empty_when_no_references(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        body = await _propose_deletion(client, c["contract_id"])
        impact = body["impact"]
        assert impact["referenced_in_part_bodies"] == []
        assert impact["referenced_in_open_proposals"] == 0
        # Just the original active body version of the contract.
        assert impact["active_history_entries"] == 1

    async def test_part_body_reference_surfaces(self, client):
        # Owner part body mentions the counterparty's name.
        await _register_part(client, "alpha")
        await _register_part(client, "beta")
        # Bump alpha's body to reference beta explicitly.
        r = await client.put(
            "/parts/alpha",
            json={
                "markdown": "# alpha\n\n## Connections\n- talks to `beta`\n",
                "version": "1.0.1",
            },
        )
        assert r.status_code == 200, r.text
        c = await _register_contract(client, "alpha", "beta")
        body = await _propose_deletion(client, c["contract_id"])
        assert "alpha" in body["impact"]["referenced_in_part_bodies"]

    async def test_counts_open_sibling_proposals(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        # Open a body proposal on the same contract.
        await client.post(
            f"/contracts/{c['contract_id']}/proposals",
            json={
                "version": "1.1.0",
                "markdown": "# updated body\n",
            },
        )
        body = await _propose_deletion(client, c["contract_id"])
        assert body["impact"]["referenced_in_open_proposals"] == 1


# ============================================================
# Accept
# ============================================================


class TestAcceptContractDeletion:
    async def test_happy_path(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["proposer_actor"] == "alice"
        assert body["acceptor_actor"] == "bob"
        assert body["rationale"] == "retire"
        assert body["single_operator_override"] is False
        assert "deleted_at" in body
        assert "impact" in body

    async def test_two_party_rule_enforced(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 422
        assert "proposer-doesn't-accept rule" in r.json()["detail"]

    async def test_single_operator_override_allowed(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["single_operator_override"] is True

    async def test_double_accept_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        # Contract is now soft-deleted, so the second accept 404s on
        # the contract guard before it can hit the proposal.
        r = await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 404


# ============================================================
# Filtering: soft-deleted hidden by default
# ============================================================


class TestSoftDeleteFiltering:
    async def _setup_and_delete(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        return c["contract_id"]

    async def test_list_hides_deleted_by_default(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get("/contracts")
        assert r.status_code == 200
        ids = [item["contract_id"] for item in r.json()["results"]]
        assert contract_id not in ids

    async def test_list_include_deleted_surfaces(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get("/contracts?include_deleted=true")
        assert r.status_code == 200
        items = r.json()["results"]
        match = next(it for it in items if it["contract_id"] == contract_id)
        assert match["deleted_at"] is not None

    async def test_detail_hides_deleted_by_default(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get(f"/contracts/{contract_id}")
        assert r.status_code == 404

    async def test_detail_include_deleted_surfaces(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get(
            f"/contracts/{contract_id}?include_deleted=true"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["deleted_at"] is not None
        assert body["deleted_by_proposer_actor"] == "alice"
        assert body["deleted_by_acceptor_actor"] == "bob"
        assert body["deletion_rationale"] == "retire"

    async def test_part_touching_list_hides_deleted(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get("/parts/a/contracts")
        ids = [it["contract_id"] for it in r.json()["results"]]
        assert contract_id not in ids
        r = await client.get("/parts/a/contracts?include_deleted=true")
        ids = [it["contract_id"] for it in r.json()["results"]]
        assert contract_id in ids

    async def test_search_mode_hides_deleted(self, client):
        contract_id = await self._setup_and_delete(client)
        r = await client.get("/contracts?owner=a&counterparty=b")
        assert r.json()["results"] == []
        r = await client.get(
            "/contracts?owner=a&counterparty=b&include_deleted=true"
        )
        ids = [it["contract_id"] for it in r.json()["results"]]
        assert contract_id in ids

    async def test_writes_404_on_deleted(self, client):
        contract_id = await self._setup_and_delete(client)
        # PUT
        r = await client.put(f"/contracts/{contract_id}", json={})
        assert r.status_code == 404
        # body proposal
        r = await client.post(
            f"/contracts/{contract_id}/proposals",
            json={"version": "1.1.0", "markdown": "# x"},
        )
        assert r.status_code == 404
        # subtype shift
        r = await client.post(
            f"/contracts/{contract_id}/subtype-proposals",
            json={"new_subtype": "binding", "rationale": "x"},
        )
        assert r.status_code == 404

    async def test_re_register_after_delete(self, client):
        # The unique index is partial-on-live (#69) so the same
        # endpoints+subtype combo can be registered fresh after delete.
        contract_id = await self._setup_and_delete(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "# fresh contract",
            },
        )
        assert r.status_code == 201, r.text
        new_id = r.json()["contract_id"]
        assert new_id != contract_id

    async def test_project_count_excludes_deleted(self, client):
        await client.post("/projects", json={"name": "wv"})
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = (
            await client.post(
                "/contracts",
                json={
                    "owner_part": "a",
                    "counterparty_part": "b",
                    "subtype": "interaction",
                    "markdown": "# x",
                    "project": "wv",
                },
            )
        ).json()
        # baseline
        r = await client.get("/projects/wv")
        assert r.json()["contract_count"] == 1
        # delete + re-check
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get("/projects/wv")
        assert r.json()["contract_count"] == 0


# ============================================================
# History
# ============================================================


class TestHistorySurfacesDeletion:
    async def test_history_hides_deleted_by_default(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        # Contract is hidden — history 404s without include_deleted.
        r = await client.get(f"/contracts/{c['contract_id']}/history")
        assert r.status_code == 404

    async def test_history_include_deleted_surfaces_events(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get(
            f"/contracts/{c['contract_id']}/history?include_deleted=true"
        )
        assert r.status_code == 200, r.text
        kinds = [item["kind"] for item in r.json()["results"]]
        assert "deletion_accepted" in kinds
        assert "deletion_proposed" in kinds
        # And the original body bump is still there.
        assert "body_bump" in kinds


# ============================================================
# Listing deletion proposals
# ============================================================


class TestListDeletionProposals:
    async def test_lists_after_propose(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        await _propose_deletion(client, c["contract_id"], actor="alice")
        r = await client.get(
            f"/contracts/{c['contract_id']}/deletion-proposals"
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["proposals"]) == 1
        assert body["proposals"][0]["proposer_actor"] == "alice"

    async def test_list_404s_on_deleted_without_opt_in(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        p = await _propose_deletion(client, c["contract_id"], actor="alice")
        await client.post(
            f"/contracts/{c['contract_id']}/deletion-proposals/"
            f"{p['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get(
            f"/contracts/{c['contract_id']}/deletion-proposals"
        )
        assert r.status_code == 404
        r = await client.get(
            f"/contracts/{c['contract_id']}/deletion-proposals"
            "?include_deleted=true"
        )
        assert r.status_code == 200
        assert r.json()["proposals"][0]["status"] == "accepted"
