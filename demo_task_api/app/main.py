"""FastAPI entrypoint for demo task API."""

from fastapi import FastAPI

from app.database import init_db
from app.routes.auth_routes import router as auth_router
from app.routes.task_routes import router as task_router

app = FastAPI(title="Demo Task API", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    """Initialize resources."""
    init_db()


@app.get("/health")
def health() -> dict:
    """Health endpoint."""
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(task_router)
