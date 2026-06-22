"""analytics_store.py
──────────────────
In-memory store for the latest analytics snapshot and LLM solution.

This module keeps only the most recent report in memory. It is intended as a
short-lived cache for the latest analytics payload, not permanent storage.
"""

from __future__ import annotations
import html
import json
import threading
from typing import Any, Dict

_lock = threading.Lock()
_latest: Dict[str, Any] = {}


def set_latest(payload: Dict[str, Any]) -> None:
    """Store the latest report payload in memory."""
    with _lock:
        _latest.clear()
        _latest.update(payload)


def get_latest() -> Dict[str, Any]:
    """Return the latest stored report payload."""
    with _lock:
        return dict(_latest)


def _render_kv_table(data: Any) -> str:
    if not isinstance(data, dict):
        return f"<pre><code>{html.escape(str(data))}</code></pre>"

    rows = []
    for key, value in data.items():
        rows.append(
            f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(json.dumps(value, indent=2))}</td></tr>"
        )
    return (
        "<table class=\"report-table\">"
        "<thead><tr><th>Field</th><th>Value</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_latest_html() -> str:
    """Render the latest report payload into a simple HTML page."""
    payload = get_latest()
    if not payload:
        return "<html><body><h1>No analytics report available</h1></body></html>"

    title = html.escape("Analytics Report")
    timestamp = html.escape(str(payload.get("timestamp", "")))
    snapshot_html = _render_kv_table(payload.get("snapshot", {}))
    conclusions_html = _render_kv_table(payload.get("conclusions", {}))
    solution_payload = payload.get("solution", payload.get("solution_text", {}))
    solution_html = _render_kv_table(solution_payload)

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: Helvetica, Arial, sans-serif; margin: 24px; background: #1e2530; color: #eef2f7; }}
    .container {{ max-width: 1200px; margin: auto; }}
    h1 {{ color: #ffffff; }}
    h2 {{ color: #d4d9e4; }}
    .section {{ margin-bottom: 24px; padding: 20px; border-radius: 18px; background: #262f42; }}
    table.report-table {{ width: 100%; border-collapse: collapse; }}
    table.report-table th, table.report-table td {{ padding: 12px; text-align: left; border-bottom: 1px solid #2f3a55; }}
    table.report-table th {{ background: #1f2a45; color: #b8c1d4; }}
    table.report-table td {{ background: #222b40; color: #e9edf9; font-family: monospace; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    <div class="section"><strong>Generated at</strong>: {timestamp}</div>
    <div class="section"><h2>Snapshot</h2>{snapshot_html}</div>
    <div class="section"><h2>Conclusions</h2>{conclusions_html}</div>
    <div class="section"><h2>LLM Solution</h2>{solution_html}</div>
  </div>
</body>
</html>"""
    return html_text
