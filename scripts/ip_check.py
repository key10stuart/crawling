#!/usr/bin/env python3
"""Check IP reputation across multiple services."""
import subprocess
import json
import sys

def main():
    print("IP Reputation Check")
    print("=" * 40)

    # Get current IP
    try:
        result = subprocess.run(
            ["curl", "-s", "https://ipinfo.io"],
            capture_output=True, text=True, timeout=10
        )
        info = json.loads(result.stdout)
        ip = info.get("ip", "unknown")
        org = info.get("org", "unknown")
        print(f"Your IP: {ip}")
        print(f"ISP: {org}")
        print()
    except Exception as e:
        print(f"Could not get IP: {e}")
        return 1

    # Check Tor status
    try:
        result = subprocess.run(
            ["curl", "-s", "https://check.torproject.org/api/ip"],
            capture_output=True, text=True, timeout=10
        )
        tor_info = json.loads(result.stdout)
        is_tor = tor_info.get("IsTor", False)
        print(f"Tor exit node: {'YES (bad)' if is_tor else 'No (good)'}")
    except:
        print("Tor check: failed")

    # Quick connectivity tests to common CDNs
    print("\nCDN connectivity (are we blocked?):")
    cdns = [
        ("Cloudflare", "https://www.cloudflare.com/cdn-cgi/trace"),
        ("Akamai", "https://www.akamai.com"),
        ("StackPath", "https://www.stackpath.com"),
    ]

    for name, url in cdns:
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10", url],
                capture_output=True, text=True, timeout=15
            )
            code = result.stdout.strip()
            status = "OK" if code in ("200", "301", "302") else f"HTTP {code}"
            print(f"  {name}: {status}")
        except:
            print(f"  {name}: timeout/error")

    print("\n" + "=" * 40)
    print("Manual checks (paste IP into these):")
    print(f"  https://www.abuseipdb.com/check/{ip}")
    print(f"  https://mxtoolbox.com/SuperTool.aspx?action=blacklist%3a{ip}")
    print(f"  https://www.spamhaus.org/query/ip/{ip}")

    print("\nRecommendations:")
    print("  - Residential IP = low risk for polite crawling")
    print("  - Use --delay 5 or --patient for sensitive sites")
    print("  - If seeing lots of 403s, try --slow-drip mode")
    print("  - For heavy crawling, consider proxy rotation")

    return 0

if __name__ == "__main__":
    sys.exit(main())
