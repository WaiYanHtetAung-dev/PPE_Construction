"""Render measured synthetic stack evidence as a standalone browser report."""

from statistics import median


def render_report(trials, summary, restart, reconnect, capacity):
    interval = restart['sample_interval_s']
    windows = [trial for trial in trials if trial['sample_interval_s'] == interval]
    camera_windows = zip(*(trial['cameras'] for trial in windows), strict=True)
    camera_rows = []
    # Interpolate only numeric metrics. Camera names are generated fixture labels.
    for index, (rates, recovery) in enumerate(zip(camera_windows, restart['restart_to_camera_s'], strict=True), 1):
        source = median(row['source_fps'] for row in rates)
        samples = median(row['offered'] / window['measurement_s'] for row, window in zip(rates, windows, strict=True))
        results = median(row['emitted_fps'] for row in rates)
        age = median(row['median_sample_to_result_ms'] for row in rates)
        replacements = sum(row['queue_replacements'] for row in rates)
        rejects = sum(row['policy_rejections'] for row in rates)
        purges = sum(row['queue_purges'] for row in rates)
        camera_rows.append(f'''<tr><th scope="row">Camera {index:d} <small>{rates[0]['input_target_fps']:d} FPS input</small></th>
          <td>{source:.2f}</td><td>{samples:.2f}</td><td>{results:.2f}</td><td>{age:.2f}</td>
          <td>{replacements:d}</td><td>{rejects:d}</td><td>{purges:d}</td><td>{recovery:.3f}</td></tr>''')

    interval_rows = ''.join(
        f'''<tr><th scope="row">{arm['interval_s']:.1f} s</th><td>{arm['windows']:d}</td>
          <td>{arm['total_emitted']:d}</td><td>{arm['total_replacements']:d}</td></tr>'''
        for arm in summary['arms']
    )
    mode_labels = {'eof': 'End of stream', 'stall': 'Frame stall'}
    reconnect_rows = []
    for row in reconnect['cycles']:
        sources, retries, recovery = [], [], []
        for source in row['sources']:
            sources.append(f"Camera {source['camera']:d} ({mode_labels[source['mode']]})")
            retries.append(f"{source['blocked_retries']:d}")
            recovery.append(f"{source['restore_to_result_s']:.3f}")
        reconnect_rows.append(f'''<tr><th scope="row">{'<br>'.join(sources)}</th>
          <td>{row['source_offline_s']:.3f}</td><td>{'<br>'.join(retries)}</td>
          <td>{row['unaffected_results']:d}</td><td>{row['mean_peer_results_per_s']:.2f}</td>
          <td>{row['peak_pending']:d} <small>{row['peak_pending_bytes'] / 1024:.1f} KiB</small></td>
          <td>{row['queue_replacements']:d}</td><td>{'<br>'.join(recovery)}</td></tr>''')
    soak_rows = ''.join(
        f'''<tr><th scope="row">Camera {row['camera']:d}</th><td>{row['offered']:d}</td>
          <td>{row['emitted']:d}</td><td>{row['replaced']:d}</td><td>{row['rejected']:d}</td><td>{row['purged']:d}</td>
          <td>{row['pending_at_shutdown']:d}</td><td>{row['in_flight_at_shutdown']:d}</td></tr>'''
        for row in reconnect['cameras']
    )
    capacity_rows = []
    timing_rows = []
    phase_order = ('decode_first', 'decode_next', 'queue', 'stage', 'worker_total',
                   'eligibility', 'model_load', 'adapter_infer')
    for run, window in enumerate(capacity, 1):
        cameras = window['cameras']
        results = sum(camera['emitted'] for camera in cameras)
        slowest = min(camera['emitted_fps'] for camera in cameras)
        gap = max(camera['max_result_gap_ms'] for camera in cameras) / 1000
        replacements = sum(camera['queue_replacements'] for camera in cameras)
        capacity_rows.append(f'''<tr><th scope="row">{run:d}</th><td>{len(cameras):d}</td>
          <td>{results:d}</td><td>{slowest:.2f}</td><td>{gap:.3f}</td><td>{replacements:d}</td>
          <td>{window['peak_pending']:d} <small>{window['peak_pending_bytes'] / 1024:.1f} KiB</small></td></tr>''')
        timings = window['phase_median_ms']
        cells = ''.join(f'<td>{timings[phase]:.2f}</td>' for phase in phase_order)
        timing_rows.append(f'<tr><th scope="row">{run:d}</th><td>{len(cameras):d}</td>{cells}</tr>')

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Synthetic pilot diagnostics | PPE Construction V2</title>
<style>
  :root {{ color-scheme: light; font: 16px/1.5 system-ui, sans-serif; color: #172d34; background: #f4f7f8; }}
  body {{ margin: 0; }}
  main {{ max-width: 76rem; margin: auto; padding: clamp(1rem, 4vw, 3rem); }}
  h1, h2, p {{ margin: 0 0 .6rem; }}
  h1 {{ font-size: clamp(1.75rem, 4vw, 2.75rem); line-height: 1.15; letter-spacing: -.035em; }}
  h2 {{ font-size: 1.3rem; }}
  h3 {{ font-size: 1.1rem; margin: 1rem 0 .6rem; }}
  p, small {{ color: #435c65; }}
  small {{ display: block; font-size: .8rem; font-weight: normal; }}
  dl {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: .75rem; margin: 1.5rem 0; }}
  dl div, section {{ background: white; border: 1px solid #cbd8dc; border-radius: .55rem; padding: 1rem; }}
  dt {{ color: #435c65; font-size: .85rem; }}
  dd {{ margin: .25rem 0 0; font-size: 1.6rem; font-weight: 700; color: #116053; }}
  section + section {{ margin-top: 1rem; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: right; border-bottom: 1px solid #dce5e8; padding: .65rem .55rem; }}
  th:first-child {{ text-align: left; white-space: nowrap; }}
  thead {{ background: #eaf2f3; }}
  .note {{ margin: .75rem 0 0; font-size: .88rem; }}
</style>
</head>
<body>
<main>
  <header>
    <h1>Synthetic pilot diagnostics</h1>
    <p>PPE Construction V2 · Generated video · Verified ONNX inference over loopback HTTPS</p>
  </header>
  <dl aria-label="Worker restart check">
    <div><dt>Outage request timed out</dt><dd>{restart['outage_dispatch_s']:.3f} s</dd></div>
    <div><dt>Worker HTTPS ready</dt><dd>{restart['worker_tls_ready_s']:.3f} s</dd></div>
    <div><dt>All cameras recovered</dt><dd>{restart['restart_to_all_cameras_s']:.3f} s</dd></div>
  </dl>
  <section aria-labelledby="camera-heading">
    <h2 id="camera-heading">Camera results at {interval:.1f} s sampling</h2>
    <div class="table-wrap" role="region" aria-labelledby="camera-heading" tabindex="0">
      <table aria-labelledby="camera-heading">
        <thead><tr><th scope="col">Fixture</th><th scope="col">Decoded FPS</th><th scope="col">Samples / s</th>
          <th scope="col">Results / s</th><th scope="col">Sample age (ms)</th><th scope="col">Replaced</th>
          <th scope="col">Rejected</th><th scope="col">Purged</th><th scope="col">Recovery (s)</th></tr></thead>
        <tbody>{''.join(camera_rows)}</tbody>
      </table>
    </div>
    <p class="note">Rates and sample ages are medians across {len(windows):d} steady-state windows.
      Sample age starts at sampling. Drop counts are totals across those windows.
      Recovery measures the first fresh result for each camera from the start of the worker restart.</p>
  </section>
  <section aria-labelledby="interval-heading">
    <h2 id="interval-heading">Sampling interval comparison</h2>
    <div class="table-wrap" role="region" aria-labelledby="interval-heading" tabindex="0">
      <table aria-labelledby="interval-heading">
        <thead><tr><th scope="col">Interval</th><th scope="col">Windows</th>
          <th scope="col">Results</th><th scope="col">Pending frames replaced</th></tr></thead>
        <tbody>{interval_rows}</tbody>
      </table>
    </div>
    <p class="note">The balanced comparison and the worker restart are separate exercises in the same synthetic run.</p>
  </section>
  <section aria-labelledby="reconnect-heading">
    <h2 id="reconnect-heading">Source reconnect soak</h2>
    <p>{reconnect['elapsed_s']:.1f} s at {interval:.1f} s sampling with single and overlapping outages.</p>
    <div class="table-wrap" role="region" aria-labelledby="reconnect-heading" tabindex="0">
      <table aria-labelledby="reconnect-heading">
        <thead><tr><th scope="col">Interrupted fixtures</th><th scope="col">Offline (s)</th>
          <th scope="col">Blocked retries</th><th scope="col">Peer results</th><th scope="col">Results / s per peer</th>
          <th scope="col">Peak queued</th><th scope="col">Replaced</th>
          <th scope="col">Restore to result (s)</th></tr></thead>
        <tbody>{''.join(reconnect_rows)}</tbody>
      </table>
    </div>
    <p class="note">Peer rates count results sampled and returned during the outage.
      Queue measurements cover the outage and include any frames already queued at its start.
      Retries and recovery times follow the listed fixture order.</p>
    <h3 id="soak-heading">Soak frame counts</h3>
    <div class="table-wrap" role="region" aria-labelledby="soak-heading" tabindex="0">
      <table aria-labelledby="soak-heading">
        <thead><tr><th scope="col">Fixture</th><th scope="col">Offered</th><th scope="col">Results</th>
          <th scope="col">Replaced</th><th scope="col">Rejected</th><th scope="col">Purged</th>
          <th scope="col">Queued at shutdown</th><th scope="col">In flight at shutdown</th></tr></thead>
        <tbody>{soak_rows}</tbody>
      </table>
    </div>
  </section>
  <section aria-labelledby="capacity-heading">
    <h2 id="capacity-heading">Three- and six-camera comparison</h2>
    <div class="table-wrap" role="region" aria-labelledby="capacity-heading" tabindex="0">
      <table aria-labelledby="capacity-heading">
        <thead><tr><th scope="col">Window</th><th scope="col">Cameras</th><th scope="col">Results</th>
          <th scope="col">Lowest results / s per camera</th><th scope="col">Longest result gap (s)</th>
          <th scope="col">Replaced</th><th scope="col">Peak queued</th></tr></thead>
        <tbody>{''.join(capacity_rows)}</tbody>
      </table>
    </div>
    <p class="note">Four steady windows at {interval:.1f} s sampling. Result gaps include the edges of each
      window. Queue peaks count pending frame payloads.</p>
    <h3 id="timing-heading">Pipeline timing (median ms)</h3>
    <div class="table-wrap" role="region" aria-labelledby="timing-heading" tabindex="0">
      <table aria-labelledby="timing-heading">
        <thead><tr><th scope="col">Window</th><th scope="col">Cameras</th><th scope="col">First frame</th>
          <th scope="col">Next frame</th><th scope="col">Queue wait</th><th scope="col">Gateway staging</th>
          <th scope="col">Worker total</th><th scope="col">Eligibility</th>
          <th scope="col">Model load</th><th scope="col">Adapter inference</th></tr></thead>
        <tbody>{''.join(timing_rows)}</tbody>
      </table>
    </div>
    <p class="note">First frame includes decoder startup. Read waits exclude replay pacing.
      Worker total includes eligibility, verification, model load and inference. Each column is
      summarized independently.</p>
  </section>
</main>
</body>
</html>
'''
