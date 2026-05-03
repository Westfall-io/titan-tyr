from __future__ import annotations

import asyncio


async def _register_part(client, name, repo="https://example.com/r"):
    r = await client.post(
        "/parts",
        json={"name": name, "subtype": "software", "repo_uri": repo, "markdown": f"# {name}"},
    )
    assert r.status_code == 201, r.text


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
    return r.json()


class TestSoftwareList:
    async def test_empty(self, client):
        r = await client.get("/parts")
        assert r.status_code == 200
        body = r.json()
        assert body["results"] == []
        assert body["next"] is None

    async def test_single_page(self, client):
        for name in ("svc-a", "svc-b", "svc-c"):
            await _register_part(client, name)
        r = await client.get("/parts")
        assert r.status_code == 200
        body = r.json()
        names = {item["name"] for item in body["results"]}
        assert names == {"svc-a", "svc-b", "svc-c"}
        assert body["next"] is None
        for item in body["results"]:
            assert "markdown" not in item
            assert "version" in item
            assert "updated_at" in item

    async def test_paginates_with_cursor(self, client):
        # Register five with small delays to ensure distinct updated_at values.
        for name in ("p1", "p2", "p3", "p4", "p5"):
            await _register_part(client, name)
            await asyncio.sleep(0.01)
        page1 = (await client.get("/parts", params={"limit": 2})).json()
        assert len(page1["results"]) == 2
        assert page1["next"] is not None

        page2 = (await client.get("/parts", params={"limit": 2, "after": page1["next"]})).json()
        assert len(page2["results"]) == 2
        assert page2["next"] is not None

        page3 = (await client.get("/parts", params={"limit": 2, "after": page2["next"]})).json()
        assert len(page3["results"]) == 1
        assert page3["next"] is None

        seen = [it["name"] for page in (page1, page2, page3) for it in page["results"]]
        assert set(seen) == {"p1", "p2", "p3", "p4", "p5"}
        assert len(seen) == len(set(seen))  # no duplicates across pages

    async def test_invalid_cursor_rejected(self, client):
        r = await client.get("/parts", params={"after": "not-base64-json"})
        assert r.status_code == 422

    async def test_limit_out_of_range(self, client):
        r = await client.get("/parts", params={"limit": 0})
        assert r.status_code == 422
        r = await client.get("/parts", params={"limit": 101})
        assert r.status_code == 422


class TestContractListMode:
    async def test_empty(self, client):
        r = await client.get("/contracts")
        assert r.status_code == 200
        body = r.json()
        assert body["results"] == []
        assert body["next"] is None

    async def test_single_page(self, client):
        await _register_part(client, "a")
        await _register_part(client, "b")
        await _register_part(client, "c")
        await _register_contract(client, "a", "b")
        await _register_contract(client, "b", "c")

        r = await client.get("/contracts")
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 2
        for entry in body["results"]:
            assert "markdown" not in entry
            assert {"contract_id", "owner", "counterparty", "version", "updated_at"} <= set(entry)
        assert body["next"] is None

    async def test_paginates(self, client):
        # Make 4 software so we can register multiple contracts.
        names = ["x1", "x2", "x3", "x4", "x5"]
        for n in names:
            await _register_part(client, n)
        # Ring of contracts: x1->x2, x2->x3, x3->x4, x4->x5
        for i in range(len(names) - 1):
            await _register_contract(client, names[i], names[i + 1])
            await asyncio.sleep(0.01)

        page1 = (await client.get("/contracts", params={"limit": 2})).json()
        assert len(page1["results"]) == 2
        assert page1["next"] is not None
        page2 = (await client.get("/contracts", params={"limit": 2, "after": page1["next"]})).json()
        assert len(page2["results"]) == 2
        assert page2["next"] is None  # 4 total contracts, 2+2 exhausts

    async def test_half_filter_rejected(self, client):
        r = await client.get("/contracts", params={"owner": "a"})
        assert r.status_code == 422
        r = await client.get("/contracts", params={"counterparty": "b"})
        assert r.status_code == 422

    async def test_search_mode_unchanged(self, client):
        # Both filters present → search mode (with markdown), unchanged behaviour.
        await _register_part(client, "s1")
        await _register_part(client, "s2")
        await _register_contract(client, "s1", "s2", markdown="hello")
        r = await client.get("/contracts", params={"owner": "s1", "counterparty": "s2"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["markdown"] == "hello"


class TestSoftwareContractsListPagination:
    async def test_paginated(self, client):
        await _register_part(client, "hub")
        for spoke in ("sp1", "sp2", "sp3"):
            await _register_part(client, spoke)
            await _register_contract(client, "hub", spoke)
            await asyncio.sleep(0.01)
        page1 = (await client.get("/parts/hub/contracts", params={"limit": 2})).json()
        assert page1["part"] == "hub"
        assert len(page1["results"]) == 2
        assert page1["next"] is not None
        page2 = (
            await client.get("/parts/hub/contracts", params={"limit": 2, "after": page1["next"]})
        ).json()
        assert len(page2["results"]) == 1
        assert page2["next"] is None
