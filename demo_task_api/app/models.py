"""Pydantic models for API payloads."""

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    """Registration payload."""

    username: str = Field(min_length=3)
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    """Login payload."""

    username: str
    password: str


class TaskCreate(BaseModel):
    """Create task payload."""

    title: str
    description: str = ""
    owner: str


class TaskUpdate(BaseModel):
    """Update task payload."""

    title: str | None = None
    description: str | None = None
    done: bool | None = None
