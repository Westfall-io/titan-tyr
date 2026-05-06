from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.cors import resolve_cors_config
from src.routers import (
    agent_actors,
    auth_tokens,
    contracts,
    health,
    parts,
    projects,
    proposals,
    templates,
)

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
    # CORS: env-configurable allow-list (CORS_ALLOWED_ORIGINS), with a
    # source-hardcoded regex (digitalforge.app + subdomains over HTTPS,
    # localhost on any port) as the fallback when nothing is set.
    # Bearer-token "credentials" travel in the header (not as cookies),
    # so allow_credentials stays False.
    cors = resolve_cors_config()
    cors_kwargs: dict = {
        "allow_methods": ["GET", "POST", "PUT"],
        "allow_headers": ["Authorization", "Content-Type"],
    }
    if cors.allow_origins is not None:
        cors_kwargs["allow_origins"] = cors.allow_origins
    if cors.allow_origin_regex is not None:
        cors_kwargs["allow_origin_regex"] = cors.allow_origin_regex
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    app.include_router(health.router)
    app.include_router(templates.router)
    app.include_router(projects.router)
    app.include_router(agent_actors.router)
    app.include_router(auth_tokens.router)
    app.include_router(parts.router)
    app.include_router(contracts.router)
    app.include_router(proposals.router)
    return app


app = create_app()
