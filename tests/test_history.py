"""Per-resource version history endpoints (#20).

GET /parts/{name}/history
GET /contracts/{contract_id}/history

Both: cursor-paginated, most-recent-first, default limit 50, max 100,
404 when parent missing. Contract history excludes RC proposals (only
status='active' rows appear); the active_must_be_stable DB constraint
guarantees those are stable, no client-side filtering needed.
"""
from __future__ import annotations

import asyncio


async def _register_part(client, name, repo="https://example.com/r"):
    r = await client.post(
        "/parts",
        json={"name": name, "subtype": "software", "repo_uri": repo, "markdown": f"# {name}"},
    )
    assert r.status_code == 201, r.text


async def _update_part(client, name, version, markdown=None):
    r = await client.put(
        f"/parts/{name}",
        json={"version": version, "markdown": markdown or f"# {name} {version}"},
    )
    assert r.status_code == 200, r.text


async def _register_contract(client, owner, counterparty, markdown="m"):
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": "interaction",
            "markdown": markdown,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["contract_id"]


async def _propose(client, cid, version, markdown="p"):
    r = await client.post(
        f"/contracts/{cid}/proposals",
        json={"version": version, "markdown": markdown},
    )
    assert r.status_code == 201, r.text


async def _accept(client, cid, version):
    r = await client.post(f"/contracts/{cid}/proposals/{version}/accept")
    assert r.status_code == 200, r.text


class TestSoftwareHistory:
    async def test_single_version_after_register(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc/history")
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 1
        entry = body["results"][0]
        assert entry["version"] == "1.0.0"
        assert "updated_at" in entry
        assert "markdown" not in entry  # body excluded by spec
        assert body["next"] is None

    async def test_multiple_versions_most_recent_first(self, client):
        await _register_part(client, "svc")
        await asyncio.sleep(0.01)
        await _update_part(client, "svc", "1.1.0")
        await asyncio.sleep(0.01)
        await _update_part(client, "svc", "2.0.0")
        r = await client.get("/parts/svc/history")
        assert r.status_code == 200
        versions = [it["version"] for it in r.json()["results"]]
        assert versions == ["2.0.0", "1.1.0", "1.0.0"]

    async def test_paginates_with_cursor(self, client):
        await _register_part(client, "svc")
        for v in ("1.1.0", "1.2.0", "1.3.0", "1.4.0"):
            await asyncio.sleep(0.01)
            await _update_part(client, "svc", v)
        # 5 versions total. Walk in pages of 2.
        page1 = (await client.get("/parts/svc/history", params={"limit": 2})).json()
        assert [it["version"] for it in page1["results"]] == ["1.4.0", "1.3.0"]
        assert page1["next"] is not None

        page2 = (
            await client.get(
                "/parts/svc/history", params={"limit": 2, "after": page1["next"]}
            )
        ).json()
        assert [it["version"] for it in page2["results"]] == ["1.2.0", "1.1.0"]
        assert page2["next"] is not None

        page3 = (
            await client.get(
                "/parts/svc/history", params={"limit": 2, "after": page2["next"]}
            )
        ).json()
        assert [it["version"] for it in page3["results"]] == ["1.0.0"]
        assert page3["next"] is None

    async def test_404_when_software_missing(self, client):
        r = await client.get("/parts/nonesuch/history")
        assert r.status_code == 404

    async def test_invalid_cursor_rejected(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc/history", params={"after": "garbage"})
        assert r.status_code == 422

    async def test_limit_out_of_range(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc/history", params={"limit": 0})
        assert r.status_code == 422
        r = await client.get("/parts/svc/history", params={"limit": 101})
        assert r.status_code == 422

    async def test_history_is_per_software(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _update_part(client, "a", "1.1.0")
        # b should still show only its own 1.0.0
        r = await client.get("/parts/b/history")
        versions = [it["version"] for it in r.json()["results"]]
        assert versions == ["1.0.0"]


class TestContractHistory:
    async def test_single_version_after_register(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{cid}/history")
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 1
        entry = body["results"][0]
        assert entry["version"] == "1.0.0"
        assert "markdown" not in entry
        assert body["next"] is None

    async def test_accepted_versions_most_recent_first(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        # Stable accept (no RC).
        await _propose(client, cid, "1.1.0")
        await asyncio.sleep(0.01)
        await _accept(client, cid, "1.1.0")
        # RC then promote.
        await _propose(client, cid, "1.2.0-rc1")
        await asyncio.sleep(0.01)
        await _accept(client, cid, "1.2.0-rc1")

        r = await client.get(f"/contracts/{cid}/history")
        versions = [it["version"] for it in r.json()["results"]]
        assert versions == ["1.2.0", "1.1.0", "1.0.0"]

    async def test_excludes_rc_proposals(self, client):
        """Both pending and superseded RC rows must not appear in history."""
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        # RC1 proposed and superseded by RC2; RC2 then accepted (becomes stable).
        await _propose(client, cid, "1.1.0-rc1")
        await _propose(client, cid, "1.1.0-rc2")
        await _accept(client, cid, "1.1.0-rc2")
        # An open RC that never got accepted.
        await _propose(client, cid, "1.2.0-rc1")

        r = await client.get(f"/contracts/{cid}/history")
        versions = [it["version"] for it in r.json()["results"]]
        # Only the two accepted stable versions; no rcN entries.
        assert versions == ["1.1.0", "1.0.0"]

    async def test_paginates_with_cursor(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        for v in ("1.1.0", "1.2.0", "1.3.0", "1.4.0"):
            await _propose(client, cid, v)
            await asyncio.sleep(0.01)
            await _accept(client, cid, v)
            await asyncio.sleep(0.01)

        page1 = (await client.get(f"/contracts/{cid}/history", params={"limit": 2})).json()
        assert [it["version"] for it in page1["results"]] == ["1.4.0", "1.3.0"]
        assert page1["next"] is not None

        page2 = (
            await client.get(
                f"/contracts/{cid}/history", params={"limit": 2, "after": page1["next"]}
            )
        ).json()
        assert [it["version"] for it in page2["results"]] == ["1.2.0", "1.1.0"]
        assert page2["next"] is not None

        page3 = (
            await client.get(
                f"/contracts/{cid}/history", params={"limit": 2, "after": page2["next"]}
            )
        ).json()
        assert [it["version"] for it in page3["results"]] == ["1.0.0"]
        assert page3["next"] is None

    async def test_404_when_contract_missing(self, client):
        r = await client.get("/contracts/00000000-0000-0000-0000-000000000000/history")
        assert r.status_code == 404

    async def test_invalid_cursor_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{cid}/history", params={"after": "garbage"})
        assert r.status_code == 422

    async def test_limit_out_of_range(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        cid = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{cid}/history", params={"limit": 0})
        assert r.status_code == 422
        r = await client.get(f"/contracts/{cid}/history", params={"limit": 101})
        assert r.status_code == 422


class TestPartHistoryActor:
    """#51 — /parts/{name}/history surfaces actor fields on shift entries.

    body_bump entries on parts surface as null/false because PartVersion
    does not yet carry propose-accept attribution (parts use direct-write
    versioning; the issue defers populating these as forward-applies once
    parts gain a content-proposal lifecycle).
    """

    async def test_body_bump_actors_null_per_forward_apply(self, client):
        await _register_part(client, "svc")
        r = await client.get("/parts/svc/history")
        assert r.status_code == 200
        rows = r.json()["results"]
        v100 = next(r for r in rows if r["version"] == "1.0.0")
        assert v100["kind"] == "body_bump"
        assert v100["proposer_actor"] is None
        assert v100["acceptor_actor"] is None
        assert v100["single_operator_override"] is False

    async def test_subtype_shift_carries_actors(self, client):
        await _register_part(client, "svc")
        prop = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "container", "rationale": "actually a container"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        proposal_id = prop.json()["proposal_id"]
        accept = await client.post(
            f"/parts/svc/subtype-proposals/{proposal_id}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accept.status_code == 200, accept.text

        r = await client.get("/parts/svc/history")
        rows = r.json()["results"]
        shift = next(r for r in rows if r["kind"] == "subtype_shift")
        assert shift["proposer_actor"] == "alice"
        assert shift["acceptor_actor"] == "bob"
        assert shift["single_operator_override"] is False

    async def test_name_shift_carries_actors(self, client):
        await _register_part(client, "svc")
        prop = await client.post(
            "/parts/svc/name-proposals",
            json={"new_name": "service", "rationale": "clearer"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        proposal_id = prop.json()["proposal_id"]
        accept = await client.post(
            f"/parts/svc/name-proposals/{proposal_id}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accept.status_code == 200, accept.text

        # History surfaces under the renamed slug.
        r = await client.get("/parts/service/history")
        rows = r.json()["results"]
        shift = next(r for r in rows if r["kind"] == "name_shift")
        assert shift["proposer_actor"] == "alice"
        assert shift["acceptor_actor"] == "bob"
        assert shift["single_operator_override"] is False

    async def test_single_operator_override_surfaces(self, client):
        await _register_part(client, "svc")
        prop = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "container", "rationale": "solo setup"},
            headers={"X-Actor": "solo"},
        )
        proposal_id = prop.json()["proposal_id"]
        # Same X-Actor accepts under single_operator override.
        accept = await client.post(
            f"/parts/svc/subtype-proposals/{proposal_id}/accept",
            params={"single_operator": "true"},
            headers={"X-Actor": "solo"},
        )
        assert accept.status_code == 200, accept.text

        r = await client.get("/parts/svc/history")
        rows = r.json()["results"]
        shift = next(r for r in rows if r["kind"] == "subtype_shift")
        assert shift["proposer_actor"] == "solo"
        assert shift["acceptor_actor"] == "solo"
        assert shift["single_operator_override"] is True
