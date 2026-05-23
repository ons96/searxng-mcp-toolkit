# opencode SearXNG Setup

Scripts and config for web search via public SearXNG instances.

## Files

| File | Purpose |
|------|---------|
| `searxng-instances.yaml` | 145 SearXNG instances with test results (status, response time, category) |
| `test-searxng.py` | Run full test suite against all instances (updates YAML) |
| `searxng-fallback.py` | CLI search tool with fallback chain (tries instances by speed) |
| `searxng-mcp-server.py` | Minimal MCP server over stdio |

## Usage

### CLI search
```bash
# Search (auto: JSON first, HTML fallback)
~/.config/opencode/setup/searxng-fallback.py "your query"

# JSON API only (faster, structured)
~/.config/opencode/setup/searxng-fallback.py --category full-json "query"

# First 10 fastest instances only
~/.config/opencode/setup/searxng-fallback.py --max-instances 10 "query"

# List all working instances ranked by speed
~/.config/opencode/setup/searxng-fallback.py --list
```

### MCP server (opencode / Claude / Cursor)
```json
{
  "mcpServers": {
    "searxng": {
      "command": "python3",
      "args": ["/home/owen/.config/opencode/setup/searxng-mcp-server.py"]
    }
  }
}
```

### Re-test all instances
```bash
~/.config/opencode/setup/test-searxng.py
```

## Stats (2026-05-23)

| Category | Count | Notes |
|----------|-------|-------|
| full-json | 3 | Direct JSON API (monocles.de, serxng-deployment, searx.mv-software.de) |
| html-only | 75 | Web scraping fallback |
| not-searxng | 8 | Resolves but is not a search engine |
| http-error | 11 | Blocked (403/429/etc.) |
| offline | 48 | Unreachable |
| **Total** | **145** | 136 clearnet + 9 Tor |

Only 3/145 expose JSON API — most operators keep HTML-only (default config).
