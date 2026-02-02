# Monkey System Integration Guide (for Agent 1)

This document describes the integration points needed to wire the monkey system
into the main crawl loop. Agent 2 has implemented the core modules; Agent 1
needs to add callouts in `scripts/crawl.py` and `fetch/fetcher.py`.

## Files Implemented by Agent 2

- `fetch/human.py` - Human emulation utilities (HumanSession, mouse/scroll/click)
- `fetch/monkey.py` - Core monkey_see/monkey_do functions + queue management
- `scripts/monkey.py` - CLI interface for operators
- `scripts/flow_editor.py` - Flow file editor/validator
- `scripts/flow_diff.py` - Compare flow versions
- `scripts/cookie_inspect.py` - Cookie management tools

## Integration Points for Agent 1

### 1. Crawl Loop Escalation (scripts/crawl.py)

After all auto methods fail, the crawl loop should:
1. Check if there's a saved flow for the domain
2. Try `monkey_do` to replay it
3. If that fails (or no flow), add to queue

```python
# Import at top of crawl.py
from fetch.monkey import (
    monkey_do,
    add_to_monkey_queue,
    check_perpetual_manual,
    has_flow,
    get_flow_path,
)

# In crawl_site() or equivalent, after auto methods fail:

async def crawl_site_with_monkey_fallback(carrier, config):
    domain = carrier['domain']
    tier = carrier.get('tier')

    # Check if perpetual manual (skip auto entirely)
    if check_perpetual_manual(domain):
        log(f"[perpetual] {domain} requires human every crawl")
        add_to_monkey_queue(domain, reason='perpetual manual site', tier=tier)
        return None

    # Try auto methods first (existing code)
    result = try_auto_methods(domain, config)
    if result and is_success(result):
        return result

    # Level 2: Try monkey_do (replay saved flow)
    if has_flow(domain):
        flow_path = get_flow_path(domain)
        log(f"[monkey_do] Attempting replay for {domain}")

        import asyncio
        monkey_result = asyncio.run(monkey_do(domain, flow_path))

        if monkey_result.success:
            log(f"[monkey_do] Success: {monkey_result.pages} pages, {monkey_result.words} words")
            # Convert monkey_result.captured_pages to your result format
            return convert_monkey_result(monkey_result)
        else:
            log(f"[monkey_do] Failed: {monkey_result.error}")

    # Level 3: Add to queue for human
    auto_methods_tried = ['http', 'js', 'stealth']  # Track what was tried
    add_to_monkey_queue(
        domain,
        reason=result.error if result else 'all methods failed',
        tier=tier,
        attempts_auto=auto_methods_tried
    )
    log(f"[queue] {domain} added to monkey_queue")

    return None
```

### 2. Cookie Loading (fetch/fetcher.py)

When fetching with Playwright, load saved cookies if available:

```python
# Import at top of fetcher.py
from fetch.monkey import load_site_cookies

# In fetch_playwright(), after creating context:

def fetch_playwright(url: str, config: FetchConfig, stealth: bool = False):
    # ... existing context creation ...

    context = browser.new_context(**context_args)

    # Load cookies if available
    domain = urlparse(url).netloc.replace('www.', '')
    cookies = load_site_cookies(domain)
    if cookies:
        context.add_cookies(cookies)

    # ... rest of fetch logic ...
```

### 3. Cookie Saving (fetch/fetcher.py)

After successful fetch, save cookies for future use:

```python
# Import
from fetch.monkey import save_site_cookies

# After successful page load, before closing:

if page and result_success:
    domain = urlparse(url).netloc.replace('www.', '')
    cookies = context.cookies()
    if cookies:
        save_site_cookies(domain, cookies)
```

### 4. Recon Integration (fetch/recon.py)

If implementing recon, use monkey queue for sites that need it:

```python
from fetch.monkey import add_to_monkey_queue

def recon_site(domain):
    recon = do_recon(domain)

    # If recon indicates need for manual handling
    if recon.recommended_method == 'manual':
        add_to_monkey_queue(domain, reason=f'recon: {recon.challenge_type}')

    return recon
```

## API Reference

### fetch/monkey.py Exports

```python
# Queue management
add_to_monkey_queue(domain: str, reason: str, tier: int = None, attempts_auto: list = None)
remove_from_queue(domain: str, pages: int, words: int)
get_next_queued() -> QueueEntry | None
list_queue() -> list[QueueEntry]
clear_queue() -> int

# Perpetual manual detection
check_perpetual_manual(domain: str, lookback_days: int = 90) -> bool

# Flow management
has_flow(domain: str) -> bool
get_flow_path(domain: str) -> Path | None
get_flow_age_days(domain: str) -> float | None

# Cookie management
load_site_cookies(domain: str) -> list[dict] | None
save_site_cookies(domain: str, cookies: list[dict])

# Core functions (async)
monkey_see(domain: str, output_dir: Path = None) -> MonkeySeeResult
monkey_do(domain: str, flow_path: Path = None, headless: bool = True) -> MonkeyDoResult

# Scheduling
run_scheduled_replays() -> list[tuple[str, MonkeyDoResult]]
add_to_schedule(domain: str, cadence: str = 'monthly')
get_due_replays() -> list[ScheduleEntry]
```

### Result Types

```python
@dataclass
class MonkeyDoResult:
    success: bool
    domain: str
    pages: int = 0
    words: int = 0
    error: str | None = None
    failed_at: int | None = None  # Action index where replay failed
    captured_pages: list[CapturedPage] = field(default_factory=list)

@dataclass
class CapturedPage:
    url: str
    html: str
    word_count: int
    timestamp: float
```

## Data Files

All data stored in `~/.crawl/`:

```
~/.crawl/
├── flows/
│   └── {domain}.flow.json     # Recorded flows
├── cookies/
│   └── {domain}.json          # Saved cookies
├── monkey_queue.json          # Queue state
└── replay_schedule.yaml       # Scheduled replays
```

## Testing Integration

After wiring in the integration points, test with:

```bash
# Check queue is empty
python scripts/monkey.py --list

# Crawl a known-blocked site
python scripts/crawl.py --domain knight-swift.com --js --stealth

# Check it was queued
python scripts/monkey.py --list

# Human processes queue
python scripts/monkey.py --next

# Verify flow was saved
python scripts/flow_editor.py --show knight-swift.com

# Test replay
python scripts/monkey.py --do knight-swift.com --visible

# Next crawl should use monkey_do automatically
python scripts/crawl.py --domain knight-swift.com
```

## Notes

- `monkey_see` and `monkey_do` are async functions - use `asyncio.run()` if calling from sync code
- Cookies are in Playwright format (list of dicts with name, value, domain, path, expires, etc.)
- Flow files are human-readable JSON - operators can edit with `flow_editor.py`
- Queue priority: tier 1 = high, others = normal
- Perpetual manual threshold: 3+ queue appearances in 90 days
