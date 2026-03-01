from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=True)


class Authenticator:
    def __init__(self) -> None:
        self.mode = os.getenv("AUTH_MODE", "token").strip().lower()

    def dependency(self):
        async def _verify(
            credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        ) -> dict[str, Any]:
            token = credentials.credentials
            if self.mode == "token":
                return self._validate_static_token(token)
            if self.mode == "entra":
                return self._validate_entra_jwt(token)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unsupported AUTH_MODE: {self.mode}",
            )

        return _verify

    @staticmethod
    def _validate_static_token(token: str) -> dict[str, Any]:
        expected = os.getenv("MCP_API_KEY")
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="MCP_API_KEY must be configured when AUTH_MODE=token",
            )
        if token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
            )
        return {"sub": "token-user"}

    @staticmethod
    def _validate_entra_jwt(token: str) -> dict[str, Any]:
        tenant_id = os.getenv("AZURE_TENANT_ID")
        client_id = os.getenv("AZURE_CLIENT_ID")
        if not tenant_id or not client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "AZURE_TENANT_ID and AZURE_CLIENT_ID are required when AUTH_MODE=entra"
                ),
            )

        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        try:
            signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
            return decoded
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Entra token: {exc}",
            ) from exc
