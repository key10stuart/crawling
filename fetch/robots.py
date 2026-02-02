"""
Robots.txt parser and compliance checker.

Supports:
- User-agent matching
- Allow/Disallow rules
- Crawl-delay directive
- Sitemap hints

Usage:
    from fetch.robots import RobotsChecker

    robots = RobotsChecker.fetch("https://example.com")
    if robots.is_allowed("/some/path"):
        # proceed with crawl
    delay = robots.crawl_delay  # respect rate limit
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests


REQUEST_TIMEOUT = 10
USER_AGENT = "TruckingCorpusBot"  # Without version for matching


@dataclass
class RobotsResult:
    """Parsed robots.txt data."""
    found: bool = False
    url: str = ''
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    disallowed_sample: list[str] = field(default_factory=list)  # First few disallowed paths
    error: str | None = None


class RobotsChecker:
    """
    Robots.txt compliance checker with caching.

    Uses Python's RobotFileParser for rule matching, plus custom
    parsing for Crawl-delay and Sitemap directives.
    """

    _cache: dict[str, 'RobotsChecker'] = {}  # domain -> checker

    def __init__(self, base_url: str):
        """
        Initialize checker for a domain.

        Args:
            base_url: Base URL (e.g., "https://example.com")
        """
        parsed = urlparse(base_url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.robots_url = urljoin(self.base_url, '/robots.txt')

        self._parser = RobotFileParser()
        self._parser.set_url(self.robots_url)

        self.found = False
        self.crawl_delay: float | None = None
        self.sitemaps: list[str] = []
        self.disallowed_paths: list[str] = []
        self.error: str | None = None
        self._raw_content: str = ''

    @classmethod
    def fetch(cls, base_url: str, use_cache: bool = True) -> 'RobotsChecker':
        """
        Fetch and parse robots.txt for a domain.

        Args:
            base_url: Base URL (e.g., "https://example.com")
            use_cache: If True, return cached checker if available

        Returns:
            RobotsChecker instance
        """
        parsed = urlparse(base_url)
        domain = parsed.netloc

        if use_cache and domain in cls._cache:
            return cls._cache[domain]

        checker = cls(base_url)
        checker._fetch_and_parse()

        if use_cache:
            cls._cache[domain] = checker

        return checker

    @classmethod
    def clear_cache(cls):
        """Clear the robots.txt cache."""
        cls._cache.clear()

    def _fetch_and_parse(self):
        """Fetch robots.txt and parse it."""
        try:
            resp = requests.get(
                self.robots_url,
                timeout=REQUEST_TIMEOUT,
                headers={'User-Agent': USER_AGENT},
                allow_redirects=True,
            )

            if resp.status_code == 200:
                self.found = True
                self._raw_content = resp.text
                self._parse_content(resp.text)

                # Also feed to RobotFileParser for rule matching
                self._parser.parse(resp.text.splitlines())

            elif resp.status_code in (404, 403, 410):
                # No robots.txt = everything allowed
                self.found = False
            else:
                self.error = f"Unexpected status: {resp.status_code}"

        except requests.RequestException as e:
            self.error = str(e)

    def _parse_content(self, content: str):
        """Parse robots.txt content for extra directives."""
        current_agent = None
        our_agent_section = False

        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse directive
            if ':' not in line:
                continue

            directive, _, value = line.partition(':')
            directive = directive.strip().lower()
            value = value.strip()

            if directive == 'user-agent':
                current_agent = value.lower()
                # Check if this section applies to us
                our_agent_section = (
                    current_agent == '*'
                    or USER_AGENT.lower() in current_agent
                    or current_agent in USER_AGENT.lower()
                )

            elif directive == 'crawl-delay' and our_agent_section:
                try:
                    self.crawl_delay = float(value)
                except ValueError:
                    pass

            elif directive == 'sitemap':
                # Sitemaps are global, not per user-agent
                if value and value not in self.sitemaps:
                    self.sitemaps.append(value)

            elif directive == 'disallow' and our_agent_section:
                if value and len(self.disallowed_paths) < 20:
                    self.disallowed_paths.append(value)

    def is_allowed(self, url_or_path: str) -> bool:
        """
        Check if a URL or path is allowed to be crawled.

        Args:
            url_or_path: Full URL or path (e.g., "/admin" or "https://example.com/admin")

        Returns:
            True if allowed, False if disallowed
        """
        # If no robots.txt found, everything is allowed
        if not self.found:
            return True

        # Normalize to full URL
        if url_or_path.startswith('http'):
            url = url_or_path
        else:
            url = urljoin(self.base_url, url_or_path)

        return self._parser.can_fetch(USER_AGENT, url)

    def get_delay(self, default: float = 1.0) -> float:
        """
        Get crawl delay to use.

        Args:
            default: Default delay if not specified in robots.txt

        Returns:
            Crawl delay in seconds
        """
        if self.crawl_delay is not None:
            return self.crawl_delay
        return default

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            'found': self.found,
            'url': self.robots_url,
            'crawl_delay': self.crawl_delay,
            'sitemaps': self.sitemaps,
            'disallowed_sample': self.disallowed_paths[:10],
            'error': self.error,
        }


def check_robots(base_url: str, path: str) -> tuple[bool, RobotsResult]:
    """
    Quick check if a path is allowed.

    Args:
        base_url: Base URL (e.g., "https://example.com")
        path: Path to check (e.g., "/admin")

    Returns:
        (is_allowed, robots_result)
    """
    checker = RobotsChecker.fetch(base_url)
    allowed = checker.is_allowed(path)
    result = RobotsResult(
        found=checker.found,
        url=checker.robots_url,
        crawl_delay=checker.crawl_delay,
        sitemaps=checker.sitemaps,
        disallowed_sample=checker.disallowed_paths[:10],
        error=checker.error,
    )
    return allowed, result
