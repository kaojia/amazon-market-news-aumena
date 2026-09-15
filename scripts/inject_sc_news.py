#!/usr/bin/env python
"""
inject_sc_news.py — Inject REAL Seller Central official announcements
(真正的 Seller Central 官方公告) into the day's daily-report-YYYY-MM-DD.html.

Why this is a separate LOCAL step (not part of the GitHub Action):
`amz-sc news list` reaches Amazon's official /seller-news feed, which needs
Midway auth and therefore cannot run on the CI cloud runner. So the CI job
fills the daily-report file with external/RSS news, and THIS script — run
locally after `mwinit -f` — pulls the genuine official announcements and
injects them as extra .card blocks that build.py then folds into index.html.

Design constraints:
- ADDITIVE + IDEMPOTENT: our cards live inside a marker block
  (SC_OFFICIAL_START/END). Re-running replaces only that block; the CI's
  external cards (outside the block) are preserved. If the daily-report file
  doesn't exist yet, we create it with the same wrapper CI uses.
- Marketplace: this identity's /seller-news serves the MENA cluster (IE/SA/AE);
  AU is NOT entitled (verified: even the browser on the AU account gets AE).
  So we pull AE official announcements. --mcid is any accessible seller; the
  feed is carried by the session's regional membership, not the seller.

Usage:
  python scripts/inject_sc_news.py                     # today, AE, 6 articles
  python scripts/inject_sc_news.py --date 2026-09-15 --limit 8
  python scripts/inject_sc_news.py --no-build          # skip build.py rerun
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import subprocess
import sys

# --- config -----------------------------------------------------------------

# /seller-news is carried by the identity's regional membership (MENA → AE),
# not by which seller is selected — BUT --marketplace AE only validates for an
# AE-homed seller (an IE-homed seller 606s on the AE Lens switch). So default to
# a real AE seller. Plustek AE (CID 290673447112). mismatch=False verified.
DEFAULT_MCID = "A33U8K4OVYB8JR"          # Plustek AE (verified: served=AE)
DEFAULT_MARKETPLACE = "AE"
DEFAULT_LIMIT = 6

# Fetch Amazon's OWN Chinese translation (AE offers zh-CN, Simplified) rather
# than machine-translating ourselves, then convert Simplified→Traditional to
# match the dashboard's zh-TW. --lang zh-Hant/zh-TW would just fall back to
# English (AE doesn't offer Traditional), so we take zh-CN + OpenCC.
DEFAULT_LANG = "zh-CN"

# Local amz-sc install isn't on PATH (see memory: amz-sc-path-workaround).
AMZ_SC_SCRIPTS = r"C:\Users\chiawenk\AppData\Roaming\Python\Python313\Scripts"

MARKER_START = "<!-- SC_OFFICIAL_START (injected by inject_sc_news.py) -->"
MARKER_END = "<!-- SC_OFFICIAL_END -->"

# amz-sc news category key -> (Chinese label, priority). Labels are chosen so
# build.py's map_tags() picks a sensible tag where possible (法規→合規,
# 物流→物流); unknown labels fall back to 總經, which is fine.
CATEGORY_ZH = {
    "news_cat_policy_and_compliance":        ("政策法規", "high"),
    "news_cat_account_health":               ("帳戶健康", "high"),
    "news_cat_manage_inventory":             ("庫存物流", "medium"),
    "news_cat_fulfill_orders":               ("物流履約", "medium"),
    "news_cat_account_setup_and_management": ("帳戶管理", "medium"),
    "news_cat_create_and_manage_listings":   ("商品刊登", "medium"),
    "news_cat_manage_your_brand":            ("品牌管理", "medium"),
    "news_cat_manage_buyer_experience":      ("買家體驗", "medium"),
    "news_cat_grow_your_business":           ("業務成長", "medium"),
    "news_cat_learning_and_development":     ("學習發展", "medium"),
    "news_cat_about_amazon":                 ("平台公告", "medium"),
}


# --- amz-sc call -------------------------------------------------------------

def fetch_official_news(mcid: str, marketplace: str, limit: int,
                        lang: str | None) -> dict:
    """Run `amz-sc news list` and return the parsed results dict."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if os.path.isdir(AMZ_SC_SCRIPTS):
        env["PATH"] = AMZ_SC_SCRIPTS + os.pathsep + env.get("PATH", "")

    cmd = [
        "amz-sc", "--mcid", mcid, "--marketplace", marketplace, "--agent",
        "news", "list", "--limit", str(limit),
    ]
    if lang:
        cmd += ["--lang", lang]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, encoding="utf-8",
            timeout=120,
        )
    except FileNotFoundError:
        sys.exit("amz-sc not found on PATH. Run the editable install first "
                 "(see the amz-sc skill setup) or fix AMZ_SC_SCRIPTS.")

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        sys.exit(f"amz-sc news list failed (exit {proc.returncode}): {err}\n"
                 "If auth-related, run `mwinit -f` and retry.")

    try:
        payload = json.loads(proc.stdout)
    except ValueError as e:
        sys.exit(f"could not parse amz-sc output: {e}\n{proc.stdout[:400]}")

    return payload.get("results", payload)


# --- Simplified -> Traditional -----------------------------------------------

def _make_s2t():
    """Return a Simplified→Traditional (Taiwan) converter, or identity."""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")  # Simplified → Traditional w/ Taiwan phrasing
        return lambda s: cc.convert(s) if s else s
    except Exception:
        print("  ⚠️ opencc unavailable — keeping Simplified Chinese as-is.")
        return lambda s: s


def convert_articles(articles: list[dict], s2t) -> None:
    """In-place convert title/summary of each article to Traditional Chinese."""
    for a in articles:
        a["title"] = s2t(a.get("title", ""))
        a["summary"] = s2t(a.get("summary", ""))


# --- external-title translation ----------------------------------------------
# The CI job also translates titles (fetch_and_push.translate_news_items), but
# its GoogleTranslator often gets rate-limited on the GitHub runner and silently
# leaves English. We run locally as a safety net: any still-English <h3> outside
# our official block gets translated (Google → MyMemory fallback).

def _is_mostly_chinese(text: str) -> bool:
    if not text:
        return True
    cn = sum(1 for c in text if "一" <= c <= "鿿")
    return cn / max(len(text), 1) > 0.3


def _translate_en(text: str) -> str:
    """Translate to Traditional Chinese; try Google, fall back to MyMemory."""
    for factory in (
        lambda: __import__("deep_translator").GoogleTranslator(source="auto", target="zh-TW"),
        lambda: __import__("deep_translator").MyMemoryTranslator(source="en-US", target="zh-TW"),
    ):
        try:
            return factory().translate(text) or text
        except Exception:
            continue
    return text


def translate_external_titles(filepath: str) -> int:
    """Translate English <h3> titles OUTSIDE the official marker block. Returns
    the number of titles translated."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Protect our official block: split it out, translate only the rest.
    block_re = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
                          re.DOTALL)
    m = block_re.search(content)
    official = m.group(0) if m else ""
    outer = block_re.sub("\x00BLOCK\x00", content) if m else content

    count = 0

    def _sub(mo: "re.Match") -> str:
        nonlocal count
        title = html.unescape(mo.group(1)).strip()
        if not title or _is_mostly_chinese(title):
            return mo.group(0)
        zh = _translate_en(title)
        if zh and zh != title:
            count += 1
            return f"<h3>{_esc(zh)}</h3>"
        return mo.group(0)

    outer = re.sub(r"<h3>(.*?)</h3>", _sub, outer, flags=re.DOTALL)
    content = outer.replace("\x00BLOCK\x00", official) if m else outer

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return count


# --- card rendering ----------------------------------------------------------

def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def render_card(article: dict) -> str:
    mp = article.get("marketplace") or ""
    zh_label, priority = CATEGORY_ZH.get(article.get("category"), ("官方公告", "medium"))
    p_class = f" {priority}" if priority in ("high", "medium") else ""

    title = _esc(article.get("title", ""))
    summary = _esc(article.get("summary", ""))
    region = _esc(f"{mp} - 官方公告 · {zh_label}")
    url = _esc(article.get("url", ""))
    date = _esc(article.get("creation_date") or "")

    action = "Amazon 官方公告，請依公告內容確認對帳戶/刊登/合規的影響與時程。"
    source_html = ""
    if url:
        source_html = (f'<div class="source">'
                       f'<a href="{url}">Amazon Seller Central 官方公告 ({date})</a>'
                       f'</div>')

    return f"""    <div class="card{p_class}">
        <h3>{title}</h3>
        <div class="region">{region}</div>
        <div class="summary">{summary}</div>
        <div class="impact"><p>{summary}</p></div>
        <div class="action"><p>{_esc(action)}</p></div>
        {source_html}
    </div>
"""


def build_block(articles: list[dict]) -> str:
    cards = "\n".join(render_card(a) for a in articles)
    return f"{MARKER_START}\n{cards}\n    {MARKER_END}"


# --- daily-report file surgery ----------------------------------------------

EMPTY_REPORT = """<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><title>Daily Report {date}</title></head>
<body>

</body>
</html>
"""


def inject(filepath: str, date: str, block: str) -> None:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = EMPTY_REPORT.format(date=date)

    # Drop any previous injected block (idempotent re-run).
    content = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "", content, flags=re.DOTALL,
    )

    # Insert our block right after <body> so official announcements lead.
    m = re.search(r"<body[^>]*>", content)
    if m:
        idx = m.end()
        content = content[:idx] + "\n" + block + "\n" + content[idx:]
    else:
        # No <body> (malformed/stub) — rebuild minimally.
        content = EMPTY_REPORT.format(date=date).replace(
            "<body>\n", f"<body>\n{block}\n", 1)

    # Tidy leftover blank lines from the removal.
    content = re.sub(r"\n{3,}", "\n\n", content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


# --- main --------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, local).")
    ap.add_argument("--mcid", default=DEFAULT_MCID)
    ap.add_argument("--marketplace", default=DEFAULT_MARKETPLACE)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--lang", default=DEFAULT_LANG,
                    help="Feed locale from Amazon (default zh-CN, then converted "
                         "to Traditional). Pass 'en' to keep English.")
    ap.add_argument("--no-translate", action="store_true",
                    help="Skip translating external (non-official) English titles.")
    ap.add_argument("--no-build", action="store_true",
                    help="Skip re-running build.py afterwards.")
    args = ap.parse_args()

    date = args.date or _dt.date.today().isoformat()

    # Run from repo root regardless of cwd.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    result = fetch_official_news(args.mcid, args.marketplace, args.limit, args.lang)
    served = result.get("served_marketplace")
    if result.get("marketplace_mismatch"):
        print(f"  ⚠️ requested {result.get('requested_marketplace')} but feed "
              f"served {served} (expected — this identity's cluster).")
    articles = result.get("articles", [])
    if not articles:
        sys.exit("no official announcements returned — nothing to inject.")

    # Amazon serves zh-CN (Simplified); convert to Traditional for the dashboard.
    if args.lang and args.lang.lower().startswith("zh"):
        convert_articles(articles, _make_s2t())

    print(f"  fetched {len(articles)} official {served} announcements ({args.lang})")
    block = build_block(articles)
    filepath = f"daily-report-{date}.html"
    inject(filepath, date, block)
    print(f"  📝 injected {len(articles)} official cards into {filepath}")

    if not args.no_translate:
        n = translate_external_titles(filepath)
        print(f"  🌐 translated {n} external title(s) to Traditional Chinese")

    if not args.no_build:
        proc = subprocess.run([sys.executable, "scripts/build.py"],
                              capture_output=True, text=True, encoding="utf-8")
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.exit(f"build.py failed: {proc.stderr}")
        print("  ✅ build.py regenerated index.html")


if __name__ == "__main__":
    main()
