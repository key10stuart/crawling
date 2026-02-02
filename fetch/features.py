"""
Feature detection - passive scanning for portals, logins, integrations.

Scans page HTML for clues about capabilities WITHOUT clicking, submitting,
or navigating. Just "try the handle" - note what doors exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class DetectedFeature:
    """A detected feature/capability on the page."""
    category: str  # portal, tracking, api, integration, form
    feature_type: str  # customer_portal, carrier_portal, tracking_tool, etc.
    evidence: list[str] = field(default_factory=list)  # What we found
    url: str | None = None  # Link if found
    confidence: float = 0.0  # 0-1


@dataclass
class FeatureScan:
    """Results of scanning a page for features."""
    features: list[DetectedFeature] = field(default_factory=list)
    portal_links: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    api_hints: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)


# Portal/login URL patterns
PORTAL_PATTERNS = {
    'customer_portal': [r'/customer', r'/shipper', r'/my-?account', r'/client'],
    'carrier_portal': [r'/carrier', r'/owner-?operator', r'/driver', r'/partner'],
    'tracking': [r'/track', r'/trace', r'/shipment', r'/pro-?search'],
    'quote': [r'/quote', r'/rate', r'/pricing', r'/estimate'],
    'login': [r'/login', r'/sign-?in', r'/auth', r'/sso', r'/portal'],
    'investor': [r'/investor', r'/shareholder', r'/sec-?filing'],
}

# OAuth/SSO providers
OAUTH_PATTERNS = [
    (r'sign\s*in\s*with\s*google', 'Google OAuth'),
    (r'sign\s*in\s*with\s*microsoft', 'Microsoft OAuth'),
    (r'sign\s*in\s*with\s*okta', 'Okta SSO'),
    (r'sign\s*in\s*with\s*azure', 'Azure AD'),
    (r'saml|sso|single\s*sign', 'SSO'),
]

# Known integrations/TMS
INTEGRATION_PATTERNS = [
    (r'salesforce', 'Salesforce'),
    (r'oracle.*transport', 'Oracle Transportation'),
    (r'sap.*tm|sap.*transport', 'SAP TM'),
    (r'bluejay|e2open', 'E2open/BluJay'),
    (r'mcleod', 'McLeod Software'),
    (r'tmw|trimble', 'Trimble TMW'),
    (r'mercurygate', 'MercuryGate'),
    (r'project44|p44', 'project44'),
    (r'fourkites', 'FourKites'),
    (r'descartes', 'Descartes'),
    (r'manhattan.*associates', 'Manhattan Associates'),
    (r'jda|blue\s*yonder', 'Blue Yonder'),
    (r'edi.*integration|x12|edifact', 'EDI'),
    (r'api.*integration|rest.*api|api.*access', 'API Integration'),
]

# API endpoint patterns in scripts
API_PATTERNS = [
    r'fetch\([\'\"](/api/[^\'"]+)',
    r'axios\.[a-z]+\([\'\"](/api/[^\'"]+)',
    r'[\'\"](https?://[^\'\"]*api[^\'\"]*)[\'"]',
    r'/api/v\d+/',
    r'graphql',
]


def detect_features(html: str, base_url: str = '') -> FeatureScan:
    """
    Scan HTML for features without any interaction.

    Args:
        html: Page HTML content
        base_url: Base URL for resolving relative links

    Returns:
        FeatureScan with detected features
    """
    soup = BeautifulSoup(html, 'lxml')
    scan = FeatureScan()

    # Scan links for portal patterns
    _scan_links(soup, base_url, scan)

    # Scan forms
    _scan_forms(soup, scan)

    # Scan for OAuth/SSO
    _scan_oauth(soup, scan)

    # Scan for integrations (in text and scripts)
    _scan_integrations(soup, html, scan)

    # Scan scripts for API hints
    _scan_apis(soup, html, scan)

    return scan


def _scan_links(soup: BeautifulSoup, base_url: str, scan: FeatureScan) -> None:
    """Find portal/login links."""
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        text = a.get_text(strip=True).lower()

        for portal_type, patterns in PORTAL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, href) or re.search(pattern, text):
                    full_url = urljoin(base_url, a['href']) if base_url else a['href']
                    scan.portal_links.append({
                        'type': portal_type,
                        'url': full_url,
                        'text': a.get_text(strip=True)[:100],
                    })
                    scan.features.append(DetectedFeature(
                        category='portal',
                        feature_type=portal_type,
                        evidence=[f"Link: {a.get_text(strip=True)[:50]}"],
                        url=full_url,
                        confidence=0.8,
                    ))
                    break


def _scan_forms(soup: BeautifulSoup, scan: FeatureScan) -> None:
    """Detect forms and their purposes."""
    for form in soup.find_all('form'):
        form_info = {
            'action': form.get('action', ''),
            'method': form.get('method', 'get').upper(),
            'fields': [],
            'has_password': False,
            'purpose': 'unknown',
        }

        # Scan inputs
        for inp in form.find_all(['input', 'select', 'textarea']):
            inp_type = inp.get('type', 'text').lower()
            inp_name = inp.get('name', inp.get('id', ''))

            if inp_type == 'password':
                form_info['has_password'] = True
            if inp_type not in ('hidden', 'submit', 'button'):
                form_info['fields'].append({
                    'name': inp_name,
                    'type': inp_type,
                })

        # Determine purpose
        action = form_info['action'].lower()
        if form_info['has_password']:
            form_info['purpose'] = 'login'
        elif re.search(r'track|trace|pro', action):
            form_info['purpose'] = 'tracking'
        elif re.search(r'quote|rate', action):
            form_info['purpose'] = 'quote'
        elif re.search(r'search', action):
            form_info['purpose'] = 'search'
        elif re.search(r'contact|email', action):
            form_info['purpose'] = 'contact'

        if form_info['fields']:  # Only add non-empty forms
            scan.forms.append(form_info)

            if form_info['purpose'] != 'unknown':
                scan.features.append(DetectedFeature(
                    category='form',
                    feature_type=form_info['purpose'],
                    evidence=[f"Form with {len(form_info['fields'])} fields"],
                    confidence=0.7 if form_info['has_password'] else 0.5,
                ))


def _scan_oauth(soup: BeautifulSoup, scan: FeatureScan) -> None:
    """Detect OAuth/SSO providers."""
    text = soup.get_text().lower()

    for pattern, provider in OAUTH_PATTERNS:
        if re.search(pattern, text, re.I):
            scan.features.append(DetectedFeature(
                category='integration',
                feature_type='oauth',
                evidence=[provider],
                confidence=0.9,
            ))


def _scan_integrations(soup: BeautifulSoup, html: str, scan: FeatureScan) -> None:
    """Detect TMS/integration mentions."""
    text = soup.get_text().lower()

    seen = set()
    for pattern, name in INTEGRATION_PATTERNS:
        if re.search(pattern, text, re.I) or re.search(pattern, html, re.I):
            if name not in seen:
                seen.add(name)
                scan.integrations.append(name)
                scan.features.append(DetectedFeature(
                    category='integration',
                    feature_type='tms' if 'TM' in name or 'Software' in name else 'platform',
                    evidence=[name],
                    confidence=0.6,
                ))


def _scan_apis(soup: BeautifulSoup, html: str, scan: FeatureScan) -> None:
    """Look for API endpoints in scripts."""
    # Check script tags
    for script in soup.find_all('script'):
        script_text = script.string or ''
        for pattern in API_PATTERNS:
            matches = re.findall(pattern, script_text, re.I)
            for match in matches:
                if match and match not in scan.api_hints:
                    scan.api_hints.append(match)

    # Also check inline event handlers and data attributes
    for pattern in API_PATTERNS:
        matches = re.findall(pattern, html, re.I)
        for match in matches:
            if match and match not in scan.api_hints:
                scan.api_hints.append(match)

    if scan.api_hints:
        scan.features.append(DetectedFeature(
            category='api',
            feature_type='endpoint',
            evidence=scan.api_hints[:5],  # First 5
            confidence=0.7,
        ))


def summarize_features(scan: FeatureScan) -> dict:
    """Summarize scan results for logging/output."""
    return {
        'portal_count': len(scan.portal_links),
        'portals': [{'type': p['type'], 'url': p['url']} for p in scan.portal_links[:5]],
        'forms': [{'purpose': f['purpose'], 'fields': len(f['fields'])} for f in scan.forms[:5]],
        'integrations': scan.integrations[:10],
        'api_hints': scan.api_hints[:5],
        'feature_count': len(scan.features),
    }
