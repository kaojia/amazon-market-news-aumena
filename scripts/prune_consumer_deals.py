#!/usr/bin/env python
"""prune_consumer_deals.py — remove already-published consumer "best deals"
noise cards from daily-report-*.html files, then rebuild index.html.

One-off backfill for cards that slipped in before fetch_and_push.py grew its
source denylist / consumer-deal / seller-signal filters. Reuses the SAME
predicate constants from fetch_and_push so the two stay in lock-step.

- Official Seller Central cards (inside the SC_OFFICIAL marker block, or whose
  region text contains 官方公告) are ALWAYS kept.
- A .card is dropped when its title/summary trips SOURCE_DENYLIST or
  CONSUMER_DEAL_KEYWORDS without a SELLER_SIGNAL_KEYWORDS rescue, or hits a hard
  EXCLUDE_KEYWORD.

Usage:
  python scripts/prune_consumer_deals.py            # prune + rebuild
  python scripts/prune_consumer_deals.py --dry-run  # report only
  python scripts/prune_consumer_deals.py --no-build
"""
from __future__ import annotations

import argparse
import glob
import html
import os
import re
import subprocess
import sys

from fetch_and_push import (
    EXCLUDE_KEYWORDS,
    CONSUMER_DEAL_KEYWORDS,
    SOURCE_DENYLIST,
    SELLER_SIGNAL_KEYWORDS,
)

MARKER_START = "<!-- SC_OFFICIAL_START (injected by inject_sc_news.py) -->"
MARKER_END = "<!-- SC_OFFICIAL_END -->"


def _find_card_spans(text: str):
    """Yield (start, end) offsets of each top-level <div class="...card...">…</div>,
    matching nested <div>s by depth-counting."""
    open_re = re.compile(r'<div\b[^>]*\bclass="[^"]*\bcard\b[^"]*"[^>]*>', re.I)
    div_re = re.compile(r'<div\b[^>]*>|</div>', re.I)
    pos = 0
    while True:
        m = open_re.search(text, pos)
        if not m:
            return
        depth = 0
        for d in div_re.finditer(text, m.start()):
            if d.group(0).lower().startswith("</div"):
                depth -= 1
            else:
                depth += 1
            if depth == 0:
                yield (m.start(), d.end())
                pos = d.end()
                break
        else:
            return  # unbalanced; stop


def _is_noise(card_html: str) -> bool:
    if "官方公告" in card_html:            # official SC card — keep
        return False
    # Judge on the HEADLINE + source only — the summary/impact/action bodies are
    # generated boilerplate ("賣家可關注…") that would falsely trip every signal.
    h3 = re.search(r"<h3>(.*?)</h3>", card_html, re.DOTALL)
    src = re.search(r'<div class="source">(.*?)</div>', card_html, re.DOTALL)
    parts = [h3.group(1) if h3 else "", src.group(0) if src else ""]
    plain = html.unescape(re.sub(r"<[^>]+>", " ", " ".join(parts))).lower()
    # source href (domain) too
    href = re.search(r'<div class="source">.*?href="([^"]*)"', card_html, re.DOTALL)
    if href:
        plain += " " + href.group(1).lower()
    if any(kw.lower() in plain for kw in EXCLUDE_KEYWORDS):
        return True
    # A seller signal (Prime Day, fee/policy/logistics/tax…) rescues the card.
    if any(kw.lower() in plain for kw in SELLER_SIGNAL_KEYWORDS):
        return False
    if any(dom in plain for dom in SOURCE_DENYLIST):
        return True
    if any(kw.lower() in plain for kw in CONSUMER_DEAL_KEYWORDS):
        return True
    return False


def prune_file(path: str, dry_run: bool) -> int:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Protect the official marker block from surgery.
    block_re = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
                          re.DOTALL)
    mblk = block_re.search(content)
    official = mblk.group(0) if mblk else ""
    work = block_re.sub("\x00BLOCK\x00", content) if mblk else content

    spans = list(_find_card_spans(work))
    drop = [(s, e) for (s, e) in spans if _is_noise(work[s:e])]
    if not drop:
        return 0

    for s, e in drop:
        title = re.search(r"<h3>(.*?)</h3>", work[s:e], re.DOTALL)
        t = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else "?"
        print(f"    - {t[:64]}")

    if not dry_run:
        for s, e in reversed(drop):        # delete back-to-front to keep offsets
            work = work[:s] + work[e:]
        work = re.sub(r"\n{3,}", "\n\n", work)
        content = work.replace("\x00BLOCK\x00", official) if mblk else work
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return len(drop)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    total = 0
    for path in sorted(glob.glob("daily-report-*.html")):
        n = prune_file(path, args.dry_run)
        if n:
            print(f"  {path}: {'would drop' if args.dry_run else 'dropped'} {n}")
            total += n
    print(f"\n{'Would drop' if args.dry_run else 'Dropped'} {total} noise card(s) total.")

    if total and not args.dry_run and not args.no_build:
        proc = subprocess.run([sys.executable, "scripts/build.py"],
                              capture_output=True, text=True, encoding="utf-8")
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.exit(f"build.py failed: {proc.stderr}")
        print("  ✅ build.py regenerated index.html")


if __name__ == "__main__":
    main()
