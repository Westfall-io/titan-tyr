from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routers import contracts, health, proposals, software, templates

try:
    PROJECT_VERSION = _pkg_version("titan-tyr")
except PackageNotFoundError:
    PROJECT_VERSION = "0.0.0+unknown"


def create_app() -> FastAPI:
    app = FastAPI(
        title="titan-tyr",
        description="WatcherVault REST API — software + interface contracts as a versioned graph.",
        version=PROJECT_VERSION,
    )
    # Restrict to digitalforge.app (+ subdomains) for production browser
    # clients, and localhost on any port for local dev. Anything else gets
    # no Access-Control-Allow-Origin header back, so the browser blocks the
    # response. Bearer-token "credentials" travel in the header (not as
    # cookies), so allow_credentials stays False.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^https://(.*\.)?digitalforge\.app$"
            r"|^https?://localhost(:\d+)?$"
        ),
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(templates.router)
    app.include_router(software.router)
    app.include_router(contracts.router)
    app.include_router(proposals.router)
    return app


app = create_app()
