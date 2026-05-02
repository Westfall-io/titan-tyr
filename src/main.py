from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI

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
    app.include_router(health.router)
    app.include_router(templates.router)
    app.include_router(software.router)
    app.include_router(contracts.router)
    app.include_router(proposals.router)
    return app


app = create_app()
