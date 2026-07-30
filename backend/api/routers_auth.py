from datetime import datetime, timedelta, timezone
import os
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
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
)
from db.models import RegistrationRequest, RegistrationStatus, User
from db.async_helpers import run_db_sync
from db.database import SessionLocal


router = APIRouter(prefix="/auth", tags=["auth"])

REGISTRATION_EXPIRY_DAYS = int(os.getenv("REGISTRATION_EXPIRY_DAYS", "2"))


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
    access_token: str
    refresh_token: str
    token_type: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


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


@router.post("/login", response_model=Token)
async def login(payload: UserLogin):
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
            refresh_token = create_refresh_token(data={"sub": user.username})

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "role": user.role.value,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/refresh", response_model=Token)
async def refresh(req: RefreshRequest):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(req.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    def _sync_work(username: str):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None or not user.is_active:
                raise credentials_exception

            access_token = create_access_token(
                data={"sub": user.username, "role": user.role.value},
                expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            refresh_token = create_refresh_token(data={"sub": user.username})

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "role": user.role.value,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work, username)


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

