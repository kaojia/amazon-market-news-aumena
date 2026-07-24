#!/usr/bin/env python3
"""
fetch_and_push.py – Fetch SC announcements, external news, and seller forums,
filter by keyword priority rules, and push top 1-2 items to LINE via /push/news.

Environment variables required:
  RENDER_DEPLOY_URL  – Base URL of line-jenny-agent on Render
  PUSH_SECRET        – Shared secret for /push/news endpoint

Optional:
  AMZ_SC_PATH        – Path to amz-sc binary (default: amz-sc)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from deep_translator import GoogleTranslator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RENDER_DEPLOY_URL = os.environ.get("RENDER_DEPLOY_URL", "")
PUSH_SECRET = os.environ.get("PUSH_SECRET", "jenny-daily-push")

MARKETPLACES = ["AU", "AE", "SA"]

# Keyword-based priority rules
HIGH_PRIORITY_KEYWORDS = [
    "政策變更", "policy change", "fee change", "費用調整",
    "FBA", "新規定", "new regulation", "合規", "compliance",
    "關稅", "tariff", "稅率", "tax rate", "VAT",
    "帳號停權", "account suspension", "listing removal",
    "deadline", "截止日", "mandatory", "強制",
]

MEDIUM_PRIORITY_KEYWORDS = [
    "新功能", "new feature", "update", "更新",
    "促銷", "promotion", "coupon", "廣告", "advertising",
    "物流", "logistics", "shipping", "配送",
    "報告", "report", "dashboard",
]

CATEGORY_RULES = {
    "政策": ["政策", "policy", "regulation", "合規", "compliance", "mandatory"],
    "費用": ["fee", "費用", "cost", "pricing", "收費"],
    "FBA": ["FBA", "fulfillment", "倉儲", "庫存", "inventory"],
    "稅務": ["tax", "VAT", "稅", "tariff", "關稅"],
    "廣告": ["advertising", "廣告", "PPC", "sponsored", "campaign"],
    "物流": ["logistics", "物流", "shipping", "配送", "delivery"],
    "平台": ["feature", "功能", "update", "更新", "tool", "工具"],
}


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_sc_announcements():
    """Fetch Seller Central news via Google News RSS with SC-specific queries (past 3 days)."""
    announcements = []

    sc_queries = [
        ("AU", "Amazon+seller+central+Australia+announcement+when:3d", "AU"),
        ("AU", "Amazon+FBA+Australia+fee+OR+policy+OR+update+when:3d", "AU"),
        ("AE", "Amazon+Seller+Central+UAE+announcement+when:3d", "AE"),
        ("AE", "Amazon+FBA+UAE+fee+OR+policy+OR+update+when:3d", "AE"),
        ("SA", "Amazon+Seller+Central+Saudi+announcement+when:3d", "AE"),
        ("SA", "Amazon+seller+MENA+policy+OR+fee+OR+FBA+when:3d", "AE"),
    ]

    for mp, query, region in sc_queries:
        try:
            url = f"https://news.google.com/rss/search?q={query}&hl=en&gl={region}&ceid={region}:en"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                items = parse_rss_items(resp.text, limit=3)
                for item in items:
                    item["source_type"] = "seller_central"
                    item["marketplace"] = mp
                announcements.extend(items)
        except Exception as e:
            print(f"  ⚠️ SC News ({mp}): {e}")

    return announcements


def fetch_external_news():
    """Fetch external news from Google News RSS for Amazon marketplace keywords (past 3 days)."""
    news = []
    queries = [
        ("Amazon+Australia+seller+OR+marketplace+when:3d", "AU", "AU"),
        ("Amazon+Australia+ecommerce+regulation+OR+logistics+when:3d", "AU", "AU"),
        ("Amazon+UAE+seller+OR+ecommerce+when:3d", "AE", "AE"),
        ("Amazon+Saudi+seller+OR+marketplace+when:3d", "AE", "AE"),
        ("UAE+ecommerce+OR+online+retail+when:3d", "AE", "AE"),
        ("Saudi+ecommerce+OR+online+retail+when:3d", "SA", "AE"),
        ("Amazon+MENA+logistics+OR+delivery+when:3d", "AE", "AE"),
    ]

    for query, mp, region in queries:
        try:
            url = f"https://news.google.com/rss/search?q={query}&hl=en&gl={region}&ceid={region}:en"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                items = parse_rss_items(resp.text, limit=5)
                for item in items:
                    item["source_type"] = "external"
                    item["marketplace"] = mp
                news.extend(items)
        except Exception as e:
            print(f"  ⚠️ Google News ({query[:40]}): {e}")

    return news


def fetch_seller_forums():
    """Fetch hot topics from Amazon Seller Forums."""
    forums = []
    forum_urls = [
        ("AU", "https://sellercentral.amazon.com.au/forums/c/announcements"),
        ("AE", "https://sellercentral.amazon.ae/forums/c/announcements"),
        ("SA", "https://sellercentral.amazon.sa/forums/c/announcements"),
    ]

    for mp, url in forum_urls:
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"
            })
            if resp.status_code == 200:
                items = parse_forum_page(resp.text, mp, limit=3)
                forums.extend(items)
        except Exception as e:
            print(f"  ⚠️ Forum {mp}: {e}")

    return forums


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_rss_items(xml_text, limit=5):
    """Simple RSS XML parser (no external deps)."""
    items = []
    # Extract <item> blocks
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)

    for block in item_blocks[:limit]:
        title = extract_xml_tag(block, "title")
        link = extract_xml_tag(block, "link")
        pub_date = extract_xml_tag(block, "pubDate")
        source = extract_xml_tag(block, "source")

        if title:
            items.append({
                "title": title,
                "summary": "",
                "source_url": link or "",
                "source_name": source or "Google News",
                "pub_date": pub_date or "",
            })

    return items


def parse_forum_page(html_text, marketplace, limit=3):
    """Extract forum topic titles from announcement page HTML."""
    items = []
    # Look for topic titles in common forum HTML patterns
    titles = re.findall(r'class="[^"]*topic-title[^"]*"[^>]*>(.*?)</a>', html_text, re.DOTALL)

    if not titles:
        titles = re.findall(r'<a[^>]*href="(/forums/[^"]*)"[^>]*>(.*?)</a>', html_text)
        titles = [t[1] for t in titles if t[1].strip()]

    for title_raw in titles[:limit]:
        title = re.sub(r"<[^>]+>", "", title_raw).strip()
        if title:
            items.append({
                "title": title,
                "summary": "",
                "source_url": "",
                "source_name": f"Seller Forum {marketplace}",
                "source_type": "forum",
                "marketplace": marketplace,
            })

    return items


def extract_xml_tag(text, tag):
    """Extract content of an XML tag."""
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        # Handle CDATA
        cdata = re.match(r"<!\[CDATA\[(.*?)\]\]>", content, re.DOTALL)
        if cdata:
            return cdata.group(1).strip()
        return re.sub(r"<[^>]+>", "", content).strip()
    return ""


# ---------------------------------------------------------------------------
# Filtering & Priority
# ---------------------------------------------------------------------------

def classify_item(item):
    """Assign priority and category based on keywords."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    # Priority
    priority = "low"
    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw.lower() in text:
            priority = "high"
            break
    if priority == "low":
        for kw in MEDIUM_PRIORITY_KEYWORDS:
            if kw.lower() in text:
                priority = "medium"
                break

    # Category
    category = "平台"
    for cat, keywords in CATEGORY_RULES.items():
        if any(kw.lower() in text for kw in keywords):
            category = cat
            break

    item["priority"] = priority
    item["category"] = category
    return item


def filter_top_news(all_items, max_items=2):
    """Filter and return top priority news items."""
    classified = [classify_item(item) for item in all_items]

    # Sort: high > medium > low, then by source_type preference (SC first)
    source_order = {"seller_central": 0, "external": 1, "forum": 2}
    priority_order = {"high": 0, "medium": 1, "low": 2}

    classified.sort(key=lambda x: (
        priority_order.get(x.get("priority"), 3),
        source_order.get(x.get("source_type"), 3),
    ))

    # Deduplicate by similar titles
    seen_titles = set()
    result = []
    for item in classified:
        title_key = re.sub(r"[^a-z0-9一-鿿]", "", item.get("title", "").lower())[:30]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            result.append(item)
        if len(result) >= max_items:
            break

    return result


# ---------------------------------------------------------------------------
# Fetch article summaries
# ---------------------------------------------------------------------------

def generate_summary(item):
    """Generate a brief summary based on title, category, and marketplace."""
    title = item.get("title", "")
    category = item.get("category", "")
    marketplace = item.get("marketplace", "")
    priority = item.get("priority", "low")

    mp_names = {"AU": "澳洲", "AE": "阿聯酋", "SA": "沙烏地阿拉伯"}
    mp_name = mp_names.get(marketplace, "AU/MENA")

    templates = {
        "FBA": f"與 Amazon {mp_name}站 FBA 物流服務相關的最新動態，可能影響賣家倉儲與配送策略。",
        "費用": f"Amazon {mp_name}站費用結構異動，賣家應留意成本變化對利潤的影響。",
        "政策": f"Amazon {mp_name}站平台政策更新，賣家需確認是否符合新規定以避免違規。",
        "稅務": f"{mp_name}稅務法規變動，跨境賣家應注意合規要求與申報時程。",
        "合規": f"{mp_name}市場合規要求更新，賣家需檢視商品與營運是否符合當地法規。",
        "物流": f"{mp_name}物流與供應鏈相關動態，可能影響配送時效與成本。",
        "廣告": f"Amazon {mp_name}站廣告與行銷工具更新，賣家可評估新功能對曝光的助益。",
        "平台": f"Amazon {mp_name}站平台最新消息，賣家可關注對業務發展的潛在機會。",
    }

    return templates.get(category, f"Amazon {mp_name}站市場動態，建議賣家持續關注相關發展。")


def enrich_summaries(news_items):
    """Add summaries to items that don't have one."""
    for item in news_items:
        if not item.get("summary"):
            item["summary"] = generate_summary(item)
    return news_items


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def translate_to_chinese(text):
    """Translate text to Traditional Chinese if not already Chinese."""
    if not text or not text.strip():
        return text
    # Skip if already mostly Chinese
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    if chinese_chars / max(len(text), 1) > 0.3:
        return text
    try:
        return GoogleTranslator(source='auto', target='zh-TW').translate(text)
    except Exception as e:
        print(f"  Translation failed: {e}")
        return text


def translate_news_items(news_items):
    """Translate title and summary of each news item to Traditional Chinese."""
    for item in news_items:
        item["title"] = translate_to_chinese(item.get("title", ""))
        item["summary"] = translate_to_chinese(item.get("summary", ""))
    return news_items


# ---------------------------------------------------------------------------
# Push to LINE
# ---------------------------------------------------------------------------

def push_to_line(news_items):
    """POST news items to line-jenny-agent /push/news endpoint."""
    if not RENDER_DEPLOY_URL:
        print("❌ RENDER_DEPLOY_URL not set, cannot push")
        return False

    print(f"  DEBUG: PUSH_SECRET length={len(PUSH_SECRET)}, repr={repr(PUSH_SECRET)}")
    print(f"  DEBUG: RENDER_DEPLOY_URL='{RENDER_DEPLOY_URL}'")

    payload = {
        "secret": PUSH_SECRET,
        "news": [
            {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "category": item.get("category", ""),
                "priority": item.get("priority", "low"),
                "source_url": item.get("source_url", ""),
                "source_name": item.get("source_name", ""),
                "marketplace": item.get("marketplace", ""),
            }
            for item in news_items
        ],
    }

    try:
        url = f"{RENDER_DEPLOY_URL.rstrip('/')}/push/news"
        resp = requests.post(url, json=payload, timeout=30)
        print(f"  推送狀態碼：{resp.status_code}")
        print(f"  回應：{resp.text}")
        return resp.status_code == 200
    except Exception as e:
        print(f"❌ 推送失敗：{e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    tz_tw = timezone(timedelta(hours=8))
    now = datetime.now(tz_tw)
    print(f"🕐 {now.strftime('%Y-%m-%d %H:%M')} (台灣時間)")
    print("=" * 50)

    # 1. Fetch from all sources
    print("\n📡 抓取 Seller Central 公告...")
    sc_news = fetch_sc_announcements()
    print(f"  → {len(sc_news)} 則")

    print("\n📡 抓取外部新聞...")
    external_news = fetch_external_news()
    print(f"  → {len(external_news)} 則")

    print("\n📡 抓取 Seller Forums...")
    forum_news = fetch_seller_forums()
    print(f"  → {len(forum_news)} 則")

    # 2. Combine all
    all_news = sc_news + external_news + forum_news
    print(f"\n📊 共抓取 {len(all_news)} 則新聞")

    if not all_news:
        print("⚠️ 今日無新聞可推送")
        return

    # 3. Filter items - top 2 for LINE, top 5 for dashboard
    top_news_line = filter_top_news(all_news, max_items=2)
    top_news_dashboard = filter_top_news(all_news, max_items=5)

    # 4. Fetch article summaries from source pages
    print("\n📝 擷取文章摘要...")
    top_news_dashboard = enrich_summaries(top_news_dashboard)

    # 5. Translate all dashboard items to Traditional Chinese
    print("\n🌐 翻譯為繁體中文...")
    top_news_dashboard = translate_news_items(top_news_dashboard)

    # LINE items are a subset of dashboard items (already translated)
    top_news_line = top_news_dashboard[:2]

    print(f"\n🎯 LINE 推播 {len(top_news_line)} 則 / Dashboard 存入 {len(top_news_dashboard)} 則：")
    for i, item in enumerate(top_news_dashboard, 1):
        marker = "📤" if i <= 2 else "📋"
        print(f"  {marker} {i}. [{item['priority']}] [{item['category']}] {item['title']}")

    # 6. Push to LINE (top 2 only)
    print("\n📤 推送到 LINE...")
    success = push_to_line(top_news_line)

    if success:
        print("\n✅ 推送完成！")
    else:
        print("\n❌ 推送失敗")
        sys.exit(1)

    # 7. Save top 5 to daily report for dashboard
    save_daily_report(top_news_dashboard, now)


def save_daily_report(news_items, now):
    """Save fetched news as a daily-report HTML for the dashboard build."""
    date_str = now.strftime("%Y-%m-%d")
    filename = f"daily-report-{date_str}.html"

    if os.path.exists(filename):
        print(f"  ℹ️ {filename} already exists, skipping")
        return

    priority_class = {"high": " high", "medium": " medium", "low": ""}

    cards_html = ""
    for item in news_items:
        p_class = priority_class.get(item.get("priority", ""), "")
        source_html = ""
        if item.get("source_url"):
            source_html = f'<div class="source"><a href="{item["source_url"]}">{item.get("source_name", "來源")}</a></div>'

        cards_html += f"""
    <div class="card{p_class}">
        <h3>{item.get("title", "")}</h3>
        <div class="region">{item.get("marketplace", "")} - {item.get("category", "")}</div>
        <div class="summary">{item.get("summary", "")}</div>
        <div class="impact"><p>{item.get("summary", "")}</p></div>
        <div class="action"><p>請關注後續發展</p></div>
        {source_html}
    </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><title>Daily Report {date_str}</title></head>
<body>
{cards_html}
</body>
</html>
"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📝 已產生 {filename}")


if __name__ == "__main__":
    main()
