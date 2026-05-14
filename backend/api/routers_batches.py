import io
from typing import List
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_password_hash, require_admin
from db.database import SessionLocal
from db.async_helpers import run_db_sync
from db.models import Batch, BatchStatus, BatchUser, User, UserRole

router = APIRouter(prefix="/batches", tags=["batches"])


# ---------- Schemas ---------- #


class BatchOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    status: str
    user_count: int

    class Config:
        from_attributes = True


class BatchCreateRequest(BaseModel):
    name: str
    description: str = ""
    status: BatchStatus = BatchStatus.current


class BatchUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: BatchStatus | None = None


class BatchUploadResult(BaseModel):
    batch_name: str
    total_rows: int
    users_created: int
    users_added: int
    skipped: int
    errors: list[str]


class BatchAddUsersRequest(BaseModel):
    user_ids: list[UUID]


class BatchAddUsersResult(BaseModel):
    batch_name: str
    added: int
    skipped: int
    errors: list[str]


# ---------- Endpoints ---------- #


@router.get("/", response_model=List[BatchOut])
async def list_batches(
    _admin: User = Depends(require_admin),
):
    """List all batches with user counts."""
    def _sync_work():
        db = SessionLocal()
        try:
            batches = db.query(Batch).order_by(Batch.name).all()
            out = []
            for b in batches:
                count = db.query(BatchUser).filter(BatchUser.batch_id == b.id).count()
                out.append({
                    "id": b.id,
                    "name": b.name,
                    "description": b.description,
                    "status": b.status.value if b.status else "current",
                    "user_count": count,
                })
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/create", response_model=BatchOut)
async def create_batch(
    body: BatchCreateRequest,
    _admin: User = Depends(require_admin),
):
    """Create a new batch."""
    def _sync_work():
        db = SessionLocal()
        try:
            if not body.name.strip():
                raise HTTPException(status_code=400, detail="Batch name is required")

            existing = db.query(Batch).filter(Batch.name == body.name.strip()).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Batch '{body.name.strip()}' already exists")

            # Don't allow creating directly as archived
            if body.status == BatchStatus.archived:
                raise HTTPException(status_code=400, detail="Cannot create a batch with status 'archived'")

            batch = Batch(
                name=body.name.strip(),
                description=body.description.strip() or None,
                status=body.status or BatchStatus.current,
            )
            db.add(batch)
            db.commit()
            db.refresh(batch)

            return {
                "id": batch.id,
                "name": batch.name,
                "description": batch.description,
                "status": batch.status.value,
                "user_count": 0,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    return BatchOut(**result)


@router.post("/upload", response_model=BatchUploadResult)
async def upload_batch_users(
    batch_name: str,
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    """Upload an Excel file to create users and add them to a batch.

    Expected columns: name, username, email, contact_email, password, account
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    filename = file.filename.lower()
    content = await file.read()

    # uses top-level run_db_sync and SessionLocal

    def _sync_work():
        import io as _io

        try:
            if filename.endswith(".xlsx") or filename.endswith(".xls"):
                df = pd.read_excel(_io.BytesIO(content), engine="openpyxl", dtype=str)
            elif filename.endswith(".csv"):
                df = pd.read_csv(_io.BytesIO(content), dtype=str)
            else:
                raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are supported")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

        # Normalize columns
        df.columns = df.columns.str.strip().str.lower()

        required = {"name", "username", "email", "contact_email", "password"}
        missing = required - set(df.columns)
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing}")

        db = SessionLocal()
        try:
            # Get or create batch
            batch = db.query(Batch).filter(Batch.name == batch_name.strip()).first()
            if not batch:
                batch = Batch(
                    name=batch_name.strip(),
                    description=f"Batch created via upload",
                    status=BatchStatus.current,
                )
                db.add(batch)
                db.flush()

            users_created = 0
            users_added = 0
            skipped = 0
            errors: list[str] = []

            for idx, row in df.iterrows():
                row_num = idx + 2
                name = str(row.get("name", "")).strip()
                username = str(row.get("username", "")).strip()
                email = str(row.get("email", "")).strip()
                contact_email = str(row.get("contact_email", "")).strip()
                password = str(row.get("password", "")).strip()
                account = str(row.get("account", "")).strip()

                if name == "nan" or not name:
                    errors.append(f"Row {row_num}: missing name")
                    skipped += 1
                    continue
                if username == "nan" or not username:
                    errors.append(f"Row {row_num}: missing username")
                    skipped += 1
                    continue
                if email == "nan" or not email:
                    errors.append(f"Row {row_num}: missing email")
                    skipped += 1
                    continue
                if contact_email == "nan" or not contact_email:
                    errors.append(f"Row {row_num}: missing contact_email")
                    skipped += 1
                    continue
                if password == "nan" or not password:
                    errors.append(f"Row {row_num}: missing password")
                    skipped += 1
                    continue
                if account == "nan":
                    account = ""

                # Check if user exists
                user = db.query(User).filter(User.username == username).first()
                if not user:
                    # Also check email
                    email_exists = db.query(User).filter(User.email == email).first()
                    if email_exists:
                        errors.append(f"Row {row_num}: email '{email}' already in use")
                        skipped += 1
                        continue

                    user = User(
                        username=username,
                        email=email,
                        contact_email=contact_email,
                        name=name,
                        hashed_password=get_password_hash(password),
                        role=UserRole.user,
                        is_active=True,
                        account=account or None,
                    )
                    db.add(user)
                    db.flush()
                    users_created += 1

                # Add to batch if not already
                existing_link = (
                    db.query(BatchUser)
                    .filter(BatchUser.batch_id == batch.id, BatchUser.user_id == user.id)
                    .first()
                )
                if not existing_link:
                    db.add(BatchUser(batch_id=batch.id, user_id=user.id))
                    users_added += 1
                else:
                    errors.append(f"Row {row_num}: user '{username}' already in batch")
                    skipped += 1

            db.commit()

            return {
                "batch_name": batch.name,
                "total_rows": users_created + users_added + skipped,
                "users_created": users_created,
                "users_added": users_added,
                "skipped": skipped,
                "errors": errors[:20],
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    return BatchUploadResult(**result)


@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Delete a batch (does not delete users). Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            # Soft-delete: mark batch as archived so assignments/users remain but
            # the batch is no longer active/visible.
            batch.status = BatchStatus.archived
            db.commit()

            return {"message": f"Batch '{batch.name}' archived"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/{batch_id}/restore")
async def restore_batch(
    batch_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Restore an archived batch back to active/current status. Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            batch.status = BatchStatus.current
            db.commit()

            return {"message": f"Batch '{batch.name}' restored"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/{batch_id}/users", response_model=BatchAddUsersResult)
async def add_existing_users_to_batch(
    batch_id: UUID,
    body: BatchAddUsersRequest,
    _admin: User = Depends(require_admin),
):
    """Add existing users to a batch. Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            if not body.user_ids:
                raise HTTPException(status_code=400, detail="Select at least one user")

            added = 0
            skipped = 0
            errors: list[str] = []

            for user_id in body.user_ids:
                user = db.query(User).filter(User.id == user_id, User.role == UserRole.user).first()
                if not user:
                    errors.append(f"User {user_id} not found")
                    skipped += 1
                    continue

                existing_link = (
                    db.query(BatchUser)
                    .filter(BatchUser.batch_id == batch.id, BatchUser.user_id == user.id)
                    .first()
                )
                if existing_link:
                    errors.append(f"User '{user.username}' is already in batch")
                    skipped += 1
                    continue

                db.add(BatchUser(batch_id=batch.id, user_id=user.id))
                added += 1

            db.commit()

            return {
                "batch_name": batch.name,
                "added": added,
                "skipped": skipped,
                "errors": errors[:20],
            }
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return BatchAddUsersResult(**res)


@router.put("/{batch_id}", response_model=BatchOut)
async def update_batch(
    batch_id: UUID,
    body: BatchUpdateRequest,
    _admin: User = Depends(require_admin),
):
    """Update batch name, description or status (cannot set archived here). Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            # Validate name uniqueness if provided
            if body.name:
                existing = db.query(Batch).filter(Batch.name == body.name.strip(), Batch.id != batch_id).first()
                if existing:
                    raise HTTPException(status_code=400, detail=f"Batch '{body.name.strip()}' already exists")
                batch.name = body.name.strip()

            if body.description is not None:
                batch.description = body.description.strip() or None

            if body.status is not None:
                if body.status == BatchStatus.archived:
                    raise HTTPException(status_code=400, detail="Cannot set status to 'archived' via edit")
                batch.status = body.status

            db.commit()
            user_count = db.query(BatchUser).filter(BatchUser.batch_id == batch.id).count()
            return {
                "id": batch.id,
                "name": batch.name,
                "description": batch.description,
                "status": batch.status.value if batch.status else "current",
                "user_count": user_count,
            }
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return BatchOut(**res)
