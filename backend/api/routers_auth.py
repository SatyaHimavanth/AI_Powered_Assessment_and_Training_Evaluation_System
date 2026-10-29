from datetime import datetime, timedelta, timezone
import os
import uuid
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from dotenv import load_dotenv
load_dotenv()

from core.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
    verify_password,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_COOKIE_NAME,
)
from db.models import RefreshSession, RegistrationRequest, RegistrationStatus, User
from db.async_helpers import run_db_sync
from db.database import SessionLocal


router = APIRouter(prefix="/auth", tags=["auth"])

REGISTRATION_EXPIRY_DAYS = int(os.getenv("REGISTRATION_EXPIRY_DAYS", "2"))
REFRESH_COOKIE_NAME = "assessment_refresh"
COOKIE_SECURE = os.getenv("APP_ENV", "development").lower() in {"production", "prod"}


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def _revoke_refresh_session(db: Session, user: User, jti: str) -> bool:
    session = (
        db.query(RefreshSession)
        .filter(RefreshSession.jti == jti, RefreshSession.user_id == user.id)
        .with_for_update()
        .first()
    )
    now = datetime.now(timezone.utc)
    if not session or session.revoked_at is not None:
        return False
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        return False
    session.revoked_at = now
    return True


# ---------- Schemas ---------- #


class UserRegister(BaseModel):
    username: str
    email: str
    contact_email: str
    name: str
    account: str | None = None
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    """Browser calls receive HttpOnly cookies; trusted API clients can opt into bearer JSON."""
    access_token: str | None = None
    token_type: str
    role: str


class MessageResponse(BaseModel):
    message: str


class UserOut(BaseModel):
    username: str
    email: str
    name: str
    role: str


# ---------- Endpoints ---------- #


@router.post("/register", response_model=MessageResponse)
async def register(payload: UserRegister):
    def _sync_work():
        db = SessionLocal()
        try:
            # Check if username/email already exists as an approved user
            existing_user = (
                db.query(User)
                .filter(
                    (User.username == payload.username)
                    | (User.email == payload.email)
                    | (User.contact_email == payload.contact_email)
                )
                .first()
            )
            if existing_user:
                raise HTTPException(status_code=400, detail="Username or email already registered")

            # Check if there's a pending registration request
            existing_request = (
                db.query(RegistrationRequest)
                .filter(
                    or_(
                        RegistrationRequest.username == payload.username,
                        RegistrationRequest.email == payload.email,
                        RegistrationRequest.contact_email == payload.contact_email,
                    ),
                )
                .filter(RegistrationRequest.status == RegistrationStatus.pending)
                .first()
            )
            if existing_request:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "A registration request is already pending for this username/email/contact. "
                        "Please wait for admin approval."
                    ),
                )

            # Check if rejected/expired within the configured window
            recent_rejected = (
                db.query(RegistrationRequest)
                .filter(
                    or_(
                        RegistrationRequest.username == payload.username,
                        RegistrationRequest.email == payload.email,
                        RegistrationRequest.contact_email == payload.contact_email,
                    ),
                )
                .filter(RegistrationRequest.status == RegistrationStatus.rejected)
                .filter(
                    RegistrationRequest.resolved_at
                    > datetime.now(timezone.utc) - timedelta(days=REGISTRATION_EXPIRY_DAYS)
                )
                .first()
            )
            if recent_rejected:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Your previous registration was rejected. You can re-register "
                        f"after {REGISTRATION_EXPIRY_DAYS} days from rejection."
                    ),
                )

            # Create pending registration request
            hashed = get_password_hash(payload.password)
            reg_request = RegistrationRequest(
                username=payload.username,
                email=payload.email,
                contact_email=payload.contact_email,
                name=payload.name,
                account=(payload.account or "").strip() or None,
                hashed_password=hashed,
                status=RegistrationStatus.pending,
            )
            db.add(reg_request)
            db.commit()

            return {"message": "Registration request submitted. Please wait for admin approval."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/login", response_model=Token, response_model_exclude_none=True)
async def login(payload: UserLogin, request: Request, response: Response):
    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == payload.username).first()
            if not user or not verify_password(payload.password, user.hashed_password):
                raise HTTPException(status_code=401, detail="Incorrect username or password")

            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account is deactivated")

            access_token = create_access_token(
                data={"sub": user.username, "role": user.role.value},
                expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            refresh_jti = str(uuid.uuid4())
            refresh_expiry = datetime.now(timezone.utc) + timedelta(days=7)
            refresh_token = create_refresh_token(
                data={"sub": user.username, "jti": refresh_jti}
            )
            db.add(RefreshSession(
                jti=refresh_jti,
                user_id=user.id,
                expires_at=refresh_expiry,
            ))
            db.commit()

            return {
                "access_token": access_token,
                "refresh_cookie": refresh_token,
                "token_type": "bearer",
                "role": user.role.value,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    access_token = result.pop("access_token")
    _set_auth_cookies(response, access_token, result.pop("refresh_cookie"))
    if request.headers.get("x-token-response", "").lower() == "bearer":
        result["access_token"] = access_token
    return result


@router.post("/refresh", response_model=Token, response_model_exclude_none=True)
async def refresh(
    request: Request,
    response: Response,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        token = refresh_cookie
        if not token:
            raise credentials_exception
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        jti: str | None = payload.get("jti")
        if username is None or not jti or payload.get("token_use") != "refresh":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    def _sync_work(username: str, jti: str):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).with_for_update().first()
            if user is None or not user.is_active:
                raise credentials_exception

            if not _revoke_refresh_session(db, user, jti):
                # Reuse invalidates all active sessions, including the rotated token.
                db.query(RefreshSession).filter(
                    RefreshSession.user_id == user.id,
                    RefreshSession.revoked_at.is_(None),
                ).update({RefreshSession.revoked_at: datetime.now(timezone.utc)})
                db.commit()
                raise credentials_exception

            access_token = create_access_token(
                data={"sub": user.username, "role": user.role.value},
                expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            next_jti = str(uuid.uuid4())
            refresh_expiry = datetime.now(timezone.utc) + timedelta(days=7)
            refresh_token = create_refresh_token(
                data={"sub": user.username, "jti": next_jti}
            )
            db.add(RefreshSession(
                jti=next_jti,
                user_id=user.id,
                expires_at=refresh_expiry,
            ))
            db.commit()

            return {
                "access_token": access_token,
                "refresh_cookie": refresh_token,
                "token_type": "bearer",
                "role": user.role.value,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work, username, jti)
    access_token = result.pop("access_token")
    _set_auth_cookies(response, access_token, result.pop("refresh_cookie"))
    if request.headers.get("x-token-response", "").lower() == "bearer":
        result["access_token"] = access_token
    return result


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if refresh_cookie:
        try:
            payload = jwt.decode(refresh_cookie, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            jti = payload.get("jti")
        except jwt.PyJWTError:
            username = None
            jti = None

        if username and jti:
            def _sync_work():
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.username == username).first()
                    if user:
                        _revoke_refresh_session(db, user, jti)
                        db.commit()
                finally:
                    db.close()

            await run_db_sync(_sync_work)

    response.delete_cookie(ACCESS_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    # Re-fetch user in a fresh sync session to ensure values are loaded
    # from a session that we control (avoids detached/expired attribute surprises).
    def _sync_work(username: str):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            return {
                "username": user.username,
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work, current_user.username)

