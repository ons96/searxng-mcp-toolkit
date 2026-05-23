#!/usr/bin/env python3
"""Scrape known instance registries for new SearXNG instances.
Merges results into searxng-instances.yaml without duplicating existing entries.

Sources:
  - https://searx.space/data/instances.json
  - https://searx.neocities.org/instancescores

Usage:
  ./scrape-searxng.py              # scan and print new instances
  ./scrape-searxng.py --merge      # merge new instances into the YAML DB
  ./scrape-searxng.py --test       # test new instances (slow)
"""
import json
import os
import sys
import urllib.request

import yaml

DB_PATH = os.path.expanduser("~/.config/opencode/setup/searxng-instances.yaml")
SOURCES = {
    "searx.space": "https://searx.space/data/instances.json",
    "instancescores": "https://searx.neocities.org/instancescores",
}
TIMEOUT = 10


def load_db():
    with open(DB_PATH) as f:
        return yaml.safe_load(f)


def save_db(db):
    with open(DB_PATH, "w") as f:
        yaml.dump(db, f, sort_keys=False, allow_unicode=True, width=999)


def fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def fetch_scores(url):
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            text = resp.read().decode()
        lines = text.strip().split("\n")
        # skip header, parse: url score
        urls = []
        for line in lines[1:]:
            parts = line.strip().split()
            if parts and parts[0].startswith("http"):
                urls.append(parts[0].rstrip("/"))
        return urls
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}", file=sys.stderr)
        return []


def parse_searxspace(data):
    urls = []
    if not data or "instances" not in data:
        return urls
    for url, info in data["instances"].items():
        url = url.rstrip("/")
        if url not in urls:
            urls.append(url)
    return urls


def main():
    args = sys.argv[1:]
    do_merge = "--merge" in args
    do_test = "--test" in args
    ci = "--ci" in args

    db = load_db()
    existing = {i["url"] for i in db["instances"]}

    new_urls = set()
    for source_name, source_url in SOURCES.items():
        if not ci:
            print(f"Fetching {source_name}...", file=sys.stderr)
        if "instancescores" in source_name:
            found = fetch_scores(source_url)
        else:
            data = fetch_json(source_url)
            found = parse_searxspace(data)
        for u in found:
            if u not in existing:
                new_urls.add(u)

    if not new_urls:
        if not ci:
            print("No new instances found.", file=sys.stderr)
        return

    if not ci:
        print(f"Found {len(new_urls)} new instances:", file=sys.stderr)
        for u in sorted(new_urls):
            print(f"  {u}", file=sys.stderr)

    if do_merge or ci:
        for u in sorted(new_urls):
            entry = {"url": u, "sources": ["scraper"], "status": "unknown"}
            db["instances"].append(entry)
        save_db(db)
        if not ci:
            print(f"Merged {len(new_urls)} new instances into {DB_PATH}", file=sys.stderr)
    elif do_test:
        # just import test capabilities
        from test_searxng import test_instance
        results = []
        for u in sorted(new_urls):
            r = test_instance(u)
            results.append(r)
            icon = "✓" if r.get("category") == "full-json" else " "
            print(f"  {icon} {u:50s} {r.get('category','?'):15s} ({r.get('response_ms',0)}ms)", file=sys.stderr)
    else:
        print("\nPass --merge to add them to the DB, or --test to probe them.", file=sys.stderr)


if __name__ == "__main__":
    main()
