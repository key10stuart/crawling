# Access Layer Runbook

Operational guide for crawling. Commands verified to work.

---

## Quick Reference

### Common Commands

```bash
# Run a crawl (HTTP only - works without GUI)
python scripts/crawl.py --domain example.com --depth 2 --fetch-method requests

# Tier crawl with parallel workers
python scripts/crawl.py --tier 1 --limit 5 -j 4 --progress

# Check access metrics
python scripts/access_report.py
python scripts/access_report.py --tier 1

# Check monkey queue
python scripts/monkey.py --list

# Process next blocked site
python scripts/monkey.py --next

# Bootstrap cookies for blocked site (requires GUI)
python scripts/bootstrap_cookies.py --domain example.com

# Check cookie status
python scripts/cookie_inspect.py --list
python scripts/cookie_inspect.py --expiring 7
```

### Key Files

| File | Purpose |
|------|---------|
| `corpus/sites/*.json` | Crawl outputs |
| `~/.crawl/cookies/*.json` | Saved cookies |
| `~/.crawl/monkey_queue.json` | Sites needing human attention |
| `~/.crawl/flows/*.flow.json` | Recorded browsing flows |
| `profiles/access_playbooks.yaml` | Per-site strategy overrides |

---

## Crawl Commands

### Basic Crawling

```bash
# Single domain (HTTP fetch, no browser needed)
python scripts/crawl.py --domain jbhunt.com --depth 2 --fetch-method requests

# Single domain with browser rendering (needs GUI or Docker)
python scripts/crawl.py --domain saia.com --depth 2 --fetch-method js

# Tier crawl
python scripts/crawl.py --tier 1 --fetch-method requests

# Tier crawl with limit and parallelism
python scripts/crawl.py --tier 1 --limit 10 -j 4 --progress
```

### Fetch Method Options

| Method | When to Use |
|--------|-------------|
| `requests` | Static HTML sites, fast, works without GUI |
| `js` | SPA sites, React/Vue/Angular, needs Playwright |
| `stealth` | Sites with bot detection, uses playwright-stealth |
| `visible` | Last resort, runs browser visibly (requires GUI) |

```bash
# Force specific method
python scripts/crawl.py --domain site.com --fetch-method stealth

# Patient mode (longer delays, helps with rate limiting)
python scripts/crawl.py --domain site.com --patient

# Ultra-patient mode (2-15 min delays)
python scripts/crawl.py --domain site.com --slow-drip

# Visible browser (bypasses some bot detection, requires GUI)
python scripts/crawl.py --domain site.com --no-headless
```

### Freshness Control

```bash
# Skip sites crawled within 7 days
python scripts/crawl.py --tier 1 --freshen 7d

# Skip sites crawled within 2 hours
python scripts/crawl.py --tier 1 --freshen 2h
```

### Docker (for browser crawls without GUI)

```bash
# Run in Docker with virtual display
./scripts/docker_crawl.sh --tier 1 --limit 5

# Force rebuild Docker image
python scripts/crawl.py --docker --docker-rebuild --tier 1 --limit 1
```

---

## Access Report

```bash
# Full report
python scripts/access_report.py

# Filter by tier
python scripts/access_report.py --tier 1

# Get single metric value
python scripts/access_report.py --metric success_rate

# JSON output
python scripts/access_report.py --json
```

---

## Monkey System (Human-in-Loop)

For sites that block automated access.

### Queue Management

```bash
# View queue
python scripts/monkey.py --list

# Add site to queue
python scripts/monkey.py --add blocked-site.com --reason "StackPath CAPTCHA" --tier 1

# Clear queue
python scripts/monkey.py --clear
```

### Recording and Replay

```bash
# Record a flow (opens browser, you navigate, it records)
python scripts/monkey.py --see knight-swift.com

# Replay a recorded flow
python scripts/monkey.py --do knight-swift.com

# Replay with visible browser (for debugging)
python scripts/monkey.py --do knight-swift.com --visible

# Process next item in queue
python scripts/monkey.py --next
```

### Schedules

```bash
# List scheduled replays
python scripts/monkey.py --schedules

# Run all due scheduled replays
python scripts/monkey.py --schedule
```

### Flow Info

```bash
# Show info about saved flow
python scripts/monkey.py --info knight-swift.com
```

---

## Cookie Management

```bash
# List all saved cookies
python scripts/cookie_inspect.py --list

# Show cookies for specific domain
python scripts/cookie_inspect.py --show knight-swift.com

# Check if cookies are still valid
python scripts/cookie_inspect.py --check knight-swift.com

# Show cookies expiring within N days
python scripts/cookie_inspect.py --expiring 7

# Open browser to refresh cookies (requires GUI)
python scripts/cookie_inspect.py --refresh knight-swift.com

# Delete cookies for domain
python scripts/cookie_inspect.py --delete knight-swift.com

# Export cookies (Netscape format)
python scripts/cookie_inspect.py --export knight-swift.com

# Bootstrap cookies (opens browser to solve CAPTCHA)
python scripts/bootstrap_cookies.py --domain knight-swift.com
```

---

## Evaluation

```bash
# Interactive evaluation
python scripts/eval_extraction.py

# Evaluate specific domain
python scripts/eval_extraction.py --domain saia.com

# Auto-evaluate (no prompts)
python scripts/eval_extraction.py --auto

# Auto-evaluate tier-1 only
python scripts/eval_extraction.py --auto --tier 1

# Auto-evaluate with parallelism
python scripts/eval_extraction.py --auto -j 4 -n 10
```

---

## Troubleshooting

### Site Returns CAPTCHA

1. Check if we have cookies:
   ```bash
   python scripts/cookie_inspect.py --check blocked-site.com
   ```

2. If expired or missing, bootstrap:
   ```bash
   python scripts/bootstrap_cookies.py --domain blocked-site.com
   ```

3. Or add to monkey queue for later:
   ```bash
   python scripts/monkey.py --add blocked-site.com --reason "CAPTCHA" --tier 1
   ```

### Browser Crawl Fails (TargetClosedError)

The `ai` user has no GUI access. Options:

1. Use HTTP-only fetch:
   ```bash
   python scripts/crawl.py --domain site.com --fetch-method requests
   ```

2. Use Docker with virtual display:
   ```bash
   ./scripts/docker_crawl.sh --domain site.com
   ```

### Cookie Expiration

Check which cookies are expiring soon:
```bash
python scripts/cookie_inspect.py --expiring 7
```

### Queue Backlog

Process queue items:
```bash
# Check queue
python scripts/monkey.py --list

# Process one at a time
python scripts/monkey.py --next

# Batch process
for i in {1..5}; do python scripts/monkey.py --next; done
```

---

## Weekly Checklist

- [ ] Check access metrics: `python scripts/access_report.py`
- [ ] Check expiring cookies: `python scripts/cookie_inspect.py --expiring 7`
- [ ] Process monkey queue: `python scripts/monkey.py --list`
- [ ] Run scheduled replays: `python scripts/monkey.py --schedule`

---

## Notes

- The `ai` user cannot open browser windows (no GUI access)
- Use `--fetch-method requests` for testing when possible
- Docker with Xvfb is required for browser-based crawling
- Monkey flows require GUI to record (`--see`) but can replay headless (`--do`)

---

## Revision History

| Date | Change |
|------|--------|
| 2026-02-07 | Rewritten with verified commands only |
| 2026-01-26 | Initial runbook (Agent 3) |
