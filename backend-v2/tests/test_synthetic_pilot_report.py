import pytest

from tests.synthetic_pilot_report import render_report


@pytest.fixture
def measurements():
    trials = [{
        'sample_interval_s': 0.3,
        'measurement_s': 12,
        'cameras': [{
            'input_target_fps': 10, 'source_fps': source, 'offered': 36,
            'emitted_fps': 2, 'median_sample_to_result_ms': 300,
            'queue_replacements': drops, 'policy_rejections': 0, 'queue_purges': 1,
            'camera_id': 'private-fixture-identifier',
        }],
    } for source, drops in [(8, 2), (9, 3), (10, 4)]]
    summary = {'arms': [{'interval_s': 0.3, 'windows': 3, 'total_emitted': 72, 'total_replacements': 9}]}
    restart = {'sample_interval_s': 0.3, 'outage_dispatch_s': 1.502, 'worker_tls_ready_s': 0.5,
               'restart_to_all_cameras_s': 1.2, 'restart_to_camera_s': [1.2],
               'raw_error': '<script>alert(1)</script>'}
    return trials, summary, restart


def test_report_labels_fixtures_and_summarizes_measured_windows(measurements):
    page = render_report(*measurements)
    assert 'Camera 1 <small>10 FPS input</small>' in page
    assert '<td>9.00</td><td>3.00</td><td>2.00</td><td>300.00</td>' in page
    assert '<td>9</td><td>0</td><td>3</td><td>1.200</td>' in page
    assert '<td>72</td><td>9</td>' in page
    assert 'default-src \'none\'' in page
    assert '<script' not in page and 'private-fixture-identifier' not in page


def test_report_rejects_markup_in_a_numeric_metric(measurements):
    trials, _, _ = measurements
    for trial in trials:
        trial['cameras'][0]['source_fps'] = '<img src="https://example.invalid">'
    with pytest.raises(ValueError, match='format code'):
        render_report(*measurements)
