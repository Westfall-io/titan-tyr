"""Part deletion via two-party proposal flow with human confirmation (#76)."""
from __future__ import annotations


# ---------- helpers ----------


async def _register_part(client, name, subtype="software", markdown=None):
    r = await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": subtype,
            "repo_uri": "u",
            "markdown": markdown if markdown is not None else f"# {name}\n\nbody.",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _register_contract(client, owner, counterparty, subtype="interaction"):
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": subtype,
            "markdown": f"# {owner}->{counterparty}",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _propose_deletion(client, part_name, rationale="retire", actor="alice"):
    r = await client.post(
        f"/parts/{part_name}/deletion-proposals",
        json={"rationale": rationale},
        headers={"X-Actor": actor} if actor else {},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# Propose
# ============================================================


class TestProposePartDeletion:
    async def test_creates_proposal(self, client):
        await _register_part(client, "throwaway")
        r = await client.post(
            "/parts/throwaway/deletion-proposals",
            json={"rationale": "experiment that didn't pan out"},
            headers={"X-Actor": "titan-tyr"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["part_name"] == "throwaway"
        assert body["rationale"] == "experiment that didn't pan out"
        assert body["proposer_actor"] == "titan-tyr"
        assert body["status"] == "proposal"
        assert "proposal_id" in body
        assert "impact" in body

    async def test_rationale_required(self, client):
        await _register_part(client, "throwaway")
        r = await client.post(
            "/parts/throwaway/deletion-proposals",
            json={"rationale": ""},
        )
        assert r.status_code == 422

    async def test_unknown_part_404(self, client):
        r = await client.post(
            "/parts/ghost/deletion-proposals",
            json={"rationale": "x"},
        )
        assert r.status_code == 404


# ============================================================
# Impact block
# ============================================================


class TestImpactBlock:
    async def test_empty_when_no_references(self, client):
        await _register_part(client, "lonely")
        body = await _propose_deletion(client, "lonely")
        impact = body["impact"]
        assert impact["touching_contracts"] == []
        assert impact["referenced_in_part_bodies"] == []
        # body_count = 1 (the registration)
        assert impact["active_history_entries"] == 1

    async def test_touching_contracts_surfaces(self, client):
        await _register_part(client, "alpha")
        await _register_part(client, "beta")
        c = await _register_contract(client, "alpha", "beta")
        body = await _propose_deletion(client, "alpha")
        ids = [t["contract_id"] for t in body["impact"]["touching_contracts"]]
        assert c["contract_id"] in ids

    async def test_referenced_in_part_bodies_surfaces(self, client):
        await _register_part(client, "alpha")
        await _register_part(
            client,
            "beta",
            markdown="# beta\n\n## Connections\n- talks to `alpha`\n",
        )
        body = await _propose_deletion(client, "alpha")
        assert "beta" in body["impact"]["referenced_in_part_bodies"]


# ============================================================
# Accept — happy path + cascade
# ============================================================


class TestAcceptPartDeletion:
    async def test_clean_delete_no_touching(self, client):
        await _register_part(client, "throwaway")
        p = await _propose_deletion(
            client, "throwaway", actor="titan-tyr"
        )
        r = await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["proposer_actor"] == "titan-tyr"
        assert body["acceptor_actor"] == "alice@example.com"
        assert body["cascade"] is False
        assert body["cascaded_contract_ids"] == []
        assert "deleted_at" in body

    async def test_block_when_touching_contracts_no_cascade(self, client):
        await _register_part(client, "alpha")
        await _register_part(client, "beta")
        await _register_contract(client, "alpha", "beta")
        p = await _propose_deletion(
            client, "alpha", actor="titan-tyr"
        )
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        assert r.status_code == 422
        assert "touching" in r.json()["detail"]
        assert "cascade=true" in r.json()["detail"]

    async def test_cascade_soft_deletes_touching_contracts(self, client):
        await _register_part(client, "alpha")
        await _register_part(client, "beta")
        c = await _register_contract(client, "alpha", "beta")
        p = await _propose_deletion(client, "alpha", actor="titan-tyr")
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept"
            "?cascade=true",
            headers={"X-Actor": "alice@example.com"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cascade"] is True
        assert c["contract_id"] in body["cascaded_contract_ids"]
        # Verify the contract is now hidden from default reads.
        r2 = await client.get(f"/contracts/{c['contract_id']}")
        assert r2.status_code == 404
        # And surfaced via include_deleted=true.
        r3 = await client.get(
            f"/contracts/{c['contract_id']}?include_deleted=true"
        )
        assert r3.status_code == 200
        assert r3.json()["deletion_rationale"].startswith(
            "cascaded from /propose-part-deletion"
        )


# ============================================================
# Human-confirmation rule
# ============================================================


class TestHumanConfirmation:
    async def test_two_agents_rejected(self, client):
        await _register_part(client, "alpha")
        p = await _propose_deletion(client, "alpha", actor="titan-tyr")
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "titan-archaedas"},
        )
        assert r.status_code == 403
        assert "human operator" in r.json()["detail"]

    async def test_anonymous_acceptor_rejected(self, client):
        await _register_part(client, "alpha")
        p = await _propose_deletion(client, "alpha", actor="titan-tyr")
        # No X-Actor on accept.
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept"
        )
        assert r.status_code == 422
        assert "X-Actor" in r.json()["detail"]

    async def test_single_operator_forbidden(self, client):
        await _register_part(client, "alpha")
        p = await _propose_deletion(client, "alpha", actor="titan-tyr")
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept"
            "?single_operator=true",
            headers={"X-Actor": "titan-tyr"},
        )
        assert r.status_code == 422
        assert "single_operator" in r.json()["detail"]

    async def test_two_party_still_required(self, client):
        # Even when the acceptor is human, proposer == acceptor still
        # fails the soft two-party rule.
        await _register_part(client, "alpha")
        p = await _propose_deletion(
            client, "alpha", actor="alice@example.com"
        )
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        assert r.status_code == 422
        assert "proposer-doesn't-accept" in r.json()["detail"]

    async def test_human_proposer_agent_acceptor_rejected(self, client):
        # Only the acceptor's role is gated by the human rule.
        # Human proposes, agent accepts → 403 (acceptor is agent).
        await _register_part(client, "alpha")
        p = await _propose_deletion(
            client, "alpha", actor="alice@example.com"
        )
        r = await client.post(
            f"/parts/alpha/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "titan-tyr"},
        )
        assert r.status_code == 403


# ============================================================
# Soft-delete filtering
# ============================================================


class TestSoftDeleteFiltering:
    async def _setup_and_delete(self, client):
        await _register_part(client, "throwaway")
        p = await _propose_deletion(client, "throwaway", actor="titan-tyr")
        await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )

    async def test_list_hides_deleted_by_default(self, client):
        await self._setup_and_delete(client)
        r = await client.get("/parts")
        names = [p["name"] for p in r.json()["results"]]
        assert "throwaway" not in names

    async def test_list_include_deleted_surfaces(self, client):
        await self._setup_and_delete(client)
        r = await client.get("/parts?include_deleted=true")
        items = r.json()["results"]
        match = next(it for it in items if it["name"] == "throwaway")
        assert match["deleted_at"] is not None

    async def test_detail_hides_deleted_by_default(self, client):
        await self._setup_and_delete(client)
        r = await client.get("/parts/throwaway")
        assert r.status_code == 404

    async def test_detail_include_deleted_surfaces(self, client):
        await self._setup_and_delete(client)
        r = await client.get("/parts/throwaway?include_deleted=true")
        assert r.status_code == 200
        body = r.json()
        assert body["deleted_at"] is not None
        assert body["deleted_by_proposer_actor"] == "titan-tyr"
        assert body["deleted_by_acceptor_actor"] == "alice@example.com"

    async def test_writes_404_on_deleted(self, client):
        await self._setup_and_delete(client)
        r = await client.put(
            "/parts/throwaway",
            json={"markdown": "# x", "version": "1.0.1"},
        )
        assert r.status_code == 404
        r = await client.post(
            "/parts/throwaway/subtype-proposals",
            json={"new_subtype": "container", "rationale": "x"},
        )
        assert r.status_code == 404
        r = await client.post(
            "/parts/throwaway/name-proposals",
            json={"new_name": "throwaway2", "rationale": "x"},
        )
        assert r.status_code == 404

    async def test_re_register_after_delete(self, client):
        # Partial-on-live unique on parts.name → same name allowed
        # after a delete. The new row gets a fresh id.
        original = await _register_part(client, "throwaway")
        p = await _propose_deletion(
            client, "throwaway", actor="titan-tyr"
        )
        await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        fresh = await _register_part(client, "throwaway")
        assert fresh["id"] != original["id"]

    async def test_register_contract_against_deleted_part_404(self, client):
        await _register_part(client, "alpha")
        await self._setup_and_delete(client)  # registers + deletes "throwaway"
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "alpha",
                "counterparty_part": "throwaway",
                "subtype": "interaction",
                "markdown": "# x",
            },
        )
        assert r.status_code == 404

    async def test_project_count_excludes_deleted_part(self, client):
        await client.post("/projects", json={"name": "wv"})
        await client.post(
            "/parts",
            json={
                "name": "throwaway",
                "subtype": "software",
                "repo_uri": "u",
                "markdown": "# x",
                "project": "wv",
            },
        )
        r = await client.get("/projects/wv")
        assert r.json()["part_count"] == 1
        p = await _propose_deletion(client, "throwaway", actor="titan-tyr")
        await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        r = await client.get("/projects/wv")
        assert r.json()["part_count"] == 0


# ============================================================
# History
# ============================================================


class TestHistorySurfacesDeletion:
    async def test_history_hides_deleted_by_default(self, client):
        await _register_part(client, "throwaway")
        p = await _propose_deletion(client, "throwaway", actor="titan-tyr")
        await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        r = await client.get("/parts/throwaway/history")
        assert r.status_code == 404

    async def test_history_include_deleted_surfaces_events(self, client):
        await _register_part(client, "throwaway")
        p = await _propose_deletion(client, "throwaway", actor="titan-tyr")
        await client.post(
            f"/parts/throwaway/deletion-proposals/{p['proposal_id']}/accept",
            headers={"X-Actor": "alice@example.com"},
        )
        r = await client.get(
            "/parts/throwaway/history?include_deleted=true"
        )
        assert r.status_code == 200, r.text
        kinds = [item["kind"] for item in r.json()["results"]]
        assert "deletion_proposed" in kinds
        assert "deletion_accepted" in kinds
        assert "body_bump" in kinds
