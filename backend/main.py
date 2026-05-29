import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles
# from fastapi.responses import FileResponse
from sqlalchemy import text

load_dotenv()

from api.routers_admin import router as admin_router
from api.routers_auth import router as auth_router
from api.routers_assessments import router as assessments_router
from api.routers_batches import router as batches_router
from api.routers_code import router as code_router
from api.routers_practice import router as practice_router
from api.routers_questions import router as questions_router
from api.routers_interviews import user_router as interviews_router, admin_router as admin_interviews_router
from api.routers_user_assessments import router as user_assessments_router
from api.routers_question_generation import router as question_generation_router
from core.auth import get_password_hash
from core.evaluation_service import start_evaluation_job_consumer
from core.setup_demo_db import create_demo_db_for_tests
from db.database import Base, SessionLocal, engine
from db.models import Batch, BatchStatus, BatchUser, RegistrationRequest, RegistrationStatus, User, UserRole

# ---------- Default credentials ---------- #
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@assessment.com")
DEFAULT_ADMIN_CONTACT_EMAIL = os.getenv("DEFAULT_ADMIN_CONTACT_EMAIL", "admin@assessment.com")
DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "System Admin")

DEFAULT_USER_USERNAME = os.getenv("DEFAULT_USER_USERNAME", "user")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD", "user123")
DEFAULT_USER_EMAIL = os.getenv("DEFAULT_USER_EMAIL", "user@assessment.com")
DEFAULT_USER_CONTACT_EMAIL = os.getenv("DEFAULT_USER_CONTACT_EMAIL", "user@assessment.com")
DEFAULT_USER_NAME = os.getenv("DEFAULT_USER_NAME", "Default User")

DEFAULT_BATCH_NAME = os.getenv("DEFAULT_BATCH_NAME", "Default Batch")

REGISTRATION_EXPIRY_DAYS = int(os.getenv("REGISTRATION_EXPIRY_DAYS", "2"))


def seed_defaults(db):
    """Create default admin, user, and batch if they don't exist."""
    admin = db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first()
    if not admin:
        admin = User(
            username=DEFAULT_ADMIN_USERNAME,
            email=DEFAULT_ADMIN_EMAIL,
            contact_email=DEFAULT_ADMIN_CONTACT_EMAIL,
            name=DEFAULT_ADMIN_NAME,
            hashed_password=get_password_hash(DEFAULT_ADMIN_PASSWORD),
            role=UserRole.admin,
            is_active=True,
            account="system",
        )
        db.add(admin)
        print("[OK] Default admin created (admin / admin123)")

    user = db.query(User).filter(User.username == DEFAULT_USER_USERNAME).first()
    if not user:
        user = User(
            username=DEFAULT_USER_USERNAME,
            email=DEFAULT_USER_EMAIL,
            contact_email=DEFAULT_USER_CONTACT_EMAIL,
            name=DEFAULT_USER_NAME,
            hashed_password=get_password_hash(DEFAULT_USER_PASSWORD),
            role=UserRole.user,
            is_active=True,
            account="system",
        )
        db.add(user)
        print("[OK] Default user created (user / user123)")

    db.flush()

    # Create default batch
    batch = db.query(Batch).filter(Batch.name == DEFAULT_BATCH_NAME).first()
    if not batch:
        batch = Batch(
            name=DEFAULT_BATCH_NAME,
            description="Default batch for system users",
            status=BatchStatus.current,
        )
        db.add(batch)
        db.flush()
        print("[OK] Default batch created")

    # Ensure default user is in default batch
    if user:
        existing_link = (
            db.query(BatchUser)
            .filter(BatchUser.batch_id == batch.id, BatchUser.user_id == user.id)
            .first()
        )
        if not existing_link:
            db.add(BatchUser(batch_id=batch.id, user_id=user.id))
            print("[OK] Default user added to default batch")

    db.commit()


def auto_reject_expired_registrations(db):
    """Reject pending registrations older than 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=REGISTRATION_EXPIRY_DAYS)
    expired = (
        db.query(RegistrationRequest)
        .filter(RegistrationRequest.status == RegistrationStatus.pending)
        .filter(RegistrationRequest.requested_at < cutoff)
        .all()
    )
    for req in expired:
        req.status = RegistrationStatus.rejected
        req.resolved_at = datetime.now(timezone.utc)
    if expired:
        db.commit()
        print(f"[CLEANUP] Auto-rejected {len(expired)} expired registration(s)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    print("[OK] Database tables created")

    db = SessionLocal()
    try:
        seed_defaults(db)
        auto_reject_expired_registrations(db)
    finally:
        db.close()

    # Start evaluation job consumer daemon
    start_evaluation_job_consumer(daemon=True)
    print("[OK] Evaluation job consumer started")

    # Create demo db for postgres assessment
    create_demo_db_for_tests()

    # Backfill embeddings for questions that don't have them yet
    import threading
    from core.embedding_backfill import backfill_missing_embeddings
    threading.Thread(target=backfill_missing_embeddings, daemon=True).start()

    yield
    # Shutdown (nothing to clean up)


app = FastAPI(
    title="AI Assessment & Training Evaluation System",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# # React assets
# app.mount(
#     "/assets",
#     StaticFiles(directory="dist/assets"),
#     name="assets"
# )

# # SPA Fallback
# @app.get("/")
# async def serve_spa():
#     return FileResponse("dist/index.html")


# Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(questions_router)
app.include_router(assessments_router)
app.include_router(batches_router)
app.include_router(user_assessments_router)
app.include_router(practice_router)
app.include_router(interviews_router)
app.include_router(admin_interviews_router)
app.include_router(code_router)
app.include_router(question_generation_router)


# @app.get("/")
# def root():
#     return {"message": "AI Assessment System API is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
