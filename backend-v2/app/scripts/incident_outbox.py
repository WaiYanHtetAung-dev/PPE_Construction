"""Deliver one pending incident event using an idempotent, trusted publisher."""

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Incident, IncidentOutbox, utcnow
from app.db.session import SessionLocal


@dataclass(frozen=True)
class IncidentCreated:
    event_id: str
    organization_id: str
    incident_id: str


class DeliveryResult(Enum):
    EMPTY = 'empty'
    PUBLISHED = 'published'
    RETRY_SCHEDULED = 'retry_scheduled'


def deliver_one(db: Session, publish: Callable[[IncidentCreated], bool]) -> DeliveryResult:
    """The publisher must enforce a deadline and deduplicate by event_id."""
    with db.begin():
        row = db.execute(select(IncidentOutbox, Incident.organization_id)
                         .join(Incident, Incident.id == IncidentOutbox.incident_id)
                         .where(IncidentOutbox.published_at.is_(None), or_(
                             IncidentOutbox.retry_at.is_(None), IncidentOutbox.retry_at <= utcnow(),
                         ))
                         .order_by(IncidentOutbox.created_at, IncidentOutbox.event_id)
                         .limit(1)
                         .with_for_update(of=IncidentOutbox, skip_locked=True)).one_or_none()
        if row is None:
            return DeliveryResult.EMPTY

        entry, organization_id = row
        delivered = publish(IncidentCreated(entry.event_id, organization_id, entry.incident_id))
        entry.attempts += 1
        if delivered:
            entry.published_at = utcnow()
            entry.retry_at = None
            return DeliveryResult.PUBLISHED

        delay = min(300, 2 ** min(entry.attempts, 9))
        entry.retry_at = utcnow() + timedelta(seconds=delay)
        return DeliveryResult.RETRY_SCHEDULED


def main() -> None:
    endpoint = httpx.URL(os.environ['INCIDENT_PUBLISH_URL'])
    if endpoint.scheme != 'https' or not endpoint.host or endpoint.userinfo or endpoint.query or endpoint.fragment:
        raise SystemExit('Incident publisher requires a configured HTTPS endpoint')
    with Path(os.environ['INCIDENT_PUBLISH_TOKEN_FILE']).open(encoding='ascii') as source:
        token = source.read(258).rstrip('\r\n')
    if not 32 <= len(token) <= 256 or any(not 33 <= ord(char) <= 126 for char in token):
        raise SystemExit('Invalid incident publisher credential')

    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client, SessionLocal() as db:
        if db.get_bind().dialect.name != 'postgresql':
            raise SystemExit('Incident outbox delivery requires PostgreSQL')

        def publish(event: IncidentCreated) -> bool:
            try:
                with client.stream('POST', endpoint, json=asdict(event), headers={
                    'Authorization': f'Bearer {token}', 'Idempotency-Key': event.event_id,
                }) as response:
                    return response.is_success
            except httpx.RequestError:
                return False

        print(deliver_one(db, publish).value)


if __name__ == '__main__':
    main()
