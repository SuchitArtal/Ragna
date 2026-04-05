"""Auth API routes."""

from fastapi import APIRouter, HTTPException

from app.models import UserLogin, UserRegister
from app.services.auth_service import bootstrap_admin, login_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.on_event("startup")
def startup_seed() -> None:
    """Seed admin user on startup."""
    bootstrap_admin()


@router.post("/register")
def register(payload: UserRegister) -> dict:
    """Register endpoint."""
    try:
        return register_user(payload.username, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
def login(payload: UserLogin) -> dict:
    """Login endpoint."""
    try:
        return login_user(payload.username, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
