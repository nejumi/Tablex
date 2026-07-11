from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tabular_harness.models.entities import AgentSupervisorLease, utc_now


def supervisor_lease_active(db: Session, session_id: str, *, now: datetime | None = None) -> bool:
    lease = db.get(AgentSupervisorLease, session_id)
    if lease is None:
        return False
    expires_at = lease.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > (now or utc_now())
