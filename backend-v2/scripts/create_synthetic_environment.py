"""Generate a private, one-project Compose environment for synthetic testing."""

import argparse
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    output = parser.parse_args().output
    if not output.name.startswith('.env.synthetic-stack'):
        parser.error('Use a .env.synthetic-stack filename so Git and Docker exclude it')
    settings = {
        'COMPOSE_PROJECT_NAME': f'ppe-v2-lab-{token_hex(6)}',
        'PPE_LAB_OWNER_PASSWORD': token_urlsafe(32),
        'PPE_LAB_API_PASSWORD': token_urlsafe(32),
        'PPE_LAB_LOGIN_PASSWORD': token_urlsafe(32),
    }
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error('The environment file already exists. Reuse it for this project or choose a new file.')
    with os.fdopen(descriptor, 'w', encoding='ascii', newline='\n') as destination:
        for key, value in settings.items():
            destination.write(f'{key}={value}\n')
    print('Created a disposable environment with fresh project credentials.')


if __name__ == '__main__':
    main()
