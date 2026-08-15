from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None = None


@lru_cache(maxsize=4)
def get_jwk_client(supabase_url: str) -> PyJWKClient:
    return PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required.")

    token = credentials.credentials
    if settings.auth_mode == "dev":
        try:
            return CurrentUser(id=UUID(token), email="demo@example.com")
        except ValueError as error:
            raise HTTPException(status_code=401, detail="Invalid development token.") from error

    if not settings.supabase_url:
        raise HTTPException(status_code=500, detail="Supabase authentication is not configured.")

    try:
        signing_key = get_jwk_client(settings.supabase_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.jwt_algorithms,
            audience=settings.jwt_audience,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
        )
        return CurrentUser(id=UUID(payload["sub"]), email=payload.get("email"))
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=401, detail="Your session is invalid or expired."
        ) from error
