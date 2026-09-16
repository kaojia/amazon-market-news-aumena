#!/usr/bin/env python
"""review_market_relevance.py — classify every published card as relevant to
Australia (AU) / Middle East (UAE, Saudi) Amazon sellers, or not.

Reads the cards straight out of index.html's articles JSON, asks Gemini to
KEEP/DROP each against a strict rubric, and writes the verdicts to
market_review.json. It does NOT delete anything — review the JSON first, then
run with --apply to prune the DROP cards from the daily-report files + rebuild.

Requires GEMINI_API_KEY.

Usage:
  GEMINI_API_KEY=... python scripts/review_market_relevance.py           # classify -> market_review.json
  GEMINI_API_KEY=... python scripts/review_market_relevance.py --apply    # delete DROPs + rebuild
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys

import fetch_and_push as F

BATCH = 12
OUT = "market_review.json"

RUBRIC = (
    "你是為澳洲(AU)與中東(阿聯酋 UAE、沙烏地阿拉伯 SA)Amazon 賣家服務的市場情報分析師。"
    "針對每則新聞，判斷它是否與 AU 或中東賣家的經營有關。\n"
    "KEEP（保留）條件（符合任一即可）：\n"
    "- 主題涉及澳洲、阿聯酋、沙烏地或中東市場；\n"
    "- 雖提及其他國家，但對 AU/中東賣家有直接影響，例如：荷姆茲海峽/中東物流、"
    "影響中東或澳洲的關稅與貿易、Amazon 全球賣家政策(費用/廣告/上架規則)、"
    "沙烏地 ZATCA 電子發票、AWS 中東資料中心、影響澳洲進出口的總經或反傾銷措施。\n"
    "DROP（移除）條件：\n"
    "- 主題主要是其他市場(印度/美國/英國/歐洲/中國/非洲/新加坡等)的在地電商、"
    "賣家費用、物流服務、市場規模或在地企業，且與 AU/中東賣家沒有直接關聯；\n"
    "- 純股市/財經行情、與 Amazon 賣家經營無關的一般時事。\n"
    "只回傳 JSON 陣列，每個元素對應清單中一則(依 index 順序)："
    '[{"index":0,"verdict":"KEEP","reason":"..."}]，reason 用繁體中文一句話，不要其他文字或 markdown。'
)


def load_cards():
    h = open("index.html", encoding="utf-8").read()
    m = re.search(r"/\*__ARTICLES_JSON__\*/(.*?)/\*__END_ARTICLES_JSON__\*/", h, re.DOTALL)
    return json.loads(m.group(1))


def classify(cards):
    verdicts = [None] * len(cards)
    for i in range(0, len(cards), BATCH):
        chunk = cards[i:i + BATCH]
        lines = []
        for j, a in enumerate(chunk):
            body = f"{a.get('summary','')} / {a.get('impact','')}"
            lines.append(f"{j}. [{a.get('market','')}] {a.get('title','')} — {body}")
        prompt = RUBRIC + "\n\n新聞清單：\n" + "\n".join(lines)
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{F.GEMINI_MODEL}:generateContent")
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": 0.1,
                                        "responseMimeType": "application/json"}}
        try:
            import requests
            resp = requests.post(url, json=payload, timeout=90,
                                 headers={"x-goog-api-key": F.GEMINI_API_KEY})
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            res = json.loads(text)
            for r in res:
                idx = r.get("index")
                if isinstance(idx, int) and 0 <= idx < len(chunk):
                    verdicts[i + idx] = (r.get("verdict", "KEEP"), r.get("reason", ""))
        except Exception as e:
            print(f"  ⚠️ batch {i}-{i+len(chunk)} failed ({e}); defaulting KEEP")
        print(f"  classified {min(i+BATCH,len(cards))}/{len(cards)}")
    # default un-answered to KEEP (never drop on uncertainty)
    return [(v if v else ("KEEP", "未分類，保留")) for v in verdicts]


def _find_card_spans(text):
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


def _norm(t):
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def apply_drops(drop_titles):
    dropped = 0
    for path in sorted(glob.glob("daily-report-*.html")):
        content = open(path, encoding="utf-8").read()
        spans = list(_find_card_spans(content))
        to_drop = []
        for s, e in spans:
            card = content[s:e]
            if "官方公告" in card:
                continue
            m = re.search(r"<h3>(.*?)</h3>", card, re.DOTALL)
            if m and _norm(m.group(1)) in drop_titles:
                to_drop.append((s, e))
        if to_drop:
            for s, e in reversed(to_drop):
                content = content[:s] + content[e:]
            content = re.sub(r"\n{3,}", "\n\n", content)
            open(path, "w", encoding="utf-8").write(content)
            print(f"  {path}: dropped {len(to_drop)}")
            dropped += len(to_drop)
    return dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="delete DROP cards (from market_review.json) + rebuild")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    if not args.apply:
        if not F.GEMINI_API_KEY:
            sys.exit("GEMINI_API_KEY not set.")
        cards = load_cards()
        verdicts = classify(cards)
        rows = []
        for a, (v, why) in zip(cards, verdicts):
            rows.append({"date": a["date"], "market": a.get("market", ""),
                         "title": a["title"], "verdict": v, "reason": why})
        json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        drops = [r for r in rows if r["verdict"] == "DROP"]
        print(f"\n{len(cards)} cards → {len(drops)} DROP proposed. Review {OUT}.")
        for r in drops:
            print(f"  DROP [{r['market']}] {r['title'][:52]}  ← {r['reason'][:40]}")
        return

    rows = json.load(open(OUT, encoding="utf-8"))
    drop_titles = {_norm(r["title"]) for r in rows if r["verdict"] == "DROP"}
    n = apply_drops(drop_titles)
    print(f"\nDropped {n} card(s). Rebuilding…")
    proc = subprocess.run([sys.executable, "scripts/build.py"],
                          capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.exit(f"build.py failed: {proc.stderr}")


if __name__ == "__main__":
    main()
