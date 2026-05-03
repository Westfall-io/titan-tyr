from tests.conftest import (
    SEED_BINDING_TEMPLATE,
    SEED_CONNECTION_TEMPLATE,
    SEED_CONTAINER_TEMPLATE,
    SEED_IMAGE_TEMPLATE,
    SEED_INTERACTION_TEMPLATE,
    SEED_POD_TEMPLATE,
    SEED_SOFTWARE_TEMPLATE,
)


class TestGetTemplate:
    async def test_software_template(self, client):
        r = await client.get("/templates/software")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_SOFTWARE_TEMPLATE

    async def test_interaction_template(self, client):
        r = await client.get("/templates/interaction")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_INTERACTION_TEMPLATE

    async def test_container_template(self, client):
        r = await client.get("/templates/container")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_CONTAINER_TEMPLATE

    async def test_image_template(self, client):
        r = await client.get("/templates/image")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_IMAGE_TEMPLATE

    async def test_pod_template(self, client):
        r = await client.get("/templates/pod")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_POD_TEMPLATE

    async def test_binding_template(self, client):
        r = await client.get("/templates/binding")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_BINDING_TEMPLATE

    async def test_connection_template(self, client):
        r = await client.get("/templates/connection")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text == SEED_CONNECTION_TEMPLATE

    async def test_unknown_kind_404(self, client):
        r = await client.get("/templates/nonexistent")
        assert r.status_code == 404


async def _propose(client, kind, version, markdown="proposal body"):
    return await client.post(
        f"/templates/{kind}/proposals",
        json={"version": version, "markdown": markdown},
    )


async def _accept(client, kind, version):
    return await client.post(f"/templates/{kind}/proposals/{version}/accept")


class TestProposeTemplate:
    async def test_create_stable(self, client):
        r = await _propose(client, "software", "1.1.0")
        assert r.status_code == 201
        body = r.json()
        assert body["kind"] == "software"
        assert body["version"] == "1.1.0"
        assert body["status"] == "proposal"

    async def test_create_rc(self, client):
        r = await _propose(client, "software", "1.1.0-rc1")
        assert r.status_code == 201
        assert r.json()["version"] == "1.1.0-rc1"

    async def test_must_be_strictly_greater_than_active(self, client):
        r = await _propose(client, "software", "1.0.0")
        assert r.status_code == 409

    async def test_rc_chain(self, client):
        for v in ["1.1.0-rc1", "1.1.0-rc2", "1.1.0"]:
            r = await _propose(client, "software", v)
            assert r.status_code == 201, (v, r.text)

    async def test_unknown_kind(self, client):
        r = await _propose(client, "nonexistent", "1.1.0")
        assert r.status_code == 404

    async def test_malformed_version(self, client):
        r = await _propose(client, "software", "not-a-version")
        assert r.status_code == 422


class TestListProposals:
    async def test_lists_only_newer_than_active(self, client):
        await _propose(client, "software", "1.1.0-rc1")
        await _propose(client, "software", "1.1.0")
        await _propose(client, "software", "2.0.0")
        r = await client.get("/templates/software/proposals")
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "software"
        assert body["active_version"] == "1.0.0"
        versions = [p["version"] for p in body["proposals"]]
        assert versions == ["1.1.0-rc1", "1.1.0", "2.0.0"]

    async def test_empty_listing(self, client):
        r = await client.get("/templates/interaction/proposals")
        assert r.status_code == 200
        assert r.json()["proposals"] == []

    async def test_unknown_kind(self, client):
        r = await client.get("/templates/nonexistent/proposals")
        assert r.status_code == 404


class TestAcceptProposal:
    async def test_accept_stable_in_place(self, client):
        await _propose(client, "software", "1.1.0", markdown="new body")
        r = await _accept(client, "software", "1.1.0")
        assert r.status_code == 200
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0"
        assert body["active_version"] == "1.1.0"

        served = (await client.get("/templates/software")).text
        assert served == "new body"

    async def test_accept_rc_creates_stable(self, client):
        await _propose(client, "software", "1.1.0-rc1", markdown="rc1 body")
        await _propose(client, "software", "1.1.0-rc2", markdown="rc2 body")
        r = await _accept(client, "software", "1.1.0-rc2")
        assert r.status_code == 200
        body = r.json()
        assert body["promoted_from_version"] == "1.1.0-rc2"
        assert body["active_version"] == "1.1.0"

        # GET returns the stable version's markdown (copied from rc2).
        served = (await client.get("/templates/software")).text
        assert served == "rc2 body"

        # The earlier rc1 row stays in the database but is now older than
        # active 1.1.0, so it drops out of the proposals listing.
        proposals = (await client.get("/templates/software/proposals")).json()
        assert proposals["active_version"] == "1.1.0"
        assert proposals["proposals"] == []

    async def test_double_accept_rejected(self, client):
        await _propose(client, "software", "1.1.0")
        assert (await _accept(client, "software", "1.1.0")).status_code == 200
        r = await _accept(client, "software", "1.1.0")
        assert r.status_code == 409

    async def test_accept_unknown_proposal(self, client):
        r = await _accept(client, "software", "9.9.9")
        assert r.status_code == 404

    async def test_accept_unknown_kind(self, client):
        r = await _accept(client, "nonexistent", "1.0.0")
        assert r.status_code == 404

    async def test_accept_malformed_version(self, client):
        r = await _accept(client, "software", "not-a-version")
        assert r.status_code == 422
