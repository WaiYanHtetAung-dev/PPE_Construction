from uuid import uuid4

import pytest

from app.db.models import ModelVersion, Organization, OrganizationMembership, PlatformPublisher
from app.db.session import SessionLocal
from tests.model_fixtures import seed_verified_model


@pytest.fixture
def catalog(client, admin_account):
    login = client.post('/api/v1/auth/login', json={
        'email': admin_account['email'], 'password': admin_account['password'],
    })
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    with SessionLocal.begin() as db:
        foreign_org = Organization(name='Foreign organization')
        models = [
            ModelVersion(model_key='ppe', version=str(number),
                         artifact_ref='private/model.bin', artifact_sha256='a' * 64,
                         class_map={'person': 'person'})
            for number in (2, 1, 3)
        ]
        db.add_all([foreign_org, *models])
        db.flush()
        for model in models[:2]:
            seed_verified_model(db, model)
        path = f"/api/v1/organizations/{admin_account['org_id']}/models"
        foreign_path = f'/api/v1/organizations/{foreign_org.id}/models'
        return headers, path, foreign_path, [model.id for model in models]


def test_catalog_paginates_only_eligible_versions(client, catalog):
    headers, path, _, (second, first, hidden) = catalog
    expected_first = {'id': first, 'model_key': 'ppe', 'version': '1'}
    response = client.get(path, headers=headers, params={'limit': 1})
    assert response.status_code == 200
    assert response.json() == {'items': [expected_first], 'total': 2, 'offset': 0, 'limit': 1}
    response = client.get(path, headers=headers, params={'limit': 1, 'offset': 1})
    assert response.json()['items'] == [{'id': second, 'model_key': 'ppe', 'version': '2'}]
    assert client.get(f'{path}/{first}', headers=headers).json() == expected_first
    concealed = client.get(f'{path}/{hidden}', headers=headers)
    unknown = client.get(f'{path}/{uuid4()}', headers=headers)
    assert concealed.status_code == unknown.status_code == 404
    assert concealed.json() == unknown.json()
    assert client.get(path, headers=headers, params={'limit': 0}).status_code == 422
    assert client.get(f'{path}/invalid-id', headers=headers).status_code == 422


@pytest.mark.parametrize('role', ['operator', 'viewer'])
def test_catalog_requires_requested_org_admin_even_for_publishers(client, catalog, admin_account, role):
    headers, path, foreign_path, (_, first, _) = catalog
    for suffix in ('', f'/{first}'):
        assert client.get(path + suffix).status_code == 401
        assert client.get(foreign_path + suffix, headers=headers).status_code == 404
    with SessionLocal.begin() as db:
        membership = db.query(OrganizationMembership).filter_by(user_id=admin_account['user_id']).one()
        membership.role = role
        db.add(PlatformPublisher(user_id=admin_account['user_id']))
    for suffix in ('', f'/{first}'):
        assert client.get(path + suffix, headers=headers).status_code == 404
