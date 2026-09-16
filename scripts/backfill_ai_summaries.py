#!/usr/bin/env python
"""backfill_ai_summaries.py — retro-fit real Gemini summaries onto cards that
were published before the Gemini enrichment step existed.

Those older cards carry a generic category TEMPLATE as their summary/impact
(often unrelated to the headline) and "請關注後續發展" as the action, so every
card looks empty beyond its title. This one-off walks each daily-report-*.html,
sends the still-template card headlines to Gemini in batches, and rewrites each
card's summary / impact / action + marks it ai-summary. Then rebuilds index.html.

Requires GEMINI_API_KEY in the environment (same key the daily workflow uses).

Usage:
  GEMINI_API_KEY=... python scripts/backfill_ai_summaries.py
  GEMINI_API_KEY=... python scripts/backfill_ai_summaries.py --dry-run
  GEMINI_API_KEY=... python scripts/backfill_ai_summaries.py --no-build
"""
from __future__ import annotations

import argparse
import glob
import html
import os
import re
import subprocess
import sys

import fetch_and_push as F

CHUNK = 20  # headlines per Gemini request


def _find_card_spans(text: str):
    """Yield (start, end) of each top-level <div class="...card...">…</div>."""
    open_re = re.compile(r'<div\b[^>]*\bclass="[^"]*\bcard\b[^"]*"[^>]*>', re.I)
    div_re = re.compile(r'<div\b[^>]*>|</div>', re.I)
    pos = 0
    while True:
        m = open_re.search(text, pos)
        if not m:
            return
        depth = 0
        for d in div_re.finditer(text, m.start()):
            depth += -1 if d.group(0).lower().startswith("</div") else 1
            if depth == 0:
                yield (m.start(), d.end())
                pos = d.end()
                break
        else:
            return


def _text(card: str, pattern: str) -> str:
    m = re.search(pattern, card, re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def _parse_region(region: str):
    """'AE - 稅務' -> ('AE', '稅務')."""
    parts = re.split(r"\s*-\s*", region, maxsplit=1)
    mkt = parts[0].strip() if parts else ""
    cat = parts[1].strip() if len(parts) > 1 else ""
    return mkt, cat


def _rewrite(card: str, summary: str, impact: str, action: str) -> str:
    esc = lambda s: html.escape(s, quote=False)
    # mark card ai-summary (once)
    if "ai-summary" not in card.split(">", 1)[0]:
        card = re.sub(r'(<div class="card[^"]*)"', r'\1 ai-summary"', card, count=1)
    card = re.sub(r'(<div class="summary">).*?(</div>)',
                  lambda m: m.group(1) + esc(summary) + m.group(2), card, count=1, flags=re.DOTALL)
    card = re.sub(r'(<div class="impact"><p>).*?(</p>)',
                  lambda m: m.group(1) + esc(impact) + m.group(2), card, count=1, flags=re.DOTALL)
    card = re.sub(r'(<div class="action"><p>).*?(</p>)',
                  lambda m: m.group(1) + esc(action) + m.group(2), card, count=1, flags=re.DOTALL)
    return card


def backfill_file(path: str, dry_run: bool) -> int:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    spans = list(_find_card_spans(content))
    jobs = []  # (span, item-dict)
    for s, e in spans:
        card = content[s:e]
        head = card.split(">", 1)[0]
        if "ai-summary" in head:            # already enriched
            continue
        if "官方公告" in card:               # official cards have their own real body
            continue
        title = _text(card, r"<h3>(.*?)</h3>")
        if not title:
            continue
        mkt, cat = _parse_region(_text(card, r'<div class="region">(.*?)</div>'))
        jobs.append(((s, e), {"title": title, "marketplace": mkt, "category": cat}))

    if not jobs:
        return 0

    # Enrich in chunks via Gemini.
    enriched = []
    for i in range(0, len(jobs), CHUNK):
        chunk = jobs[i:i + CHUNK]
        items = [dict(j[1]) for j in chunk]
        F.gemini_enrich(items)
        enriched.extend(items)

    # Apply back-to-front so offsets stay valid.
    updated = 0
    new_content = content
    for (span, _), item in sorted(zip(jobs, enriched), key=lambda x: x[0][0][0], reverse=True):
        if not item.get("ai"):
            continue
        s, e = span
        new_content = new_content[:s] + _rewrite(new_content[s:e],
                                                 item.get("summary", ""),
                                                 item.get("impact", ""),
                                                 item.get("action", "")) + new_content[e:]
        updated += 1

    if updated and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    return updated


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    if not F.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY not set — cannot backfill.")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    total = 0
    for path in sorted(glob.glob("daily-report-*.html")):
        n = backfill_file(path, args.dry_run)
        if n:
            print(f"  {path}: {'would enrich' if args.dry_run else 'enriched'} {n}")
            total += n
    print(f"\n{'Would enrich' if args.dry_run else 'Enriched'} {total} card(s) total.")

    if total and not args.dry_run and not args.no_build:
        proc = subprocess.run([sys.executable, "scripts/build.py"],
                              capture_output=True, text=True, encoding="utf-8")
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.exit(f"build.py failed: {proc.stderr}")
        print("  ✅ build.py regenerated index.html")


if __name__ == "__main__":
    main()
