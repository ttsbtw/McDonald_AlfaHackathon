from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .errors import APIError
from .models import User

password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("unused-password-for-constant-work")
bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        yield session


DB = Annotated[Session, Depends(get_db)]


def unauthorized():
    return APIError(401, "UNAUTHORIZED", "Требуется действующий вход.", headers={"WWW-Authenticate": "Bearer"})


def create_token(user, settings):
    now = datetime.now(timezone.utc)
    lifetime = settings.token_lifetime_minutes * 60
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(seconds=lifetime),
               "iss": "mcdonald-backend", "aud": "credit-cabinet"}
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": lifetime}


def get_user(request: Request, db: DB, token: Annotated[str | None, Depends(bearer)]):
    if not token:
        raise unauthorized()
    try:
        payload = jwt.decode(token, request.app.state.settings.jwt_secret.get_secret_value(),
                             algorithms=["HS256"], issuer="mcdonald-backend", audience="credit-cabinet",
                             options={"require": ["sub", "iat", "exp", "iss", "aud"]})
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_user)]


def require_client(user: CurrentUser):
    if user.role != "CLIENT":
        raise APIError(403, "FORBIDDEN", "Действие доступно только клиенту.")
    return user


Client = Annotated[User, Depends(require_client)]
