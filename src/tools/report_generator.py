"""
Custom HTML Report Generator
-----------------------------
Parses pytest -v --tb=short output and generates a beautiful
self-contained dark-theme HTML report.  No external deps needed.
"""

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_tests(logs: str) -> list:
    """Return list of {name, result, failure_log} from verbose pytest output."""
    tests = []
    for m in re.finditer(
        r'[\w./\\-]+\.py::(test_\w+)\s+(PASSED|FAILED|ERROR|SKIPPED)',
        logs, re.MULTILINE
    ):
        tests.append({"name": m.group(1), "result": m.group(2), "failure_log": ""})

    # Attach failure blocks
    trimmed = logs.split("short test summary info")[0]
    for m in re.finditer(r'_{10,}\s+(test_\w+)\s+_{10,}\n(.*?)(?=_{10,}|\Z)',
                         trimmed, re.DOTALL):
        for t in tests:
            if t["name"] == m.group(1):
                t["failure_log"] = m.group(2).strip()
    return tests


def _parse_docstrings(code: str) -> dict:
    """Extract {test_name: docstring} from generated Python source."""
    docs = {}
    for m in re.finditer(
        r'def (test_\w+)\s*\([^)]*\)\s*:\s*"""(.*?)"""', code, re.DOTALL
    ):
        docs[m.group(1)] = m.group(2).strip()
    return docs


def _summary(logs: str) -> dict:
    passed = int(m.group(1)) if (m := re.search(r'(\d+) passed', logs)) else 0
    failed = int(m.group(1)) if (m := re.search(r'(\d+) failed', logs)) else 0
    errors = int(m.group(1)) if (m := re.search(r'(\d+) error',  logs)) else 0
    dur    = m.group(1) if (m := re.search(r'in (\d+\.?\d*)s', logs)) else "N/A"
    return {"passed": passed, "failed": failed + errors,
            "total": passed + failed + errors, "duration": dur}


def _fmt(name: str) -> str:
    return name.removeprefix("test_").replace("_", " ").title()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def generate_html_report(
    logs: str,
    output_path: str,
    test_code: str = "",
    target_url: str = "",
    pr_number: str = "",
    github_repo: str = "",
) -> None:
    """Write a modern self-contained HTML report to output_path."""

    tests  = _parse_tests(logs)
    docs   = _parse_docstrings(test_code)
    stats  = _summary(logs)
    ts     = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    for t in tests:
        t["doc"] = docs.get(t["name"], "")

    ok        = stats["failed"] == 0
    s_col     = "#10b981" if ok else "#ef4444"
    s_txt     = "ALL TESTS PASSED" if ok else f"{stats['failed']} TEST(S) FAILED"
    s_ico     = "✅" if ok else "❌"
    progress  = round(stats["passed"] / stats["total"] * 100) if stats["total"] else 0

    # ── cards ──────────────────────────────────────────────────────────────
    cards = []
    for t in tests:
        ip   = t["result"] == "PASSED"
        cc   = "card-pass" if ip else "card-fail"
        bc   = "badge-pass" if ip else "badge-fail"
        icon = "✓" if ip else "✗"

        doc_html = (
            f'<div class="intent"><b>📋 Intent</b><p>{_esc(t["doc"])}</p></div>'
            if t["doc"] else ""
        )
        fail_html = (
            f'<div class="failure"><b>🔴 Failure Detail</b>'
            f'<pre>{_esc(t["failure_log"])}</pre></div>'
            if t["failure_log"] else ""
        )

        cards.append(f"""
        <div class="card {cc}">
          <div class="card-hdr">
            <div class="ci {bc}">{icon}</div>
            <div style="flex:1;min-width:0">
              <div class="cn">{_fmt(t["name"])}</div>
              <div class="cid">{t["name"]}</div>
            </div>
            <span class="badge {bc}">{t["result"]}</span>
          </div>
          {doc_html}{fail_html}
        </div>""")

    cards_html = "\n".join(cards) or '<p class="none">No test results found.</p>'

    # ── meta pills ─────────────────────────────────────────────────────────
    pills = []
    if pr_number and pr_number != "0":
        pills.append(f'<div class="pill">🔗 PR <b>#{pr_number}</b></div>')
    if target_url:
        pills.append(f'<div class="pill">🌐 <b>{target_url}</b></div>')
    pills.append(f'<div class="pill">⏱ <b>{stats["duration"]}s</b></div>')
    pills.append(f'<div class="pill">🧪 <b>{stats["total"]} tests</b></div>')
    pills_html = "\n".join(pills)

    footer_href = f"https://github.com/{github_repo}" if github_repo else "#"

    # ── full HTML ──────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AI Test Report – PR#{pr_number or "local"}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0d1017;--sf:#141824;--sf2:#1c2135;--bd:#252d45;
  --tx:#dde1f0;--mu:#6b7799;--pa:#10b981;--fa:#ef4444;--ac:#818cf8;--r:14px}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);
  color:var(--tx);min-height:100vh;padding-bottom:60px;line-height:1.5}}
/* Hero */
.hero{{background:linear-gradient(135deg,#141824,#0d1017 50%,#160d2a);
  border-bottom:1px solid var(--bd);padding:44px 48px 36px;position:relative;overflow:hidden}}
.hero::before{{content:'';position:absolute;top:-80px;right:-80px;width:400px;height:400px;
  background:radial-gradient(circle,rgba(129,140,248,.12),transparent 70%);pointer-events:none}}
.eyebrow{{font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;
  color:var(--ac);margin-bottom:10px}}
.hero h1{{font-size:28px;font-weight:800;color:#fff;margin-bottom:4px}}
.hero p{{font-size:13px;color:var(--mu)}}
.pills{{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}}
.pill{{display:flex;align-items:center;gap:6px;background:var(--sf2);
  border:1px solid var(--bd);border-radius:999px;padding:5px 14px;
  font-size:12px;color:var(--mu)}}
.pill b{{color:var(--tx)}}
/* Status */
.status{{display:flex;align-items:center;gap:16px;
  background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);
  padding:20px 28px;margin:28px 48px 0;border-left:4px solid {s_col}}}
.si{{font-size:30px}}
.st{{font-size:20px;font-weight:700;color:{s_col}}}
.ss{{font-size:13px;color:var(--mu);margin-top:3px}}
/* Progress bar */
.prog-wrap{{margin:24px 48px 0}}
.prog-label{{font-size:12px;color:var(--mu);margin-bottom:6px}}
.prog-bar{{height:8px;background:var(--sf2);border-radius:99px;overflow:hidden}}
.prog-fill{{height:100%;border-radius:99px;
  background:linear-gradient(90deg,var(--pa),#34d399);
  width:{progress}%;transition:width .5s ease}}
/* Stats */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:14px;margin:24px 48px 0}}
.sc{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);
  padding:18px 20px}}
.sc .lbl{{font-size:11px;font-weight:600;text-transform:uppercase;
  letter-spacing:.1em;color:var(--mu)}}
.sc .val{{font-size:30px;font-weight:700;margin-top:4px}}
.green{{color:var(--pa)}} .red{{color:var(--fa)}}
.purple{{color:var(--ac)}} .white{{color:var(--tx)}}
/* Section */
.section{{margin:32px 48px 0}}
.sec-title{{font-size:12px;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:var(--mu);margin-bottom:14px;
  padding-bottom:10px;border-bottom:1px solid var(--bd)}}
/* Cards */
.card{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);
  margin-bottom:12px;overflow:hidden;transition:transform .15s,box-shadow .15s}}
.card:hover{{transform:translateY(-1px);box-shadow:0 4px 24px rgba(0,0,0,.35)}}
.card-pass{{border-left:4px solid var(--pa)}}
.card-fail{{border-left:4px solid var(--fa)}}
.card-hdr{{display:flex;align-items:center;gap:14px;padding:16px 20px}}
.ci{{width:36px;height:36px;border-radius:50%;display:flex;
  align-items:center;justify-content:center;font-size:18px;font-weight:700;flex-shrink:0}}
.badge-pass.ci{{background:rgba(16,185,129,.15);color:var(--pa)}}
.badge-fail.ci{{background:rgba(239,68,68,.15);color:var(--fa)}}
.cn{{font-size:14px;font-weight:600;color:var(--tx)}}
.cid{{font-size:11px;color:var(--mu);font-family:monospace;margin-top:2px}}
.badge{{padding:3px 12px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.08em;flex-shrink:0}}
.badge-pass{{background:rgba(16,185,129,.15);color:var(--pa)}}
.badge-fail{{background:rgba(239,68,68,.15);color:var(--fa)}}
/* Intent */
.intent{{border-top:1px solid var(--bd);padding:12px 20px;font-size:13px;color:var(--mu)}}
.intent b{{color:var(--ac);display:block;margin-bottom:4px;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em}}
.intent p{{color:var(--tx);line-height:1.6}}
/* Failure */
.failure{{border-top:1px solid var(--bd);padding:14px 20px}}
.failure b{{color:var(--fa);font-size:11px;text-transform:uppercase;
  letter-spacing:.08em;display:block;margin-bottom:8px}}
.failure pre{{background:#08090f;border:1px solid var(--bd);border-radius:8px;
  padding:12px 14px;font-family:'Courier New',monospace;font-size:12px;
  line-height:1.6;color:#c9d1d9;white-space:pre-wrap;overflow-x:auto;
  max-height:280px;overflow-y:auto}}
.none{{color:var(--mu);padding:20px 0}}
/* Footer */
footer{{text-align:center;margin-top:48px;font-size:11px;color:var(--mu)}}
footer a{{color:var(--ac);text-decoration:none}}
</style>
</head>
<body>
<div class="hero">
  <div class="eyebrow">Autonomous AI Testing Agent</div>
  <h1>Test Execution Report</h1>
  <p>Generated {ts}</p>
  <div class="pills">{pills_html}</div>
</div>

<div class="status">
  <div class="si">{s_ico}</div>
  <div>
    <div class="st">{s_txt}</div>
    <div class="ss">{stats["passed"]} passed &middot; {stats["failed"]} failed
      &middot; {stats["total"]} total &middot; {stats["duration"]}s</div>
  </div>
</div>

<div class="prog-wrap">
  <div class="prog-label">Pass rate: {progress}%</div>
  <div class="prog-bar"><div class="prog-fill"></div></div>
</div>

<div class="stats">
  <div class="sc"><div class="lbl">Passed</div><div class="val green">{stats["passed"]}</div></div>
  <div class="sc"><div class="lbl">Failed</div><div class="val red">{stats["failed"]}</div></div>
  <div class="sc"><div class="lbl">Total</div><div class="val purple">{stats["total"]}</div></div>
  <div class="sc"><div class="lbl">Duration</div><div class="val white">{stats["duration"]}s</div></div>
</div>

<div class="section">
  <div class="sec-title">Test Results</div>
  {cards_html}
</div>

<footer>Generated by <a href="{footer_href}">Autonomous AI Testing Agent</a></footer>
</body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ReportGen] Custom HTML report written → {output_path}")
