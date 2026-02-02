"""
Human emulation utilities for authentic browser automation.

Provides timing variance, mouse movement curves, scroll patterns, and
session consistency to make automated browsing indistinguishable from
real human behavior.
"""

import math
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page as AsyncPage
    from playwright.sync_api import Page as SyncPage


# Common screen resolutions (from web analytics data)
COMMON_VIEWPORTS = [
    (1920, 1080),  # Full HD - most common
    (1366, 768),   # HD laptop
    (1536, 864),   # Scaled laptop
    (1440, 900),   # MacBook Air
    (1280, 720),   # HD
    (2560, 1440),  # QHD
    (1680, 1050),  # WSXGA+
    (1600, 900),   # HD+
]

# Common timezones for US-based browsing
COMMON_TIMEZONES = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Phoenix',
]

# Common locales
COMMON_LOCALES = ['en-US', 'en-GB', 'en-CA', 'en-AU']


@dataclass
class HumanSession:
    """
    Maintains consistent browser fingerprint across a session.

    Use one HumanSession per domain to maintain consistency
    that real browsers exhibit.
    """
    viewport: tuple[int, int] = field(default_factory=lambda: random.choice(COMMON_VIEWPORTS))
    timezone: str = field(default_factory=lambda: random.choice(COMMON_TIMEZONES))
    locale: str = field(default_factory=lambda: random.choice(COMMON_LOCALES))
    color_depth: int = field(default_factory=lambda: random.choice([24, 32]))
    device_scale_factor: float = field(default_factory=lambda: random.choice([1.0, 1.25, 1.5, 2.0]))
    user_agent: str | None = None

    # Session state
    mouse_position: tuple[float, float] = (0, 0)
    last_action_time: float = field(default_factory=time.time)

    def apply_to_context_options(self) -> dict:
        """Return options dict for Playwright context creation."""
        return {
            'viewport': {'width': self.viewport[0], 'height': self.viewport[1]},
            'timezone_id': self.timezone,
            'locale': self.locale,
            'color_scheme': random.choice(['light', 'dark', 'no-preference']),
            'device_scale_factor': self.device_scale_factor,
        }

    def record_action(self):
        """Record that an action was taken (updates timing baseline)."""
        self.last_action_time = time.time()

    def time_since_last_action(self) -> float:
        """Get seconds since last action."""
        return time.time() - self.last_action_time


# =============================================================================
# TIMING FUNCTIONS
# =============================================================================

def human_delay(base: float = 1.0, allow_distraction: bool = True) -> float:
    """
    Generate human-like delay with natural variance.

    Args:
        base: Base delay in seconds (from recorded flow)
        allow_distraction: If True, 10% chance of longer "distraction" pause

    Returns:
        Delay in seconds with human-like variance

    Human reaction times follow a skewed distribution:
    - Fast: 200-400ms (focused, expecting action)
    - Normal: 500-1500ms (reading, deciding)
    - Slow: 2-5s (distracted, reading longer text)
    """
    # 10% chance of "distraction" - longer pause as if reading
    if allow_distraction and random.random() < 0.1:
        return base + random.uniform(2.0, 5.0)

    # Normal variance: 80-130% of base + small random offset
    variance_factor = random.uniform(0.8, 1.3)
    offset = random.gauss(0.2, 0.1)  # Small additional noise

    result = base * variance_factor + max(0, offset)
    return max(0.05, result)  # Minimum 50ms


def typing_delay(char: str) -> float:
    """
    Generate delay between keystrokes for human-like typing.

    Args:
        char: Character being typed

    Returns:
        Delay in seconds before next keystroke

    Real typing patterns:
    - Average: 150-250ms between keys
    - Faster for common letter sequences
    - Slower after space, punctuation
    - Occasional pause for thinking
    """
    # Base delay
    base = random.gauss(0.12, 0.04)  # ~120ms average

    # Slower after punctuation or space (cognitive pause)
    if char in ' .,;:!?':
        base += random.uniform(0.1, 0.3)

    # Occasional thinking pause (2% chance)
    if random.random() < 0.02:
        base += random.uniform(0.5, 1.5)

    return max(0.03, base)


def reading_time(word_count: int, min_seconds: float = 0.5) -> float:
    """
    Estimate time to read content.

    Args:
        word_count: Number of words in content
        min_seconds: Minimum reading time

    Returns:
        Reading time in seconds

    Average reading speed: 200-250 words per minute
    Skimming: 400-700 words per minute
    """
    # Random reading speed (words per minute)
    wpm = random.gauss(250, 50)
    wpm = max(150, min(400, wpm))  # Clamp to reasonable range

    seconds = (word_count / wpm) * 60

    # Add variance
    seconds *= random.uniform(0.7, 1.3)

    return max(min_seconds, seconds)


# =============================================================================
# EASING FUNCTIONS
# =============================================================================

def ease_out_quad(t: float) -> float:
    """Quadratic ease-out: decelerating to zero velocity."""
    return t * (2 - t)


def ease_in_out_quad(t: float) -> float:
    """Quadratic ease-in-out: acceleration then deceleration."""
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: stronger deceleration."""
    return 1 - pow(1 - t, 3)


def ease_in_out_sine(t: float) -> float:
    """Sinusoidal ease-in-out: smooth acceleration and deceleration."""
    return -(math.cos(math.pi * t) - 1) / 2


# =============================================================================
# MOUSE MOVEMENT
# =============================================================================

def lerp(start: float, end: float, t: float) -> float:
    """Linear interpolation between two values."""
    return start + (end - start) * t


def bezier_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float
) -> tuple[float, float]:
    """
    Calculate point on cubic Bezier curve.

    Args:
        p0: Start point
        p1: First control point
        p2: Second control point
        p3: End point
        t: Parameter 0-1

    Returns:
        (x, y) point on curve
    """
    u = 1 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]

    return (x, y)


def generate_mouse_path(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int | None = None,
) -> list[tuple[float, float]]:
    """
    Generate human-like mouse movement path using Bezier curves.

    Args:
        start: Starting position (x, y)
        end: Target position (x, y)
        steps: Number of intermediate points (None = auto-calculate)

    Returns:
        List of (x, y) points along the path

    Human mouse movement characteristics:
    - Curved paths, not straight lines
    - Slight overshoot and correction
    - Speed varies (faster in middle, slower at ends)
    - Small jitter/noise
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.sqrt(dx * dx + dy * dy)

    # Auto-calculate steps based on distance
    if steps is None:
        steps = max(10, min(50, int(distance / 20)))

    # Generate control points for Bezier curve
    # Control points create natural curve and potential overshoot

    # First control point: offset from start
    ctrl1_offset = random.uniform(0.2, 0.4)
    ctrl1_perpendicular = random.gauss(0, distance * 0.1)  # Perpendicular offset
    ctrl1 = (
        start[0] + dx * ctrl1_offset + ctrl1_perpendicular * (-dy / (distance + 1)),
        start[1] + dy * ctrl1_offset + ctrl1_perpendicular * (dx / (distance + 1)),
    )

    # Second control point: near end with potential overshoot
    ctrl2_offset = random.uniform(0.6, 0.9)
    overshoot = random.uniform(-0.05, 0.15)  # Slight overshoot tendency
    ctrl2_perpendicular = random.gauss(0, distance * 0.05)
    ctrl2 = (
        start[0] + dx * (ctrl2_offset + overshoot) + ctrl2_perpendicular * (-dy / (distance + 1)),
        start[1] + dy * (ctrl2_offset + overshoot) + ctrl2_perpendicular * (dx / (distance + 1)),
    )

    # Generate path points
    path = []
    for i in range(steps + 1):
        t = i / steps

        # Use easing for non-uniform speed
        eased_t = ease_in_out_sine(t)

        # Get base point on Bezier curve
        point = bezier_point(start, ctrl1, ctrl2, end, eased_t)

        # Add micro-jitter (except at start and end)
        if 0 < i < steps:
            jitter_x = random.gauss(0, 1.5)
            jitter_y = random.gauss(0, 1.5)
            point = (point[0] + jitter_x, point[1] + jitter_y)

        path.append(point)

    return path


async def human_mouse_move_async(
    page: 'AsyncPage',
    target_x: float,
    target_y: float,
    session: HumanSession | None = None,
) -> None:
    """
    Move mouse with human-like curve (async version).

    Args:
        page: Playwright page
        target_x: Target X coordinate
        target_y: Target Y coordinate
        session: HumanSession for tracking mouse position
    """
    import asyncio

    # Get current position
    if session:
        start = session.mouse_position
    else:
        start = (0, 0)

    # Generate path
    path = generate_mouse_path(start, (target_x, target_y))

    # Move along path
    for point in path:
        await page.mouse.move(point[0], point[1])
        await asyncio.sleep(random.uniform(0.005, 0.02))

    # Update session
    if session:
        session.mouse_position = (target_x, target_y)
        session.record_action()


def human_mouse_move_sync(
    page: 'SyncPage',
    target_x: float,
    target_y: float,
    session: HumanSession | None = None,
) -> None:
    """
    Move mouse with human-like curve (sync version).

    Args:
        page: Playwright page
        target_x: Target X coordinate
        target_y: Target Y coordinate
        session: HumanSession for tracking mouse position
    """
    # Get current position
    if session:
        start = session.mouse_position
    else:
        start = (0, 0)

    # Generate path
    path = generate_mouse_path(start, (target_x, target_y))

    # Move along path
    for point in path:
        page.mouse.move(point[0], point[1])
        time.sleep(random.uniform(0.005, 0.02))

    # Update session
    if session:
        session.mouse_position = (target_x, target_y)
        session.record_action()


# =============================================================================
# CLICK BEHAVIOR
# =============================================================================

async def human_click_async(
    page: 'AsyncPage',
    x: float,
    y: float,
    session: HumanSession | None = None,
    box: dict | None = None,
) -> None:
    """
    Click with human-like targeting and timing (async version).

    Args:
        page: Playwright page
        x: Target X coordinate
        y: Target Y coordinate
        session: HumanSession for tracking
        box: Optional bounding box to add natural offset within element
    """
    import asyncio

    # Add natural offset from exact target
    # Humans don't click dead center
    if box:
        # Click within element bounds, biased toward center
        offset_x = random.gauss(0, box.get('width', 20) * 0.15)
        offset_y = random.gauss(0, box.get('height', 20) * 0.15)
    else:
        offset_x = random.gauss(0, 3)
        offset_y = random.gauss(0, 3)

    target_x = x + offset_x
    target_y = y + offset_y

    # Move to target
    await human_mouse_move_async(page, target_x, target_y, session)

    # Brief hover before click (humans don't click instantly)
    await asyncio.sleep(random.uniform(0.05, 0.15))

    # Click
    await page.mouse.click(target_x, target_y)

    if session:
        session.record_action()


def human_click_sync(
    page: 'SyncPage',
    x: float,
    y: float,
    session: HumanSession | None = None,
    box: dict | None = None,
) -> None:
    """
    Click with human-like targeting and timing (sync version).

    Args:
        page: Playwright page
        x: Target X coordinate
        y: Target Y coordinate
        session: HumanSession for tracking
        box: Optional bounding box to add natural offset within element
    """
    # Add natural offset from exact target
    if box:
        offset_x = random.gauss(0, box.get('width', 20) * 0.15)
        offset_y = random.gauss(0, box.get('height', 20) * 0.15)
    else:
        offset_x = random.gauss(0, 3)
        offset_y = random.gauss(0, 3)

    target_x = x + offset_x
    target_y = y + offset_y

    # Move to target
    human_mouse_move_sync(page, target_x, target_y, session)

    # Brief hover before click
    time.sleep(random.uniform(0.05, 0.15))

    # Click
    page.mouse.click(target_x, target_y)

    if session:
        session.record_action()


# =============================================================================
# SCROLL BEHAVIOR
# =============================================================================

async def human_scroll_async(
    page: 'AsyncPage',
    amount: int,
    direction: str = 'down',
    session: HumanSession | None = None,
) -> None:
    """
    Scroll with human-like patterns (async version).

    Args:
        page: Playwright page
        amount: Total scroll amount in pixels
        direction: 'down' or 'up'
        session: HumanSession for tracking

    Human scroll characteristics:
    - Scroll in bursts, not continuous
    - Pause to "read" occasionally
    - Occasional overshoot and correction
    """
    import asyncio

    scrolled = 0
    target = abs(amount)
    sign = 1 if direction == 'down' else -1

    while scrolled < target:
        # Scroll chunk size varies
        remaining = target - scrolled
        chunk = min(random.randint(50, 200), remaining)

        await page.mouse.wheel(0, chunk * sign)
        scrolled += chunk

        # Reading pause (30% chance)
        if random.random() < 0.3:
            await asyncio.sleep(random.uniform(0.3, 1.2))
        else:
            await asyncio.sleep(random.uniform(0.03, 0.1))

    # Occasional overshoot and correction (20% chance)
    if random.random() < 0.2:
        overshoot = random.randint(20, 60)
        await page.mouse.wheel(0, overshoot * sign)
        await asyncio.sleep(random.uniform(0.2, 0.4))
        await page.mouse.wheel(0, -overshoot * sign)

    if session:
        session.record_action()


def human_scroll_sync(
    page: 'SyncPage',
    amount: int,
    direction: str = 'down',
    session: HumanSession | None = None,
) -> None:
    """
    Scroll with human-like patterns (sync version).

    Args:
        page: Playwright page
        amount: Total scroll amount in pixels
        direction: 'down' or 'up'
        session: HumanSession for tracking
    """
    scrolled = 0
    target = abs(amount)
    sign = 1 if direction == 'down' else -1

    while scrolled < target:
        remaining = target - scrolled
        chunk = min(random.randint(50, 200), remaining)

        page.mouse.wheel(0, chunk * sign)
        scrolled += chunk

        # Reading pause (30% chance)
        if random.random() < 0.3:
            time.sleep(random.uniform(0.3, 1.2))
        else:
            time.sleep(random.uniform(0.03, 0.1))

    # Occasional overshoot and correction (20% chance)
    if random.random() < 0.2:
        overshoot = random.randint(20, 60)
        page.mouse.wheel(0, overshoot * sign)
        time.sleep(random.uniform(0.2, 0.4))
        page.mouse.wheel(0, -overshoot * sign)

    if session:
        session.record_action()


# =============================================================================
# TYPING BEHAVIOR
# =============================================================================

async def human_type_async(
    page: 'AsyncPage',
    selector: str,
    text: str,
    session: HumanSession | None = None,
) -> None:
    """
    Type text with human-like timing (async version).

    Args:
        page: Playwright page
        selector: Element selector to type into
        text: Text to type
        session: HumanSession for tracking
    """
    import asyncio

    # Focus the element
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.1, 0.3))

    # Type each character with variable delay
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(typing_delay(char))

    if session:
        session.record_action()


def human_type_sync(
    page: 'SyncPage',
    selector: str,
    text: str,
    session: HumanSession | None = None,
) -> None:
    """
    Type text with human-like timing (sync version).

    Args:
        page: Playwright page
        selector: Element selector to type into
        text: Text to type
        session: HumanSession for tracking
    """
    # Focus the element
    page.click(selector)
    time.sleep(random.uniform(0.1, 0.3))

    # Type each character with variable delay
    for char in text:
        page.keyboard.type(char)
        time.sleep(typing_delay(char))

    if session:
        session.record_action()


# =============================================================================
# COMPOSITE BEHAVIORS
# =============================================================================

async def human_browse_page_async(
    page: 'AsyncPage',
    session: HumanSession | None = None,
) -> None:
    """
    Simulate natural page browsing behavior (async version).

    Performs actions a real human would do when landing on a page:
    - Brief pause to orient
    - Scroll down to see content
    - Move mouse around (reading behavior)
    - Scroll back up
    """
    import asyncio

    viewport = session.viewport if session else (1920, 1080)

    # Initial pause (orienting)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Scroll down to see content
    await human_scroll_async(page, random.randint(300, 600), 'down', session)

    # Reading time
    await asyncio.sleep(random.uniform(1.0, 3.0))

    # Random mouse movements (simulating reading)
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, viewport[0] - 100)
        y = random.randint(100, viewport[1] - 100)
        await human_mouse_move_async(page, x, y, session)
        await asyncio.sleep(random.uniform(0.3, 1.0))

    # Scroll back up partially
    await human_scroll_async(page, random.randint(100, 300), 'up', session)


def human_browse_page_sync(
    page: 'SyncPage',
    session: HumanSession | None = None,
) -> None:
    """
    Simulate natural page browsing behavior (sync version).
    """
    viewport = session.viewport if session else (1920, 1080)

    # Initial pause (orienting)
    time.sleep(random.uniform(0.5, 1.5))

    # Scroll down to see content
    human_scroll_sync(page, random.randint(300, 600), 'down', session)

    # Reading time
    time.sleep(random.uniform(1.0, 3.0))

    # Random mouse movements (simulating reading)
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, viewport[0] - 100)
        y = random.randint(100, viewport[1] - 100)
        human_mouse_move_sync(page, x, y, session)
        time.sleep(random.uniform(0.3, 1.0))

    # Scroll back up partially
    human_scroll_sync(page, random.randint(100, 300), 'up', session)
