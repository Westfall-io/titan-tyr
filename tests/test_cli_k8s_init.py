"""src.cli k8s-init-token subcommand (#89).

Mocks the HTTP layer so tests don't need a running API or a K8s
cluster. Verifies the four branches of the init flow:

1. Existing token + probe-success → reuse, no issuance, no patch.
2. Existing token + probe-fail   → issue new + patch + handoff.
3. Missing token file            → issue new + patch + handoff.
4. Missing admin token file      → clear error, exit 2.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src import cli


@pytest.fixture
def tmpdirs(tmp_path: Path):
    """Three mount-point dirs, mimicking what the K8s pod spec creates."""
    admin = tmp_path / "admin"
    ui = tmp_path / "ui-secret"
    handoff = tmp_path / "handoff"
    for d in (admin, ui, handoff):
        d.mkdir()
    return {
        "admin_file": admin / "TITAN_TYR_TOKEN",
        "ui_file": ui / "TITAN_TYR_TOKEN",
        "handoff_file": handoff / "TITAN_TYR_TOKEN",
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TITAN_TYR_URL", "http://test")
    monkeypatch.setenv("POD_NAMESPACE", "default")


def _argv(tmpdirs):
    return [
        "k8s-init-token",
        "--actor", "titan-mimiron-spa",
        "--description", "test",
        "--scopes", "read",
        "--ui-secret", "ui-secret",
        "--admin-token-file", str(tmpdirs["admin_file"]),
        "--existing-token-file", str(tmpdirs["ui_file"]),
        "--handoff-file", str(tmpdirs["handoff_file"]),
    ]


class TestProbeSuccess:
    def test_existing_token_reused(self, env, tmpdirs):
        """Existing token + 200 probe → no issue, no patch, handoff matches."""
        tmpdirs["ui_file"].write_text("old-plaintext")

        # _http_request is the single HTTP boundary; only the probe is hit.
        calls = []

        def fake_http(url, **kw):
            calls.append((url, kw.get("method", "GET")))
            return (200, b'{"results":[]}')

        with patch.object(cli, "_http_request", side_effect=fake_http):
            rc = cli.main(_argv(tmpdirs))

        assert rc == 0
        assert tmpdirs["handoff_file"].read_text() == "old-plaintext"
        # Only the probe should run; no POST to /auth-tokens, no PATCH.
        assert calls == [("http://test/parts?limit=1", "GET")]


class TestIssueAndPatch:
    def test_existing_fails_probe_issues_fresh(self, env, tmpdirs, monkeypatch):
        tmpdirs["ui_file"].write_text("stale-plaintext")
        tmpdirs["admin_file"].write_text("admin-bearer")

        # Pretend we're inside a Pod: provide the SA token + CA path.
        sa_dir = tmpdirs["admin_file"].parent.parent / "sa"
        sa_dir.mkdir()
        (sa_dir / "token").write_text("sa-token")
        (sa_dir / "ca.crt").write_text("---ca---")
        monkeypatch.setattr(cli, "_SA_TOKEN_PATH", str(sa_dir / "token"))
        monkeypatch.setattr(cli, "_SA_CA_PATH", str(sa_dir / "ca.crt"))

        # Sequence: probe (401), POST /auth-tokens (201), PATCH Secret (200).
        responses = iter([
            (401, b'{"detail":"revoked"}'),
            (201, json.dumps({"token": "fresh-plaintext"}).encode()),
            (200, b"{}"),
        ])
        observed = []

        def fake_http(url, **kw):
            observed.append((url, kw.get("method", "GET"), kw.get("headers", {})))
            return next(responses)

        with patch.object(cli, "_http_request", side_effect=fake_http):
            rc = cli.main(_argv(tmpdirs))

        assert rc == 0
        assert tmpdirs["handoff_file"].read_text() == "fresh-plaintext"

        # Three calls: probe, issue, patch.
        assert len(observed) == 3
        assert observed[0][:2] == ("http://test/parts?limit=1", "GET")
        assert observed[1][:2] == ("http://test/auth-tokens", "POST")
        assert observed[1][2]["Authorization"] == "Bearer admin-bearer"
        assert observed[2][1] == "PATCH"
        assert "/api/v1/namespaces/default/secrets/ui-secret" in observed[2][0]
        assert observed[2][2]["Authorization"] == "Bearer sa-token"

    def test_no_existing_token_issues_fresh(self, env, tmpdirs, monkeypatch):
        # ui_file does not exist on first deploy.
        tmpdirs["admin_file"].write_text("admin-bearer")

        sa_dir = tmpdirs["admin_file"].parent.parent / "sa"
        sa_dir.mkdir()
        (sa_dir / "token").write_text("sa-token")
        (sa_dir / "ca.crt").write_text("---ca---")
        monkeypatch.setattr(cli, "_SA_TOKEN_PATH", str(sa_dir / "token"))
        monkeypatch.setattr(cli, "_SA_CA_PATH", str(sa_dir / "ca.crt"))

        responses = iter([
            (201, json.dumps({"token": "first-deploy-plaintext"}).encode()),
            (200, b"{}"),
        ])

        with patch.object(cli, "_http_request", side_effect=lambda *a, **k: next(responses)):
            rc = cli.main(_argv(tmpdirs))

        assert rc == 0
        assert tmpdirs["handoff_file"].read_text() == "first-deploy-plaintext"

    def test_secret_patch_encodes_plaintext_base64(
        self, env, tmpdirs, monkeypatch
    ):
        tmpdirs["admin_file"].write_text("admin-bearer")
        sa_dir = tmpdirs["admin_file"].parent.parent / "sa"
        sa_dir.mkdir()
        (sa_dir / "token").write_text("sa-token")
        (sa_dir / "ca.crt").write_text("---ca---")
        monkeypatch.setattr(cli, "_SA_TOKEN_PATH", str(sa_dir / "token"))
        monkeypatch.setattr(cli, "_SA_CA_PATH", str(sa_dir / "ca.crt"))

        captured: dict = {}
        responses = iter([
            (201, json.dumps({"token": "patch-test-plaintext"}).encode()),
            (200, b"{}"),
        ])

        def fake_http(url, **kw):
            if kw.get("method") == "PATCH":
                captured["url"] = url
                captured["body"] = kw["data"]
                captured["headers"] = kw["headers"]
            return next(responses)

        with patch.object(cli, "_http_request", side_effect=fake_http):
            rc = cli.main(_argv(tmpdirs))

        assert rc == 0
        body = json.loads(captured["body"])
        assert (
            base64.b64decode(body["data"]["TITAN_TYR_TOKEN"]).decode()
            == "patch-test-plaintext"
        )
        assert (
            captured["headers"]["Content-Type"]
            == "application/strategic-merge-patch+json"
        )


class TestErrorPaths:
    def test_missing_admin_token_file(self, env, tmpdirs, capsys):
        # Existing token is missing AND admin token file is absent.
        rc = cli.main(_argv(tmpdirs))
        assert rc == 2
        err = capsys.readouterr().err
        assert "admin token file" in err
        assert "issue-token" in err

    def test_missing_titan_tyr_url(self, tmpdirs, capsys, monkeypatch):
        monkeypatch.delenv("TITAN_TYR_URL", raising=False)
        monkeypatch.setenv("POD_NAMESPACE", "default")
        rc = cli.main(_argv(tmpdirs))
        assert rc == 2
        assert "TITAN_TYR_URL" in capsys.readouterr().err

    def test_missing_pod_namespace(self, tmpdirs, capsys, monkeypatch):
        monkeypatch.setenv("TITAN_TYR_URL", "http://test")
        monkeypatch.delenv("POD_NAMESPACE", raising=False)
        rc = cli.main(_argv(tmpdirs))
        assert rc == 2
        assert "POD_NAMESPACE" in capsys.readouterr().err

    def test_unknown_scope_rejected(self, env, tmpdirs, capsys):
        argv = _argv(tmpdirs)
        # Replace the value at index after "--scopes".
        i = argv.index("--scopes")
        argv[i + 1] = "delete-everything"
        rc = cli.main(argv)
        assert rc == 2
        assert "unknown scope" in capsys.readouterr().err
