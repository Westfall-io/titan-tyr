SAMPLE_MD = "# payments-service\n\nDescribes the payments service."


async def _register(client, name="payments-service", version="1.0.0", repo="https://example.com/repo"):
    r = await client.post(
        "/software",
        json={"name": name, "repo_uri": repo, "markdown": SAMPLE_MD, "version": version},
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestRegister:
    async def test_default_version_is_1_0_0(self, client):
        r = await client.post(
            "/software",
            json={"name": "x", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201
        assert r.json()["version"] == "1.0.0"

    async def test_explicit_initial_version(self, client):
        body = await _register(client, version="0.1.0")
        assert body["version"] == "0.1.0"

    async def test_duplicate_name_conflicts(self, client):
        await _register(client, name="dup")
        r = await client.post(
            "/software",
            json={"name": "dup", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 409

    async def test_prerelease_rejected_on_software(self, client):
        r = await client.post(
            "/software",
            json={"name": "rc", "repo_uri": "u", "markdown": "m", "version": "1.0.0-rc1"},
        )
        assert r.status_code == 422

    async def test_malformed_version_rejected(self, client):
        r = await client.post(
            "/software",
            json={"name": "bad", "repo_uri": "u", "markdown": "m", "version": "1.0"},
        )
        assert r.status_code == 422


class TestGet:
    async def test_get_returns_latest(self, client):
        await _register(client, name="g")
        r = await client.get("/software/g")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "g"
        assert body["version"] == "1.0.0"
        assert body["markdown"] == SAMPLE_MD

    async def test_get_unknown(self, client):
        r = await client.get("/software/nope")
        assert r.status_code == 404


class TestUpdate:
    async def test_append_new_version(self, client):
        await _register(client, name="u")
        r = await client.put(
            "/software/u",
            json={"version": "1.1.0", "markdown": "v2"},
        )
        assert r.status_code == 200
        assert r.json()["version"] == "1.1.0"

        latest = (await client.get("/software/u")).json()
        assert latest["version"] == "1.1.0"
        assert latest["markdown"] == "v2"

    async def test_must_be_strictly_greater(self, client):
        await _register(client, name="lt", version="2.0.0")
        r = await client.put(
            "/software/lt",
            json={"version": "1.0.0", "markdown": "older"},
        )
        assert r.status_code == 409

    async def test_equal_version_conflicts(self, client):
        await _register(client, name="eq", version="2.0.0")
        r = await client.put(
            "/software/eq",
            json={"version": "2.0.0", "markdown": "same"},
        )
        assert r.status_code == 409

    async def test_unknown_software(self, client):
        r = await client.put(
            "/software/missing",
            json={"version": "1.0.0", "markdown": "m"},
        )
        assert r.status_code == 404

    async def test_prerelease_rejected(self, client):
        await _register(client, name="prc")
        r = await client.put(
            "/software/prc",
            json={"version": "1.1.0-rc1", "markdown": "m"},
        )
        assert r.status_code == 422


class TestSoftwareContracts:
    async def test_lists_contracts_in_both_directions(self, client):
        await _register(client, name="a")
        await _register(client, name="b")
        await _register(client, name="c")
        r1 = await client.post(
            "/contracts",
            json={
                "owner_software": "a",
                "counterparty_software": "b",
                "markdown": "ab",
            },
        )
        assert r1.status_code == 201
        r2 = await client.post(
            "/contracts",
            json={
                "owner_software": "c",
                "counterparty_software": "a",
                "markdown": "ca",
            },
        )
        assert r2.status_code == 201

        listing = (await client.get("/software/a/contracts")).json()
        assert listing["software"] == "a"
        assert len(listing["contracts"]) == 2
        owners = {c["owner"] for c in listing["contracts"]}
        assert owners == {"a", "c"}

    async def test_unknown_software(self, client):
        r = await client.get("/software/missing/contracts")
        assert r.status_code == 404
