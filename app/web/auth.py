"""Authentication utilities for the admin web UI."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

security = HTTPBasic()


def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Authenticate the request using HTTP Basic credentials."""

    settings = get_settings()
    if (
        credentials.username != settings.admin_username
        or credentials.password != settings.admin_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
