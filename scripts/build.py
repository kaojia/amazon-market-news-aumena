#!/usr/bin/env python
"""
build.py – Scan daily-report-*.html files, extract news cards,
and inject a JSON articles array into index.html.

Run from repo root:  python scripts/build.py
"""

import glob
import json
import os
import re
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

def map_tags(region_text):
    """Map region/topic keywords to category tags."""
    if any(kw in region_text for kw in ("供應鏈", "物流")):
        return ["物流", "地緣政治"]
    if any(kw in region_text for kw in ("總經", "利率", "消費")):
        return ["總經"]
    if any(kw in region_text for kw in ("稅務", "電商合規", "電子發票", "VAT")):
        return ["稅務"]
    if any(kw in region_text for kw in ("法規", "消費者保護", "AML")):
        return ["合規"]
    if any(kw in region_text for kw in ("投資", "稅務優惠")):
        return ["稅務"]
    if any(kw in region_text for kw in ("貿易", "關稅")):
        return ["貿易"]
    if any(kw in region_text for kw in ("電商市場", "競爭")):
        return ["平台"]
    if "支付" in region_text:
        return ["合規"]
    return ["總經"]


# ---------------------------------------------------------------------------
# HTML parser for daily-report files
# ---------------------------------------------------------------------------

class DailyReportParser(HTMLParser):
    """Parse a daily-report-*.html file and extract news cards."""

    def __init__(self):
        super().__init__()
        self.cards = []
        self._current_card = None
        self._in_card = False
        self._card_classes = []
        self._context = None          # 'h3' | 'region' | 'summary' | 'impact_p' | 'action_p' | 'source'
        self._in_region = False
        self._in_summary = False
        self._in_impact = False
        self._in_action = False
        self._in_source = False
        self._in_h3 = False
        self._in_impact_p = False
        self._in_action_p = False
        self._in_source_a = False
        self._current_a_href = None
        self._text_buf = ""
        self._depth = 0               # nesting depth inside a card div
        self._region_depth = 0
        self._summary_depth = 0
        self._impact_depth = 0
        self._action_depth = 0
        self._source_depth = 0

    # -- helpers --
    def _classes(self, attrs):
        for name, val in attrs:
            if name == "class" and val:
                return val.split()
        return []

    def _href(self, attrs):
        for name, val in attrs:
            if name == "href":
                return val
        return None

    def handle_starttag(self, tag, attrs):
        cls = self._classes(attrs)

        # Detect card start
        if tag == "div" and "card" in cls:
            self._in_card = True
            self._card_classes = cls
            self._depth = 1
            self._current_card = {
                "title": "",
                "region_text": "",
                "summary": "",
                "impact": "",
                "action": "",
                "sources": [],
                "priority": None,
            }
            if "high" in cls:
                self._current_card["priority"] = "high"
            elif "medium" in cls:
                self._current_card["priority"] = "medium"
            return

        if not self._in_card:
            return

        # Track div nesting inside card
        if tag == "div":
            self._depth += 1

        # Detect sub-sections
        if tag == "div" and "region" in cls:
            self._in_region = True
            self._region_depth = self._depth
            self._text_buf = ""
        elif tag == "div" and "summary" in cls:
            self._in_summary = True
            self._summary_depth = self._depth
            self._text_buf = ""
        elif tag == "div" and "impact" in cls:
            self._in_impact = True
            self._impact_depth = self._depth
        elif tag == "div" and "action" in cls:
            self._in_action = True
            self._action_depth = self._depth
        elif tag == "div" and "source" in cls:
            self._in_source = True
            self._source_depth = self._depth

        # h3 title
        if tag == "h3":
            self._in_h3 = True
            self._text_buf = ""

        # impact <p>
        if tag == "p" and self._in_impact:
            self._in_impact_p = True
            self._text_buf = ""

        # action <p>
        if tag == "p" and self._in_action:
            self._in_action_p = True
            self._text_buf = ""

        # source <a>
        if tag == "a" and self._in_source:
            self._in_source_a = True
            self._current_a_href = self._href(attrs)
            self._text_buf = ""

    def handle_endtag(self, tag):
        if not self._in_card:
            return

        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            self._current_card["title"] = self._text_buf.strip()
            self._text_buf = ""

        if tag == "a" and self._in_source_a:
            self._in_source_a = False
            name = self._text_buf.strip()
            if name and self._current_a_href:
                self._current_card["sources"].append({
                    "name": name,
                    "url": self._current_a_href,
                })
            self._text_buf = ""
            self._current_a_href = None

        if tag == "p" and self._in_impact_p:
            self._in_impact_p = False
            self._current_card["impact"] = self._text_buf.strip()
            self._text_buf = ""

        if tag == "p" and self._in_action_p:
            self._in_action_p = False
            self._current_card["action"] = self._text_buf.strip()
            self._text_buf = ""

        if tag == "div":
            if self._in_region and self._depth == self._region_depth:
                self._in_region = False
                self._current_card["region_text"] = self._text_buf.strip()
                self._text_buf = ""
            if self._in_summary and self._depth == self._summary_depth:
                self._in_summary = False
                self._current_card["summary"] = self._text_buf.strip()
                self._text_buf = ""
            if self._in_impact and self._depth == self._impact_depth:
                self._in_impact = False
            if self._in_action and self._depth == self._action_depth:
                self._in_action = False
            if self._in_source and self._depth == self._source_depth:
                self._in_source = False

            self._depth -= 1
            # Card closed
            if self._depth == 0:
                self._in_card = False
                self.cards.append(self._current_card)
                self._current_card = None

    def handle_data(self, data):
        if not self._in_card:
            return
        if self._in_h3:
            self._text_buf += data
        elif self._in_source_a:
            self._text_buf += data
        elif self._in_impact_p:
            self._text_buf += data
        elif self._in_action_p:
            self._text_buf += data
        elif self._in_summary:
            self._text_buf += data
        elif self._in_region:
            self._text_buf += data

    def handle_entityref(self, name):
        char = {
            "amp": "&", "lt": "<", "gt": ">", "quot": '"',
            "middot": "\u00b7", "nbsp": "\u00a0",
        }.get(name, f"&{name};")
        self.handle_data(char)

    def handle_charref(self, name):
        try:
            if name.startswith("x"):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
        except (ValueError, OverflowError):
            char = f"&#{name};"
        self.handle_data(char)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_date(filename):
    """Extract YYYY-MM-DD from daily-report-YYYY-MM-DD.html."""
    m = re.search(r"daily-report-(\d{4}-\d{2}-\d{2})\.html", filename)
    return m.group(1) if m else None


def priority_color(priority):
    if priority == "high":
        return "#dc2626"
    if priority == "medium":
        return "#f59e0b"
    return "#0369a1"


def build():
    report_files = sorted(glob.glob("daily-report-*.html"))
    if not report_files:
        print("No daily-report-*.html files found.")
        return

    all_articles = []

    for filepath in report_files:
        date = extract_date(filepath)
        if not date:
            print(f"  Skipping {filepath}: cannot extract date")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        parser = DailyReportParser()
        parser.feed(html)

        print(f"  {filepath}: {len(parser.cards)} cards")

        for card in parser.cards:
            tags = map_tags(card["region_text"])
            article = {
                "date": date,
                "tags": tags,
                "title": card["title"],
                "summary": card["summary"],
                "impact": card["impact"],
                "action": card["action"],
                "sources": card["sources"],
                "color": priority_color(card["priority"]),
            }
            all_articles.append(article)

    # Sort by date descending
    all_articles.sort(key=lambda a: a["date"], reverse=True)

    print(f"\nTotal articles: {len(all_articles)}")

    # Build JSON string
    articles_json = json.dumps(all_articles, ensure_ascii=False, indent=2)

    # Read template
    with open("index.html", "r", encoding="utf-8") as f:
        template = f.read()

    # Replace placeholder
    pattern = r"/\*__ARTICLES_JSON__\*/\[\]/\*__END_ARTICLES_JSON__\*/"
    if not re.search(pattern, template):
        # Also try with existing content between markers (re-run scenario)
        pattern = r"/\*__ARTICLES_JSON__\*/.*?/\*__END_ARTICLES_JSON__\*/"
    replacement = f"/*__ARTICLES_JSON__*/{articles_json}/*__END_ARTICLES_JSON__*/"
    result = re.sub(pattern, replacement, template, count=1, flags=re.DOTALL)

    # Write back
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(result)

    print("index.html updated successfully.")


if __name__ == "__main__":
    build()
