from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from src.auth import require_password
from src.config import Settings, get_settings

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[Depends(require_password)])


def _read_template(name: str, settings: Settings) -> str:
    path = settings.templates_dir / name
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"Template {name!r} not found on disk")
    return path.read_text(encoding="utf-8")


@router.get("/software", response_class=PlainTextResponse, responses={200: {"content": {"text/markdown": {}}}})
async def get_software_template(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    return PlainTextResponse(_read_template("software.md", settings), media_type="text/markdown")


@router.get("/contract", response_class=PlainTextResponse, responses={200: {"content": {"text/markdown": {}}}})
async def get_contract_template(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    return PlainTextResponse(_read_template("contract.md", settings), media_type="text/markdown")
