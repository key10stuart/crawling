import json
import os
import subprocess
import argparse
import asyncio  # ← this was missing


def run_from_config(path="pull_run.json"):
    print(f"📂 Loading config from {path}")
    with open(path) as f:
        config = json.load(f)

    script = config.get("script")
    print(f"🎬 Running script: {script}")

    if script == "monkey_do":
        print("🙈 Doing the monkey_do dance!")
    elif script == "monkey_see":
        from scrape_japes import monkey_see
        asyncio.run(monkey_see.record_interactions())
    elif script == "test":
        print("test")
    else:
        print("❌ Unknown script!")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config", default="pull_run.json")
    args = parser.parse_args()

    if args.command == "run":
        run_from_config(args.config)
