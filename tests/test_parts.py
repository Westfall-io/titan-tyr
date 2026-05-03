import pytest

SAMPLE_MD = "# payments-service\n\nDescribes the payments service."


async def _register(
    client,
    name="payments-service",
    version="1.0.0",
    repo="https://example.com/repo",
    subtype="software",
):
    r = await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": subtype,
            "repo_uri": repo,
            "markdown": SAMPLE_MD,
            "version": version,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestRegister:
    async def test_default_version_is_1_0_0(self, client):
        r = await client.post(
            "/parts",
            json={"name": "x", "subtype": "software", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201
        assert r.json()["version"] == "1.0.0"

    async def test_explicit_initial_version(self, client):
        body = await _register(client, version="0.1.0")
        assert body["version"] == "0.1.0"

    async def test_duplicate_name_conflicts(self, client):
        await _register(client, name="dup")
        r = await client.post(
            "/parts",
            json={"name": "dup", "subtype": "software", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 409

    async def test_prerelease_rejected_on_software(self, client):
        r = await client.post(
            "/parts",
            json={"name": "rc", "subtype": "software", "repo_uri": "u", "markdown": "m", "version": "1.0.0-rc1"},
        )
        assert r.status_code == 422

    async def test_malformed_version_rejected(self, client):
        r = await client.post(
            "/parts",
            json={"name": "bad", "subtype": "software", "repo_uri": "u", "markdown": "m", "version": "1.0"},
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
            "/parts",
            json={"name": name, "subtype": "software", "repo_uri": "u", "markdown": "m"},
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
            "/parts",
            json={"name": name, "subtype": "software", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 422


class TestGet:
    async def test_get_returns_latest(self, client):
        await _register(client, name="g")
        r = await client.get("/parts/g")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "g"
        assert body["version"] == "1.0.0"
        assert body["markdown"] == SAMPLE_MD

    async def test_get_unknown(self, client):
        r = await client.get("/parts/nope")
        assert r.status_code == 404


class TestUpdate:
    async def test_append_new_version(self, client):
        await _register(client, name="u")
        r = await client.put(
            "/parts/u",
            json={"version": "1.1.0", "markdown": "v2"},
        )
        assert r.status_code == 200
        assert r.json()["version"] == "1.1.0"

        latest = (await client.get("/parts/u")).json()
        assert latest["version"] == "1.1.0"
        assert latest["markdown"] == "v2"

    async def test_must_be_strictly_greater(self, client):
        await _register(client, name="lt", version="2.0.0")
        r = await client.put(
            "/parts/lt",
            json={"version": "1.0.0", "markdown": "older"},
        )
        assert r.status_code == 409

    async def test_equal_version_conflicts(self, client):
        await _register(client, name="eq", version="2.0.0")
        r = await client.put(
            "/parts/eq",
            json={"version": "2.0.0", "markdown": "same"},
        )
        assert r.status_code == 409

    async def test_unknown_software(self, client):
        r = await client.put(
            "/parts/missing",
            json={"version": "1.0.0", "markdown": "m"},
        )
        assert r.status_code == 404

    async def test_prerelease_rejected(self, client):
        await _register(client, name="prc")
        r = await client.put(
            "/parts/prc",
            json={"version": "1.1.0-rc1", "markdown": "m"},
        )
        assert r.status_code == 422


class TestRepoUriOnUpdate:
    async def test_put_sets_repo_uri(self, client):
        await _register(client, name="r-set", repo="https://example.com/before")
        r = await client.put(
            "/parts/r-set",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "repo_uri": "https://example.com/after",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/parts/r-set")).json()
        assert body["repo_uri"] == "https://example.com/after"

    async def test_put_without_repo_uri_leaves_existing(self, client):
        await _register(client, name="r-leave", repo="https://example.com/keep")
        r = await client.put(
            "/parts/r-leave",
            json={"version": "1.1.0", "markdown": "m"},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/r-leave")).json()
        assert body["repo_uri"] == "https://example.com/keep"

    async def test_put_explicit_null_rejected(self, client):
        await _register(client, name="r-null")
        r = await client.put(
            "/parts/r-null",
            json={"version": "1.1.0", "markdown": "m", "repo_uri": None},
        )
        assert r.status_code == 422

    async def test_put_empty_string_rejected(self, client):
        await _register(client, name="r-empty")
        r = await client.put(
            "/parts/r-empty",
            json={"version": "1.1.0", "markdown": "m", "repo_uri": ""},
        )
        assert r.status_code == 422

    async def test_put_ssh_form_repo_uri_accepted(self, client):
        await _register(client, name="r-ssh")
        r = await client.put(
            "/parts/r-ssh",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "repo_uri": "git@github.com:example/r-ssh.git",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/parts/r-ssh")).json()
        assert body["repo_uri"] == "git@github.com:example/r-ssh.git"


class TestIssueTrackerUri:
    async def test_register_without_tracker_returns_null(self, client):
        await _register(client, name="no-tracker")
        body = (await client.get("/parts/no-tracker")).json()
        assert body["issue_tracker_uri"] is None

    async def test_register_with_tracker(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "with-tracker", "subtype": "software",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.atlassian.net/browse/PROJ",
                "markdown": "m",
            },
        )
        assert r.status_code == 201
        body = (await client.get("/parts/with-tracker")).json()
        assert body["issue_tracker_uri"] == "https://example.atlassian.net/browse/PROJ"

    async def test_register_rejects_http_scheme(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "http-tracker", "subtype": "software",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "http://example.com/issues",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_register_rejects_garbage(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "junk-tracker", "subtype": "software",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "not a url",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_put_sets_tracker(self, client):
        await _register(client, name="put-set")
        r = await client.put(
            "/parts/put-set",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "issue_tracker_uri": "https://linear.app/team/X",
            },
        )
        assert r.status_code == 200
        body = (await client.get("/parts/put-set")).json()
        assert body["issue_tracker_uri"] == "https://linear.app/team/X"

    async def test_put_without_tracker_leaves_existing(self, client):
        r0 = await client.post(
            "/parts",
            json={
                "name": "put-leave", "subtype": "software",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.com/before",
                "markdown": "m",
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/parts/put-leave",
            json={"version": "1.1.0", "markdown": "m2"},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/put-leave")).json()
        assert body["issue_tracker_uri"] == "https://example.com/before"

    async def test_put_explicit_null_clears_tracker(self, client):
        r0 = await client.post(
            "/parts",
            json={
                "name": "put-clear", "subtype": "software",
                "repo_uri": "https://example.com/repo",
                "issue_tracker_uri": "https://example.com/before",
                "markdown": "m",
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/parts/put-clear",
            json={"version": "1.1.0", "markdown": "m2", "issue_tracker_uri": None},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/put-clear")).json()
        assert body["issue_tracker_uri"] is None

    async def test_put_rejects_http_scheme(self, client):
        await _register(client, name="put-http")
        r = await client.put(
            "/parts/put-http",
            json={
                "version": "1.1.0",
                "markdown": "m",
                "issue_tracker_uri": "http://example.com/issues",
            },
        )
        assert r.status_code == 422


class TestAliases:
    async def test_register_without_aliases_returns_empty_list(self, client):
        await _register(client, name="al-empty")
        body = (await client.get("/parts/al-empty")).json()
        assert body["aliases"] == []

    async def test_register_with_aliases(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-set", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["Front End", "前端", "ui"],
            },
        )
        assert r.status_code == 201, r.text
        body = (await client.get("/parts/al-set")).json()
        assert body["aliases"] == ["Front End", "前端", "ui"]

    async def test_register_dedupes_case_insensitively(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-dup", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["Foo", "foo", "FOO", "bar"],
            },
        )
        assert r.status_code == 201
        body = (await client.get("/parts/al-dup")).json()
        assert body["aliases"] == ["Foo", "bar"]

    async def test_register_strips_whitespace(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-strip", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["  spaced  "],
            },
        )
        assert r.status_code == 201
        body = (await client.get("/parts/al-strip")).json()
        assert body["aliases"] == ["spaced"]

    async def test_register_rejects_empty_alias(self, client):
        r = await client.post(
            "/parts",
            json={"name": "al-mt", "subtype": "software", "repo_uri": "u", "markdown": "m", "aliases": [""]},
        )
        assert r.status_code == 422

    async def test_register_rejects_whitespace_only_alias(self, client):
        r = await client.post(
            "/parts",
            json={"name": "al-ws", "subtype": "software", "repo_uri": "u", "markdown": "m", "aliases": ["   "]},
        )
        assert r.status_code == 422

    async def test_register_rejects_alias_over_128_chars(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-long", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["x" * 129],
            },
        )
        assert r.status_code == 422

    async def test_register_accepts_alias_at_128_chars(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-at-limit", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["x" * 128],
            },
        )
        assert r.status_code == 201

    async def test_register_rejects_newline_in_alias(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-nl", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["a\nb"],
            },
        )
        assert r.status_code == 422

    async def test_register_rejects_control_char_in_alias(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "al-ctrl", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["a\x07b"],
            },
        )
        assert r.status_code == 422

    async def test_collisions_across_software_allowed(self, client):
        r1 = await client.post(
            "/parts",
            json={
                "name": "al-c1", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["frontend"],
            },
        )
        assert r1.status_code == 201
        r2 = await client.post(
            "/parts",
            json={
                "name": "al-c2", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["frontend"],
            },
        )
        assert r2.status_code == 201

    async def test_put_replaces_aliases(self, client):
        await _register(client, name="al-put")
        r = await client.put(
            "/parts/al-put",
            json={"version": "1.1.0", "markdown": "m", "aliases": ["new-one"]},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/al-put")).json()
        assert body["aliases"] == ["new-one"]

    async def test_put_without_aliases_leaves_existing(self, client):
        r0 = await client.post(
            "/parts",
            json={
                "name": "al-keep", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["keepme"],
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/parts/al-keep",
            json={"version": "1.1.0", "markdown": "m2"},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/al-keep")).json()
        assert body["aliases"] == ["keepme"]

    async def test_put_null_clears_aliases(self, client):
        r0 = await client.post(
            "/parts",
            json={
                "name": "al-null", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["a", "b"],
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/parts/al-null",
            json={"version": "1.1.0", "markdown": "m", "aliases": None},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/al-null")).json()
        assert body["aliases"] == []

    async def test_put_empty_list_clears_aliases(self, client):
        r0 = await client.post(
            "/parts",
            json={
                "name": "al-mt-clear", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["a"],
            },
        )
        assert r0.status_code == 201
        r = await client.put(
            "/parts/al-mt-clear",
            json={"version": "1.1.0", "markdown": "m", "aliases": []},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/al-mt-clear")).json()
        assert body["aliases"] == []

    async def test_listing_returns_aliases(self, client):
        await client.post(
            "/parts",
            json={
                "name": "al-list", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["alpha"],
            },
        )
        listing = (await client.get("/parts")).json()
        entry = next(e for e in listing["results"] if e["name"] == "al-list")
        assert entry["aliases"] == ["alpha"]


class TestMatchQuery:
    async def test_match_filters_by_name_substring(self, client):
        await _register(client, name="payments-service")
        await _register(client, name="orders-service")
        await _register(client, name="other")
        r = await client.get("/parts?match=service")
        assert r.status_code == 200
        names = {e["name"] for e in r.json()["results"]}
        assert names == {"payments-service", "orders-service"}

    async def test_match_filters_by_alias_substring(self, client):
        await client.post(
            "/parts",
            json={
                "name": "admin-ui", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["Front End", "operator console"],
            },
        )
        await _register(client, name="other-svc")
        r = await client.get("/parts?match=front")
        assert r.status_code == 200
        names = {e["name"] for e in r.json()["results"]}
        assert names == {"admin-ui"}

    async def test_match_is_case_insensitive(self, client):
        await client.post(
            "/parts",
            json={
                "name": "ci-test", "subtype": "software",
                "repo_uri": "u",
                "markdown": "m",
                "aliases": ["MixedCase"],
            },
        )
        r = await client.get("/parts?match=mixedcase")
        assert r.status_code == 200
        assert len(r.json()["results"]) == 1
        r2 = await client.get("/parts?match=MIXEDCASE")
        assert r2.status_code == 200
        assert len(r2.json()["results"]) == 1

    async def test_match_no_results(self, client):
        await _register(client, name="something")
        r = await client.get("/parts?match=nothingmatches")
        assert r.status_code == 200
        assert r.json()["results"] == []

    async def test_match_escapes_wildcards(self, client):
        # ILIKE % shouldn't act as a wildcard from user input. Register
        # something that doesn't contain a literal %, then verify the search
        # treats it literally.
        await _register(client, name="literal-percent")
        r = await client.get("/parts?match=%25")  # decodes to "%"
        assert r.status_code == 200
        assert r.json()["results"] == []



    async def test_lists_contracts_in_both_directions(self, client):
        await _register(client, name="a")
        await _register(client, name="b")
        await _register(client, name="c")
        r1 = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "ab",
            },
        )
        assert r1.status_code == 201
        r2 = await client.post(
            "/contracts",
            json={
                "owner_part": "c",
                "counterparty_part": "a",
                "subtype": "interaction",
                "markdown": "ca",
            },
        )
        assert r2.status_code == 201

        listing = (await client.get("/parts/a/contracts")).json()
        assert listing["part"] == "a"
        assert len(listing["results"]) == 2
        owners = {c["owner"] for c in listing["results"]}
        assert owners == {"a", "c"}
        # Listing should not include markdown bodies (per #7).
        for entry in listing["results"]:
            assert "markdown" not in entry

    async def test_unknown_part(self, client):
        r = await client.get("/parts/missing/contracts")
        assert r.status_code == 404


class TestSubtype:
    async def test_subtype_required_on_register(self, client):
        r = await client.post(
            "/parts",
            json={"name": "no-subtype", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 422

    async def test_unknown_subtype_rejected(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "bad-subtype",
                "subtype": "compose",  # Compose is deferred per #37
                "repo_uri": "u",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_subtype_returned_on_detail(self, client):
        await _register(client, name="d-soft")
        body = (await client.get("/parts/d-soft")).json()
        assert body["subtype"] == "software"

    async def test_subtype_returned_on_list(self, client):
        await _register(client, name="l-soft")
        listing = (await client.get("/parts")).json()
        entry = next(e for e in listing["results"] if e["name"] == "l-soft")
        assert entry["subtype"] == "software"

    async def test_list_filter_by_subtype(self, client):
        await _register(client, name="f-soft", subtype="software")
        await _register(client, name="f-cont", subtype="container")
        soft_only = (await client.get("/parts?subtype=software")).json()
        names = {e["name"] for e in soft_only["results"]}
        assert "f-soft" in names
        assert "f-cont" not in names

        cont_only = (await client.get("/parts?subtype=container")).json()
        names = {e["name"] for e in cont_only["results"]}
        assert "f-cont" in names
        assert "f-soft" not in names

    async def test_list_filter_unknown_subtype_rejected(self, client):
        r = await client.get("/parts?subtype=compose")
        assert r.status_code == 422

    async def test_subtype_not_mutable_via_put(self, client):
        # PUT body has no subtype field; the part's subtype is structural
        # and cannot be changed by an update. New version, same subtype.
        await _register(client, name="m-soft", subtype="software")
        r = await client.put(
            "/parts/m-soft",
            json={"version": "1.1.0", "markdown": "v2"},
        )
        assert r.status_code == 200
        body = (await client.get("/parts/m-soft")).json()
        assert body["subtype"] == "software"


class TestContainerSubtype:
    async def test_register_container(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "payments-svc-prod",
                "subtype": "container",
                "repo_uri": "https://example.com/repo",
                "markdown": "# payments-svc-prod\n\nProd container.",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subtype"] == "container"

    async def test_container_runs_software_via_contract(self, client):
        # The container ↔ software 'runs' relationship is encoded as a
        # regular contract for now (typed connections are deferred to a
        # follow-up ticket). This test pins that wiring.
        await _register(client, name="payments-svc", subtype="software")
        await client.post(
            "/parts",
            json={
                "name": "payments-svc-prod",
                "subtype": "container",
                "repo_uri": "https://example.com/repo",
                "markdown": "# payments-svc-prod",
            },
        )
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-svc-prod",
                "counterparty_part": "payments-svc",
                "subtype": "binding",
                "markdown": "# runs binding\n\nContainer hosts software at host:port.",
            },
        )
        assert r.status_code == 201


class TestImageSubtype:
    async def test_register_image(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "payments-image",
                "subtype": "image",
                "repo_uri": "https://example.com/repo",
                "markdown": "# payments-image\n\nBuilt artifact.",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subtype"] == "image"

    async def test_list_filter_subtype_image(self, client):
        await _register(client, name="i-soft", subtype="software")
        await client.post(
            "/parts",
            json={
                "name": "i-img",
                "subtype": "image",
                "repo_uri": "u",
                "markdown": "m",
            },
        )
        img_only = (await client.get("/parts?subtype=image")).json()
        names = {e["name"] for e in img_only["results"]}
        assert "i-img" in names
        assert "i-soft" not in names

    async def test_image_chain_software_to_image_to_container(self, client):
        # Full builds-from + instantiates chain: a Software Part builds
        # into an Image Part which instantiates as a Container Part.
        # Both connection arms are unblocked by #35.
        await _register(client, name="payments-service", subtype="software")
        await client.post(
            "/parts",
            json={
                "name": "payments-image",
                "subtype": "image",
                "repo_uri": "u",
                "markdown": "m",
            },
        )
        await client.post(
            "/parts",
            json={
                "name": "payments-prod",
                "subtype": "container",
                "repo_uri": "u",
                "markdown": "m",
            },
        )
        r1 = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-service",
                "counterparty_part": "payments-image",
                "subtype": "connection",
                "connection_type": "builds-from",
                "markdown": "m",
            },
        )
        assert r1.status_code == 201, r1.text
        r2 = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-image",
                "counterparty_part": "payments-prod",
                "subtype": "connection",
                "connection_type": "instantiates",
                "markdown": "m",
            },
        )
        assert r2.status_code == 201, r2.text


class TestPodSubtype:
    async def test_register_pod(self, client):
        r = await client.post(
            "/parts",
            json={
                "name": "payments-pod",
                "subtype": "pod",
                "repo_uri": "https://example.com/repo",
                "markdown": "# payments-pod\n\nK8s pod.",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["subtype"] == "pod"

    async def test_list_filter_subtype_pod(self, client):
        await _register(client, name="p-soft", subtype="software")
        await client.post(
            "/parts",
            json={
                "name": "p-pod",
                "subtype": "pod",
                "repo_uri": "u",
                "markdown": "m",
            },
        )
        pod_only = (await client.get("/parts?subtype=pod")).json()
        names = {e["name"] for e in pod_only["results"]}
        assert "p-pod" in names
        assert "p-soft" not in names
