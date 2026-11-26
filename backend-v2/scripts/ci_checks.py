"""Run the backend validation shared by GitHub Actions and GitLab CI."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, *args], cwd=BACKEND, check=True)


def backend():
    run('-c', 'import numpy, onnx, onnxruntime; from PIL import Image')
    run('-m', 'compileall', '-q', 'app', 'inference_worker', 'media_gateway',
        'infra/onnx_export', 'tests', 'scripts')
    run('-m', 'pytest', '-q')
    run('scripts/check_architecture.py')
    run('scripts/verify_contracts.py')


def browser():
    run('-m', 'pytest', '-q', 'tests/browser_smoke.py')


def media():
    run('-m', 'unittest', '-v', 'tests.test_frame_queue', 'tests.test_media_sampler',
        'tests.media_decoder_integration', 'tests.test_inference_dispatch',
        'tests.media_inference_integration', 'tests.media_assignment_integration')


def disposable_postgres_url():
    from sqlalchemy.engine import make_url

    url = make_url(os.environ.get('DATABASE_URL', '')) if os.environ.get('DATABASE_URL') else None
    if (os.environ.get('APP_ENV') != 'ci' or url is None or url.drivername != 'postgresql+psycopg'
            or url.host not in {'127.0.0.1', 'postgres'} or url.port != 5432
            or url.database != 'ppe_ci' or url.username != 'ppe_ci' or url.query):
        raise SystemExit('PostgreSQL checks require the isolated ppe_ci service')
    return url


def postgres():
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    url = disposable_postgres_url()
    engine = create_engine(url, connect_args={'connect_timeout': 2}, hide_parameters=True)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text('SELECT 1'))
                break
            except OperationalError:
                if time.monotonic() >= deadline:
                    raise SystemExit('Disposable PostgreSQL service did not become ready') from None
                time.sleep(1)
    finally:
        engine.dispose()

    run('-m', 'alembic', 'upgrade', 'head')
    run('-m', 'alembic', 'check')
    run('-m', 'alembic', 'current', '--check-heads')
    os.environ['PPE_DISPOSABLE_POSTGRES_URL'] = os.environ['DATABASE_URL']
    run('-m', 'pytest', '-q', 'tests/test_platform_models.py', 'tests/test_camera_models.py',
        'tests/test_model_verification.py', 'tests/test_inference_worker.py',
        'tests/test_incident_ingestion.py', 'tests/test_assignment_snapshot.py', '-k', 'postgres')


def stack(report=None):
    disposable_postgres_url()
    if sys.platform != 'linux':
        raise SystemExit('The integrated stack requires Linux POSIX reads and read-only bind mounts')
    os.environ['PPE_DISPOSABLE_POSTGRES_URL'] = os.environ['DATABASE_URL']
    os.environ['PPE_STACK_RUN'] = '1'
    if report is not None:
        os.environ['PPE_STACK_REPORT'] = str(report.resolve())
    run('-m', 'pytest', '-q', '-s', 'tests/synthetic_assignment_stack.py')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=('backend', 'browser', 'media', 'postgres', 'stack'))
    parser.add_argument('--report', type=Path, help='Write a standalone HTML report for the synthetic stack')
    args = parser.parse_args()
    if args.check == 'stack':
        stack(args.report)
    elif args.report is not None:
        parser.error('--report requires the stack check')
    else:
        {'backend': backend, 'browser': browser, 'media': media, 'postgres': postgres}[args.check]()
