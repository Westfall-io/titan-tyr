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

    async def test_binding_owner_must_be_container_or_pod(self, client):
        # Software → software with subtype=binding is rejected. The
        # owner-side rule was relaxed in #36 from container-only to
        # {container, pod}; software remains invalid.
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
        detail = r.json()["detail"]
        assert "container" in detail
        assert "pod" in detail

    async def test_register_binding_pod_to_software(self, client):
        # Pod → software is the K8s sibling of container → software.
        # Both arms are valid binding owners after #36.
        await _register_part(client, "payments-service", subtype="software")
        await _register_part(client, "payments-pod", subtype="pod")
        body = await _new_contract(
            client,
            owner="payments-pod",
            counterparty="payments-service",
            subtype="binding",
        )
        assert body["subtype"] == "binding"
        assert body["owner"] == "payments-pod"
        assert body["counterparty"] == "payments-service"

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


class TestConnectionSubtype:
    """Connection contracts (#32): structural binding with no data flow.

    Six labels distinguish the kinds of structural binding. Five
    (`depends-on`, `submodule`, `builds-from`, `instantiates`,
    `runs`) work today; only `member-of` references a Part subtype
    (`compose`) that isn't implemented yet — it rejects at
    registration with a 'not yet implemented' error rather than
    silently 404'ing on the part lookup.
    """

    async def test_register_depends_on_container_to_container(self, client):
        await _register_part(client, "c1", subtype="container")
        await _register_part(client, "c2", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "c1",
                "counterparty_part": "c2",
                "subtype": "connection",
                "connection_type": "depends-on",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subtype"] == "connection"
        assert body["connection_type"] == "depends-on"

    async def test_register_submodule_software_to_software(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "connection",
                "connection_type": "submodule",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "submodule"

    async def test_connection_type_required_when_subtype_connection(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "connection",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "connection_type" in r.json()["detail"]

    async def test_connection_type_rejected_when_subtype_not_connection(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "interaction",
                "connection_type": "submodule",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "only valid when subtype" in r.json()["detail"]

    async def test_unknown_connection_type_rejected(self, client):
        await _register_pair(client)
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "connection",
                "connection_type": "nonsense",
                "markdown": "m",
            },
        )
        assert r.status_code == 422

    async def test_depends_on_owner_must_be_container(self, client):
        # Software → container with depends-on is rejected.
        await _register_part(client, "a", subtype="software")
        await _register_part(client, "c", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "c",
                "subtype": "connection",
                "connection_type": "depends-on",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "container" in r.json()["detail"]

    async def test_submodule_owner_must_be_software(self, client):
        # Container → software with submodule is rejected.
        await _register_part(client, "c", subtype="container")
        await _register_part(client, "s", subtype="software")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "c",
                "counterparty_part": "s",
                "subtype": "connection",
                "connection_type": "submodule",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "software" in r.json()["detail"]

    async def test_builds_from_software_to_image(self, client):
        # `builds-from` is software → image. Now implemented (#35).
        await _register_part(client, "payments-service", subtype="software")
        await _register_part(client, "payments-image", subtype="image")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-service",
                "counterparty_part": "payments-image",
                "subtype": "connection",
                "connection_type": "builds-from",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "builds-from"

    async def test_builds_from_owner_must_be_software(self, client):
        # Image → image with builds-from is rejected.
        await _register_part(client, "img1", subtype="image")
        await _register_part(client, "img2", subtype="image")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "img1",
                "counterparty_part": "img2",
                "subtype": "connection",
                "connection_type": "builds-from",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "software" in r.json()["detail"]

    async def test_builds_from_counterparty_must_be_image(self, client):
        # Software → software with builds-from is rejected.
        await _register_part(client, "repo", subtype="software")
        await _register_part(client, "other", subtype="software")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "repo",
                "counterparty_part": "other",
                "subtype": "connection",
                "connection_type": "builds-from",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "image" in r.json()["detail"]

    async def test_instantiates_image_to_container(self, client):
        # `instantiates` is image → container (or pod, deferred). The
        # container arm works today.
        await _register_part(client, "payments-image", subtype="image")
        await _register_part(client, "payments-prod", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-image",
                "counterparty_part": "payments-prod",
                "subtype": "connection",
                "connection_type": "instantiates",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "instantiates"

    async def test_instantiates_owner_must_be_image(self, client):
        # Software → container with instantiates is rejected.
        await _register_part(client, "svc", subtype="software")
        await _register_part(client, "ctr", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "svc",
                "counterparty_part": "ctr",
                "subtype": "connection",
                "connection_type": "instantiates",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        assert "image" in r.json()["detail"]

    async def test_instantiates_image_to_pod(self, client):
        # The pod arm of instantiates was unblocked by #36.
        await _register_part(client, "payments-image", subtype="image")
        await _register_part(client, "payments-pod", subtype="pod")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-image",
                "counterparty_part": "payments-pod",
                "subtype": "connection",
                "connection_type": "instantiates",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "instantiates"

    async def test_runs_container_to_software(self, client):
        # The container arm of runs works today.
        await _register_part(client, "payments-service", subtype="software")
        await _register_part(client, "payments-prod", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-prod",
                "counterparty_part": "payments-service",
                "subtype": "connection",
                "connection_type": "runs",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "runs"

    async def test_runs_pod_to_software(self, client):
        # The pod arm of runs was unblocked by #36.
        await _register_part(client, "payments-service", subtype="software")
        await _register_part(client, "payments-pod", subtype="pod")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "payments-pod",
                "counterparty_part": "payments-service",
                "subtype": "connection",
                "connection_type": "runs",
                "markdown": "m",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "runs"

    async def test_runs_owner_must_be_runtime(self, client):
        # Software → software with runs is rejected; owner must be a
        # container or pod (the two implemented runtime subtypes).
        await _register_part(client, "a", subtype="software")
        await _register_part(client, "b", subtype="software")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "connection",
                "connection_type": "runs",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "container" in detail
        assert "pod" in detail

    async def test_member_of_rejected_compose_not_implemented(self, client):
        # `member-of` requires a compose counterparty; compose subtype
        # isn't implemented yet.
        await _register_part(client, "ctr", subtype="container")
        await _register_part(client, "other", subtype="container")
        r = await client.post(
            "/contracts",
            json={
                "owner_part": "ctr",
                "counterparty_part": "other",
                "subtype": "connection",
                "connection_type": "member-of",
                "markdown": "m",
            },
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "compose" in detail
        assert "not yet implemented" in detail

    async def test_connection_type_returned_on_get(self, client):
        await _register_part(client, "c1", subtype="container")
        await _register_part(client, "c2", subtype="container")
        body = await _register_connection_depends_on(client, "c1", "c2")
        r = await client.get(f"/contracts/{body['contract_id']}")
        assert r.status_code == 200
        assert r.json()["connection_type"] == "depends-on"

    async def test_connection_type_returned_on_search(self, client):
        await _register_part(client, "c1", subtype="container")
        await _register_part(client, "c2", subtype="container")
        await _register_connection_depends_on(client, "c1", "c2")
        r = await client.get(
            "/contracts", params={"owner": "c1", "counterparty": "c2"}
        )
        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["connection_type"] == "depends-on"

    async def test_connection_type_returned_on_list(self, client):
        await _register_part(client, "c1", subtype="container")
        await _register_part(client, "c2", subtype="container")
        await _register_connection_depends_on(client, "c1", "c2")
        r = await client.get("/contracts")
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["connection_type"] == "depends-on"

    async def test_connection_type_filter(self, client):
        # Two connections of different types; ?connection_type=depends-on
        # returns only the depends-on row.
        for name in ("a", "b"):
            await _register_part(client, name, subtype="software")
        for name in ("c1", "c2"):
            await _register_part(client, name, subtype="container")
        await _register_connection_depends_on(client, "c1", "c2")
        await client.post(
            "/contracts",
            json={
                "owner_part": "a",
                "counterparty_part": "b",
                "subtype": "connection",
                "connection_type": "submodule",
                "markdown": "m",
            },
        )
        r = await client.get(
            "/contracts",
            params={"subtype": "connection", "connection_type": "depends-on"},
        )
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["connection_type"] == "depends-on"

    async def test_connection_type_filter_only_with_subtype_connection(self, client):
        # connection_type filter with subtype=interaction is rejected.
        r = await client.get(
            "/contracts",
            params={"subtype": "interaction", "connection_type": "depends-on"},
        )
        assert r.status_code == 422

    async def test_connection_type_filter_unknown_value_rejected(self, client):
        r = await client.get("/contracts", params={"connection_type": "nonsense"})
        assert r.status_code == 422

    async def test_connection_type_null_for_non_connection(self, client):
        # interaction and binding contracts have connection_type = null.
        await _register_pair(client)
        body = await _new_contract(client, subtype="interaction")
        assert body["connection_type"] is None
        r = await client.get(f"/contracts/{body['contract_id']}")
        assert r.json()["connection_type"] is None


async def _register_connection_depends_on(client, owner, counterparty):
    r = await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": "connection",
            "connection_type": "depends-on",
            "markdown": "m",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
