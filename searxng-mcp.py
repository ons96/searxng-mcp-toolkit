#!/usr/bin/env python3
"""SearXNG MCP server — lightweight, reads pre-sorted instances.json.
Stdio transport. Zero runtime deps beyond stdlib.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

INSTANCES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "instances.json"
)
SEARCH_TIMEOUT = 15
MAX_RESULTS = 5


def load_chain():
    with open(INSTANCES_PATH) as f:
        all_instances = json.load(f)
    working = [
        i for i in all_instances
        if i.get("category") in ("full-json", "html-only")
        and ".onion" not in i.get("url", "")
    ]
    return working


def try_instance(inst, query):
    base = inst["url"].rstrip("/")
    cat = inst.get("category", "html-only")
    if cat == "full-json":
        url = f"{base}/search?format=json&q={urllib.parse.quote(query)}"
    else:
        url = f"{base}/search?q={urllib.parse.quote(query)}"
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            body = resp.read().decode(errors="replace")
        if cat == "full-json":
            data = json.loads(body)
            return [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                }
                for r in data.get("results", [])[:MAX_RESULTS]
            ]
        else:
            return _parse_html(body)
    except Exception:
        return None


def _parse_html(html):
    import re
    results = []
    for art in re.findall(
        r'<article[^>]*class="result[^"]*"[^>]*>.*?</article>', html, re.DOTALL
    )[:MAX_RESULTS]:
        m = re.search(r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', art, re.DOTALL)
        if m:
            results.append({
                "url": m.group(1),
                "title": re.sub(r"<[^>]+>", "", m.group(2)).strip(),
                "snippet": "",
            })
    if results:
        return results
    for m in re.findall(
        r'<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL
    )[:MAX_RESULTS]:
        title = re.sub(r"<[^>]+>", "", m[1]).strip()
        if title and not any(r["url"] == m[0] for r in results):
            results.append({"url": m[0], "title": title, "snippet": ""})
    return results[:MAX_RESULTS]


def rpc_error(req_id, code, msg):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}


def handle(msg):
    rid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "serverInfo": {"name": "searxng-mcp", "version": "2.0.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": [
                    {
                        "name": "web_search",
                        "description": "Web search via SearXNG public instances "
                        "(pre-tested, fallback chain). Returns up to 5 results.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "max_results": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    }
                ]
            },
        }
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "web_search":
            query = args.get("query", "")
            max_r = min(args.get("max_results", 5), 10)
            if not query:
                return rpc_error(rid, -32602, "Missing query")
            results = None
            dead = set()
            for inst in load_chain():
                if inst["url"] in dead:
                    continue
                r = try_instance(inst, query)
                if r is None:
                    dead.add(inst["url"])
                    continue
                results = r
                break
            text = json.dumps(results, indent=2) if results else "No results."
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            }
    return rpc_error(rid, -32601, f"Unknown: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
