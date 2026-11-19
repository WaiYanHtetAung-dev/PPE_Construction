"""Manage publisher grants using restricted PostgreSQL credentials."""
import argparse
from uuid import UUID

from sqlalchemy import select, text

from app.db.models import PlatformAuditLog, PlatformPublisher, User
from app.db.session import SessionLocal


def change_grant(db, user_id: str, grant: bool, actor: str) -> bool:
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                   {'key': 'platform-publisher:' + user_id})
    is_active = db.scalar(select(User.is_active).where(User.id == user_id))
    if is_active is None or (grant and not is_active):
        raise ValueError('User does not exist or is ineligible for a publisher grant')
    existing = db.get(PlatformPublisher, user_id)
    if grant == (existing is not None):
        return False
    if grant:
        db.add(PlatformPublisher(user_id=user_id))
    else:
        db.delete(existing)
    db.add(PlatformAuditLog(
        actor=actor,
        action='publisher.grant' if grant else 'publisher.revoke',
        target_id=user_id,
        details={},
    ))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['grant', 'revoke'])
    parser.add_argument('user_id', type=UUID)
    args = parser.parse_args()
    try:
        with SessionLocal.begin() as db:
            if db.get_bind().dialect.name != 'postgresql':
                raise ValueError('Publisher administration requires PostgreSQL')
            if not db.scalar(text("SELECT pg_has_role(session_user, to_regrole('ppe_publisher_admin'), 'MEMBER')")):
                raise ValueError('Publisher administration requires the ppe_publisher_admin role')
            actor = db.scalar(text('SELECT session_user'))
            changed = change_grant(db, str(args.user_id), args.action == 'grant', f'postgres:{actor}')
    except ValueError as error:
        parser.error(str(error))
    except Exception:
        parser.exit(1, 'Could not change publisher permission. Transaction rolled back.\n')
    print('Publisher permission updated.' if changed else 'Publisher permission already in requested state.')


if __name__ == '__main__':
    main()
