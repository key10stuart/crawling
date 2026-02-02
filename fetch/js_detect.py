"""
Detect if a page requires JavaScript rendering.

Checks raw HTML for SPA framework signatures before deciding
whether to use Playwright.
"""

import re
from dataclasses import dataclass


@dataclass
class JSDetectionResult:
    """Result of JS requirement detection."""
    js_required: bool
    confidence: str  # high, medium, low
    signals: list[str]
    framework: str | None = None


# Empty root divs used by SPAs
SPA_ROOT_PATTERNS = [
    r'<div\s+id=["\']root["\']\s*>\s*</div>',
    r'<div\s+id=["\']app["\']\s*>\s*</div>',
    r'<div\s+id=["\']__next["\']\s*>\s*</div>',
    r'<div\s+id=["\']__nuxt["\']\s*>\s*</div>',
    r'<div\s+id=["\']main-app["\']\s*>\s*</div>',
    r'<div\s+id=["\']application["\']\s*>\s*</div>',
]

# Framework-specific markers in HTML/scripts
FRAMEWORK_MARKERS = {
    'next.js': [
        r'__NEXT_DATA__',
        r'_next/static',
        r'next/dist',
        r'<meta\s+name=["\']generator["\']\s+content=["\']Next\.js',
    ],
    'nuxt': [
        r'__NUXT__',
        r'_nuxt/',
        r'nuxt\.js',
    ],
    'react': [
        r'react\.production\.min\.js',
        r'react-dom',
        r'data-reactroot',
        r'data-reactid',
    ],
    'vue': [
        r'vue\.runtime',
        r'vue\.min\.js',
        r'data-v-[a-f0-9]+',
        r'v-cloak',
    ],
    'angular': [
        r'ng-version',
        r'angular\.min\.js',
        r'ng-app',
        r'<app-root',
    ],
    'svelte': [
        r'svelte',
        r'__svelte',
    ],
    'aem': [
        r'/etc\.clientlibs/',
        r'/_jcr_content/',
        r'/content/dam/',
        r'/content/experience-fragments/',
        r'cq:cloudserviceconfigs',
        r'data-cmp-',
        r'aemanalytics',
        r'granite/ui',
    ],
}

# Generic SPA signals
SPA_SIGNALS = [
    r'window\.__INITIAL_STATE__',
    r'window\.__PRELOADED_STATE__',
    r'window\.__APP_STATE__',
    r'hydrate\(',
    r'createRoot\(',
    r'ReactDOM\.render',
]

# Noscript warnings (strong signal)
NOSCRIPT_PATTERNS = [
    r'<noscript>.*?(?:enable|requires?|need).*?javascript.*?</noscript>',
    r'<noscript>.*?(?:browser|support).*?javascript.*?</noscript>',
]

# Bundle patterns in script src
BUNDLE_PATTERNS = [
    r'src=["\'][^"\']*(?:bundle|main|app|vendor|chunk)\.[a-f0-9]+\.js',
    r'src=["\'][^"\']*webpack',
    r'src=["\'][^"\']*\.chunk\.js',
]


def detect_js_required(html: str, word_count: int | None = None) -> JSDetectionResult:
    """
    Detect if a page likely requires JavaScript rendering.

    Args:
        html: Raw HTML content (static fetch)
        word_count: Optional word count from static extraction

    Returns:
        JSDetectionResult with detection info
    """
    signals = []
    framework = None
    html_lower = html.lower()

    # Check for empty SPA root divs (strong signal)
    for pattern in SPA_ROOT_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            signals.append(f'empty_root_div:{pattern.split("id=")[1][:10]}')

    # Check for framework-specific markers
    for fw_name, patterns in FRAMEWORK_MARKERS.items():
        for pattern in patterns:
            if re.search(pattern, html, re.IGNORECASE):
                if not framework:
                    framework = fw_name
                signals.append(f'framework:{fw_name}')
                break

    # Check for generic SPA signals
    for pattern in SPA_SIGNALS:
        if re.search(pattern, html, re.IGNORECASE):
            signals.append('spa_state_hydration')
            break

    # Check for noscript warnings (very strong signal)
    for pattern in NOSCRIPT_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE | re.DOTALL):
            signals.append('noscript_warning')
            break

    # Check for bundle patterns
    bundle_count = 0
    for pattern in BUNDLE_PATTERNS:
        bundle_count += len(re.findall(pattern, html, re.IGNORECASE))
    if bundle_count >= 2:
        signals.append(f'js_bundles:{bundle_count}')

    # Check script-to-text ratio
    script_bytes = sum(len(m) for m in re.findall(r'<script[^>]*>.*?</script>', html, re.DOTALL | re.IGNORECASE))
    total_bytes = len(html)
    if total_bytes > 0:
        script_ratio = script_bytes / total_bytes
        if script_ratio > 0.5:
            signals.append(f'high_script_ratio:{script_ratio:.0%}')

    # Check for suspiciously low content in body
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_content = body_match.group(1)
        # Strip scripts and styles
        body_text = re.sub(r'<script[^>]*>.*?</script>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_text = re.sub(r'<style[^>]*>.*?</style>', '', body_text, flags=re.DOTALL | re.IGNORECASE)
        body_text = re.sub(r'<[^>]+>', ' ', body_text)
        body_words = len(body_text.split())
        if body_words < 50 and len(html) > 10000:
            signals.append(f'empty_body:{body_words}_words')

    # Use provided word count as signal
    if word_count is not None and word_count < 100 and len(html) > 5000:
        signals.append(f'low_extracted_words:{word_count}')

    # Determine confidence and result
    signals = list(set(signals))  # dedupe

    # Strong signals that alone indicate JS required
    strong_signals = {'noscript_warning', 'empty_body'}
    strong_frameworks = {'aem', 'angular'}  # These are almost always JS-heavy

    if any(s.split(':')[0] in strong_signals for s in signals):
        return JSDetectionResult(
            js_required=True,
            confidence='high',
            signals=signals,
            framework=framework,
        )

    # AEM and Angular are strong indicators even alone
    if framework in strong_frameworks:
        return JSDetectionResult(
            js_required=True,
            confidence='medium',
            signals=signals,
            framework=framework,
        )

    if len(signals) >= 3:
        return JSDetectionResult(
            js_required=True,
            confidence='high',
            signals=signals,
            framework=framework,
        )

    if len(signals) >= 2:
        return JSDetectionResult(
            js_required=True,
            confidence='medium',
            signals=signals,
            framework=framework,
        )

    if len(signals) == 1:
        return JSDetectionResult(
            js_required=False,
            confidence='low',
            signals=signals,
            framework=framework,
        )

    return JSDetectionResult(
        js_required=False,
        confidence='high',
        signals=[],
        framework=None,
    )


def quick_js_check(html: str) -> bool:
    """
    Quick boolean check - does this page need JS?

    Use for fast decisions in crawl loop.
    """
    result = detect_js_required(html)
    return result.js_required and result.confidence in ('high', 'medium')
