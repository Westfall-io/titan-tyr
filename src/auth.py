from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Placeholder shared password. Real auth lands in a future capability update;
# do not promote this to a config value (see DESIGN.md → Configuration).
PASSWORD = "sysmlv2"

_bearer = HTTPBearer(auto_error=False)


def require_password(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if credentials is None or credentials.credentials != PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
