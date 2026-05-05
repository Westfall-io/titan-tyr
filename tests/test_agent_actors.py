"""Agent-actor allowlist registration + the live human-confirmation gate (#78).

Two threads here:

1. CRUD on /agent-actors — register, list, detail, revoke. Slug
   validation, double-register conflict, revoke-by-agent gating.
2. The human-confirmation gate (`enforce_human_confirmation`) reads
   the live table per request, so revoking an agent immediately makes
   that actor pass the gate on subsequent destructive accepts. The
   final test class covers that wiring against the actual part-
   deletion accept endpoint to prove the integration works end-to-end.
"""
from __future__ import annotations

import pytest


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


async def _propose_part_deletion(client, name, *, actor="titan-tyr"):
    r = await client.post(
        f"/parts/{name}/deletion-proposals",
        headers={"X-Actor": actor},
        json={"rationale": "test"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- CRUD ----------


class TestRegisterAgentActor:
    @pytest.mark.asyncio
    async def test_register_creates_row(self, client):
        r = await client.post(
            "/agent-actors",
            headers={"X-Actor": "titan-tyr"},
            json={"actor": "new-bot", "description": "freshly onboarded test agent"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["actor"] == "new-bot"
        assert body["description"] == "freshly onboarded test agent"
        assert body["registered_by_actor"] == "titan-tyr"
        assert body["revoked_at"] is None

    @pytest.mark.asyncio
    async def test_double_register_409(self, client):
        # Seed in conftest already includes `mimiron`. Registering it
        # again without a revoke first must conflict so an operator
        # can't accidentally double-list an agent.
        r = await client.post(
            "/agent-actors",
            json={"actor": "mimiron", "description": "duplicate"},
        )
        assert r.status_code == 409, r.text

    @pytest.mark.asyncio
    async def test_invalid_slug_422(self, client):
        r = await client.post(
            "/agent-actors",
            json={"actor": "Bad Actor!", "description": "x"},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_description_required(self, client):
        r = await client.post(
            "/agent-actors",
            json={"actor": "no-desc", "description": ""},
        )
        assert r.status_code == 422, r.text


class TestListAgentActors:
    @pytest.mark.asyncio
    async def test_lists_seeded_actors(self, client):
        r = await client.get("/agent-actors")
        assert r.status_code == 200, r.text
        actors = {row["actor"] for row in r.json()["results"]}
        # Conftest seeds these four; #78 prod migration omits
        # titan-archaedas.
        assert {"titan-tyr", "titan-archaedas", "archaedas", "mimiron"} <= actors

    @pytest.mark.asyncio
    async def test_revoked_hidden_by_default(self, client):
        r = await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "no longer in use"},
        )
        assert r.status_code == 200, r.text
        live = await client.get("/agent-actors")
        assert "mimiron" not in {row["actor"] for row in live.json()["results"]}
        with_revoked = await client.get("/agent-actors?include_revoked=true")
        assert "mimiron" in {row["actor"] for row in with_revoked.json()["results"]}


class TestGetAgentActor:
    @pytest.mark.asyncio
    async def test_unknown_actor_404(self, client):
        r = await client.get("/agent-actors/never-registered")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_revoked_404_unless_include_revoked(self, client):
        await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "test"},
        )
        r = await client.get("/agent-actors/mimiron")
        assert r.status_code == 404
        r = await client.get("/agent-actors/mimiron?include_revoked=true")
        assert r.status_code == 200


class TestRevokeAgentActor:
    @pytest.mark.asyncio
    async def test_revoke_marks_row(self, client):
        r = await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "moving off"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["revoked_at"] is not None
        assert body["revoked_by_actor"] == "alice@example.com"
        assert body["revoke_rationale"] == "moving off"

    @pytest.mark.asyncio
    async def test_re_register_after_revoke_creates_new_row(self, client):
        await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "test"},
        )
        r = await client.post(
            "/agent-actors",
            headers={"X-Actor": "alice@example.com"},
            json={"actor": "mimiron", "description": "re-registered"},
        )
        assert r.status_code == 201, r.text
        # Detail returns the new live row, not the historical revoked one.
        detail = await client.get("/agent-actors/mimiron")
        assert detail.json()["description"] == "re-registered"
        assert detail.json()["revoked_at"] is None

    @pytest.mark.asyncio
    async def test_revoke_unknown_actor_404(self, client):
        r = await client.post(
            "/agent-actors/never-registered/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "x"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_by_agent_403(self, client):
        # An agent X-Actor cannot revoke peers — otherwise a
        # compromised agent could quietly evict the human-confirmation
        # gate from itself by clearing the allowlist.
        r = await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "titan-tyr"},
            json={"rationale": "x"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_revoke_no_x_actor_422(self, client):
        r = await client.post(
            "/agent-actors/mimiron/revoke",
            json={"rationale": "x"},
        )
        assert r.status_code == 422


# ---------- Live integration with the human-confirmation gate ----------


class TestHumanConfirmationReflectsLiveTable:
    @pytest.mark.asyncio
    async def test_revoking_agent_lets_them_accept_destructive(self, client):
        # Setup: a part to delete, proposed by titan-tyr.
        await _register_part(client, "throwaway")
        prop = await _propose_part_deletion(client, "throwaway", actor="titan-tyr")

        # Pre-revoke: mimiron is in the allowlist, so accepting under
        # X-Actor: mimiron is rejected as agent-bouncing-the-handshake.
        r = await client.post(
            f"/parts/throwaway/deletion-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "mimiron"},
        )
        assert r.status_code == 403, r.text

        # Revoke mimiron, then retry — now the gate lets it through
        # because the live allowlist no longer contains mimiron. The
        # accept still has to clear the soft two-party rule (titan-tyr
        # ≠ mimiron, which it does), so the delete succeeds.
        rev = await client.post(
            "/agent-actors/mimiron/revoke",
            headers={"X-Actor": "alice@example.com"},
            json={"rationale": "letting test through"},
        )
        assert rev.status_code == 200, rev.text

        r = await client.post(
            f"/parts/throwaway/deletion-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "mimiron"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["acceptor_actor"] == "mimiron"

    @pytest.mark.asyncio
    async def test_registering_agent_blocks_destructive_accept(self, client):
        # alice is not in the seeded allowlist — she counts as a human
        # by default and her accept goes through.
        await _register_part(client, "throwaway")
        prop = await _propose_part_deletion(client, "throwaway", actor="titan-tyr")

        # Now register alice as an agent, and a fresh accept attempt
        # under that X-Actor is rejected (after re-proposing because
        # the prior part is now deleted).
        await _register_part(client, "throwaway2")
        prop2 = await _propose_part_deletion(client, "throwaway2", actor="titan-tyr")

        reg = await client.post(
            "/agent-actors",
            headers={"X-Actor": "titan-tyr"},
            json={
                "actor": "alice",
                "description": "now considered an agent",
            },
        )
        assert reg.status_code == 201, reg.text

        r = await client.post(
            f"/parts/throwaway2/deletion-proposals/{prop2['proposal_id']}/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 403, r.text

        # Sanity: prop1 (filed before alice was registered) still uses
        # the live gate at accept time, not propose time, so it's also
        # blocked now.
        r = await client.post(
            f"/parts/throwaway/deletion-proposals/{prop['proposal_id']}/accept",
            headers={"X-Actor": "alice"},
        )
        assert r.status_code == 403, r.text
