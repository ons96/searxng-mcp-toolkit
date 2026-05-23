#!/usr/bin/env python3
"""Minimal MCP server: SearXNG web search via fallback chain.
Stdio transport — configure in opencode.json as a subprocess MCP tool.
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
TIMEOUT = 15
MAX_RESULTS = 5


def load_instances():
    with open(DB_PATH) as f:
        db = yaml.safe_load(f)
    return db["instances"]


def build_chain(instances):
    priority = {"full-json": 0, "html-only": 1}
    candidates = []
    for i in instances:
        cat = i.get("category", "unknown")
        if cat not in priority:
            continue
        if ".onion" in i.get("url", ""):
            continue
        candidates.append((priority[cat], i.get("response_ms", 99999), i))
    candidates.sort(key=lambda x: (x[0], x[1]))
    return [c[2] for c in candidates]


def search_json(instance, query):
    base = instance["url"].rstrip("/")
    url = f"{base}/search?format=json&q={urllib.parse.quote(query)}"
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode()
            data = json.loads(body)
            return data.get("results", [])
    except Exception:
        return None


def search_html(instance, query):
    base = instance["url"].rstrip("/")
    url = f"{base}/search?q={urllib.parse.quote(query)}"
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            html = resp.read().decode(errors="replace")
    except Exception:
        return None
    import re
    results = []
    articles = re.findall(
        r'<article[^>]*class="result[^"]*"[^>]*>.*?</article>',
        html, re.DOTALL
    )
    for art in articles[:MAX_RESULTS]:
        title_m = re.search(
            r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', art, re.DOTALL
        )
        snippet_m = re.search(
            r'<p[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</p>', art, re.DOTALL
        )
        if title_m:
            results.append({
                "url": title_m.group(1),
                "title": re.sub(r'<[^>]+>', '', title_m.group(2)).strip(),
                "snippet": re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()
                if snippet_m else "",
            })
    if not results:
        divs = re.findall(
            r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        for url, title in divs[:MAX_RESULTS]:
            clean = re.sub(r'<[^>]+>', '', title).strip()
            results.append({"url": url, "title": clean, "snippet": ""})
    return results[:MAX_RESULTS]


def web_search(query, max_results=5):
    instances = load_instances()
    chain = build_chain(instances)
    results = []
    for inst in chain:
        cat = inst.get("category", "full-json")
        if cat == "full-json":
            r = search_json(inst, query)
            if r is not None and r:
                results = [{
                    "url": hit.get("url", ""),
                    "title": hit.get("title", ""),
                    "snippet": hit.get("content", ""),
                } for hit in r[:max_results]]
                break
            continue
        r = search_html(inst, query)
        if r is not None and r:
            results = r[:max_results]
            break
    return results


# ── Minimal MCP server (JSON-RPC 2.0 over stdio) ──

def jsonrpc_error(req_id, code, message, data=None):
    resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data:
        resp["error"]["data"] = data
    return resp


def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "serverInfo": {"name": "searxng-fallback", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "tools": [{
                    "name": "web_search",
                    "description": "Web search via SearXNG public instances (fallback chain). "
                                   "Returns up to 5 results with url, title, snippet.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "max_results": {"type": "integer", "description": "Max results (1-10)", "default": 5},
                        },
                        "required": ["query"],
                    },
                }]
            }
        }
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "web_search":
            query = args.get("query", "")
            max_results = min(args.get("max_results", 5), 10)
            if not query:
                return jsonrpc_error(req_id, -32602, "Missing required parameter: query")
            try:
                results = web_search(query, max_results)
                content = json.dumps(results, indent=2) if results else "No results found."
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": content}],
                        "isError": False,
                    }
                }
            except Exception as e:
                return jsonrpc_error(req_id, -32603, f"Search failed: {e}")
    else:
        return jsonrpc_error(req_id, -32601, f"Method not found: {method}")


def main():
    # consume stdin line by line
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
