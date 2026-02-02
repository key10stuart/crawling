"""
Crawl profile loader for domain-specific crawling behavior.

Profiles define:
- Path priority scoring (what to crawl first)
- Expected nav sections (for coverage tracking)
- Features of interest (what to flag)
- Industry terms (for term counting)
- Crawl settings (depth, max pages, etc.)

Usage:
    from fetch.profile import load_profile, score_url_priority

    profile = load_profile("trucking")
    priority = score_url_priority("/services/intermodal", profile)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


PROFILES_DIR = Path(__file__).parent.parent / "profiles"

# Common nav label prefixes/suffixes to strip for normalization
_NAV_STRIP_PATTERNS = [
    r'^our\s+',           # "Our Services" → "Services"
    r'^the\s+',           # "The Company" → "Company"
    r'^all\s+',           # "All Products" → "Products"
    r'^view\s+(all\s+)?', # "View All Services" → "Services"
    r'^explore\s+',       # "Explore Solutions" → "Solutions"
    r'^discover\s+',      # "Discover Products" → "Products"
    r'\s+us$',            # "About Us" → "About"
    r'\s+overview$',      # "Services Overview" → "Services"
    r'\s+home$',          # "Investors Home" → "Investors"
]

# Synonyms for common nav sections (maps variations to canonical form)
_NAV_SYNONYMS = {
    'about': ['about', 'company', 'who we are', 'our story', 'why'],
    'services': ['services', 'what we do', 'our services', 'capabilities', 'freight', 'shipping', 'transportation'],
    'solutions': ['solutions', 'offerings', 'what we offer', 'freight-shipping'],
    'products': ['products', 'our products', 'product line'],
    'resources': ['resources', 'insights', 'knowledge', 'learn', 'tools', 'calculators'],
    'contact': ['contact', 'get in touch', 'reach us', 'connect'],
    'careers': ['careers', 'jobs', 'work with us', 'join us', 'employment', 'drive for us'],
    'news': ['news', 'newsroom', 'press', 'media', 'announcements', 'market updates'],
    'investors': ['investors', 'investor relations', 'ir', 'shareholders'],
    'support': ['support', 'help', 'customer service', 'faq'],
    'developers': ['developers', 'developer', 'dev', 'api', 'documentation', 'docs'],
    # Trucking-specific
    'carriers': ['carriers', 'haul with us', 'owner operators', 'drive for', 'partner carriers'],
    'shippers': ['shippers', 'ship with us', 'customers', 'freight shipping'],
    'technology': ['technology', 'tech', 'platform', 'digital', 'freightpower'],
}


@dataclass
class Product:
    """A product to track during crawling."""
    name: str
    description: str = ""
    patterns: list[re.Pattern] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    page_types: list[str] = field(default_factory=list)


@dataclass
class CrawlProfile:
    """Domain-specific crawl configuration."""
    name: str

    # Priority patterns (compiled regexes)
    priority_high: list[re.Pattern] = field(default_factory=list)
    priority_medium: list[re.Pattern] = field(default_factory=list)
    priority_low: list[re.Pattern] = field(default_factory=list)

    # Coverage tracking
    expected_nav_sections: list[str] = field(default_factory=list)

    # Product tracking
    products: list[Product] = field(default_factory=list)

    # Feature detection
    features_of_interest: list[str] = field(default_factory=list)

    # Term counting
    industry_terms: list[str] = field(default_factory=list)

    # Crawl settings
    max_depth: int = 2
    max_pages: int = 100
    prioritize_nav: bool = True
    skip_external: bool = True


def normalize_nav_label(label: str) -> str:
    """
    Normalize a nav label for comparison.

    Strips common prefixes/suffixes and lowercases.
    E.g., "Our Services Overview" → "services"
    """
    normalized = label.lower().strip()

    # Strip common prefixes/suffixes
    for pattern in _NAV_STRIP_PATTERNS:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE).strip()

    return normalized


def get_canonical_nav_section(label: str) -> str | None:
    """
    Map a nav label to its canonical section name.

    E.g., "Who We Are" → "about", "What We Do" → "services"
    Returns None if no mapping found.
    """
    normalized = normalize_nav_label(label)

    # Check direct match first
    if normalized in _NAV_SYNONYMS:
        return normalized

    # Check against synonym lists
    for canonical, synonyms in _NAV_SYNONYMS.items():
        for syn in synonyms:
            if syn in normalized or normalized in syn:
                return canonical

    return None


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    """Compile path patterns to regexes."""
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            # Treat as literal if not valid regex
            compiled.append(re.compile(re.escape(p), re.IGNORECASE))
    return compiled


def _parse_products(products_data: list) -> list[Product]:
    """Parse product definitions from YAML."""
    products = []
    for p in products_data:
        if isinstance(p, dict):
            products.append(Product(
                name=p.get("name", "Unknown"),
                description=p.get("description", ""),
                patterns=_compile_patterns(p.get("patterns", [])),
                terms=p.get("terms", []),
                page_types=p.get("page_types", []),
            ))
    return products


def load_profile(name: str) -> CrawlProfile:
    """
    Load a crawl profile by name.

    Args:
        name: Profile name (e.g., "trucking", "generic", "nvidia")

    Returns:
        CrawlProfile instance

    Raises:
        FileNotFoundError if profile doesn't exist
    """
    profile_path = PROFILES_DIR / f"{name}.yaml"

    if not profile_path.exists():
        # Fall back to generic
        profile_path = PROFILES_DIR / "generic.yaml"
        if not profile_path.exists():
            # Return default if no profiles exist
            return CrawlProfile(name="default")

    with open(profile_path) as f:
        data = yaml.safe_load(f)

    priority = data.get("priority", {})
    settings = data.get("settings", {})

    return CrawlProfile(
        name=data.get("name", name),
        priority_high=_compile_patterns(priority.get("high", [])),
        priority_medium=_compile_patterns(priority.get("medium", [])),
        priority_low=_compile_patterns(priority.get("low", [])),
        expected_nav_sections=data.get("expected_nav_sections", []),
        products=_parse_products(data.get("products", [])),
        features_of_interest=data.get("features_of_interest", []),
        industry_terms=data.get("industry_terms", []),
        max_depth=settings.get("max_depth", 2),
        max_pages=settings.get("max_pages", 100),
        prioritize_nav=settings.get("prioritize_nav", True),
        skip_external=settings.get("skip_external", True),
    )


def score_url_priority(path: str, profile: CrawlProfile) -> Literal["high", "medium", "low", "normal"]:
    """
    Score a URL path's crawl priority based on profile.

    Args:
        path: URL path (e.g., "/services/intermodal")
        profile: CrawlProfile instance

    Returns:
        Priority level: "high", "medium", "low", or "normal"
    """
    path_lower = path.lower()

    # Check high priority first
    for pattern in profile.priority_high:
        if pattern.search(path_lower):
            return "high"

    # Then medium
    for pattern in profile.priority_medium:
        if pattern.search(path_lower):
            return "medium"

    # Then low
    for pattern in profile.priority_low:
        if pattern.search(path_lower):
            return "low"

    return "normal"


def score_url_numeric(path: str, profile: CrawlProfile, depth: int = 0) -> int:
    """
    Score a URL with a numeric value for queue ordering.

    Higher scores = higher priority (should be crawled first).
    Factors in: profile priority, path depth, and path patterns.

    Args:
        path: URL path (e.g., "/services/intermodal")
        profile: CrawlProfile instance
        depth: Current crawl depth (0 = homepage)

    Returns:
        Numeric priority score (higher = more important)
    """
    base_score = 50  # Normal priority baseline

    # Profile-based priority
    priority = score_url_priority(path, profile)
    if priority == "high":
        base_score = 100
    elif priority == "medium":
        base_score = 75
    elif priority == "low":
        base_score = 10

    # Depth penalty (prefer shallower pages)
    depth_penalty = depth * 5
    score = base_score - depth_penalty

    # Path length penalty (prefer shorter paths)
    path_segments = len([s for s in path.split('/') if s])
    score -= path_segments * 2

    # Bonus for key paths (likely main content)
    path_lower = path.lower()
    if path_lower == '/' or path_lower == '':
        score += 20  # Homepage
    elif re.search(r'^/[^/]+/?$', path):
        score += 10  # Top-level page

    # Penalty for likely noise
    if re.search(r'(page|p)=?\d+', path_lower):  # Pagination
        score -= 20
    if re.search(r'\.(pdf|doc|xls|ppt)', path_lower):  # Documents
        score -= 10
    if '#' in path:  # Anchors
        score -= 15

    return max(0, score)  # Don't go negative


def check_nav_coverage(nav_labels: list[str], profile: CrawlProfile) -> dict:
    """
    Check coverage of expected nav sections with normalization.

    Uses nav label normalization and synonym mapping for fuzzy matching.
    E.g., profile expects "services", site has "What We Do" → matches via synonym.

    Args:
        nav_labels: List of nav link text labels from site
        profile: CrawlProfile instance

    Returns:
        Dict with coverage stats including match details
    """
    if not profile.expected_nav_sections:
        return {"expected": [], "found": [], "missing": [], "matches": {}, "coverage": 1.0}

    # Normalize all nav labels and get canonical mappings
    normalized_labels = {}
    canonical_labels = {}
    for label in nav_labels:
        norm = normalize_nav_label(label)
        normalized_labels[label] = norm
        canonical = get_canonical_nav_section(label)
        if canonical:
            canonical_labels[label] = canonical

    found = []
    missing = []
    matches = {}  # Maps expected → matched label

    for expected in profile.expected_nav_sections:
        expected_lower = expected.lower()
        expected_norm = normalize_nav_label(expected)
        matched = False

        # 1. Direct substring match (original behavior)
        for label in nav_labels:
            if expected_lower in label.lower():
                found.append(expected)
                matches[expected] = {"label": label, "method": "direct"}
                matched = True
                break

        if matched:
            continue

        # 2. Normalized match
        for label, norm in normalized_labels.items():
            if expected_norm in norm or norm in expected_norm:
                found.append(expected)
                matches[expected] = {"label": label, "method": "normalized"}
                matched = True
                break

        if matched:
            continue

        # 3. Synonym match (e.g., expected="about", found="Who We Are")
        for label, canonical in canonical_labels.items():
            if canonical == expected_lower or expected_norm == canonical:
                found.append(expected)
                matches[expected] = {"label": label, "method": "synonym", "canonical": canonical}
                matched = True
                break

        if not matched:
            missing.append(expected)

    coverage = len(found) / len(profile.expected_nav_sections) if profile.expected_nav_sections else 1.0

    return {
        "expected": profile.expected_nav_sections,
        "found": found,
        "missing": missing,
        "matches": matches,
        "coverage": round(coverage, 2),
    }


def list_profiles() -> list[str]:
    """List available profile names."""
    if not PROFILES_DIR.exists():
        return []
    return [p.stem for p in PROFILES_DIR.glob("*.yaml")]


def match_product(path: str, text: str, profile: CrawlProfile) -> str | None:
    """
    Check if a page matches a product in the profile.

    Args:
        path: URL path (e.g., "/geforce/rtx-4090")
        text: Page text content
        profile: CrawlProfile with products

    Returns:
        Product name if matched, None otherwise
    """
    if not profile.products:
        return None

    path_lower = path.lower()
    text_lower = text.lower() if text else ""

    for product in profile.products:
        # Check path patterns
        for pattern in product.patterns:
            if pattern.search(path_lower):
                return product.name

        # Check terms in text (require multiple matches for confidence)
        if product.terms and text_lower:
            term_matches = sum(1 for term in product.terms if term.lower() in text_lower)
            if term_matches >= 2:  # At least 2 terms must match
                return product.name

    return None


@dataclass
class CrawlHint:
    """A hint for feature-driven crawling."""
    feature: str           # Feature name (e.g., "portal", "tracking", "api_docs")
    subtree: str          # URL path to explore (e.g., "/carrier-portal")
    priority: str         # "high", "medium", "low"
    reason: str           # Why this hint was generated
    depth_boost: int = 1  # Extra depth to crawl this subtree


# Feature detection patterns for crawl hints
_FEATURE_PATTERNS = {
    'portal': {
        'url_patterns': [r'/portal', r'/login', r'/carrier', r'/shipper', r'/customer'],
        'text_patterns': [r'carrier\s+portal', r'shipper\s+portal', r'customer\s+portal', r'my\s+account'],
        'priority': 'high',
        'depth_boost': 1,
    },
    'tracking': {
        'url_patterns': [r'/track', r'/shipment', r'/tracing'],
        'text_patterns': [r'track\s+(your\s+)?shipment', r'shipment\s+tracking', r'tracking\s+number'],
        'priority': 'high',
        'depth_boost': 1,
    },
    'api_docs': {
        'url_patterns': [r'/api', r'/developer', r'/docs', r'/documentation', r'/sdk'],
        'text_patterns': [r'api\s+documentation', r'developer\s+portal', r'rest\s+api', r'sdk'],
        'priority': 'high',
        'depth_boost': 2,
    },
    'edi': {
        'url_patterns': [r'/edi', r'/integration'],
        'text_patterns': [r'edi\s+integration', r'electronic\s+data\s+interchange'],
        'priority': 'medium',
        'depth_boost': 1,
    },
    'tms': {
        'url_patterns': [r'/tms', r'/logistics'],
        'text_patterns': [r'transportation\s+management', r'tms\s+integration', r'logistics\s+platform'],
        'priority': 'medium',
        'depth_boost': 1,
    },
    'pricing': {
        'url_patterns': [r'/pricing', r'/rates', r'/quote'],
        'text_patterns': [r'get\s+a?\s*quote', r'request\s+pricing', r'rate\s+calculator'],
        'priority': 'medium',
        'depth_boost': 0,
    },
}


def detect_crawl_hints(
    links: list[dict],
    page_text: str,
    profile: CrawlProfile,
) -> list[CrawlHint]:
    """
    Detect feature-driven crawl hints from page links and text.

    Analyzes links and text to find features that warrant deeper crawling
    (portals, tracking systems, API docs, etc.).

    Args:
        links: List of link dicts with 'text' and 'url' keys
        page_text: Full page text content
        profile: CrawlProfile (uses features_of_interest)

    Returns:
        List of CrawlHint objects for subtrees to explore
    """
    hints = []
    seen_subtrees = set()
    text_lower = page_text.lower() if page_text else ""

    # Get features to look for (from profile or use all)
    features_to_check = _FEATURE_PATTERNS.keys()
    if profile.features_of_interest:
        # Map profile features to our pattern keys
        profile_features = set(f.lower().replace('_', '') for f in profile.features_of_interest)
        features_to_check = [
            f for f in _FEATURE_PATTERNS
            if f in profile_features or any(pf in f or f in pf for pf in profile_features)
        ]
        # If profile has features but none match our patterns, check all
        if not features_to_check:
            features_to_check = _FEATURE_PATTERNS.keys()

    for feature, config in _FEATURE_PATTERNS.items():
        if feature not in features_to_check:
            continue

        # Check links for URL patterns
        for link in links:
            url = link.get('url', '') or link.get('href', '')
            link_text = link.get('text', '') or link.get('label', '')
            url_lower = url.lower()

            for url_pattern in config['url_patterns']:
                if re.search(url_pattern, url_lower):
                    # Extract subtree path
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    subtree = parsed.path
                    if subtree and subtree not in seen_subtrees:
                        seen_subtrees.add(subtree)
                        hints.append(CrawlHint(
                            feature=feature,
                            subtree=subtree,
                            priority=config['priority'],
                            reason=f"URL pattern '{url_pattern}' matched: {url}",
                            depth_boost=config['depth_boost'],
                        ))
                    break

            # Check link text for text patterns
            for text_pattern in config['text_patterns']:
                if re.search(text_pattern, link_text.lower()):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    subtree = parsed.path
                    if subtree and subtree not in seen_subtrees:
                        seen_subtrees.add(subtree)
                        hints.append(CrawlHint(
                            feature=feature,
                            subtree=subtree,
                            priority=config['priority'],
                            reason=f"Link text matched '{text_pattern}': {link_text}",
                            depth_boost=config['depth_boost'],
                        ))
                    break

        # Check page text (less precise, only if feature not already found via links)
        feature_found = any(h.feature == feature for h in hints)
        if not feature_found and text_lower:
            for text_pattern in config['text_patterns']:
                if re.search(text_pattern, text_lower):
                    hints.append(CrawlHint(
                        feature=feature,
                        subtree='',  # No specific subtree, just flag presence
                        priority=config['priority'],
                        reason=f"Page text contains '{text_pattern}'",
                        depth_boost=0,  # No depth boost without specific URL
                    ))
                    break

    # Sort by priority
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    hints.sort(key=lambda h: priority_order.get(h.priority, 1))

    return hints


def hints_to_dict(hints: list[CrawlHint]) -> list[dict]:
    """Convert CrawlHint list to JSON-serializable dicts."""
    return [
        {
            'feature': h.feature,
            'subtree': h.subtree,
            'priority': h.priority,
            'reason': h.reason,
            'depth_boost': h.depth_boost,
        }
        for h in hints
    ]


def check_product_coverage(pages: list[dict], profile: CrawlProfile) -> dict:
    """
    Check coverage of products defined in profile.

    Args:
        pages: List of crawled page dicts (need 'path' and 'full_text')
        profile: CrawlProfile with products

    Returns:
        Dict with product coverage stats
    """
    if not profile.products:
        return {"products": [], "coverage": {}, "overall_coverage": 1.0}

    coverage = {}
    for product in profile.products:
        coverage[product.name] = {
            "description": product.description,
            "pages_found": [],
            "terms_found": set(),
            "covered": False,
        }

    # Check each page
    for page in pages:
        path = page.get("path", "")
        text = page.get("full_text", "") or page.get("main_content", "")
        url = page.get("url", "")

        matched_product = match_product(path, text, profile)
        if matched_product and matched_product in coverage:
            coverage[matched_product]["pages_found"].append({
                "path": path,
                "url": url,
                "word_count": page.get("word_count", 0),
            })
            coverage[matched_product]["covered"] = True

            # Track which terms were found
            text_lower = text.lower() if text else ""
            for product in profile.products:
                if product.name == matched_product:
                    for term in product.terms:
                        if term.lower() in text_lower:
                            coverage[matched_product]["terms_found"].add(term)

    # Convert sets to lists for JSON serialization
    for name in coverage:
        coverage[name]["terms_found"] = list(coverage[name]["terms_found"])

    # Calculate overall coverage
    covered_count = sum(1 for c in coverage.values() if c["covered"])
    overall = covered_count / len(profile.products) if profile.products else 1.0

    return {
        "products": [p.name for p in profile.products],
        "coverage": coverage,
        "covered_count": covered_count,
        "total_products": len(profile.products),
        "overall_coverage": round(overall, 2),
    }
