#!/usr/bin/env python
"""
inject_sc_news.py — Inject REAL Seller Central official announcements
(真正的 Seller Central 官方公告) into the day's daily-report-YYYY-MM-DD.html.

Why this is a separate LOCAL step (not part of the GitHub Action):
the official /seller-news feed needs Midway auth and therefore cannot run on
the CI cloud runner. So the CI job fills the daily-report file with
external/RSS news, and THIS script — run locally — pulls the genuine official
announcements and injects them as extra .card blocks that build.py then folds
into index.html.

How it fetches (2026-09-30 rewrite — browser-driven):
Instead of the `amz-sc` CLI (whose Lens marketplace-switch is sticky: it can
move the session forward AE→AU but not back, so AE and AU were mutually
exclusive per run), we drive the user's real logged-in Chrome via
amz-chromebridge. The /seller-news page has a top-right COUNTRY dropdown
(a <kat-dropdown>) that is DECOUPLED from the account switcher and lists all
23 marketplaces. A real (trusted) click on it writes a per-session preference
(with the page's CSRF token) and the feed follows — verified we can pull UAE
(=dashboard "AE") and Australia (AU) back-to-back from ONE session, with no
marketplace-homed seller required. Raw fetch()/synthetic events fail (missing
CSRF token; the ?marketplaceId= query param is ignored) — only trusted clicks
switch it, which is exactly what amz-chromebridge sends.

Prereq: the user's Chrome is open + logged in to sellercentral.amazon.dev
(Midway). Run `mwinit -f` first if the session has lapsed. The script opens a
/seller-news tab itself if one isn't already present.

Design constraints:
- ADDITIVE + IDEMPOTENT: our cards live inside a marker block
  (SC_OFFICIAL_START/END). Re-running replaces only that block; the CI's
  external cards (outside the block) are preserved. If the daily-report file
  doesn't exist yet, we create it with the same wrapper CI uses.

Usage:
  python scripts/inject_sc_news.py                     # today, AE+AU, 6 each
  python scripts/inject_sc_news.py --date 2026-09-15 --limit 8
  python scripts/inject_sc_news.py --markets AU        # only AU
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
import time

# --- config -----------------------------------------------------------------

# amz-chromebridge CLI. Override with AMZ_CB_PY if the plugin lives elsewhere.
CB_PY = os.environ.get(
    "AMZ_CB_PY",
    r"C:\Users\chiawenk\AmzClaudeSkills\plugins\amz-toolbox\skills\amz-chromebridge\cb.py",
)
SELLER_NEWS_URL = "https://www.sellercentral.amazon.dev/seller-news"

# Marketplace id -> short label used on the cards / for --markets selection.
# "AE" on the dashboard = amazon.ae = United Arab Emirates (A2VIGQ35RCS4UG).
MARKET_LABELS = {
    "A2VIGQ35RCS4UG": "AE",
    "A39IBJ37TRP1C6": "AU",
    "A17E79C6D8DWNP": "SA",
    "A28R8C7NBKEWEA": "IE",
}
LABEL_TO_ID = {v: k for k, v in MARKET_LABELS.items()}

# Markets to pull official Seller News from, in order. The browser country
# dropdown reaches ANY of these regardless of the logged-in account's home
# marketplace (verified: a Saudi-Arabia account still serves AU when selected).
DEFAULT_MARKETS = [
    ("A2VIGQ35RCS4UG", "AE"),   # United Arab Emirates (amazon.ae)
    ("A39IBJ37TRP1C6", "AU"),   # Australia
]

DEFAULT_LIMIT = 6

MARKER_START = "<!-- SC_OFFICIAL_START (injected by inject_sc_news.py) -->"
MARKER_END = "<!-- SC_OFFICIAL_END -->"

# Seconds to wait after clicking a marketplace option before fetching, to let
# the preference PUT + client-side data refetch settle.
SWITCH_SETTLE_SECS = 3.5

# nameStringId (from appInfo.categoryList) -> (Chinese label, priority). Labels
# are chosen so build.py's map_tags() picks a sensible tag where possible; unknown
# labels fall back to 官方公告, which is fine.
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


# --- amz-chromebridge driver -------------------------------------------------

def _cb(*args: str, timeout: int = 90):
    """Run cb.py with args, return the parsed `result`. Raises on failure."""
    try:
        proc = subprocess.run(
            [sys.executable, CB_PY, *args],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
    except FileNotFoundError:
        sys.exit(f"amz-chromebridge CLI not found at {CB_PY}. Set AMZ_CB_PY to "
                 "point at the plugin's cb.py.")
    except subprocess.TimeoutExpired:
        sys.exit(f"cb.py {args[0] if args else ''} timed out.")
    if proc.returncode != 0:
        sys.exit(f"cb.py {' '.join(args[:2])} failed: "
                 f"{(proc.stderr or proc.stdout).strip()}")
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        sys.exit(f"cb.py {' '.join(args[:2])} returned non-JSON:\n"
                 f"{proc.stdout[:300]}")
    if not payload.get("ok"):
        sys.exit(f"cb.py {' '.join(args[:2])} error: {payload.get('error')}\n"
                 "If it's a connection error, open Chrome and click the "
                 "amz-chromebridge extension once. If auth-related, run "
                 "`mwinit -f` and reload the Seller Central tab.")
    return payload.get("result")


def _cb_eval(tab: int, code: str):
    """Run JS in the tab; return the evaluated value (unwrapped)."""
    res = _cb("eval", "--tab", str(tab), "--code", code)
    return res.get("value") if isinstance(res, dict) else res


def ensure_seller_news_tab() -> int:
    """Return the id of a /seller-news tab, opening one if needed."""
    tabs = _cb("list_tabs")
    if isinstance(tabs, dict):
        tabs = tabs.get("tabs", [])
    for t in tabs:
        if "sellercentral.amazon.dev/seller-news" in (t.get("url") or ""):
            return t["id"]

    print("  no /seller-news tab open — opening one …")
    res = _cb("open_tab", "--url", SELLER_NEWS_URL)
    tab_id = res.get("id") if isinstance(res, dict) else res
    # Give the SPA time to authenticate + render __NEXT_DATA__.
    for _ in range(15):
        time.sleep(2)
        ok = _cb_eval(tab_id,
                      "!!(window.__NEXT_DATA__ && document.querySelector('kat-dropdown'))")
        if ok is True:
            return tab_id
    sys.exit("Seller News page didn't finish loading — is Chrome logged in to "
             "sellercentral.amazon.dev? Try `mwinit -f` then retry.")


_SWITCH_OPEN_JS = (
    "(function(){var d=document.querySelector('kat-dropdown');"
    "if(!d||!d.shadowRoot)return 'no-dropdown';"
    "var h=d.shadowRoot.querySelector('.select-header');"
    "if(!h)return 'no-header';h.click();return 'opened';})()"
)


def switch_marketplace(tab: int, mkt_id: str, label: str) -> None:
    """Trusted-click the country dropdown open, then click the target option.
    Retries until the dropdown's own value reflects the pick (the server-side
    preference propagation is then polled by the caller's fetch)."""
    select_js = (
        "(function(){var o=document.querySelector('kat-option[value=\"%s\"]');"
        "if(!o)return 'no-option';o.click();return 'selected';})()" % mkt_id
    )
    val_js = ("var d=document.querySelector('kat-dropdown');"
              "d?d.getAttribute('value'):''")
    for attempt in range(4):
        if _cb_eval(tab, val_js) == mkt_id:
            time.sleep(SWITCH_SETTLE_SECS)
            return
        if _cb_eval(tab, _SWITCH_OPEN_JS) != "opened":
            sys.exit("could not open the Seller News country dropdown "
                     "(page layout changed?).")
        time.sleep(1)
        if _cb_eval(tab, select_js) != "selected":
            sys.exit(f"country option for {label} ({mkt_id}) not found in dropdown.")
        time.sleep(1.5)
    time.sleep(SWITCH_SETTLE_SECS)


_FETCH_JS = r"""(async()=>{try{
var nd=window.__NEXT_DATA__;var bid=nd.buildId;
var r=await fetch('/seller-news/_next/data/'+bid+'/articles.json?dateFilter=ALL_TIME',{headers:{'x-nextjs-data':'1'}});
var j=await r.json();var pp=j.pageProps||{};var st=pp.initialState||{};
var arts=(st.articleList||{}).articles||[];
var ai=st.appInfo||{};
var catMap={};(ai.categoryList||[]).forEach(function(c){catMap[c.id]=c.nameStringId;});
function strip(h){var d=document.createElement('div');d.innerHTML=h||'';return (d.textContent||'').replace(/\s+/g,' ').trim();}
var out=arts.slice(0,%d).map(function(a){return{
title:a.title,
summary:strip(a.content).slice(0,300),
url:'https://www.sellercentral.amazon.dev/seller-news/articles/'+a.id,
creation_date:new Date(a.creationDate).toISOString().slice(0,10),
category:catMap[a.categoryId]||'',
marketplace:a.marketplaceId};});
return JSON.stringify({selected:ai.selectedMarketplaceId,served:(arts[0]||{}).marketplaceId,total:pp.totalCount,articles:out});
}catch(e){return JSON.stringify({error:String(e)});}})()"""


def fetch_marketplace_articles(tab: int, mkt_id: str, label: str,
                               limit: int) -> list[dict]:
    """Switch to `mkt_id` and return up to `limit` mapped official articles.
    Returns [] (with a warning) if the served feed doesn't match the request."""
    switch_marketplace(tab, mkt_id, label)
    # The dropdown value updates instantly client-side, but the server-side
    # preference that the SSR feed reads can lag — poll until served matches.
    data = {}
    for attempt in range(5):
        raw = _cb_eval(tab, _FETCH_JS % limit)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            data = {}
        if data.get("served") == mkt_id:
            break
        time.sleep(2)
    if data.get("error"):
        print(f"  ⚠️ {label}: feed fetch error {data['error']} — skipping.")
        return []
    served = data.get("served")
    if served and served != mkt_id:
        print(f"  ⚠️ {label}: requested {mkt_id} but feed served {served} "
              f"({MARKET_LABELS.get(served, served)}) after retries — skipping "
              "to avoid mislabeled cards.")
        return []
    articles = data.get("articles", [])
    # Normalise the marketplace field to the short label for the card.
    for a in articles:
        a["marketplace"] = label
    print(f"  fetched {len(articles)} official {label} announcements "
          f"(of {data.get('total')} total)")
    return articles


# --- dedupe across markets ---------------------------------------------------
# Amazon publishes most announcements globally, so the AE and AU feeds overlap
# heavily. Merge same-title articles into one card whose region shows every
# market it applies to (e.g. "AE·AU"); market-specific ones keep a single label.
# Run BEFORE translation so we match on the identical English source title.

def dedupe_by_title(articles: list[dict]) -> list[dict]:
    """Merge same-title articles, unioning their market labels. Idempotent and
    composable: existing "AE·AU" labels are split back out so it can run both
    before translation (English titles) and after (zh-TW titles collapse cases
    where AE/AU had slightly different English wording)."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for a in articles:
        key = re.sub(r"\s+", " ", (a.get("title") or "").strip().lower())
        labels = [m for m in (a.get("marketplace") or "").split("·") if m]
        if key not in merged:
            a = dict(a)
            a["_markets"] = list(labels)
            merged[key] = a
            order.append(key)
        else:
            for mk in labels:
                if mk not in merged[key]["_markets"]:
                    merged[key]["_markets"].append(mk)
    out = []
    for key in order:
        a = merged[key]
        a["marketplace"] = "·".join(a.pop("_markets"))
        out.append(a)
    return out


# --- English -> Traditional Chinese translation ------------------------------
# Both the AE and AU browser feeds come back in English, so we machine-translate
# the official titles/summaries to zh-TW to match the dashboard.

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


def translate_english_articles(articles: list[dict]) -> int:
    """In-place translate title/summary of any still-English official article
    to Traditional Chinese. Returns count translated."""
    n = 0
    for a in articles:
        title = a.get("title", "")
        if title and not _is_mostly_chinese(title):
            a["title"] = _translate_en(title)
            summary = a.get("summary", "")
            if summary and not _is_mostly_chinese(summary):
                a["summary"] = _translate_en(summary)
            n += 1
    return n


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

def _resolve_markets(spec: str | None) -> list[tuple[str, str]]:
    if not spec:
        return DEFAULT_MARKETS
    out = []
    for label in (s.strip().upper() for s in spec.split(",") if s.strip()):
        mkt_id = LABEL_TO_ID.get(label)
        if not mkt_id:
            sys.exit(f"unknown market '{label}'. Known: {', '.join(LABEL_TO_ID)}")
        out.append((mkt_id, label))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, local).")
    ap.add_argument("--markets", default=None,
                    help="Comma-separated labels to pull (default AE,AU). "
                         f"Known: {', '.join(LABEL_TO_ID)}.")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="Max articles PER market (default 6).")
    ap.add_argument("--no-translate", action="store_true",
                    help="Skip translating external (non-official) English titles.")
    ap.add_argument("--keep-english", action="store_true",
                    help="Skip translating the official articles (keep English).")
    ap.add_argument("--no-build", action="store_true",
                    help="Skip re-running build.py afterwards.")
    args = ap.parse_args()

    date = args.date or _dt.date.today().isoformat()
    markets = _resolve_markets(args.markets)

    # Run from repo root regardless of cwd.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    tab = ensure_seller_news_tab()
    articles: list[dict] = []
    for mkt_id, label in markets:
        articles.extend(fetch_marketplace_articles(tab, mkt_id, label, args.limit))

    # Leave the dropdown on AU (its usual resting state) so the tab looks tidy.
    if any(label == "AU" for _, label in markets):
        switch_marketplace(tab, LABEL_TO_ID["AU"], "AU")

    if not articles:
        sys.exit("no official announcements returned — nothing to inject.")

    n_before = len(articles)
    articles = dedupe_by_title(articles)
    if len(articles) < n_before:
        print(f"  🔀 merged {n_before - len(articles)} cross-market duplicate(s) "
              f"→ {len(articles)} unique announcements")

    if not args.keep_english:
        n_tr = translate_english_articles(articles)
        if n_tr:
            print(f"  🌐 translated {n_tr} English official article(s) to Traditional")
        # Second pass: AE/AU sometimes ship the same announcement with slightly
        # different English wording that collapses to identical zh-TW.
        n2 = len(articles)
        articles = dedupe_by_title(articles)
        if len(articles) < n2:
            print(f"  🔀 merged {n2 - len(articles)} more post-translation "
                  f"duplicate(s) → {len(articles)}")

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
