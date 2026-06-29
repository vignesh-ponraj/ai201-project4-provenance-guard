"""Analytics (stretch: detection-patterns dashboard).

Aggregates the audit trail into platform-level metrics:
  - detection patterns: breakdown by attribution tier (and by content type)
  - appeal rate: appeals ÷ classifications
  - average confidence (the extra metric), plus the 'uncertain' rate as a
    health signal — a high uncertain rate means the system is honestly
    declining to guess rather than risking false positives.
"""
from __future__ import annotations

import db


def compute() -> dict:
    contents = db.all_contents()
    total = len(contents)
    appeals = db.count_appeals()

    by_attribution = {"likely_ai": 0, "likely_human": 0, "uncertain": 0}
    by_type: dict[str, int] = {}
    conf_sum = 0.0
    for c in contents:
        by_attribution[c["attribution"]] = by_attribution.get(c["attribution"], 0) + 1
        by_type[c["content_type"]] = by_type.get(c["content_type"], 0) + 1
        conf_sum += c["confidence"]

    avg_conf = round(conf_sum / total, 4) if total else 0.0
    uncertain_rate = round(by_attribution["uncertain"] / total, 4) if total else 0.0
    appeal_rate = round(appeals / total, 4) if total else 0.0

    return {
        "total_submissions": total,
        "by_attribution": by_attribution,
        "by_content_type": by_type,
        "appeals": appeals,
        "appeal_rate": appeal_rate,
        "average_confidence": avg_conf,
        "uncertain_rate": uncertain_rate,
    }


def render_html(stats: dict) -> str:
    a = stats["by_attribution"]
    types = "".join(
        f"<li>{k}: <b>{v}</b></li>" for k, v in stats["by_content_type"].items()
    ) or "<li>—</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Provenance Guard — Analytics</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
         margin: 40px auto; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  .card {{ border: 1px solid #e2e2e2; border-radius: 10px; padding: 16px; }}
  .num {{ font-size: 1.8rem; font-weight: 700; }}
  .ai {{ color: #b00020; }} .human {{ color: #0a7d2c; }} .unc {{ color: #8a6d00; }}
  .muted {{ color: #666; font-size: .85rem; }}
</style></head><body>
  <h1>Provenance Guard — Detection Analytics</h1>
  <p class="muted">Total submissions analyzed: <b>{stats['total_submissions']}</b></p>
  <div class="grid">
    <div class="card"><div class="num ai">{a['likely_ai']}</div>Likely AI</div>
    <div class="card"><div class="num human">{a['likely_human']}</div>Likely human</div>
    <div class="card"><div class="num unc">{a['uncertain']}</div>Uncertain</div>
  </div>
  <div class="grid" style="margin-top:16px">
    <div class="card"><div class="num">{round(stats['appeal_rate']*100)}%</div>Appeal rate
      <div class="muted">{stats['appeals']} appeals</div></div>
    <div class="card"><div class="num">{round(stats['average_confidence']*100)}%</div>Avg confidence</div>
    <div class="card"><div class="num">{round(stats['uncertain_rate']*100)}%</div>Uncertain rate</div>
  </div>
  <h2 style="font-size:1rem;margin-top:24px">By content type</h2>
  <ul>{types}</ul>
  <p class="muted">Raw JSON at <code>GET /analytics</code>.</p>
</body></html>"""
