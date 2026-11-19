"""One-time bootstrap. Prompts for password without placing it in shell history."""
import argparse
from getpass import getpass

from argon2 import PasswordHasher
from sqlalchemy import select

from app.db.models import Organization, OrganizationMembership, User
from app.db.session import SessionLocal


def main():
    parser = argparse.ArgumentParser(description='Create first organization + admin in migrated database')
    parser.add_argument('--email', required=True)
    parser.add_argument('--organization', required=True)
    args = parser.parse_args()
    email = args.email.strip().lower()
    if '@' not in email or not args.organization.strip():
        parser.error('Provide valid email and non-empty organization')
    password = getpass('New admin password (minimum 12 characters): ')
    confirm = getpass('Confirm password: ')
    if password != confirm or len(password) < 12:
        parser.error('Passwords differ or too short')
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == email)):
            parser.error('Email already exists')
        org = Organization(name=args.organization.strip())
        user = User(email=email, password_hash=PasswordHasher().hash(password))
        db.add_all([org, user])
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role='admin'))
        org_id = org.id
    print(f'Bootstrap complete. Organization ID: {org_id}')
    print('Password and access token were not printed.')


if __name__ == '__main__':
    main()
