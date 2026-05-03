async def _register_pair(client, owner="a", counterparty="b"):
    for name in (owner, counterparty):
        r = await client.post(
            "/parts",
            json={"name": name, "subtype": "software", "repo_uri": "u", "markdown": "m"},
        )
        assert r.status_code == 201, r.text


async def _new_contract(
    client, owner="a", counterparty="b", version="1.0.0", subtype="interaction"
):
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": subtype,
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
            json={"owner_part": "a", "counterparty_part": "a", "subtype": "interaction", "markdown": "m"},
        )
        assert r.status_code == 422

    async def test_unknown_software(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={"owner_part": "a", "counterparty_part": "ghost", "subtype": "interaction", "markdown": "m"},
        )
        assert r.status_code == 404

    async def test_non_slug_owner_rejected(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "Bad Name",
                "counterparty_part": "b",
                "subtype": "interaction",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_non_slug_counterparty_rejected(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "Has.Dot",
                "subtype": "interaction",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_duplicate_pair_conflicts(self, client):
        await _register_pair(client)
        await _new_contract(client)
        r = await client.post(
            "/contracts",
            json={"owner_part": "a", "counterparty_part": "b", "subtype": "interaction", "markdown": "m"},
        )
        assert r.status_code == 409

    async def test_prerelease_rejected_on_initial(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
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
                "/parts", json={"name": n, "subtype": "software", "repo_uri": "u", "markdown": "m"}
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


async def _register_part(client, name, subtype="software"):
    r = await client.post(
        "/parts",
        json={"name": name, "subtype": subtype, "repo_uri": "u", "markdown": "m"},
    )
    assert r.status_code == 201, r.text


class TestContractSubtype:
    async def test_subtype_required(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={"owner_part": "a", "counterparty_part": "b", "markdown": "m"},
        )
        assert r.status_code == 422

    async def test_unknown_subtype_rejected(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "nonsense",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_subtype_returned_on_register(self, client):
        await _register_pair(client)
        body = await _new_contract(client)
        assert body["subtype"] == "interaction"

    async def test_subtype_returned_on_get(self, client):
        await _register_pair(client)
        body = await _new_contract(client)
        r = await client.get(f"/contracts/{body['contract_id']}")
        assert r.status_code == 200
        assert r.json()["subtype"] == "interaction"

    async def test_subtype_returned_on_search(self, client):
        await _register_pair(client)
        await _new_contract(client)
        r = await client.get("/contracts", params={"owner": "a", "counterparty": "b"})
        assert r.status_code == 200
        assert r.json()["results"][0]["subtype"] == "interaction"

    async def test_subtype_returned_on_list(self, client):
        await _register_pair(client)
        await _new_contract(client)
        r = await client.get("/contracts")
        assert r.status_code == 200
        assert r.json()["results"][0]["subtype"] == "interaction"

    async def test_subtype_filter_on_list(self, client):
        # Two interaction contracts + one binding; ?subtype=binding returns only the binding.
        for name in ("a", "b", "c"):
            await _register_part(client, name)
        await _register_part(client, "container-prod", subtype="container")
        await _new_contract(client, owner="a", counterparty="b")
        await _new_contract(client, owner="b", counterparty="c")
        await _new_contract(
            client, owner="container-prod", counterparty="a", subtype="binding"
        )
        r = await client.get("/contracts", params={"subtype": "binding"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["subtype"] == "binding"
        assert results[0]["owner"] == "container-prod"

    async def test_subtype_filter_invalid_rejected(self, client):
        r = await client.get("/contracts", params={"subtype": "nope"})
        assert r.status_code == 422


class TestBindingSubtype:
    async def test_register_binding_container_to_software(self, client):
        await _register_part(client, "payments-service", subtype="software")
        await _register_part(client, "payments-prod", subtype="container")
        body = await _new_contract(
            client,
            owner="payments-prod",
            counterparty="payments-service",
            subtype="binding",
        )
        assert body["subtype"] == "binding"
        assert body["owner"] == "payments-prod"
        assert body["counterparty"] == "payments-service"

    async def test_binding_owner_must_be_container(self, client):
        # Software → software with subtype=binding is rejected.
        await _register_part(client, "a", subtype="software")
        await _register_part(client, "b", subtype="software")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "binding",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "container" in r.json()["detail"]

    async def test_binding_counterparty_must_be_software(self, client):
        # Container → container with subtype=binding is rejected.
        await _register_part(client, "c1", subtype="container")
        await _register_part(client, "c2", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "c1",
                "counterparty_part": "c2",
                "subtype": "binding",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "software" in r.json()["detail"]

    async def test_interaction_accepts_any_pair(self, client):
        # Container → software with subtype=interaction is allowed (interaction
        # has no source/target subtype rules — preserves today's behavior).
        await _register_part(client, "svc", subtype="software")
        await _register_part(client, "ctr", subtype="container")
        body = await _new_contract(
            client, owner="ctr", counterparty="svc", subtype="interaction"
        )
        assert body["subtype"] == "interaction"
