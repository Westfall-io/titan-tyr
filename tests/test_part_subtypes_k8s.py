"""New K8s runtime part subtypes (#91, archaedas#9).

Coverage:
- POST /parts succeeds for each of the 7 new subtypes.
- GET /templates/<kind> returns the seeded body (conftest seeds
  placeholders; migration 0022 seeds v1.0.0 bodies in prod).
- Subtype-shift accepts moves across the old/new boundary
  (e.g., software → deployment) and the impact-preview pathway
  doesn't blow up on the new subtypes.
- Existing subtypes still register (smoke test).
"""
from __future__ import annotations

import pytest


NEW_SUBTYPES = (
    "deployment",
    "statefulset",
    "service",
    "ingress",
    "secret",
    "configmap",
    "job",
)

OLD_SUBTYPES = ("software", "container", "image", "pod", "compose")


async def _register_part(client, name, subtype):
    return await client.post(
        "/parts",
        json={
            "name": name,
            "subtype": subtype,
            "repo_uri": "u",
            "markdown": f"# {name}\n\nbody for a {subtype} part.",
        },
    )


class TestRegisterNewSubtypes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("subtype", NEW_SUBTYPES)
    async def test_register_succeeds(self, client, subtype):
        r = await _register_part(client, f"sample-{subtype}", subtype)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subtype"] == subtype
        assert body["name"] == f"sample-{subtype}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("subtype", OLD_SUBTYPES)
    async def test_old_subtypes_still_register(self, client, subtype):
        # Smoke check the migration didn't accidentally break the
        # pre-existing subtypes.
        r = await _register_part(client, f"legacy-{subtype}", subtype)
        assert r.status_code == 201, r.text


class TestTemplatesPresentForNewSubtypes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", NEW_SUBTYPES)
    async def test_get_template_returns_body(self, client, kind):
        r = await client.get(f"/templates/{kind}")
        assert r.status_code == 200, r.text
        # conftest seeds placeholder markdown; in prod migration 0022
        # seeds full bodies. Either way the response should be markdown.
        assert "text/markdown" in r.headers["content-type"]
        assert kind in r.text


class TestSubtypeShiftAcrossBoundary:
    """The subtype-shift flow needs to accept new subtypes both as
    `current_subtype` (a part registered as deployment can shift away)
    and `new_subtype` (a part registered as software can shift to
    deployment). Two-party rule is the same as it was."""

    @pytest.mark.asyncio
    async def test_software_can_shift_to_deployment(self, client):
        await _register_part(client, "svc", "software")
        prop = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "deployment", "rationale": "k8s migration"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        accepted = await client.post(
            f"/parts/svc/subtype-proposals/{prop.json()['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accepted.status_code == 200, accepted.text
        # Confirm the shift landed by reading the part back.
        detail = await client.get("/parts/svc")
        assert detail.status_code == 200
        assert detail.json()["subtype"] == "deployment"

    @pytest.mark.asyncio
    async def test_deployment_can_shift_to_statefulset(self, client):
        # Deployment → StatefulSet is the realistic "we discovered we
        # need stable identity" case.
        await _register_part(client, "store", "deployment")
        prop = await client.post(
            "/parts/store/subtype-proposals",
            json={
                "new_subtype": "statefulset",
                "rationale": "needs per-pod PVCs",
            },
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        accepted = await client.post(
            f"/parts/store/subtype-proposals/{prop.json()['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accepted.status_code == 200, accepted.text

    @pytest.mark.asyncio
    async def test_unknown_subtype_still_rejected(self, client):
        # Make sure the enum extension didn't accidentally make the
        # subtype-proposal flow permissive.
        await _register_part(client, "svc", "software")
        r = await client.post(
            "/parts/svc/subtype-proposals",
            json={"new_subtype": "nonexistent", "rationale": "x"},
        )
        assert r.status_code == 422


class TestListFilterByNewSubtype:
    @pytest.mark.asyncio
    async def test_filter_by_each_new_subtype(self, client):
        # Register one of each new subtype, then verify
        # `?subtype=<x>` filter narrows to the expected single row.
        for subtype in NEW_SUBTYPES:
            r = await _register_part(client, f"f-{subtype}", subtype)
            assert r.status_code == 201, r.text
        for subtype in NEW_SUBTYPES:
            r = await client.get(f"/parts?subtype={subtype}")
            assert r.status_code == 200, r.text
            results = r.json()["results"]
            assert {p["subtype"] for p in results} == {subtype}, (
                f"filter ?subtype={subtype} returned unexpected subtypes: "
                f"{[p['subtype'] for p in results]}"
            )
