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
    reconnect = {'elapsed_s': 90, 'cycles': [{
        'sources': [{'camera': 1, 'mode': 'stall', 'blocked_retries': 2, 'restore_to_result_s': 1.1},
                    {'camera': 2, 'mode': 'eof', 'blocked_retries': 4, 'restore_to_result_s': 1.2}],
        'source_offline_s': 4, 'unaffected_results': 9, 'mean_peer_results_per_s': 2.25,
        'peak_pending': 2, 'peak_pending_bytes': 6144, 'queue_replacements': 1}],
                 'cameras': [{'camera': 1, 'offered': 11, 'emitted': 8, 'replaced': 2, 'rejected': 0, 'purged': 0,
                              'pending_at_shutdown': 1, 'in_flight_at_shutdown': 0}]}
    capacity = [{'peak_pending': 2, 'peak_pending_bytes': 6144, 'cameras': [
        {'emitted': 12, 'emitted_fps': 1, 'max_result_gap_ms': 1100, 'queue_replacements': 4},
        {'emitted': 18, 'emitted_fps': 1.5, 'max_result_gap_ms': 800, 'queue_replacements': 2},
    ]}]
    return trials, summary, restart, reconnect, capacity


def test_report_labels_fixtures_and_summarizes_measured_windows(measurements):
    page = render_report(*measurements)
    assert 'Camera 1 <small>10 FPS input</small>' in page
    assert '<td>9.00</td><td>3.00</td><td>2.00</td><td>300.00</td>' in page
    assert '<td>9</td><td>0</td><td>3</td><td>1.200</td>' in page
    assert '<td>72</td><td>9</td>' in page
    assert 'Camera 1 (Frame stall)<br>Camera 2 (End of stream)' in page
    assert '<td>2<br>4</td>' in page and '<td>1.100<br>1.200</td>' in page
    assert '<td>9</td><td>2.25</td>' in page and '<td>2 <small>6.0 KiB</small></td>' in page
    assert '<td>30</td><td>1.00</td><td>1.100</td><td>6</td>' in page
    assert 'default-src \'none\'' in page
    assert '<script' not in page and 'private-fixture-identifier' not in page


def test_report_rejects_markup_in_a_numeric_metric(measurements):
    trials, _, _, _, _ = measurements
    for trial in trials:
        trial['cameras'][0]['source_fps'] = '<img src="https://example.invalid">'
    with pytest.raises(ValueError, match='format code'):
        render_report(*measurements)
