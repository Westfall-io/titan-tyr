"""Project tagging on parts and contracts (#44)."""
from __future__ import annotations


async def _create_project(client, name="payments", description=None):
    body = {"name": name}
    if description is not None:
        body["description"] = description
    r = await client.post("/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _register_part(
    client, name, subtype="software", project=None, **extras
):
    body = {
        "name": name,
        "subtype": subtype,
        "repo_uri": "u",
        "markdown": "m",
        **extras,
    }
    if project is not None:
        body["project"] = project
    r = await client.post("/parts", json=body)
    return r


async def _register_contract(
    client,
    owner,
    counterparty,
    subtype="interaction",
    connection_type=None,
    project=None,
    version="1.0.0",
):
    body = {
        "owner_part": owner,
        "counterparty_part": counterparty,
        "subtype": subtype,
        "markdown": "m",
        "version": version,
    }
    if connection_type is not None:
        body["connection_type"] = connection_type
    if project is not None:
        body["project"] = project
    r = await client.post("/contracts", json=body)
    return r


class TestProjectsCRUD:
    async def test_create_minimal(self, client):
        r = await client.post("/projects", json={"name": "alpha"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "alpha"
        assert body["description"] is None

    async def test_create_with_description(self, client):
        body = await _create_project(client, "alpha", "the WatcherVault project")
        assert body["description"] == "the WatcherVault project"

    async def test_duplicate_name_rejected(self, client):
        await _create_project(client, "alpha")
        r = await client.post("/projects", json={"name": "alpha"})
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]

    async def test_slug_validation_rejects_uppercase(self, client):
        r = await client.post("/projects", json={"name": "Alpha"})
        assert r.status_code == 422

    async def test_slug_validation_rejects_dots(self, client):
        r = await client.post("/projects", json={"name": "alpha.beta"})
        assert r.status_code == 422

    async def test_slug_validation_rejects_leading_hyphen(self, client):
        r = await client.post("/projects", json={"name": "-alpha"})
        assert r.status_code == 422

    async def test_get_unknown_project_404(self, client):
        r = await client.get("/projects/ghost")
        assert r.status_code == 404

    async def test_get_returns_counts(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "p1", project="alpha")
        await _register_part(client, "p2", project="alpha")
        await _register_part(client, "p3", project="alpha", subtype="container")
        await _register_contract(client, "p1", "p2", project="alpha")
        r = await client.get("/projects/alpha")
        assert r.status_code == 200
        body = r.json()
        assert body["part_count"] == 3
        assert body["contract_count"] == 1

    async def test_list_returns_all(self, client):
        await _create_project(client, "alpha")
        await _create_project(client, "beta")
        r = await client.get("/projects")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["results"]]
        assert set(names) == {"alpha", "beta"}

    async def test_update_description(self, client):
        await _create_project(client, "alpha", "v1")
        r = await client.put("/projects/alpha", json={"description": "v2"})
        assert r.status_code == 200
        assert r.json()["description"] == "v2"

    async def test_update_can_clear_description(self, client):
        await _create_project(client, "alpha", "v1")
        r = await client.put("/projects/alpha", json={"description": None})
        assert r.status_code == 200
        assert r.json()["description"] is None

    async def test_actor_recorded_on_create(self, client):
        r = await client.post(
            "/projects",
            json={"name": "alpha"},
            headers={"X-Actor": "alice@example.com"},
        )
        assert r.status_code == 201
        assert r.json()["created_by_actor"] == "alice@example.com"


class TestPartProjectTagging:
    async def test_register_with_project(self, client):
        await _create_project(client, "alpha")
        r = await _register_part(client, "p1", project="alpha")
        assert r.status_code == 201, r.text
        # Detail surfaces the project
        d = await client.get("/parts/p1")
        assert d.status_code == 200
        assert d.json()["project"] == "alpha"

    async def test_register_without_project_is_unprojected(self, client):
        r = await _register_part(client, "p1")
        assert r.status_code == 201, r.text
        d = await client.get("/parts/p1")
        assert d.json()["project"] is None

    async def test_register_with_unknown_project_rejected(self, client):
        r = await _register_part(client, "p1", project="ghost")
        assert r.status_code == 422
        assert "ghost" in r.json()["detail"]

    async def test_register_with_invalid_project_slug_rejected(self, client):
        r = await _register_part(client, "p1", project="Bad.Slug")
        assert r.status_code == 422

    async def test_put_reassigns_project(self, client):
        await _create_project(client, "alpha")
        await _create_project(client, "beta")
        await _register_part(client, "p1", project="alpha")
        r = await client.put(
            "/parts/p1",
            json={"markdown": "m2", "version": "1.1.0", "project": "beta"},
        )
        assert r.status_code == 200, r.text
        d = await client.get("/parts/p1")
        assert d.json()["project"] == "beta"

    async def test_put_clears_project_with_explicit_null(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "p1", project="alpha")
        r = await client.put(
            "/parts/p1",
            json={"markdown": "m2", "version": "1.1.0", "project": None},
        )
        assert r.status_code == 200, r.text
        d = await client.get("/parts/p1")
        assert d.json()["project"] is None

    async def test_put_omitting_project_leaves_unchanged(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "p1", project="alpha")
        r = await client.put(
            "/parts/p1", json={"markdown": "m2", "version": "1.1.0"}
        )
        assert r.status_code == 200
        d = await client.get("/parts/p1")
        assert d.json()["project"] == "alpha"


class TestContractProjectTagging:
    async def test_register_with_project(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "a", project="alpha")
        await _register_part(client, "b", project="alpha")
        r = await _register_contract(client, "a", "b", project="alpha")
        assert r.status_code == 201, r.text
        assert r.json()["project"] == "alpha"

    async def test_cross_project_contract_allowed(self, client):
        # Owner in alpha, counterparty in beta, contract tagged alpha.
        # Permitted by design.
        await _create_project(client, "alpha")
        await _create_project(client, "beta")
        await _register_part(client, "a", project="alpha")
        await _register_part(client, "b", project="beta")
        r = await _register_contract(client, "a", "b", project="alpha")
        assert r.status_code == 201, r.text
        assert r.json()["project"] == "alpha"

    async def test_register_with_unknown_project_rejected(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        r = await _register_contract(client, "a", "b", project="ghost")
        assert r.status_code == 422


class TestListFilter:
    async def test_filter_parts_by_project(self, client):
        await _create_project(client, "alpha")
        await _create_project(client, "beta")
        await _register_part(client, "a-1", project="alpha")
        await _register_part(client, "a-2", project="alpha")
        await _register_part(client, "b-1", project="beta")
        await _register_part(client, "u-1")  # unprojected

        r = await client.get("/parts?project=alpha")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["results"]]
        assert set(names) == {"a-1", "a-2"}

    async def test_filter_parts_unprojected_sentinel(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "a-1", project="alpha")
        await _register_part(client, "u-1")
        await _register_part(client, "u-2")

        r = await client.get("/parts?project=__none__")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["results"]]
        assert set(names) == {"u-1", "u-2"}

    async def test_filter_parts_unknown_project_rejected(self, client):
        r = await client.get("/parts?project=ghost")
        assert r.status_code == 422

    async def test_no_filter_returns_all(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "a-1", project="alpha")
        await _register_part(client, "u-1")

        r = await client.get("/parts")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["results"]]
        assert set(names) == {"a-1", "u-1"}

    async def test_filter_contracts_by_project(self, client):
        await _create_project(client, "alpha")
        await _create_project(client, "beta")
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "c")
        await _register_contract(client, "a", "b", project="alpha")
        await _register_contract(client, "b", "c", project="beta")

        r = await client.get("/contracts?project=alpha")
        assert r.status_code == 200
        rows = r.json()["results"]
        assert len(rows) == 1
        assert rows[0]["project"] == "alpha"
        assert {rows[0]["owner"], rows[0]["counterparty"]} == {"a", "b"}

    async def test_filter_contracts_unprojected_sentinel(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "c")
        await _register_contract(client, "a", "b", project="alpha")
        await _register_contract(client, "b", "c")  # unprojected

        r = await client.get("/contracts?project=__none__")
        assert r.status_code == 200
        rows = r.json()["results"]
        assert len(rows) == 1
        assert rows[0]["project"] is None

    async def test_filter_contracts_unknown_project_rejected(self, client):
        r = await client.get("/contracts?project=ghost")
        assert r.status_code == 422

    async def test_part_filter_combinable_with_subtype(self, client):
        await _create_project(client, "alpha")
        await _register_part(client, "a-1", project="alpha", subtype="software")
        await _register_part(client, "a-2", project="alpha", subtype="container")
        await _register_part(client, "b-1", subtype="software")  # unprojected

        r = await client.get("/parts?project=alpha&subtype=software")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["results"]]
        assert names == ["a-1"]
