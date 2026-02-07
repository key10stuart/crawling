#!/usr/bin/env python3
"""
Sample tweet extraction via three free API approaches.
Tests 10 tweets per method and compares results.
"""

import json
import re
import time
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = PROJECT_ROOT / "docs" / "targetx.txt"
OUTPUT_DIR = PROJECT_ROOT / "corpus" / "tweets"


# ---------------------------------------------------------------------------
# Parse target file
# ---------------------------------------------------------------------------

def load_targets(path: Path, limit: int = 10) -> list[dict]:
    """Load tweet URLs from targetx.txt (TSV: idx, timestamp, url)."""
    targets = []
    for line in path.read_text().splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        url = parts[2].strip()
        if not url or "x.com/" not in url:
            continue
        m = re.search(r"x\.com/(\w+)/status/(\d+)", url)
        if not m:
            continue
        targets.append({
            "url": url,
            "user": m.group(1),
            "tweet_id": m.group(2),
            "saved_at": parts[1].strip(),
        })
        if len(targets) >= limit:
            break
    return targets


# ---------------------------------------------------------------------------
# Method 1: fxtwitter
# ---------------------------------------------------------------------------

def fetch_fxtwitter(user: str, tweet_id: str) -> dict:
    url = f"https://api.fxtwitter.com/{user}/status/{tweet_id}"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:200]}
    data = resp.json()
    tweet = data.get("tweet", {})
    return {
        "ok": True,
        "method": "fxtwitter",
        "text": tweet.get("text", ""),
        "author": tweet.get("author", {}).get("screen_name", ""),
        "author_name": tweet.get("author", {}).get("name", ""),
        "created_at": tweet.get("created_at", ""),
        "likes": tweet.get("likes"),
        "retweets": tweet.get("retweets"),
        "replies": tweet.get("replies"),
        "views": tweet.get("views"),
        "replying_to": tweet.get("replying_to"),
        "lang": tweet.get("lang"),
        "media_count": len(tweet.get("media", {}).get("all", []))
            if tweet.get("media") else 0,
    }


# ---------------------------------------------------------------------------
# Method 2: syndication (Twitter first-party)
# ---------------------------------------------------------------------------

def fetch_syndication(tweet_id: str) -> dict:
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token=0"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:200]}
    data = resp.json()
    parent = data.get("parent", {})
    return {
        "ok": True,
        "method": "syndication",
        "text": data.get("text", ""),
        "author": data.get("user", {}).get("screen_name", ""),
        "author_name": data.get("user", {}).get("name", ""),
        "created_at": data.get("created_at", ""),
        "likes": data.get("favorite_count"),
        "retweets": data.get("retweet_count"),
        "replies": data.get("conversation_count"),
        "lang": data.get("lang"),
        "parent_text": parent.get("text") if parent else None,
        "parent_author": parent.get("user", {}).get("screen_name") if parent else None,
        "has_parent": bool(parent),
    }


# ---------------------------------------------------------------------------
# Method 3: vxtwitter
# ---------------------------------------------------------------------------

def fetch_vxtwitter(user: str, tweet_id: str) -> dict:
    url = f"https://api.vxtwitter.com/{user}/status/{tweet_id}"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:200]}
    data = resp.json()
    return {
        "ok": True,
        "method": "vxtwitter",
        "text": data.get("text", ""),
        "author": data.get("user_screen_name", ""),
        "author_name": data.get("user_name", ""),
        "created_at": data.get("date", ""),
        "likes": data.get("likes"),
        "retweets": data.get("retweets"),
        "replies": data.get("replies"),
        "lang": data.get("lang"),
        "replying_to": data.get("replyingTo"),
        "media_count": len(data.get("mediaURLs", [])),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

METHODS = {
    "fxtwitter": lambda t: fetch_fxtwitter(t["user"], t["tweet_id"]),
    "syndication": lambda t: fetch_syndication(t["tweet_id"]),
    "vxtwitter": lambda t: fetch_vxtwitter(t["user"], t["tweet_id"]),
}


def run_sample(targets: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = {}

    for method_name, fetcher in METHODS.items():
        print(f"\n{'='*60}")
        print(f"  METHOD: {method_name}")
        print(f"{'='*60}")

        results = []
        successes = 0
        for i, t in enumerate(targets):
            print(f"  [{i+1}/{len(targets)}] @{t['user']} / {t['tweet_id']} ... ", end="", flush=True)
            try:
                result = fetcher(t)
                result["tweet_id"] = t["tweet_id"]
                result["input_user"] = t["user"]
                results.append(result)

                if result["ok"]:
                    successes += 1
                    text_preview = result["text"][:80].replace("\n", " ")
                    print(f"OK  \"{text_preview}\"")
                else:
                    print(f"FAIL ({result.get('status', '?')})")
            except Exception as e:
                print(f"ERROR ({type(e).__name__}: {e})")
                results.append({
                    "ok": False, "tweet_id": t["tweet_id"],
                    "input_user": t["user"], "error": str(e),
                })

            time.sleep(0.3)  # politeness

        all_results[method_name] = results
        print(f"\n  {method_name}: {successes}/{len(targets)} succeeded")

        # Save per-method results
        out_path = OUTPUT_DIR / f"sample_{method_name}.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"  Saved: {out_path}")

    # --- Comparison ---
    print(f"\n{'='*60}")
    print("  COMPARISON")
    print(f"{'='*60}\n")

    for i, t in enumerate(targets):
        tid = t["tweet_id"]
        print(f"  Tweet {i+1}: @{t['user']} / {tid}")
        for method_name in METHODS:
            r = all_results[method_name][i]
            if r["ok"]:
                text_len = len(r.get("text", ""))
                likes = r.get('likes') or 0
                rts = r.get('retweets') or 0
                print(f"    {method_name:14s}  OK  {text_len:>5} chars  "
                      f"likes={likes:>6}  rt={rts:>5}")
            else:
                print(f"    {method_name:14s}  FAIL")
        print()

    # Save combined
    combined_path = OUTPUT_DIR / "sample_combined.json"
    combined_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"  Combined results: {combined_path}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    targets = load_targets(TARGET_FILE, limit=limit)
    print(f"Loaded {len(targets)} targets from {TARGET_FILE.name}")
    run_sample(targets)
