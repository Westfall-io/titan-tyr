"""Two-party rule on content + template proposals (#38).

Parity with tests/test_subtype_shifts.py for the four endpoints
that previously bypassed the rule:
- POST /contracts/{id}/proposals[/accept]
- POST /templates/{kind}/proposals[/accept]

Plus the single_operator_override flag retrofit on the existing
shift accepts.
"""
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


async def _register_contract(client, owner, counterparty):
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": "interaction",
            "markdown": "contract body",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _propose(client, contract_id, version, *, actor=None):
    headers = {"X-Actor": actor} if actor else {}
    r = await client.post(
        f"/contracts/{contract_id}/proposals",
        json={"version": version, "markdown": f"# v{version}\n\nbody"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _accept(client, contract_id, version, *, actor=None, single_operator=False):
    headers = {"X-Actor": actor} if actor else {}
    url = f"/contracts/{contract_id}/proposals/{version}/accept"
    if single_operator:
        url += "?single_operator=true"
    return await client.post(url, headers=headers)


# ============================================================
# Contract content proposals
# ============================================================


class TestContractProposalAttribution:
    async def test_propose_records_proposer_actor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0", actor="alice")

        r = await client.get(f"/contracts/{cid}/proposals")
        assert r.status_code == 200
        proposals = r.json()["proposals"]
        match = [p for p in proposals if p["version"] == "1.1.0"][0]
        assert match["proposer_actor"] == "alice"
        assert match["acceptor_actor"] is None
        assert match["single_operator_override"] is False

    async def test_propose_anonymous_is_null(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0")

        r = await client.get(f"/contracts/{cid}/proposals")
        match = [p for p in r.json()["proposals"] if p["version"] == "1.1.0"][0]
        assert match["proposer_actor"] is None

    async def test_accept_records_acceptor_actor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0", actor="alice")

        r = await _accept(client, cid, "1.1.0", actor="bob")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["proposer_actor"] == "alice"
        assert body["acceptor_actor"] == "bob"
        assert body["single_operator_override"] is False

    async def test_proposer_cannot_accept_own_proposal(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0", actor="alice")

        r = await _accept(client, cid, "1.1.0", actor="alice")
        assert r.status_code == 422, r.text
        assert "alice" in r.json()["detail"]

    async def test_single_operator_override_allows_same_actor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0", actor="alice")

        r = await _accept(client, cid, "1.1.0", actor="alice", single_operator=True)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["single_operator_override"] is True

    async def test_anonymous_proposer_allows_any_acceptor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0")

        r = await _accept(client, cid, "1.1.0", actor="bob")
        assert r.status_code == 200

    async def test_anonymous_acceptor_allows(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0", actor="alice")

        r = await _accept(client, cid, "1.1.0")
        assert r.status_code == 200

    async def test_rc_promotion_carries_actors_to_stable(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]
        await _propose(client, cid, "1.1.0-rc1", actor="alice")

        r = await _accept(client, cid, "1.1.0-rc1", actor="bob")
        assert r.status_code == 200
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0-rc1"
        assert body["active_version"] == "1.1.0"
        assert body["proposer_actor"] == "alice"
        assert body["acceptor_actor"] == "bob"


# ============================================================
# Template content proposals
# ============================================================


class TestTemplateProposalAttribution:
    async def test_proposer_cannot_accept_own_template_proposal(self, client):
        # Bump software template to 1.0.1 to give us a proposal target
        # (initial seed is 1.0.0).
        r = await client.post(
            "/templates/software/proposals",
            json={"version": "1.0.1", "markdown": "# software\n"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201, r.text

        r = await client.post(
            "/templates/software/proposals/1.0.1/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 422

    async def test_template_single_operator_override(self, client):
        r = await client.post(
            "/templates/software/proposals",
            json={"version": "1.0.1", "markdown": "# software\n"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201

        r = await client.post(
            "/templates/software/proposals/1.0.1/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["single_operator_override"] is True

    async def test_template_attribution_surfaces_in_listing(self, client):
        r = await client.post(
            "/templates/software/proposals",
            json={"version": "1.0.1", "markdown": "# software\n"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201

        r = await client.get("/templates/software/proposals")
        assert r.status_code == 200
        match = [p for p in r.json()["proposals"] if p["version"] == "1.0.1"][0]
        assert match["proposer_actor"] == "alice"

    async def test_template_rc_promotion_carries_actors(self, client):
        r = await client.post(
            "/templates/software/proposals",
            json={"version": "1.1.0-rc1", "markdown": "# software\n"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201

        r = await client.post(
            "/templates/software/proposals/1.1.0-rc1/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0-rc1"
        assert body["active_version"] == "1.1.0"
        assert body["proposer_actor"] == "alice"
        assert body["acceptor_actor"] == "bob"


# ============================================================
# Shift-table override flag retrofit (#38 scope cleanup)
# ============================================================


class TestShiftOverrideFlagRecorded:
    async def test_part_shift_override_flag_recorded_on_accept(self, client):
        await _register_part(client, "svc", subtype="software")
        r = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "container", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201
        pid = r.json()["proposal_id"]

        r = await client.post(
            f"/parts/svc/subtype-proposals/{pid}/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["single_operator_override"] is True

    async def test_part_shift_listing_surfaces_override_flag(self, client):
        await _register_part(client, "svc", subtype="software")
        r = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "container", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        pid = r.json()["proposal_id"]
        await client.post(
            f"/parts/svc/subtype-proposals/{pid}/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )

        r = await client.get("/parts/svc/subtype-proposals")
        assert r.status_code == 200
        match = [p for p in r.json()["proposals"] if p["proposal_id"] == pid][0]
        assert match["single_operator_override"] is True

    async def test_contract_shift_override_flag_recorded(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        cid = c["contract_id"]

        # Shift interaction → interaction would be a no-op; shift to
        # binding requires the owner to be a container/pod. Use a
        # connection-type-only relabel shape that's equivalent for the
        # override-flag test: shift the contract subtype to connection
        # with a label whose owner/counterparty rule is satisfied by
        # the existing software→software pair (`submodule`).
        r = await client.post(
            f"/contracts/{cid}/subtype-proposals",
            json={
                "new_subtype": "connection",
                "new_connection_type": "submodule",
                "rationale": "actually a submodule relationship",
            },
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["proposal_id"]

        r = await client.post(
            f"/contracts/{cid}/subtype-proposals/{pid}/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["single_operator_override"] is True
