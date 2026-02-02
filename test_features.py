#!/usr/bin/env python3
"""Test feature detection on a site."""

import sys
sys.path.insert(0, '.')

from fetch import fetch_source
from fetch.features import detect_features, summarize_features
from fetch.config import FetchConfig

url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.schneider.com'

print(f'Scanning: {url}\n')

config = FetchConfig(return_html=True)
result = fetch_source(url, config)

if not result or not result.raw_html:
    print('Failed to fetch')
    sys.exit(1)

scan = detect_features(result.raw_html, result.final_url)
summary = summarize_features(scan)

print(f"Portals found: {summary['portal_count']}")
for p in summary['portals']:
    print(f"  - {p['type']}: {p['url']}")

print(f"\nForms: {len(summary['forms'])}")
for f in summary['forms']:
    print(f"  - {f['purpose']} ({f['fields']} fields)")

print(f"\nIntegrations: {summary['integrations'] or 'none detected'}")
print(f"API hints: {summary['api_hints'] or 'none detected'}")
print(f"\nTotal features: {summary['feature_count']}")
