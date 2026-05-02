async def _register_pair(client, owner="a", counterparty="b"):
    for name in (owner, counterparty):
        r = await client.post(
            "/software",
            json={"name": name, "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201, r.text


async def _new_contract(client, owner="a", counterparty="b", version="1.0.0"):
    r = await client.post(
        "/contracts",
        json={
            "owner_software": owner,
            "counterparty_software": counterparty,
            "markdown": "contract md",
            "version": version,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestRegister:
    async def test_creates_active_at_default_version(self, client):
        await _register_pair(client)
        body = await _new_contract(client)
        assert body["version"] == "1.0.0"
        assert body["status"] == "active"
        assert body["owner"] == "a"
        assert body["counterparty"] == "b"

    async def test_explicit_initial_version(self, client):
        await _register_pair(client)
        body = await _new_contract(client, version="0.1.0")
        assert body["version"] == "0.1.0"

    async def test_owner_eq_counterparty_rejected(self, client):
        await _register_pair(client, owner="a", counterparty="b")
        r = await client.post(
            "/contracts",
            json={"owner_software": "a", "counterparty_software": "a", "markdown": "m"},
        )
        assert r.status_code == 422

    async def test_unknown_software(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={"owner_software": "a", "counterparty_software": "ghost", "markdown": "m"},
        )
        assert r.status_code == 404

    async def test_duplicate_pair_conflicts(self, client):
        await _register_pair(client)
        await _new_contract(client)
        r = await client.post(
            "/contracts",
            json={"owner_software": "a", "counterparty_software": "b", "markdown": "m"},
        )
        assert r.status_code == 409

    async def test_prerelease_rejected_on_initial(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_software": "a",
                "counterparty_software": "b",
                "markdown": "m",
                "version": "1.0.0-rc1",
            },
        )
        assert r.status_code == 422


class TestGet:
    async def test_get_by_id(self, client):
        await _register_pair(client)
        body = await _new_contract(client)
        r = await client.get(f"/contracts/{body['contract_id']}")
        assert r.status_code == 200
        assert r.json()["version"] == "1.0.0"

    async def test_unknown_contract(self, client):
        r = await client.get("/contracts/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


class TestSearch:
    async def test_finds_in_either_direction(self, client):
        await _register_pair(client, owner="a", counterparty="b")
        await _new_contract(client, owner="a", counterparty="b")
        # Reverse order in the query — should still find the a→b contract.
        r = await client.get("/contracts", params={"owner": "b", "counterparty": "a"})
        assert r.status_code == 200
        assert len(r.json()["results"]) == 1

    async def test_returns_both_directions(self, client):
        for n in ("a", "b"):
            await client.post(
                "/software", json={"name": n, "repo_uri": "u", "markdown": "m"}
            )
        await _new_contract(client, owner="a", counterparty="b")
        await _new_contract(client, owner="b", counterparty="a")
        r = await client.get("/contracts", params={"owner": "a", "counterparty": "b"})
        assert r.status_code == 200
        assert len(r.json()["results"]) == 2

    async def test_no_match_returns_empty(self, client):
        await _register_pair(client)
        r = await client.get("/contracts", params={"owner": "a", "counterparty": "b"})
        assert r.status_code == 200
        assert r.json()["results"] == []

    async def test_unknown_software_404(self, client):
        await _register_pair(client)
        r = await client.get("/contracts", params={"owner": "a", "counterparty": "ghost"})
        assert r.status_code == 404
