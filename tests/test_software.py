import pytest

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


class TestNameValidation:
    @pytest.mark.parametrize("name", [
        "x",
        "ab",
        "payments-service",
        "a1",
        "1a",
        "abc-123-def",
        "a" * 64,
    ])
    async def test_accepts_slug(self, client, name):
        r = await client.post(
            "/software",
            json={"name": name, "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201, r.text

    @pytest.mark.parametrize("name", [
        "",                          # empty
        "Capital",                   # uppercase
        "name with spaces",          # spaces
        "weird.name",                # dot
        "weird/name",                # slash
        "weird_name",                # underscore
        "-leading-hyphen",
        "trailing-hyphen-",
        "a" * 65,                    # too long
        "name@example",              # punctuation
        "café",                 # non-ascii
    ])
    async def test_rejects_non_slug(self, client, name):
        r = await client.post(
            "/software",
            json={"name": name, "repo_uri": "u", "markdown": "m"},
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


class TestRepoUriOnUpdate:
    async def test_put_sets_repo_uri(self, client):
        await _register(client, name="r-set", repo="https://example.com/before")
        r = await client.put(
            "/software/r-set",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "repo_uri": "https://example.com/after",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/software/r-set")).json()
        assert body["repo_uri"] == "https://example.com/after"

    async def test_put_without_repo_uri_leaves_existing(self, client):
        await _register(client, name="r-leave", repo="https://example.com/keep")
        r = await client.put(
            "/software/r-leave",
            json={"version": "1.1.0", "markdown": "m"},
        )
        assert r.status_code == 200
        body = (await client.get("/software/r-leave")).json()
        assert body["repo_uri"] == "https://example.com/keep"

    async def test_put_explicit_null_rejected(self, client):
        await _register(client, name="r-null")
        r = await client.put(
            "/software/r-null",
            json={"version": "1.1.0", "markdown": "m", "repo_uri": None},
        )
        assert r.status_code == 422

    async def test_put_empty_string_rejected(self, client):
        await _register(client, name="r-empty")
        r = await client.put(
            "/software/r-empty",
            json={"version": "1.1.0", "markdown": "m", "repo_uri": ""},
        )
        assert r.status_code == 422

    async def test_put_ssh_form_repo_uri_accepted(self, client):
        await _register(client, name="r-ssh")
        r = await client.put(
            "/software/r-ssh",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "repo_uri": "git@github.com:example/r-ssh.git",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/software/r-ssh")).json()
        assert body["repo_uri"] == "git@github.com:example/r-ssh.git"


class TestIssueTrackerUri:
    async def test_register_without_tracker_returns_null(self, client):
        await _register(client, name="no-tracker")
        body = (await client.get("/software/no-tracker")).json()
        assert body["issue_tracker_uri"] is None

    async def test_register_with_tracker(self, client):
        r = await client.post(
            "/software",
            json={
                "name": "with-tracker",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.atlassian.net/browse/PROJ",
                "markdown": "m",
            },
        )
        assert r.status_code == 201
        body = (await client.get("/software/with-tracker")).json()
        assert body["issue_tracker_uri"] == "https://example.atlassian.net/browse/PROJ"

    async def test_register_rejects_http_scheme(self, client):
        r = await client.post(
            "/software",
            json={
                "name": "http-tracker",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "http://example.com/issues",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_register_rejects_garbage(self, client):
        r = await client.post(
            "/software",
            json={
                "name": "junk-tracker",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "not a url",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_put_sets_tracker(self, client):
        await _register(client, name="put-set")
        r = await client.put(
            "/software/put-set",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "issue_tracker_uri": "https://linear.app/team/X",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/software/put-set")).json()
        assert body["issue_tracker_uri"] == "https://linear.app/team/X"

    async def test_put_without_tracker_leaves_existing(self, client):
        r0 = await client.post(
            "/software",
            json={
                "name": "put-leave",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.com/before",
                "markdown": "m",
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/software/put-leave",
            json={"version": "1.1.0", "markdown": "m2"},
        )
        assert r.status_code == 200
        body = (await client.get("/software/put-leave")).json()
        assert body["issue_tracker_uri"] == "https://example.com/before"

    async def test_put_explicit_null_clears_tracker(self, client):
        r0 = await client.post(
            "/software",
            json={
                "name": "put-clear",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.com/before",
                "markdown": "m",
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/software/put-clear",
            json={"version": "1.1.0", "markdown": "m2", "issue_tracker_uri": None},
        )
        assert r.status_code == 200
        body = (await client.get("/software/put-clear")).json()
        assert body["issue_tracker_uri"] is None

    async def test_put_rejects_http_scheme(self, client):
        await _register(client, name="put-http")
        r = await client.put(
            "/software/put-http",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "issue_tracker_uri": "http://example.com/issues",
            },
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
        assert len(listing["results"]) == 2
        owners = {c["owner"] for c in listing["results"]}
        assert owners == {"a", "c"}
        # Listing should not include markdown bodies (per #7).
        for entry in listing["results"]:
            assert "markdown" not in entry

    async def test_unknown_software(self, client):
        r = await client.get("/software/missing/contracts")
        assert r.status_code == 404
