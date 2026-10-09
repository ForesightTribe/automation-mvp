"""Account user management. No field here ever carries a password hash."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ClientRef(BaseModel):
    id: uuid.UUID
    name: str


class AccountUserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    client_scope: str          # 'all' | 'listed'
    clients: list[ClientRef]   # populated only for 'listed'
    created_at: datetime


class CreateUserIn(BaseModel):
    email: str
    full_name: str = ""
    # Set by the admin and shared out of band — there is no transactional email
    # in this system, so an invite link is not an option today.
    password: str = Field(min_length=8)
    role: str = "member"


class CreateUserOut(BaseModel):
    id: uuid.UUID
    email: str


class SetRoleIn(BaseModel):
    role: str


class SetActiveIn(BaseModel):
    is_active: bool


class SetClientsIn(BaseModel):
    # None = every client on the account. A list scopes to exactly those and
    # replaces any previous grants.
    client_ids: list[uuid.UUID] | None = None


class ChangePasswordIn(BaseModel):
    """Self-service. The current password is required even though the caller is
    already authenticated — see `change_own_password`."""

    current_password: str
    new_password: str = Field(min_length=8)


class ResetPasswordIn(BaseModel):
    """Admin-set, for someone who cannot sign in. Shared out of band."""

    new_password: str = Field(min_length=8)
