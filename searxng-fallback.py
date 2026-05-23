#!/usr/bin/env python3
"""SearXNG fallback chain — tries instances in order of speed/reliability.

Usage:
  ./searxng-fallback.py "your search query"
  ./searxng-fallback.py --category full-json "query"   # JSON only
  ./searxng-fallback.py --skip-tor "query"              # skip .onion
  ./searxng-fallback.py --max-instances 5 "query"       # limit tries
  ./searxng-fallback.py --list                          # show ranked list
  ./searxng-fallback.py --list-all                      # all instances
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

DB_PATH = os.path.expanduser("~/.config/opencode/setup/searxng-instances.yaml")
TIMEOUT = 10
MAX_RESULTS = 5  # max results to return from each successful instance


def load_instances():
    with open(DB_PATH) as f:
        db = yaml.safe_load(f)
    return db["instances"]


def build_chain(instances, category=None, skip_tor=True, max_instances=None):
    """Filter and sort instances into a fallback chain."""
    # scoring: full-json > html-only, lower ms = better
    priority = {"full-json": 0, "html-only": 1, "ua-workaround": 2}
    candidates = []
    for i in instances:
        cat = i.get("category", "unknown")
        if category and cat != category:
            continue
        if cat not in priority:
            continue
        if skip_tor and ".onion" in i.get("url", ""):
            continue
        score = priority.get(cat, 99)
        ms = i.get("response_ms", 99999) or 99999
        candidates.append((score, ms, i))
    candidates.sort(key=lambda x: (x[0], x[1]))
    chain = [c[2] for c in candidates]
    if max_instances:
        chain = chain[:max_instances]
    return chain


def search_instance(instance, query):
    """Try to search one instance. Returns (url, query, results, ms) or None."""
    base = instance["url"].rstrip("/")
    cat = instance.get("category", "html-only")

    if cat == "full-json":
        url = f"{base}/search?format=json&q={urllib.parse.quote(query)}"
    else:
        url = f"{base}/search?q={urllib.parse.quote(query)}"

    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    headers = {"User-Agent": ua}
    start = time.time()

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed = round((time.time() - start) * 1000)
            body = resp.read().decode(errors="replace")

            if cat == "full-json":
                data = json.loads(body)
                results = data.get("results", [])
                return base, query, results, elapsed
            else:
                # html-only: parse basic results from HTML
                results = parse_html_results(body)
                return base, query, results, elapsed

    except Exception as e:
        return None


def parse_html_results(html):
    """Crude HTML result extraction — finds result items in common patterns."""
    results = []
    # pattern 1: searxng default template — article.result
    import re
    articles = re.findall(
        r'<article[^>]*class="result[^"]*"[^>]*>.*?</article>',
        html, re.DOTALL
    )
    for art in articles[:MAX_RESULTS]:
        title_m = re.search(r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', art, re.DOTALL)
        snippet_m = re.search(r'<p[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</p>', art, re.DOTALL)
        if title_m:
            results.append({
                "url": title_m.group(1),
                "title": re.sub(r'<[^>]+>', '', title_m.group(2)).strip(),
                "snippet": re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else "",
            })
    if results:
        return results[:MAX_RESULTS]

    # pattern 2: raw links with result headers
    sections = re.findall(
        r'<h3[^>]*>(.*?)</h3>.*?<a[^>]*href="(https?://[^"]*)"[^>]*>', html, re.DOTALL
    )
    for title, url in sections[:MAX_RESULTS]:
        clean = re.sub(r'<[^>]+>', '', title).strip()
        results.append({"url": url, "title": clean, "snippet": ""})

    # pattern 3: result-* class divs
    divs = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    for url, title in divs[:MAX_RESULTS]:
        clean = re.sub(r'<[^>]+>', '', title).strip()
        if clean and not any(r["url"] == url for r in results):
            results.append({"url": url, "title": clean, "snippet": ""})

    return results[:MAX_RESULTS]


def list_instances(all_flag=False):
    instances = load_instances()
    for inst in instances:
        cat = inst.get("category", "unknown")
        if not all_flag and cat not in ("full-json", "html-only"):
            continue
        ms = inst.get("response_ms", 0)
        url = inst["url"]
        tc = inst.get("tested", "?")
        j = "✓" if inst.get("json_api") else " "
        print(f"  [{ms:5d}ms] {'J' if j else ' '} {cat:12s} {url}  (tested {tc})")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip())
        sys.exit(1)

    if "--list" in args:
        args.remove("--list")
        if "--list-all" in args:
            args.remove("--list-all")
            list_instances(all_flag=True)
        else:
            list_instances()
        return

    category = None
    if "--category" in args:
        idx = args.index("--category")
        args.pop(idx)
        category = args.pop(idx)

    skip_tor = "--skip-tor" not in args
    if "--skip-tor" in args:
        args.remove("--skip-tor")

    max_instances = None
    if "--max-instances" in args:
        idx = args.index("--max-instances")
        args.pop(idx)
        max_instances = int(args.pop(idx))

    query = " ".join(args)
    instances = load_instances()
    chain = build_chain(instances, category=category, skip_tor=skip_tor,
                        max_instances=max_instances)

    if not chain:
        print("No working instances found.", file=sys.stderr)
        sys.exit(1)

    print(f"Fallback chain: {len(chain)} instances", file=sys.stderr)
    for idx, inst in enumerate(chain):
        cat = inst.get("category", "?")
        ms = inst.get("response_ms", 0)
        print(f"  [{idx+1}] {cat:12s} {inst['url']} ({ms}ms)", file=sys.stderr)

    print(file=sys.stderr)
    for inst in chain:
        result = search_instance(inst, query)
        if result is None:
            print(f"  ✗ {inst['url']} — failed", file=sys.stderr)
            continue
        base, _, results, elapsed = result
        if results:
            print(f"  ✓ {base} ({len(results)} results, {elapsed}ms)", file=sys.stderr)
            print(file=sys.stderr)
            output = {"source": base, "query": query, "results": results, "elapsed_ms": elapsed}
            print(json.dumps(output, indent=2))
            return
        print(f"  ~ {base} — 0 results ({elapsed}ms)", file=sys.stderr)

    print("All instances exhausted. No results found.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
