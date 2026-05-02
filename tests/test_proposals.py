async def _bootstrap(client):
    for n in ("a", "b"):
        r = await client.post(
            "/software", json={"name": n, "repo_uri": "u", "markdown": "m"}
        )
        assert r.status_code == 201, r.text
    r = await client.post(
        "/contracts",
        json={"owner_software": "a", "counterparty_software": "b", "markdown": "v1.0.0"},
    )
    assert r.status_code == 201
    return r.json()["contract_id"]


async def _propose(client, contract_id, version, markdown="proposal md"):
    r = await client.post(
        f"/contracts/{contract_id}/proposals",
        json={"version": version, "markdown": markdown},
    )
    return r


async def _accept(client, contract_id, version):
    r = await client.post(f"/contracts/{contract_id}/proposals/{version}/accept")
    return r


class TestCreateProposal:
    async def test_stable_proposal(self, client):
        cid = await _bootstrap(client)
        r = await _propose(client, cid, "1.1.0")
        assert r.status_code == 201
        assert r.json()["version"] == "1.1.0"
        assert r.json()["status"] == "proposal"

    async def test_rc_proposal(self, client):
        cid = await _bootstrap(client)
        r = await _propose(client, cid, "1.1.0-rc1")
        assert r.status_code == 201
        assert r.json()["version"] == "1.1.0-rc1"

    async def test_must_be_strictly_greater_than_active(self, client):
        cid = await _bootstrap(client)
        r = await _propose(client, cid, "1.0.0")
        assert r.status_code == 409

    async def test_must_be_strictly_greater_than_existing_proposal(self, client):
        cid = await _bootstrap(client)
        assert (await _propose(client, cid, "1.1.0-rc1")).status_code == 201
        r = await _propose(client, cid, "1.1.0-rc1")
        assert r.status_code == 409

    async def test_rc_chain(self, client):
        cid = await _bootstrap(client)
        for v in ["1.1.0-rc1", "1.1.0-rc2", "1.1.0-rc10", "1.1.0"]:
            r = await _propose(client, cid, v)
            assert r.status_code == 201, (v, r.text)

    async def test_unknown_contract(self, client):
        r = await _propose(client, "00000000-0000-0000-0000-000000000000", "1.1.0")
        assert r.status_code == 404

    async def test_malformed_version(self, client):
        cid = await _bootstrap(client)
        r = await _propose(client, cid, "1.1")
        assert r.status_code == 422


class TestListProposals:
    async def test_lists_only_newer_than_active(self, client):
        cid = await _bootstrap(client)
        await _propose(client, cid, "1.1.0-rc1")
        await _propose(client, cid, "1.1.0")
        await _propose(client, cid, "2.0.0")
        r = await client.get(f"/contracts/{cid}/proposals")
        assert r.status_code == 200
        body = r.json()
        assert body["active_version"] == "1.0.0"
        versions = [p["version"] for p in body["proposals"]]
        assert versions == ["1.1.0-rc1", "1.1.0", "2.0.0"]

    async def test_empty_listing(self, client):
        cid = await _bootstrap(client)
        r = await client.get(f"/contracts/{cid}/proposals")
        assert r.status_code == 200
        assert r.json()["proposals"] == []

    async def test_unknown_contract(self, client):
        r = await client.get("/contracts/00000000-0000-0000-0000-000000000000/proposals")
        assert r.status_code == 404


class TestAccept:
    async def test_accept_stable_in_place(self, client):
        cid = await _bootstrap(client)
        await _propose(client, cid, "1.1.0", markdown="new active")
        r = await _accept(client, cid, "1.1.0")
        assert r.status_code == 200
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0"
        assert body["active_version"] == "1.1.0"

        latest = (await client.get(f"/contracts/{cid}")).json()
        assert latest["version"] == "1.1.0"
        assert latest["markdown"] == "new active"

    async def test_accept_rc_creates_stable_and_keeps_rc(self, client):
        cid = await _bootstrap(client)
        await _propose(client, cid, "1.1.0-rc1", markdown="rc1 md")
        await _propose(client, cid, "1.1.0-rc2", markdown="rc2 md")
        r = await _accept(client, cid, "1.1.0-rc2")
        assert r.status_code == 200
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0-rc2"
        assert body["active_version"] == "1.1.0"

        # GET /contracts only ever shows stable.
        active = (await client.get(f"/contracts/{cid}")).json()
        assert active["version"] == "1.1.0"
        assert active["markdown"] == "rc2 md"

        # Listing proposals: stable 1.1.0 is now active, so any older RC drops out.
        proposals = (await client.get(f"/contracts/{cid}/proposals")).json()
        assert proposals["active_version"] == "1.1.0"
        assert proposals["proposals"] == []

    async def test_double_accept_rejected(self, client):
        cid = await _bootstrap(client)
        await _propose(client, cid, "1.1.0")
        assert (await _accept(client, cid, "1.1.0")).status_code == 200
        r = await _accept(client, cid, "1.1.0")
        # Second accept: row is now status='active', so we refuse.
        assert r.status_code == 409

    async def test_accept_rc_then_propose_higher_rc_then_accept(self, client):
        cid = await _bootstrap(client)
        await _propose(client, cid, "1.1.0-rc1", markdown="early")
        # Accept rc1 — creates stable 1.1.0.
        assert (await _accept(client, cid, "1.1.0-rc1")).status_code == 200
        # Now propose 1.2.0; must be > stable 1.1.0.
        r = await _propose(client, cid, "1.2.0")
        assert r.status_code == 201

    async def test_unknown_proposal(self, client):
        cid = await _bootstrap(client)
        r = await _accept(client, cid, "9.9.9")
        assert r.status_code == 404

    async def test_unknown_contract(self, client):
        r = await _accept(client, "00000000-0000-0000-0000-000000000000", "1.0.0")
        assert r.status_code == 404

    async def test_malformed_version_in_path(self, client):
        cid = await _bootstrap(client)
        r = await _accept(client, cid, "not-a-version")
        assert r.status_code == 422

    async def test_rc_promotion_blocked_if_stable_already_exists(self, client):
        cid = await _bootstrap(client)
        # Bring the active up to 1.1.0 directly via PUT-equivalent: propose + accept stable.
        await _propose(client, cid, "1.1.0", markdown="stable")
        assert (await _accept(client, cid, "1.1.0")).status_code == 200
        # Manually propose a low-version rc somehow — this requires it to be greater than
        # 1.1.0. Use 1.2.0-rc1 instead, and confirm it works fine (sanity check).
        assert (await _propose(client, cid, "1.2.0-rc1")).status_code == 201
        # Then propose AND accept stable 1.2.0, which leaves the rc in place.
        await _propose(client, cid, "1.2.0")
        assert (await _accept(client, cid, "1.2.0")).status_code == 200
        # Now accepting the rc should fail because stable 1.2.0 already exists.
        r = await _accept(client, cid, "1.2.0-rc1")
        assert r.status_code == 409
