# Project: Crawling Service

## Environment Constraints

**IMPORTANT: The `ai` user has NO GUI access.**

- Playwright/browser automation will fail with `TargetClosedError`
- Use `--fetch-method requests` for testing when possible
- Docker with Xvfb (`./scripts/docker_crawl.sh`) is required for browser-based crawling
- Never assume browser windows can open - they cannot

## Quick Reference

```bash
# Safe testing (no browser needed)
python scripts/crawl.py --domain example.com --depth 0 --fetch-method requests

# Browser crawling requires Docker
./scripts/docker_crawl.sh --tier 1 --limit 1

# Check what's blocked
python scripts/access_report.py
```

## Key Directories

- `corpus/sites/` - Site JSON outputs
- `corpus/raw/` - Archived HTML (capture mode)
- `fetch/` - Core fetch/extraction modules
- `docs/div4*.txt` - Implementation plans
