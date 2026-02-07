#!/usr/bin/env python3
"""
Bulk tweet text extraction via fxtwitter (primary) + vxtwitter (fallback).
Reads targetx.txt, outputs CSV in batches of 100.
"""

import csv
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = PROJECT_ROOT / "docs" / "targetx.txt"
OUTPUT_DIR = PROJECT_ROOT / "corpus" / "tweets"
OUTPUT_CSV = OUTPUT_DIR / "tweets_extracted.tsv"
PROGRESS_FILE = OUTPUT_DIR / ".pull_progress.json"

BATCH_SIZE = 100
DELAY = 0.3  # seconds between requests
FALLBACK_DELAY = 0.5


# ---------------------------------------------------------------------------
# Parse targets
# ---------------------------------------------------------------------------

def load_all_targets(path: Path) -> list[dict]:
    targets = []
    for line in path.read_text().splitlines()[1:]:
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
            "saved_at": parts[1].strip(),
            "url": url,
            "user": m.group(1),
            "tweet_id": m.group(2),
        })
    return targets


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_fxtwitter(user: str, tweet_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"https://api.fxtwitter.com/{user}/status/{tweet_id}",
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        tweet = resp.json().get("tweet", {})
        return {
            "text": tweet.get("text", ""),
            "author": tweet.get("author", {}).get("screen_name", ""),
            "method": "fxtwitter",
        }
    except Exception:
        return None


def fetch_vxtwitter(user: str, tweet_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"https://api.vxtwitter.com/{user}/status/{tweet_id}",
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "text": data.get("text", ""),
            "author": data.get("user_screen_name", ""),
            "method": "vxtwitter",
        }
    except Exception:
        return None


def fetch_tweet(user: str, tweet_id: str) -> dict:
    """Try fxtwitter, fall back to vxtwitter."""
    result = fetch_fxtwitter(user, tweet_id)
    if result and result["text"]:
        return result
    time.sleep(FALLBACK_DELAY)
    result = fetch_vxtwitter(user, tweet_id)
    if result and result["text"]:
        return result
    return {"text": "", "author": user, "method": "failed"}


# ---------------------------------------------------------------------------
# Progress tracking (resume support)
# ---------------------------------------------------------------------------

def load_progress() -> int:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text()).get("completed", 0)
        except Exception:
            pass
    return 0


def save_progress(n: int):
    PROGRESS_FILE.write_text(json.dumps({"completed": n}))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = load_all_targets(TARGET_FILE)
    total = len(targets)
    print(f"Loaded {total} tweet targets")

    already_done = load_progress()

    # If resuming, open in append mode; otherwise write fresh with header
    if already_done > 0 and OUTPUT_CSV.exists():
        print(f"Resuming from tweet {already_done + 1}")
        mode = "a"
        write_header = False
    else:
        already_done = 0
        mode = "w"
        write_header = True

    csvfile = open(OUTPUT_CSV, mode, newline="", encoding="utf-8")
    writer = csv.writer(csvfile, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    if write_header:
        writer.writerow(["saved_at", "url", "user", "tag", "text"])

    stats = {"ok": 0, "fail": 0, "fx": 0, "vx": 0}
    batch_num = (already_done // BATCH_SIZE) + 1

    try:
        for i in range(already_done, total):
            t = targets[i]
            batch_pos = (i % BATCH_SIZE) + 1

            if batch_pos == 1:
                batch_end = min(i + BATCH_SIZE, total)
                print(f"\n--- Batch {batch_num}: tweets {i+1}-{batch_end} of {total} ---")

            result = fetch_tweet(t["user"], t["tweet_id"])
            text = result["text"]
            method = result["method"]

            writer.writerow([
                t["saved_at"],
                t["url"],
                t["user"],
                "",  # tag - blank for now
                text.replace("\n", "\\n") if text else "",
            ])

            if method == "failed":
                stats["fail"] += 1
                status = "FAIL"
            else:
                stats["ok"] += 1
                stats["fx" if method == "fxtwitter" else "vx"] += 1
                status = f"OK({method[:2]})"

            preview = text[:60].replace("\n", " ") if text else "-"
            print(f"  [{i+1}/{total}] {status:8s} @{t['user'][:16]:<16s} \"{preview}\"")

            # Flush + save progress every row
            csvfile.flush()
            save_progress(i + 1)

            # End-of-batch summary
            if batch_pos == BATCH_SIZE or i == total - 1:
                pct = (i + 1) / total * 100
                print(f"  >> {stats['ok']} ok / {stats['fail']} fail "
                      f"({pct:.1f}% complete, fx={stats['fx']} vx={stats['vx']})")
                batch_num += 1

            time.sleep(DELAY)

    except KeyboardInterrupt:
        print(f"\n\nInterrupted at tweet {i+1}. Resume with: python {sys.argv[0]}")
    finally:
        csvfile.close()

    print(f"\nDone. {stats['ok']} extracted, {stats['fail']} failed out of {total}.")
    print(f"Output: {OUTPUT_CSV}")
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


if __name__ == "__main__":
    run()
