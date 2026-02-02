"""
Monkey system for human-assisted crawling.

monkey_see: Human browses + record flow + capture content
monkey_do: Unattended replay of saved flows with human emulation

When automation fails, queue for minimal human assist.
When human assists, record everything so we can replay next time.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .human import (
    HumanSession,
    human_delay,
    human_click_async,
    human_scroll_async,
    human_mouse_move_async,
)

# Default paths
CRAWL_DIR = Path.home() / '.crawl'
FLOWS_DIR = CRAWL_DIR / 'flows'
QUEUE_FILE = CRAWL_DIR / 'monkey_queue.json'
SCHEDULE_FILE = CRAWL_DIR / 'replay_schedule.yaml'
COOKIES_DIR = CRAWL_DIR / 'cookies'


def ensure_dirs():
    """Ensure all required directories exist."""
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# FLOW FILE FORMAT
# =============================================================================

@dataclass
class FlowAction:
    """Single action in a recorded flow."""
    action: str  # 'navigate', 'click', 'scroll', 'type', 'wait'
    timestamp: float
    delay_since_last: float

    # Navigate-specific
    url: str | None = None

    # Click-specific
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    meta: dict = field(default_factory=dict)  # tagName, text, href

    # Scroll-specific
    direction: str | None = None  # 'up', 'down'
    amount: int | None = None

    # Type-specific
    text: str | None = None


@dataclass
class Flow:
    """Complete recorded flow for a domain."""
    domain: str
    recorded: str  # ISO timestamp
    total_duration_sec: float
    viewport: dict
    user_agent: str | None
    actions: list[FlowAction] = field(default_factory=list)

    def save(self, path: Path | None = None):
        """Save flow to JSON file."""
        if path is None:
            ensure_dirs()
            path = FLOWS_DIR / f'{self.domain}.flow.json'

        data = asdict(self)
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> 'Flow':
        """Load flow from JSON file."""
        data = json.loads(path.read_text())
        actions = [FlowAction(**a) for a in data.pop('actions', [])]
        return cls(**data, actions=actions)


# =============================================================================
# QUEUE MANAGEMENT
# =============================================================================

@dataclass
class QueueEntry:
    """Entry in the monkey queue."""
    domain: str
    added: str  # ISO timestamp
    reason: str
    attempts_auto: list[str] = field(default_factory=list)
    attempts_monkey_do: int = 0
    priority: str = 'normal'  # 'high', 'normal', 'low'
    tier: int | None = None
    last_flow_date: str | None = None


@dataclass
class CompletedEntry:
    """Completed queue entry."""
    domain: str
    completed: str  # ISO timestamp
    pages: int
    words: int


@dataclass
class MonkeyQueue:
    """Monkey queue state."""
    queue: list[QueueEntry] = field(default_factory=list)
    completed: list[CompletedEntry] = field(default_factory=list)

    def save(self):
        """Save queue to file."""
        ensure_dirs()
        data = {
            'queue': [asdict(e) for e in self.queue],
            'completed': [asdict(e) for e in self.completed],
        }
        QUEUE_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> 'MonkeyQueue':
        """Load queue from file."""
        if not QUEUE_FILE.exists():
            return cls()
        try:
            data = json.loads(QUEUE_FILE.read_text())
            queue = [QueueEntry(**e) for e in data.get('queue', [])]
            completed = [CompletedEntry(**e) for e in data.get('completed', [])]
            return cls(queue=queue, completed=completed)
        except (json.JSONDecodeError, TypeError):
            return cls()


def add_to_monkey_queue(
    domain: str,
    reason: str,
    tier: int | None = None,
    attempts_auto: list[str] | None = None,
) -> None:
    """
    Add site to queue for human attention.

    Args:
        domain: Domain name
        reason: Why it was queued
        tier: Carrier tier (1=high priority)
        attempts_auto: List of auto methods that were tried
    """
    queue = MonkeyQueue.load()

    # Check if already in queue
    existing = next((e for e in queue.queue if e.domain == domain), None)
    if existing:
        existing.attempts_monkey_do += 1
        existing.reason = reason
        if attempts_auto:
            existing.attempts_auto = list(set(existing.attempts_auto + attempts_auto))
    else:
        # Check for existing flow
        flow_path = FLOWS_DIR / f'{domain}.flow.json'
        last_flow_date = None
        if flow_path.exists():
            try:
                flow = Flow.load(flow_path)
                last_flow_date = flow.recorded
            except Exception:
                pass

        entry = QueueEntry(
            domain=domain,
            added=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            attempts_auto=attempts_auto or [],
            attempts_monkey_do=0,
            priority='high' if tier == 1 else 'normal',
            tier=tier,
            last_flow_date=last_flow_date,
        )
        queue.queue.append(entry)

    queue.save()


def remove_from_queue(domain: str, pages: int, words: int) -> None:
    """
    Move site from queue to completed.

    Args:
        domain: Domain name
        pages: Number of pages captured
        words: Total words captured
    """
    queue = MonkeyQueue.load()

    # Remove from queue
    queue.queue = [e for e in queue.queue if e.domain != domain]

    # Add to completed
    queue.completed.append(CompletedEntry(
        domain=domain,
        completed=datetime.now(timezone.utc).isoformat(),
        pages=pages,
        words=words,
    ))

    queue.save()


def get_next_queued() -> QueueEntry | None:
    """
    Get next site from queue (highest priority first).

    Priority order:
    1. High priority (tier 1)
    2. Oldest queue entries
    """
    queue = MonkeyQueue.load()
    if not queue.queue:
        return None

    # Sort by priority (high first), then by age (oldest first)
    priority_order = {'high': 0, 'normal': 1, 'low': 2}
    sorted_queue = sorted(
        queue.queue,
        key=lambda e: (priority_order.get(e.priority, 1), e.added)
    )

    return sorted_queue[0] if sorted_queue else None


def list_queue() -> list[QueueEntry]:
    """List all entries in queue."""
    queue = MonkeyQueue.load()
    return queue.queue


def clear_queue() -> int:
    """Clear the queue. Returns number of entries cleared."""
    queue = MonkeyQueue.load()
    count = len(queue.queue)
    queue.queue = []
    queue.save()
    return count


# =============================================================================
# PERPETUAL MANUAL DETECTION
# =============================================================================

def check_perpetual_manual(domain: str, lookback_days: int = 90) -> bool:
    """
    Check if site needs human every time.

    A site is perpetual manual if queued 3+ times in lookback period.

    Args:
        domain: Domain to check
        lookback_days: Days to look back

    Returns:
        True if site is perpetual manual
    """
    queue = MonkeyQueue.load()
    cutoff = datetime.now(timezone.utc).timestamp() - (lookback_days * 86400)

    # Count recent completions for this domain
    recent_completions = 0
    for entry in queue.completed:
        if entry.domain != domain:
            continue
        try:
            completed_time = datetime.fromisoformat(entry.completed.replace('Z', '+00:00'))
            if completed_time.timestamp() > cutoff:
                recent_completions += 1
        except ValueError:
            pass

    return recent_completions >= 3


# =============================================================================
# REPLAY SCHEDULING
# =============================================================================

@dataclass
class ScheduleEntry:
    """Scheduled replay entry."""
    domain: str
    cadence: str  # 'daily', 'weekly', 'monthly', 'quarterly'
    last_success: str | None = None
    last_attempt: str | None = None
    consecutive_failures: int = 0


def load_replay_schedule() -> list[ScheduleEntry]:
    """Load replay schedule from file."""
    if not SCHEDULE_FILE.exists():
        return []
    try:
        data = yaml.safe_load(SCHEDULE_FILE.read_text())
        return [ScheduleEntry(**e) for e in data.get('schedules', [])]
    except Exception:
        return []


def save_replay_schedule(schedules: list[ScheduleEntry]) -> None:
    """Save replay schedule to file."""
    ensure_dirs()
    data = {'schedules': [asdict(e) for e in schedules]}
    SCHEDULE_FILE.write_text(yaml.dump(data, default_flow_style=False))


def add_to_schedule(domain: str, cadence: str = 'monthly') -> None:
    """Add domain to replay schedule."""
    schedules = load_replay_schedule()

    # Check if already scheduled
    existing = next((s for s in schedules if s.domain == domain), None)
    if existing:
        existing.cadence = cadence
    else:
        schedules.append(ScheduleEntry(
            domain=domain,
            cadence=cadence,
            last_success=datetime.now(timezone.utc).isoformat(),
        ))

    save_replay_schedule(schedules)


def get_due_replays() -> list[ScheduleEntry]:
    """Get list of domains due for replay."""
    schedules = load_replay_schedule()
    now = datetime.now(timezone.utc)
    due = []

    cadence_days = {
        'daily': 1,
        'weekly': 7,
        'monthly': 30,
        'quarterly': 90,
    }

    for entry in schedules:
        if not entry.last_success:
            due.append(entry)
            continue

        try:
            last = datetime.fromisoformat(entry.last_success.replace('Z', '+00:00'))
            days_since = (now - last).days
            threshold = cadence_days.get(entry.cadence, 30)

            if days_since >= threshold:
                due.append(entry)
        except ValueError:
            due.append(entry)

    return due


# =============================================================================
# COOKIE MANAGEMENT
# =============================================================================

def load_site_cookies(domain: str) -> list[dict] | None:
    """Load cookies for a domain."""
    cookie_file = COOKIES_DIR / f'{domain}.json'
    if not cookie_file.exists():
        return None
    try:
        return json.loads(cookie_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_site_cookies(domain: str, cookies: list[dict]) -> None:
    """Save cookies for a domain."""
    ensure_dirs()
    cookie_file = COOKIES_DIR / f'{domain}.json'
    cookie_file.write_text(json.dumps(cookies, indent=2))


# =============================================================================
# MONKEY_SEE: Human-Assisted Recording
# =============================================================================

# JavaScript to inject for recording user actions
RECORDER_JS = """
(function() {
    // Track last action time
    let lastActionTime = Date.now();

    // Record click events
    document.addEventListener('click', function(e) {
        const target = e.target;
        const now = Date.now();

        // Build selector path
        let selector = '';
        let el = target;
        const path = [];
        while (el && el !== document.body) {
            let s = el.tagName.toLowerCase();
            if (el.id) {
                s += '#' + el.id;
                path.unshift(s);
                break;
            } else if (el.className && typeof el.className === 'string') {
                const classes = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                if (classes) s += '.' + classes;
            }
            const parent = el.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                if (siblings.length > 1) {
                    const idx = siblings.indexOf(el) + 1;
                    s += ':nth-child(' + idx + ')';
                }
            }
            path.unshift(s);
            el = parent;
        }
        selector = path.join(' > ');

        window.recordClick({
            selector: selector,
            x: e.clientX,
            y: e.clientY,
            timestamp: now,
            delay_since_last: (now - lastActionTime) / 1000,
            meta: {
                tagName: target.tagName,
                text: (target.innerText || '').slice(0, 100),
                href: target.href || null
            }
        });

        lastActionTime = now;
    }, true);

    // Record scroll events (debounced)
    let scrollTimeout;
    let scrollStart = null;
    let lastScrollY = window.scrollY;

    window.addEventListener('scroll', function() {
        const now = Date.now();
        if (scrollStart === null) {
            scrollStart = now;
            lastScrollY = window.scrollY;
        }

        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(function() {
            const scrollAmount = window.scrollY - lastScrollY;
            if (Math.abs(scrollAmount) > 50) {
                window.recordScroll({
                    direction: scrollAmount > 0 ? 'down' : 'up',
                    amount: Math.abs(scrollAmount),
                    timestamp: now,
                    delay_since_last: (scrollStart - lastActionTime) / 1000
                });
                lastActionTime = now;
            }
            scrollStart = null;
            lastScrollY = window.scrollY;
        }, 150);
    });
})();
"""


@dataclass
class CapturedPage:
    """Page captured during monkey_see session."""
    url: str
    html: str
    word_count: int
    timestamp: float


@dataclass
class MonkeySeeResult:
    """Result of monkey_see session."""
    domain: str
    pages: int
    words: int
    flow_saved: bool
    flow_path: str | None = None
    captured_pages: list[CapturedPage] = field(default_factory=list)
    error: str | None = None


async def monkey_see(domain: str, output_dir: Path | None = None) -> MonkeySeeResult:
    """
    Human browses, record flow, capture content.

    Opens visible browser for human to navigate.
    Records all clicks, scrolls, and navigations.
    Captures page content at each navigation.

    Args:
        domain: Domain to browse
        output_dir: Directory to save captured content (optional)

    Returns:
        MonkeySeeResult with captured pages and flow info
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return MonkeySeeResult(
            domain=domain,
            pages=0,
            words=0,
            flow_saved=False,
            error='playwright not installed'
        )

    ensure_dirs()

    flow_actions: list[dict] = []
    captured_pages: list[CapturedPage] = []
    session_start = time.time()
    last_action_time = session_start

    async with async_playwright() as p:
        # Launch visible browser
        browser = await p.chromium.launch(headless=False)

        # Create session with consistent fingerprint
        session = HumanSession()
        context_options = session.apply_to_context_options()
        context = await browser.new_context(**context_options)

        page = await context.new_page()

        # === RECORDING BINDINGS ===

        async def record_click(data: dict):
            nonlocal last_action_time
            flow_actions.append({
                'action': 'click',
                **data
            })
            last_action_time = time.time()

        async def record_scroll(data: dict):
            nonlocal last_action_time
            flow_actions.append({
                'action': 'scroll',
                **data
            })
            last_action_time = time.time()

        await page.expose_function('recordClick', record_click)
        await page.expose_function('recordScroll', record_scroll)

        # === CAPTURE ON NAVIGATION ===

        async def capture_current_page():
            try:
                html = await page.content()
                url = page.url

                # Quick word count
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'lxml')
                # Remove script/style
                for tag in soup(['script', 'style', 'noscript']):
                    tag.decompose()
                text = soup.get_text(separator=' ', strip=True)
                word_count = len(text.split())

                captured_pages.append(CapturedPage(
                    url=url,
                    html=html,
                    word_count=word_count,
                    timestamp=time.time()
                ))
                print(f"  Captured: {url} ({word_count} words)")

            except Exception as e:
                print(f"  Capture failed: {e}")

        # Track navigation
        async def on_load():
            nonlocal last_action_time
            now = time.time()
            flow_actions.append({
                'action': 'navigate',
                'url': page.url,
                'timestamp': now,
                'delay_since_last': now - last_action_time
            })
            last_action_time = now
            await capture_current_page()

        page.on('load', lambda: asyncio.create_task(on_load()))

        # === INJECT RECORDER ===

        async def inject_recorder():
            try:
                await page.evaluate(RECORDER_JS)
            except Exception:
                pass  # May fail on some pages, that's ok

        page.on('load', lambda: asyncio.create_task(inject_recorder()))

        # === START SESSION ===

        start_url = f'https://www.{domain}'
        print(f"Opening {domain}...")
        print("Browse around. Press ENTER when done.\n")

        await page.goto(start_url, wait_until='networkidle')
        await inject_recorder()
        await capture_current_page()

        # Wait for user to press Enter
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Final capture of current page
        await capture_current_page()

        # Get cookies for future use
        cookies = await context.cookies()
        if cookies:
            save_site_cookies(domain, cookies)
            print(f"Saved {len(cookies)} cookies")

        await browser.close()

    # === SAVE FLOW ===

    session_end = time.time()
    flow = Flow(
        domain=domain,
        recorded=datetime.now(timezone.utc).isoformat(),
        total_duration_sec=session_end - session_start,
        viewport={'width': session.viewport[0], 'height': session.viewport[1]},
        user_agent=session.user_agent,
        actions=[FlowAction(**a) for a in flow_actions]
    )

    flow_path = FLOWS_DIR / f'{domain}.flow.json'
    flow.save(flow_path)

    # === SAVE CAPTURED CONTENT ===

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for i, cp in enumerate(captured_pages):
            html_path = output_dir / f'{domain}_{i}.html'
            html_path.write_text(cp.html)

    # === SUMMARY ===

    total_words = sum(cp.word_count for cp in captured_pages)
    unique_pages = len(set(cp.url for cp in captured_pages))

    print(f"\nDone: {unique_pages} pages, {total_words} words")
    print(f"Flow saved to {flow_path}")

    # Add to replay schedule
    add_to_schedule(domain, 'monthly')

    # Remove from queue if present
    remove_from_queue(domain, unique_pages, total_words)

    return MonkeySeeResult(
        domain=domain,
        pages=unique_pages,
        words=total_words,
        flow_saved=True,
        flow_path=str(flow_path),
        captured_pages=captured_pages
    )


# =============================================================================
# MONKEY_DO: Unattended Replay
# =============================================================================

@dataclass
class MonkeyDoResult:
    """Result of monkey_do replay."""
    success: bool
    domain: str
    pages: int = 0
    words: int = 0
    error: str | None = None
    failed_at: int | None = None
    captured_pages: list[CapturedPage] = field(default_factory=list)


async def monkey_do(
    domain: str,
    flow_path: Path | None = None,
    headless: bool = True,
) -> MonkeyDoResult:
    """
    Replay saved flow unattended with human emulation.

    Args:
        domain: Domain to replay
        flow_path: Path to flow file (default: ~/.crawl/flows/{domain}.flow.json)
        headless: Run browser headlessly

    Returns:
        MonkeyDoResult with captured pages or error info
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return MonkeyDoResult(
            success=False,
            domain=domain,
            error='playwright not installed'
        )

    # Load flow
    if flow_path is None:
        flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        return MonkeyDoResult(
            success=False,
            domain=domain,
            error='no_flow'
        )

    try:
        flow = Flow.load(flow_path)
    except Exception as e:
        return MonkeyDoResult(
            success=False,
            domain=domain,
            error=f'flow_parse_error: {e}'
        )

    captured_pages: list[CapturedPage] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        # Create session matching recorded flow
        session = HumanSession(
            viewport=(flow.viewport.get('width', 1920), flow.viewport.get('height', 1080))
        )
        context_options = session.apply_to_context_options()
        if flow.user_agent:
            context_options['user_agent'] = flow.user_agent

        context = await browser.new_context(**context_options)

        # Load cookies if available
        cookies = load_site_cookies(domain)
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        # === REPLAY ACTIONS ===

        for i, action in enumerate(flow.actions):
            try:
                # Apply delay with human variance
                delay = human_delay(action.delay_since_last, allow_distraction=True)
                await asyncio.sleep(delay)

                if action.action == 'navigate':
                    await page.goto(action.url, wait_until='networkidle', timeout=30000)

                elif action.action == 'click':
                    if action.x is not None and action.y is not None:
                        # Position-based click with human emulation
                        await human_click_async(page, action.x, action.y, session)
                    elif action.selector:
                        # Selector-based fallback
                        try:
                            element = page.locator(action.selector)
                            box = await element.bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2
                                y = box['y'] + box['height'] / 2
                                await human_click_async(page, x, y, session, box)
                            else:
                                await element.click()
                        except Exception:
                            # Last resort: direct click at recorded position
                            if action.x and action.y:
                                await page.mouse.click(action.x, action.y)

                elif action.action == 'scroll':
                    await human_scroll_async(
                        page,
                        action.amount or 300,
                        action.direction or 'down',
                        session
                    )

                # Capture after each navigation/major action
                if action.action == 'navigate' or (action.action == 'click' and action.meta.get('href')):
                    await asyncio.sleep(0.5)  # Brief settle time
                    try:
                        html = await page.content()
                        url = page.url

                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'lxml')
                        for tag in soup(['script', 'style', 'noscript']):
                            tag.decompose()
                        text = soup.get_text(separator=' ', strip=True)
                        word_count = len(text.split())

                        captured_pages.append(CapturedPage(
                            url=url,
                            html=html,
                            word_count=word_count,
                            timestamp=time.time()
                        ))
                    except Exception:
                        pass

            except Exception as e:
                await browser.close()
                return MonkeyDoResult(
                    success=False,
                    domain=domain,
                    error=f'replay_failed: {e}',
                    failed_at=i,
                    pages=len(captured_pages),
                    captured_pages=captured_pages
                )

        # Save updated cookies
        cookies = await context.cookies()
        if cookies:
            save_site_cookies(domain, cookies)

        await browser.close()

    # === RESULT ===

    total_words = sum(cp.word_count for cp in captured_pages)
    unique_pages = len(set(cp.url for cp in captured_pages))

    # Check if we got meaningful content
    if total_words < 100:
        return MonkeyDoResult(
            success=False,
            domain=domain,
            error='low_content',
            pages=unique_pages,
            words=total_words,
            captured_pages=captured_pages
        )

    return MonkeyDoResult(
        success=True,
        domain=domain,
        pages=unique_pages,
        words=total_words,
        captured_pages=captured_pages
    )


# =============================================================================
# SCHEDULED REPLAY RUNNER
# =============================================================================

async def run_scheduled_replays() -> list[tuple[str, MonkeyDoResult]]:
    """
    Run all due scheduled replays.

    Returns:
        List of (domain, result) tuples
    """
    due = get_due_replays()
    results = []

    for entry in due:
        print(f"Scheduled replay: {entry.domain} ({entry.cadence})")

        result = await monkey_do(entry.domain)
        results.append((entry.domain, result))

        # Update schedule
        schedules = load_replay_schedule()
        for s in schedules:
            if s.domain == entry.domain:
                s.last_attempt = datetime.now(timezone.utc).isoformat()
                if result.success:
                    s.last_success = s.last_attempt
                    s.consecutive_failures = 0
                    print(f"  Success: {result.pages} pages, {result.words} words")
                else:
                    s.consecutive_failures += 1
                    print(f"  Failed: {result.error}")

                    # Re-queue after 2 consecutive failures
                    if s.consecutive_failures >= 2:
                        add_to_monkey_queue(
                            entry.domain,
                            reason=f'scheduled replay failed {s.consecutive_failures}x'
                        )
                        print(f"  Re-queued (flow may be stale)")
                break

        save_replay_schedule(schedules)

    return results


# =============================================================================
# INTEGRATION HELPERS (for Agent 1 to wire in)
# =============================================================================

def get_flow_path(domain: str) -> Path | None:
    """Get path to flow file for domain, or None if doesn't exist."""
    path = FLOWS_DIR / f'{domain}.flow.json'
    return path if path.exists() else None


def has_flow(domain: str) -> bool:
    """Check if domain has a saved flow."""
    return (FLOWS_DIR / f'{domain}.flow.json').exists()


def get_flow_age_days(domain: str) -> float | None:
    """Get age of flow in days, or None if no flow."""
    path = FLOWS_DIR / f'{domain}.flow.json'
    if not path.exists():
        return None

    try:
        flow = Flow.load(path)
        recorded = datetime.fromisoformat(flow.recorded.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - recorded
        return age.total_seconds() / 86400
    except Exception:
        return None
