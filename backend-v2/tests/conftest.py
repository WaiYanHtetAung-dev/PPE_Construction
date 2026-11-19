import os
from pathlib import Path
import tempfile

# Force an isolated DB before application import. Tests never touch local PostgreSQL.
_temp_db_dir = tempfile.TemporaryDirectory(prefix='ppe_v2_tests_')
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///' + str(Path(_temp_db_dir.name) / 'test.sqlite')
os.environ['ENABLE_API_DOCS'] = 'true'

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.base import Base
from app.db.models import Organization, OrganizationMembership, User
from app.db.session import SessionLocal, engine
from app.main import app


@event.listens_for(engine, 'connect')
def sqlite_fk(dbapi_connection, _connection_record):
    dbapi_connection.execute('PRAGMA foreign_keys=ON')


@pytest.fixture(scope='session', autouse=True)
def close_test_database():
    yield
    engine.dispose()
    _temp_db_dir.cleanup()


@pytest.fixture(autouse=True)
def reset_db(close_test_database):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_account():
    with SessionLocal.begin() as db:
        user = User(email='admin@ppe.example', password_hash=PasswordHasher().hash('strong-test-password'))
        org = Organization(name='Construction Org A')
        db.add_all([user, org])
        db.flush()
        db.add(OrganizationMembership(user_id=user.id, organization_id=org.id, role='admin'))
        return {'user_id': user.id, 'org_id': org.id, 'email': user.email, 'password': 'strong-test-password'}
