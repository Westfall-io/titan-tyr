from fastapi import FastAPI

from src.routers import contracts, proposals, software, templates


def create_app() -> FastAPI:
    app = FastAPI(
        title="titan-tyr",
        description="WatcherVault REST API — software + interface contracts as a versioned graph.",
        version="0.1.0",
    )
    app.include_router(templates.router)
    app.include_router(software.router)
    app.include_router(contracts.router)
    app.include_router(proposals.router)
    return app


app = create_app()
