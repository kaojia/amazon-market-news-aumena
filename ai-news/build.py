#!/usr/bin/env python
"""
build.py - Scan ai-report-*.json files, merge into data.js for the AI Pulse site.

Run from ai-news/ directory:  python build.py
"""

import glob
import json
import os


def build():
    report_files = sorted(glob.glob("ai-report-*.json"), reverse=True)
    if not report_files:
        print("No ai-report-*.json files found. Using existing data.js.")
        return

    all_articles = []

    for filepath in report_files:
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  Skipping {filepath}: JSON parse error - {e}")
                continue

        if isinstance(data, list):
            articles = data
        elif isinstance(data, dict) and "articles" in data:
            articles = data["articles"]
        else:
            print(f"  Skipping {filepath}: unexpected format")
            continue

        print(f"  {filepath}: {len(articles)} articles")
        all_articles.extend(articles)

    # Sort by date descending
    all_articles.sort(key=lambda a: a.get("date", ""), reverse=True)

    # Deduplicate by title
    seen_titles = set()
    unique_articles = []
    for a in all_articles:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            unique_articles.append(a)

    print(f"\nTotal unique articles: {len(unique_articles)}")

    # Write data.js
    articles_json = json.dumps(unique_articles, ensure_ascii=False, indent=2)
    data_js = f"var articles = {articles_json};\n"

    with open("data.js", "w", encoding="utf-8") as f:
        f.write(data_js)

    print("data.js updated successfully.")


if __name__ == "__main__":
    build()
