"""Render measured synthetic stack evidence as a standalone browser report."""

from statistics import median


def render_report(trials, summary, restart):
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
</main>
</body>
</html>
'''
