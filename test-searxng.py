#!/usr/bin/env python3
"""Test all SearXNG instances from searxng-instances.yaml.

Usage:
  ./test-searxng.py              # interactive, print progress
  ./test-searxng.py --ci         # quiet, write instances.json for MCP
"""
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
import yaml

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "searxng-instances.yaml")
JSON_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instances.json")
TIMEOUT = 10
MAX_WORKERS = 20


def test_instance(url):
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    base = url.rstrip("/")

    json_url = f"{base}/search?format=json&q=test"
    start = time.time()
    try:
        req = urllib.request.Request(json_url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed = round((time.time() - start) * 1000)
            body = resp.read().decode()
            data = json.loads(body)
            results = data.get("results", [])
            engines = list(dict.fromkeys(r.get("engine", "?") for r in results))
            return {
                "status": "up",
                "category": "full-json",
                "response_ms": elapsed,
                "http_status": resp.status,
                "result_count": len(results),
                "engines": engines,
                "json_api": True,
            }
    except urllib.error.HTTPError as e:
        elapsed = round((time.time() - start) * 1000)
        return {
            "status": "down",
            "category": "http-error",
            "response_ms": elapsed,
            "http_status": e.code,
            "result_count": 0,
            "engines": [],
            "json_api": False,
            "error": str(e),
        }
    except json.JSONDecodeError:
        pass
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return {
            "status": "down",
            "category": "offline",
            "response_ms": elapsed,
            "http_status": 0,
            "result_count": 0,
            "engines": [],
            "json_api": False,
            "error": str(e),
        }

    try:
        start = time.time()
        req = urllib.request.Request(base, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed = round((time.time() - start) * 1000)
            body = resp.read().decode(errors="replace").lower()
            if resp.status < 400:
                cat = "html-only" if ("searx" in body or "search" in body) else "not-searxng"
                return {
                    "status": "up",
                    "category": cat,
                    "response_ms": elapsed,
                    "http_status": resp.status,
                    "result_count": 0,
                    "engines": [],
                    "json_api": False,
                    "html_accessible": True,
                }
    except Exception:
        pass

    return {
        "status": "down",
        "category": "offline",
        "response_ms": 0,
        "http_status": 0,
        "result_count": 0,
        "engines": [],
        "json_api": False,
        "error": "unreachable",
    }


def main():
    ci = "--ci" in sys.argv

    with open(DB_PATH) as f:
        db = yaml.safe_load(f)

    instances = db["instances"]
    results = {}

    if not ci:
        print(f"Testing {len(instances)} instances ({MAX_WORKERS} workers)...\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        fut_map = {pool.submit(test_instance, i["url"]): i for i in instances}
        done = 0
        for fut in concurrent.futures.as_completed(fut_map):
            inst = fut_map[fut]
            url = inst["url"]
            done += 1
            try:
                result = fut.result()
                results[url] = result
            except Exception as e:
                results[url] = {"status": "down", "category": "error", "error": str(e)}
            if not ci:
                r = results[url]
                icon = {"full-json": "✓", "html-only": "▸", "not-searxng": "?",
                        "offline": "✗", "http-error": "✗", "error": "!"}.get(r["category"], "?")
                ms = r.get("response_ms", 0)
                print(f"  [{done}/{len(instances)}] {icon} {url}  ({ms}ms, {r['category']})")

    for inst in instances:
        url = inst["url"]
        r = results.get(url, {})
        inst["tested"] = time.strftime("%Y-%m-%d")
        inst["status"] = r.get("status", "unknown")
        inst["category"] = r.get("category", "unknown")
        inst["response_ms"] = r.get("response_ms", 0)
        inst["http_status"] = r.get("http_status", 0)
        inst["json_api"] = r.get("json_api", False)
        inst["result_count"] = r.get("result_count", 0)
        if r.get("engines"):
            inst["engines"] = r["engines"]
        if r.get("error"):
            inst["error"] = r["error"]

    cat_order = {"full-json": 0, "html-only": 1, "not-searxng": 2,
                 "http-error": 3, "offline": 4, "error": 5, "unknown": 6}
    instances.sort(key=lambda i: (
        cat_order.get(i.get("category", "unknown"), 99),
        i.get("response_ms", 99999),
        i["url"],
    ))

    with open(DB_PATH, "w") as f:
        yaml.dump(db, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # --ci: write instances.json (all instances, sorted, for MCP consumption)
    if ci:
        json_out = []
        for i in instances:
            json_out.append({
                "url": i["url"],
                "category": i.get("category", "unknown"),
                "response_ms": i.get("response_ms", 0),
                "tested": i.get("tested", ""),
                "status": i.get("status", ""),
            })
        with open(JSON_OUT, "w") as f:
            json.dump(json_out, f, indent=2)
        print(f"instances.json written ({len(json_out)} entries)")
    else:
        cats = {}
        for i in instances:
            cats[i.get("category", "unknown")] = cats.get(i.get("category", "unknown"), 0) + 1
        print(f"\n{'='*40}")
        for c in ("full-json", "html-only", "not-searxng", "http-error", "offline"):
            if c in cats:
                print(f"  {c:15s}: {cats[c]}")
        print(f"{'='*40}")
        print(f"\nSaved to {DB_PATH}")


if __name__ == "__main__":
    main()
