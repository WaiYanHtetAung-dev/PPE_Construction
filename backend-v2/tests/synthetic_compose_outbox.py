"""Exercise the existing outbox publisher against a disposable HTTPS receiver."""

import asyncio
import hmac
import sqlite3
import ssl
from contextlib import closing
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

import httpx
from fastapi import FastAPI, Header, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Incident, IncidentOutbox, utcnow
from app.scripts.incident_outbox import DeliveryResult, IncidentCreated, deliver_one, post_event
from tests.synthetic_compose_ai import CONTROL, fixture_engine
from tests.synthetic_compose_ids import NORTH, NORTH_CAMERA, PROBE_VIOLATION
from tests.synthetic_stack_support import listener

PATH = '/receive'


def receiver(receipts, token, expected, *, lose_ack):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post(PATH)
    def accept(event: IncidentCreated, authorization: str = Header(default=''),
               idempotency_key: str = Header(default='')):
        if not hmac.compare_digest(authorization.encode('utf-8'), f'Bearer {token}'.encode('ascii')):
            return Response(status_code=401)
        if idempotency_key != event.event_id or event != expected:
            return Response(status_code=409)
        with closing(sqlite3.connect(receipts)) as db, db:
            inserted = db.execute('INSERT OR IGNORE INTO receipts(event_id) VALUES (?)', (event.event_id,)).rowcount
        # Simulate failure after durable acceptance but before the sender sees a successful acknowledgement.
        return Response(status_code=503 if inserted and lose_ack else 204)

    return app


def probe_outbox(engine):
    with Session(engine) as db:
        row = db.execute(
            select(IncidentOutbox, Incident).join(Incident, Incident.id == IncidentOutbox.incident_id)
            .where(IncidentOutbox.published_at.is_(None)).limit(2)
        ).one_or_none()
        if row is None:
            raise ValueError('Record one synthetic incident in a fresh disposable lab before running this probe')
        entry, incident = row
        if ((incident.organization_id, incident.camera_id, incident.violation_type) !=
                (NORTH, NORTH_CAMERA, PROBE_VIOLATION) or entry.attempts):
            raise ValueError('The pending outbox event does not match the fresh synthetic probe')
        return IncidentCreated(entry.event_id, incident.organization_id, incident.id)


async def exercise(engine, receipts):
    event = probe_outbox(engine)
    token = token_urlsafe(32)
    cert, key = CONTROL / 'listener.pem', CONTROL / 'listener.key'
    trust = ssl.create_default_context(cafile=str(CONTROL / 'ca.pem'))
    with closing(sqlite3.connect(receipts)) as db, db:
        db.execute('CREATE TABLE receipts (event_id TEXT PRIMARY KEY)')

    def attempt(origin):
        with httpx.Client(verify=trust, timeout=5, follow_redirects=False, trust_env=False) as client, Session(engine) as db:
            result = deliver_one(db, lambda event: post_event(client, httpx.URL(origin + PATH), token, event))
            entry = db.get(IncidentOutbox, event.event_id)
            return result, entry.attempts, entry.retry_at, entry.published_at

    async with listener(receiver(receipts, token, event, lose_ack=True), cert, key) as origin:
        async with httpx.AsyncClient(verify=trust, timeout=5, trust_env=False) as client:
            body = {'event_id': event.event_id, 'incident_id': event.incident_id, 'organization_id': event.organization_id}
            assert (await client.post(origin + PATH, json=body)).status_code == 401
            headers = {'Authorization': f'Bearer {token}', 'Idempotency-Key': 'wrong-key'}
            assert (await client.post(origin + PATH, json=body, headers=headers)).status_code == 409
        result, attempts, retry_at, published_at = await asyncio.to_thread(attempt, origin)
        assert result is DeliveryResult.RETRY_SCHEDULED and attempts == 1 and published_at is None
        assert retry_at is not None
    with closing(sqlite3.connect(receipts)) as db:
        assert db.execute('SELECT event_id FROM receipts').fetchall() == [(event.event_id,)]

    await asyncio.sleep(max(0, (retry_at - utcnow()).total_seconds()))
    async with listener(receiver(receipts, token, event, lose_ack=False), cert, key) as origin:
        result, attempts, retry_at, published_at = await asyncio.to_thread(attempt, origin)
        assert result is DeliveryResult.PUBLISHED and attempts == 2 and retry_at is None and published_at is not None
        assert (await asyncio.to_thread(attempt, origin))[0] is DeliveryResult.EMPTY
    with closing(sqlite3.connect(receipts)) as db:
        assert db.execute('SELECT event_id FROM receipts').fetchall() == [(event.event_id,)]
    print('PPE_COMPOSE_OUTBOX: HTTPS acknowledgement failure, receiver restart and one durable receipt verified')


def main():
    engine = fixture_engine('outbox_fixture')
    try:
        with TemporaryDirectory() as root:
            asyncio.run(exercise(engine, Path(root) / 'receipts.sqlite'))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
