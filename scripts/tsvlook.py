#!/usr/bin/env python3
"""
Quick TSV viewer. Usage:
  python scripts/tsvlook.py corpus/tweets/tweets_extracted.tsv
  python scripts/tsvlook.py file.tsv -n 30        # first 30 rows
  python scripts/tsvlook.py file.tsv -t 60         # truncate text to 60 chars
  python scripts/tsvlook.py file.tsv -c user,text  # only these columns
  python scripts/tsvlook.py file.tsv -s fail       # search rows containing "fail"
"""

import csv
import sys
import argparse


def truncate(s, n):
    return s[:n-1] + "…" if len(s) > n else s


def run():
    p = argparse.ArgumentParser(description="Quick TSV viewer")
    p.add_argument("file", help="TSV file to view")
    p.add_argument("-n", "--rows", type=int, default=20, help="Number of rows (default 20, 0=all)")
    p.add_argument("-t", "--trunc", type=int, default=80, help="Max text column width (default 80)")
    p.add_argument("-c", "--cols", help="Comma-separated column names to show")
    p.add_argument("-s", "--search", help="Only show rows containing this string (case-insensitive)")
    p.add_argument("-T", "--tail", action="store_true", help="Show last N rows instead of first")
    args = p.parse_args()

    with open(args.file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        all_cols = reader.fieldnames or []

        if args.cols:
            show_cols = [c.strip() for c in args.cols.split(",")]
        else:
            show_cols = all_cols

        rows = []
        for row in reader:
            if args.search and args.search.lower() not in "\t".join(row.values()).lower():
                continue
            rows.append(row)

    if args.tail:
        rows = rows[-args.rows:] if args.rows else rows
    elif args.rows:
        rows = rows[:args.rows]

    if not rows:
        print("No matching rows.")
        return

    # Build display data with truncation
    display = []
    for row in rows:
        display.append({c: truncate(row.get(c, ""), args.trunc) for c in show_cols})

    # Compute column widths
    widths = {}
    for c in show_cols:
        widths[c] = max(len(c), max((len(d[c]) for d in display), default=0))

    # Print header
    header = "  ".join(c.ljust(widths[c]) for c in show_cols)
    print(f"\033[1m{header}\033[0m")
    print("  ".join("─" * widths[c] for c in show_cols))

    # Print rows
    for d in display:
        print("  ".join(d[c].ljust(widths[c]) for c in show_cols))

    # Footer
    total_in_file = sum(1 for _ in open(args.file)) - 1
    print(f"\n\033[2m[{len(rows)} of {total_in_file} rows]\033[0m")


if __name__ == "__main__":
    run()
