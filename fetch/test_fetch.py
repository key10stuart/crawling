#!/usr/bin/env python3
"""
Quick test script for fetch module.

Usage:
    python -m fetch.test_fetch
    python -m fetch.test_fetch https://example.com
"""

import sys
from pprint import pprint

from . import fetch_source, FetchConfig


TEST_URLS = [
    "https://www.reuters.com",
    "https://en.wikipedia.org/wiki/Web_scraping",
    "https://example.com",
]


def test_single(url: str) -> None:
    """Test fetching a single URL."""
    print(f"\n{'='*60}")
    print(f"Fetching: {url}")
    print('='*60)

    config = FetchConfig(
        js_fallback=True,
        archive_html=False,  # don't save for tests
    )

    result = fetch_source(url, config)

    if result is None:
        print("FAILED: fetch_source returned None")
        return

    print(f"\nResult:")
    print(f"  final_url:      {result.final_url}")
    print(f"  fetch_method:   {result.fetch_method}")
    print(f"  extract_method: {result.extract_method}")
    print(f"  confidence:     {result.confidence}")
    print(f"  title:          {result.title[:60]}..." if result.title and len(result.title) > 60 else f"  title:          {result.title}")
    print(f"  author:         {result.author}")
    print(f"  publish_date:   {result.publish_date}")
    print(f"  word_count:     {result.word_count}")
    print(f"  content_hash:   {result.content_hash}")
    print(f"  raw_html_hash:  {result.raw_html_hash}")

    if result.error:
        print(f"  error:          {result.error}")

    if result.text:
        preview = result.text[:300].replace('\n', ' ')
        print(f"\n  Text preview:\n  {preview}...")


def main() -> None:
    """Run tests."""
    if len(sys.argv) > 1:
        # Test specific URL
        test_single(sys.argv[1])
    else:
        # Test default URLs
        for url in TEST_URLS:
            test_single(url)


if __name__ == '__main__':
    main()
