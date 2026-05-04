"""Endpoint-shift (contracts) and name-shift (parts) flows (#45)."""
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
):
    body = {
        "owner_part": owner,
        "counterparty_part": counterparty,
        "subtype": subtype,
        "markdown": f"# contract {owner}->{counterparty}",
    }
    if connection_type is not None:
        body["connection_type"] = connection_type
    r = await client.post("/contracts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# Part name shifts
# ============================================================


class TestProposePartNameShift:
    async def test_creates_proposal(self, client):
        await _register_part(client, "svc")
        r = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "service", "rationale": "clearer"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["part_name"] == "svc"
        assert body["current_name"] == "svc"
        assert body["new_name"] == "service"
        assert body["rationale"] == "clearer"
        assert "proposal_id" in body

    async def test_unknown_part_404(self, client):
        r = await client.post(
            "/parts/ghost/name-proposals",
            json={"new_name": "ghost-2", "rationale": "x"},
        )
        assert r.status_code == 404

    async def test_invalid_slug_rejected(self, client):
        await _register_part(client, "svc")
        r = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "Svc.Service", "rationale": "x"},
        )
        assert r.status_code == 422

    async def test_noop_rejected(self, client):
        await _register_part(client, "svc")
        r = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "svc", "rationale": "x"},
        )
        assert r.status_code == 409
        assert "no-op" in r.json()["detail"]

    async def test_collision_rejected_at_propose(self, client):
        await _register_part(client, "svc")
        await _register_part(client, "service")
        r = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "service", "rationale": "x"},
        )
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]

    async def test_actor_recorded(self, client):
        await _register_part(client, "svc")
        r = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "service", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201
        assert r.json()["proposer_actor"] == "alice"


class TestListPartNameShifts:
    async def test_empty_when_no_proposals(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc/name-proposals")
        assert r.status_code == 200
        body = r.json()
        assert body["part_name"] == "svc"
        assert body["proposals"] == []

    async def test_lists_open_and_accepted(self, client):
        await _register_part(client, "svc")
        p1 = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "first"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/parts/svc/name-proposals/{p1['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        # File another against the *renamed* part
        await client.post(
            "/parts/service/name-proposals",
            json={"new_name": "the-service", "rationale": "second"},
            headers={"X-Actor": "alice"},
        )
        r = await client.get("/parts/service/name-proposals")
        assert r.status_code == 200
        rows = r.json()["proposals"]
        assert {row["status"] for row in rows} == {"proposal", "accepted"}
        # Newest first
        assert rows[0]["new_name"] == "the-service"
        assert rows[1]["new_name"] == "service"


class TestAcceptPartNameShift:
    async def test_renames_part(self, client):
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shifted_from_name"] == "svc"
        assert body["shifted_to_name"] == "service"
        # Old slug 404s, new slug serves the part
        assert (await client.get("/parts/svc")).status_code == 404
        d = await client.get("/parts/service")
        assert d.status_code == 200
        assert d.json()["name"] == "service"

    async def test_two_party_enforced(self, client):
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 422

    async def test_single_operator_overrides(self, client):
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept"
            "?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["single_operator_override"] is True

    async def test_double_accept_409(self, client):
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        # Second accept against the (now-renamed) part: proposal has
        # already moved to 'accepted'; the part itself has no record at
        # the old slug. The 404 on the part path is the correct guard.
        r = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 404

    async def test_collision_at_accept_time(self, client):
        # File a name-shift, then register a competing part that
        # claims the proposed slug, then try to accept.
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await _register_part(client, "service")
        r = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 409
        assert "now taken" in r.json()["detail"]

    async def test_contracts_surface_new_name(self, client):
        # Renaming a part on which contracts terminate should surface
        # the new name on the next contract GET — no contract-side
        # cascade needed (FK-by-id).
        await _register_part(client, "svc")
        await _register_part(client, "other")
        c = await _register_contract(client, "svc", "other")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        accept = await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accept.status_code == 200
        d = await client.get(f"/contracts/{c['contract_id']}")
        assert d.status_code == 200
        assert d.json()["owner"] == "service"
        assert d.json()["counterparty"] == "other"

    async def test_bookkeeping_emitted_in_history(self, client):
        await _register_part(client, "svc")
        prop = (
            await client.post(
                "/parts/svc/name-proposals",
                json={"new_name": "service", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/parts/svc/name-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get("/parts/service/history")
        assert r.status_code == 200
        kinds = [row["kind"] for row in r.json()["results"]]
        assert "name_shift" in kinds


# ============================================================
# Contract endpoint shifts
# ============================================================


class TestProposeContractEndpointShift:
    async def test_creates_proposal_one_sided_owner(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_owner": "a2", "rationale": "owner moved"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["current_owner"] == "a"
        assert body["new_owner"] == "a2"
        assert body["new_counterparty"] is None

    async def test_creates_proposal_both_sides(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        await _register_part(client, "b2")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={
                "new_owner": "a2",
                "new_counterparty": "b2",
                "rationale": "both moved",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["new_owner"] == "a2"
        assert body["new_counterparty"] == "b2"

    async def test_unknown_contract_404(self, client):
        r = await client.post(
            "/contracts/00000000-0000-0000-0000-000000000000/endpoint-proposals",
            json={"new_owner": "a", "rationale": "x"},
        )
        assert r.status_code == 404

    async def test_unknown_endpoint_part_404(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_owner": "ghost", "rationale": "x"},
        )
        assert r.status_code == 404

    async def test_neither_side_set_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"rationale": "x"},
        )
        assert r.status_code == 422

    async def test_noop_shift_rejected(self, client):
        # Both sides set but resolving to the current (owner, cp).
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={
                "new_owner": "a",
                "new_counterparty": "b",
                "rationale": "x",
            },
        )
        assert r.status_code == 422
        assert "no-op" in r.json()["detail"]

    async def test_self_loop_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_counterparty": "a", "rationale": "x"},
        )
        assert r.status_code == 422
        assert "differ" in r.json()["detail"]

    async def test_collision_with_existing_contract(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        # a2 -> b interaction already exists — shifting c's owner to a2
        # would collide (#42's widened uniqueness key).
        await _register_contract(client, "a2", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_owner": "a2", "rationale": "x"},
        )
        assert r.status_code == 409
        assert "collide" in r.json()["detail"]

    async def test_source_target_rule_violation(self, client):
        # Connection contract with binding rule: replacing the
        # software counterparty with a non-software part should 422.
        await _register_part(client, "svc", subtype="software")
        await _register_part(client, "ctr", subtype="container")
        await _register_part(client, "img", subtype="image")
        c = await _register_contract(client, "ctr", "svc", subtype="binding")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_counterparty": "img", "rationale": "x"},
        )
        assert r.status_code == 422
        assert "source/target" in r.json()["detail"]

    async def test_actor_recorded(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals",
            json={"new_owner": "a2", "rationale": "x"},
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 201
        assert r.json()["proposer_actor"] == "alice"


class TestListContractEndpointShifts:
    async def test_empty(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        c = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{c['contract_id']}/endpoint-proposals")
        assert r.status_code == 200
        assert r.json()["proposals"] == []

    async def test_lists_proposal_and_accept(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get(f"/contracts/{c['contract_id']}/endpoint-proposals")
        assert r.status_code == 200
        body = r.json()
        # current_owner reflects post-accept state
        assert body["current_owner"] == "a2"
        assert body["proposals"][0]["status"] == "accepted"
        assert body["proposals"][0]["accepted_by"] == "bob"


class TestAcceptContractEndpointShift:
    async def test_swaps_owner(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shifted_from_owner"] == "a"
        assert body["shifted_to_owner"] == "a2"
        assert body["shifted_from_counterparty"] == "b"
        assert body["shifted_to_counterparty"] == "b"
        # Detail GET reflects the new owner
        d = await client.get(f"/contracts/{c['contract_id']}")
        assert d.json()["owner"] == "a2"

    async def test_swaps_both_sides(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        await _register_part(client, "b2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={
                    "new_owner": "a2",
                    "new_counterparty": "b2",
                    "rationale": "x",
                },
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 200
        d = await client.get(f"/contracts/{c['contract_id']}")
        assert d.json()["owner"] == "a2"
        assert d.json()["counterparty"] == "b2"

    async def test_two_party_enforced(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 422

    async def test_single_operator_overrides(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept?single_operator=true",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["single_operator_override"] is True

    async def test_collision_at_accept_time(self, client):
        # File a shift, then create a colliding contract before accept.
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        # Create the would-be collision after the proposal lands.
        await _register_contract(client, "a2", "b")
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 409
        assert "collide" in r.json()["detail"]

    async def test_double_accept_409(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert r.status_code == 409

    async def test_bookkeeping_emitted_in_history(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "a2")
        c = await _register_contract(client, "a", "b")
        prop = (
            await client.post(
                f"/contracts/{c['contract_id']}/endpoint-proposals",
                json={"new_owner": "a2", "rationale": "x"},
                headers={"X-Actor": "alice"},
            )
        ).json()
        await client.post(
            f"/contracts/{c['contract_id']}/endpoint-proposals/"
            f"{prop['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        r = await client.get(f"/contracts/{c['contract_id']}/history")
        assert r.status_code == 200
        kinds = [row["kind"] for row in r.json()["results"]]
        assert "endpoint_shift" in kinds
