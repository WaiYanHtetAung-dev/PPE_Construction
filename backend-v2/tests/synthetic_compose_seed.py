"""Migrate the disposable Compose database and provision dashboard fixtures."""

import os
from re import fullmatch

from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import Camera, Incident, Organization, OrganizationMembership, Site, User, utcnow

EMAIL = 'operator@ppe-lab.example.com'
OPERATOR = '8b351059-d530-49d9-8b85-8bac94f01c01'
NORTH = '8b351059-d530-49d9-8b85-8bac94f01c02'
SOUTH = '8b351059-d530-49d9-8b85-8bac94f01c03'
UNASSIGNED = '8b351059-d530-49d9-8b85-8bac94f01c04'
SECRET = r'[A-Za-z0-9_-]{43}'


def credential(name):
    value = os.environ.get(name, '')
    if not fullmatch(SECRET, value):
        raise SystemExit('Use credentials from the disposable lab environment generator.')
    return value


def owner_url():
    if os.environ.get('APP_ENV') != 'synthetic-compose':
        raise SystemExit('The bootstrap only accepts the private Compose ppe_lab database.')
    url = make_url(os.environ.get('DATABASE_URL', ''))
    if (url.query or (url.drivername, url.username, url.host, url.port, url.database) !=
            ('postgresql+psycopg', 'ppe_lab_owner', 'postgres', 5432, 'ppe_lab')
            or not fullmatch(SECRET, url.password or '')):
        raise SystemExit('The bootstrap only accepts the private Compose ppe_lab database.')
    return url


def provision_api(engine, password):
    with engine.begin() as connection:
        if connection.scalar(text("SELECT to_regrole('ppe_lab_api')")) is None:
            connection.exec_driver_sql('CREATE ROLE ppe_lab_api NOLOGIN')
        # The generator's fixed-length URL-safe alphabet excludes SQL quoting and separators.
        connection.exec_driver_sql(f"ALTER ROLE ppe_lab_api LOGIN PASSWORD '{password}'")
        connection.exec_driver_sql('GRANT USAGE ON SCHEMA public TO ppe_lab_api')
        connection.exec_driver_sql(
            'GRANT SELECT ON organizations, organization_memberships, users, session_tokens, '
            'sites, cameras, incidents, camera_model_assignments, model_versions, '
            'eligible_model_versions TO ppe_lab_api'
        )
        connection.exec_driver_sql('GRANT INSERT ON session_tokens, sites, cameras, audit_logs TO ppe_lab_api')
        connection.exec_driver_sql('GRANT UPDATE (revoked_at) ON session_tokens TO ppe_lab_api')
        connection.exec_driver_sql('GRANT UPDATE (status) ON incidents TO ppe_lab_api')


def seed(engine, password):
    with Session(engine) as db, db.begin():
        if db.get(User, OPERATOR) is not None:
            return
        db.add(User(id=OPERATOR, email=EMAIL, password_hash=PasswordHasher().hash(password)))
        for org_id, name, role in (
            (NORTH, 'North', 'admin'), (SOUTH, 'South', 'viewer'), (UNASSIGNED, 'Restricted', None),
        ):
            db.add(Organization(id=org_id, name=f'Synthetic {name}'))
            db.flush()
            if role:
                db.add(OrganizationMembership(user_id=OPERATOR, organization_id=org_id, role=role))
            site = Site(organization_id=org_id, name=f'{name} Synthetic Site')
            db.add(site)
            db.flush()
            camera = Camera(site_id=site.id, name=f'{name} Synthetic Camera', stream_ref=f'stream:lab/{name.lower()}')
            db.add(camera)
            db.flush()
            db.add(Incident(organization_id=org_id, site_id=site.id, camera_id=camera.id,
                            violation_type=f'{name} synthetic fixture', detected_at=utcnow()))


def main():
    try:
        url = owner_url()
        api_password = credential('PPE_LAB_API_PASSWORD')
        login_password = credential('PPE_LAB_LOGIN_PASSWORD')
        alembic = Config('alembic.ini')
        command.upgrade(alembic, 'head')
        command.current(alembic, check_heads=True)
        engine = create_engine(url, hide_parameters=True)
        try:
            provision_api(engine, api_password)
            seed(engine, login_password)
        finally:
            engine.dispose()
    except Exception:
        raise SystemExit('Synthetic PostgreSQL bootstrap failed. Check migration output and lab configuration.') from None
    print('Migrated disposable PostgreSQL, restricted API role and synthetic fixtures are ready.')


if __name__ == '__main__':
    main()
