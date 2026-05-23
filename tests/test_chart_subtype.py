"""Chart part subtype + chart-side composes pairs (#100, archaedas#9).

Coverage:
- POST /parts succeeds for `chart` subtype.
- GET /templates/chart returns the seeded body.
- chart -composes-> each of the 7 admitted counterparty subtypes
  registers cleanly.
- chart -composes-> pod is rejected (intentional — pods are reached
  transitively via deployment / statefulset / job).
- chart -composes-> non-K8s counterparty (e.g. software, container)
  is rejected.
- Subtype-shift accepts software ↔ chart in both directions.
- List filter `?subtype=chart` narrows correctly.
"""
from __future__ import annotations

import pytest


CHART_COMPOSES_COUNTERPARTIES = (
    "deployment",
    "statefulset",
    "job",
    "service",
    "ingress",
    "secret",
    "configmap",
)

CHART_COMPOSES_INVALID_COUNTERPARTIES = (
    # pods are reached transitively via controllers, not directly.
    "pod",
    # Non-K8s parts never compose under a chart.
    "container",
    "software",
    "compose",
    "image",
)


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


async def _register_composes_contract(client, owner, counterparty):
    return await client.post(
        "/contracts",
        json={
            "owner_part": owner,
            "counterparty_part": counterparty,
            "subtype": "connection",
            "connection_type": "composes",
            "markdown": "m",
        },
    )


class TestRegisterChartSubtype:
    @pytest.mark.asyncio
    async def test_register_chart_part(self, client):
        r = await _register_part(client, "watchervault", "chart")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subtype"] == "chart"
        assert body["name"] == "watchervault"

    @pytest.mark.asyncio
    async def test_chart_template_returns_body(self, client):
        r = await client.get("/templates/chart")
        assert r.status_code == 200, r.text
        assert "text/markdown" in r.headers["content-type"]
        assert "chart" in r.text


class TestChartComposesPairs:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("counterparty_subtype", CHART_COMPOSES_COUNTERPARTIES)
    async def test_chart_composes_admitted_counterparty(
        self, client, counterparty_subtype
    ):
        # Per #100 the chart -composes-> {deployment, statefulset, job,
        # service, ingress, secret, configmap} pair list is admitted.
        await _register_part(client, "wv-chart", "chart")
        await _register_part(
            client, f"wv-{counterparty_subtype}", counterparty_subtype
        )
        r = await _register_composes_contract(
            client, "wv-chart", f"wv-{counterparty_subtype}"
        )
        assert r.status_code == 201, r.text
        assert r.json()["connection_type"] == "composes"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "counterparty_subtype", CHART_COMPOSES_INVALID_COUNTERPARTIES
    )
    async def test_chart_composes_rejected_counterparty(
        self, client, counterparty_subtype
    ):
        await _register_part(client, "wv-chart", "chart")
        await _register_part(
            client, f"wv-bad-{counterparty_subtype}", counterparty_subtype
        )
        r = await _register_composes_contract(
            client, "wv-chart", f"wv-bad-{counterparty_subtype}"
        )
        assert r.status_code == 422


class TestChartSubtypeShift:
    @pytest.mark.asyncio
    async def test_software_can_shift_to_chart(self, client):
        # The realistic "this was registered as a software repo but
        # is actually a Helm release" correction.
        await _register_part(client, "wv", "software")
        prop = await client.post(
            "/parts/wv/subtype-proposals",
            json={"new_subtype": "chart", "rationale": "actually a Helm release"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        accepted = await client.post(
            f"/parts/wv/subtype-proposals/{prop.json()['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accepted.status_code == 200, accepted.text
        detail = await client.get("/parts/wv")
        assert detail.status_code == 200
        assert detail.json()["subtype"] == "chart"

    @pytest.mark.asyncio
    async def test_chart_can_shift_to_software(self, client):
        # The reverse correction — registered as chart but really it's
        # just the chart-source repo, not a deployed release.
        await _register_part(client, "wv-chart-src", "chart")
        prop = await client.post(
            "/parts/wv-chart-src/subtype-proposals",
            json={"new_subtype": "software", "rationale": "source repo, not release"},
            headers={"X-Actor": "alice"},
        )
        assert prop.status_code == 201, prop.text
        accepted = await client.post(
            f"/parts/wv-chart-src/subtype-proposals/"
            f"{prop.json()['proposal_id']}/accept",
            headers={"X-Actor": "bob"},
        )
        assert accepted.status_code == 200, accepted.text


class TestListFilterByChart:
    @pytest.mark.asyncio
    async def test_filter_by_chart_subtype(self, client):
        await _register_part(client, "wv-c1", "chart")
        await _register_part(client, "wv-c2", "chart")
        await _register_part(client, "wv-software", "software")
        r = await client.get("/parts?subtype=chart")
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert {p["subtype"] for p in results} == {"chart"}
        assert {p["name"] for p in results} == {"wv-c1", "wv-c2"}
