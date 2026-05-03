"""Per-resource version history endpoints (#20).

GET /software/{name}/history
GET /contracts/{contract_id}/history

Both: cursor-paginated, most-recent-first, default limit 50, max 100,
404 when parent missing. Contract history excludes RC proposals (only
status='active' rows appear); the active_must_be_stable DB constraint
guarantees those are stable, no client-side filtering needed.
"""
from __future__ import annotations

import asyncio


async def _register_software(client, name, repo="https://example.com/r"):
    r = await client.post(
        "/software",
        json={"name": name, "repo_uri": repo, "markdown": f"# {name}"},
    )
    assert r.status_code == 201, r.text


async def _update_software(client, name, version, markdown=None):
    r = await client.put(
        f"/software/{name}",
        json={"version": version, "markdown": markdown or f"# {name} {version}"},
    )
    assert r.status_code == 200, r.text


async def _register_contract(client, owner, counterparty, markdown="m"):
    r = await client.post(
        "/contracts",
        json={
            "owner_software": owner,
            "counterparty_software": counterparty,
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
        await _register_software(client, "svc")
        r = await client.get("/software/svc/history")
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 1
        entry = body["results"][0]
        assert entry["version"] == "1.0.0"
        assert "updated_at" in entry
        assert "markdown" not in entry  # body excluded by spec
        assert body["next"] is None

    async def test_multiple_versions_most_recent_first(self, client):
        await _register_software(client, "svc")
        await asyncio.sleep(0.01)
        await _update_software(client, "svc", "1.1.0")
        await asyncio.sleep(0.01)
        await _update_software(client, "svc", "2.0.0")
        r = await client.get("/software/svc/history")
        assert r.status_code == 200
        versions = [it["version"] for it in r.json()["results"]]
        assert versions == ["2.0.0", "1.1.0", "1.0.0"]

    async def test_paginates_with_cursor(self, client):
        await _register_software(client, "svc")
        for v in ("1.1.0", "1.2.0", "1.3.0", "1.4.0"):
            await asyncio.sleep(0.01)
            await _update_software(client, "svc", v)
        # 5 versions total. Walk in pages of 2.
        page1 = (await client.get("/software/svc/history", params={"limit": 2})).json()
        assert [it["version"] for it in page1["results"]] == ["1.4.0", "1.3.0"]
        assert page1["next"] is not None

        page2 = (
            await client.get(
                "/software/svc/history", params={"limit": 2, "after": page1["next"]}
            )
        ).json()
        assert [it["version"] for it in page2["results"]] == ["1.2.0", "1.1.0"]
        assert page2["next"] is not None

        page3 = (
            await client.get(
                "/software/svc/history", params={"limit": 2, "after": page2["next"]}
            )
        ).json()
        assert [it["version"] for it in page3["results"]] == ["1.0.0"]
        assert page3["next"] is None

    async def test_404_when_software_missing(self, client):
        r = await client.get("/software/nonesuch/history")
        assert r.status_code == 404

    async def test_invalid_cursor_rejected(self, client):
        await _register_software(client, "svc")
        r = await client.get("/software/svc/history", params={"after": "garbage"})
        assert r.status_code == 422

    async def test_limit_out_of_range(self, client):
        await _register_software(client, "svc")
        r = await client.get("/software/svc/history", params={"limit": 0})
        assert r.status_code == 422
        r = await client.get("/software/svc/history", params={"limit": 101})
        assert r.status_code == 422

    async def test_history_is_per_software(self, client):
        await _register_software(client, "a")
        await _register_software(client, "b")
        await _update_software(client, "a", "1.1.0")
        # b should still show only its own 1.0.0
        r = await client.get("/software/b/history")
        versions = [it["version"] for it in r.json()["results"]]
        assert versions == ["1.0.0"]


class TestContractHistory:
    async def test_single_version_after_register(self, client):
        await _register_software(client, "a")
        await _register_software(client, "b")
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
        await _register_software(client, "a")
        await _register_software(client, "b")
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
        await _register_software(client, "a")
        await _register_software(client, "b")
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
        await _register_software(client, "a")
        await _register_software(client, "b")
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
        await _register_software(client, "a")
        await _register_software(client, "b")
        cid = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{cid}/history", params={"after": "garbage"})
        assert r.status_code == 422

    async def test_limit_out_of_range(self, client):
        await _register_software(client, "a")
        await _register_software(client, "b")
        cid = await _register_contract(client, "a", "b")
        r = await client.get(f"/contracts/{cid}/history", params={"limit": 0})
        assert r.status_code == 422
        r = await client.get(f"/contracts/{cid}/history", params={"limit": 101})
        assert r.status_code == 422
