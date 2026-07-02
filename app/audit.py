"""Minimal audit-log helper.

Every write to a Client, Account, Liability, Deductible, or Report is recorded
here so Andrew (admin) can review who changed what and when.
"""

from __future__ import annotations

from typing import Any

from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def record(
    entity: str, entity_id: int | None, action: str, diff: dict[str, Any] | None = None
) -> None:
    """Append an audit entry. Safe to call before or after commit."""
    user_id = current_user.id if current_user.is_authenticated else None
    entry = AuditLog(
        user_id=user_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        diff_json=diff,
    )
    db.session.add(entry)
