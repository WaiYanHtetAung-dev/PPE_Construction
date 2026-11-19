import pytest

from infra.onnx_export import preflight, run_offline


@pytest.mark.parametrize('release', ['8.4.102', '8.4.96'])
def test_lock_rejects_unhashed_unpinned_and_nonlocal_resolution(release):
    wheel_hash = '--hash=sha256:' + 'a' * 64
    pins = {'ultralytics': release, 'onnx': '1.20.0', 'opencv-python-headless': '4.10.0',
            'torch': '2.8.0+cpu', 'numpy': '2.2.0', 'example-transitive': '1.0'}
    lock = '\n'.join(f'{package}=={version} {wheel_hash}' for package, version in pins.items())
    assert preflight.parse_lock(lock, release) == pins
    continued = lock.replace(' ' + wheel_hash, ' ' + chr(92) + '\r\n  ' + wheel_hash)
    assert preflight.parse_lock(continued, release) == pins
    for bad in (lock + '\nextra==1.0', lock + '\nexample @ https://example.invalid/example.whl',
                lock.replace('onnx==1.20.0', 'onnx>=1.20.0'), lock + '\n--extra-index-url https://example.invalid'):
        with pytest.raises(ValueError):
            preflight.parse_lock(bad, release)
    dependencies = [
        {'metadata': {'name': name, 'version': version},
         'download_info': {'url': f'file:///build/wheels/{name}.whl'}}
        for name, version in pins.items()
    ]
    preflight.verify_install_plan(pins, dependencies)
    with pytest.raises(ValueError, match='full lock'):
        preflight.verify_install_plan(pins, dependencies[:-1])
    dependencies[0]['download_info']['url'] = 'https://example.invalid/ultralytics.whl'
    with pytest.raises(ValueError, match='wheelhouse'):
        preflight.verify_install_plan(pins, dependencies)


def test_readiness_requires_external_approval_with_matching_bindings(tmp_path):
    import json

    bindings = {'checkpoint_sha256': 'a' * 64}
    with pytest.raises(ValueError, match='missing'):
        run_offline.require_approval(tmp_path, 'synthetic-test', 'checkpoint-rights', bindings)
    (tmp_path / 'synthetic-test.json').write_text(json.dumps({
        'id': 'synthetic-test', 'status': 'approved', 'purpose': 'checkpoint-rights',
        'bindings': bindings,
    }))
    run_offline.require_approval(tmp_path, 'synthetic-test', 'checkpoint-rights', bindings)
    with pytest.raises(ValueError, match='does not match'):
        run_offline.require_approval(tmp_path, 'synthetic-test', 'checkpoint-rights',
                                     {'checkpoint_sha256': 'b' * 64})


def test_image_inspection_rejects_wrong_digest_and_implicit_mounts(monkeypatch):
    import json
    from types import SimpleNamespace

    image = 'exporter@sha256:' + 'a' * 64
    record = {'Os': 'linux', 'Architecture': 'amd64', 'RepoDigests': [image], 'Config': {}}
    monkeypatch.setattr(run_offline.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([record])))
    run_offline.inspect_image(image)
    record['Config']['Volumes'] = {'/unsafe': {}}
    with pytest.raises(ValueError):
        run_offline.inspect_image(image)
    record['Config'] = {}
    record['RepoDigests'] = ['exporter@sha256:' + 'b' * 64]
    with pytest.raises(ValueError):
        run_offline.inspect_image(image)
