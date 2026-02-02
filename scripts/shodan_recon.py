#!/usr/bin/env python3
"""
Shodan reconnaissance tool - standalone experimentation script.

Queries Shodan for IP intelligence on domains:
- Open ports
- Hosting provider / ASN
- Server software
- SSL certificate info
- Known vulnerabilities (if on paid plan)

Usage:
    # Set API key
    export SHODAN_API_KEY="your-key-here"

    # Single domain
    python scripts/shodan_recon.py jbhunt.com

    # Multiple domains
    python scripts/shodan_recon.py jbhunt.com schneider.com werner.com

    # From seed file (tier 1)
    python scripts/shodan_recon.py --tier 1

    # Save results
    python scripts/shodan_recon.py jbhunt.com -o results.json

Requirements:
    pip install shodan
"""

import argparse
import json
import os
import socket
import ssl
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# Optional Shodan import
try:
    import shodan
    SHODAN_AVAILABLE = True
except ImportError:
    SHODAN_AVAILABLE = False
    shodan = None

PROJECT_ROOT = Path(__file__).parent.parent
SEEDS_FILE = PROJECT_ROOT / "seeds" / "trucking_carriers.json"


@dataclass
class ShodanResult:
    """Result of Shodan IP lookup."""
    domain: str
    ip: str | None = None
    available: bool = False

    # Shodan data
    open_ports: list[int] = field(default_factory=list)
    hostnames: list[str] = field(default_factory=list)
    hosting_provider: str | None = None
    asn: str | None = None
    isp: str | None = None
    country: str | None = None
    city: str | None = None

    # Server info
    server_software: list[str] = field(default_factory=list)
    http_server: str | None = None

    # SSL
    ssl_issuer: str | None = None
    ssl_expires: str | None = None
    ssl_subject_cn: str | None = None
    cert_san_domains: list[str] = field(default_factory=list)

    # Security
    known_vulns: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Meta
    last_update: str | None = None
    error: str | None = None
    queried_at: str = ""


@dataclass
class DnsResult:
    """DNS lookup result (no Shodan needed)."""
    domain: str
    ip_addresses: list[str] = field(default_factory=list)
    cert_subdomains: list[str] = field(default_factory=list)
    error: str | None = None


def resolve_domain(domain: str) -> str | None:
    """Resolve domain to IP address."""
    try:
        return socket.gethostbyname(domain)
    except socket.gaierror:
        return None


def get_cert_subdomains(domain: str, port: int = 443) -> list[str]:
    """Extract Subject Alternative Names from SSL certificate."""
    subdomains = []
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    san = cert.get('subjectAltName', ())
                    for type_, value in san:
                        if type_ == 'DNS' and value not in subdomains:
                            subdomains.append(value)
    except Exception:
        pass
    return subdomains


def dns_recon(domain: str) -> DnsResult:
    """Basic DNS recon (no API key needed)."""
    result = DnsResult(domain=domain)

    # A records
    try:
        ips = socket.gethostbyname_ex(domain)[2]
        result.ip_addresses = ips
    except socket.gaierror as e:
        result.error = str(e)

    # Cert SANs
    try:
        result.cert_subdomains = get_cert_subdomains(domain)
    except Exception:
        pass

    return result


def shodan_recon(domain: str, api: 'shodan.Shodan') -> ShodanResult:
    """Query Shodan for domain intelligence."""
    result = ShodanResult(
        domain=domain,
        queried_at=datetime.utcnow().isoformat() + "Z"
    )

    # Resolve domain first
    ip = resolve_domain(domain)
    if not ip:
        result.error = "DNS resolution failed"
        return result

    result.ip = ip

    try:
        host = api.host(ip)
        result.available = True

        # Basic info
        result.open_ports = host.get('ports', [])
        result.hostnames = host.get('hostnames', [])
        result.asn = host.get('asn')
        result.isp = host.get('isp')
        result.hosting_provider = host.get('org')
        result.country = host.get('country_name')
        result.city = host.get('city')
        result.last_update = host.get('last_update')

        # Tags and vulns
        result.tags = host.get('tags', [])
        result.known_vulns = host.get('vulns', [])

        # Parse banners for more details
        for banner in host.get('data', []):
            # Server software
            product = banner.get('product')
            if product:
                version = banner.get('version', '')
                sw = f"{product} {version}".strip() if version else product
                if sw not in result.server_software:
                    result.server_software.append(sw)

            # HTTP server header
            http = banner.get('http', {})
            if http:
                server = http.get('server')
                if server and not result.http_server:
                    result.http_server = server

            # SSL certificate
            ssl_info = banner.get('ssl', {})
            if ssl_info:
                cert = ssl_info.get('cert', {})
                if cert:
                    # Issuer
                    issuer = cert.get('issuer', {})
                    if issuer and not result.ssl_issuer:
                        result.ssl_issuer = issuer.get('O') or issuer.get('CN')

                    # Subject
                    subject = cert.get('subject', {})
                    if subject and not result.ssl_subject_cn:
                        result.ssl_subject_cn = subject.get('CN')

                    # Expiry
                    expires = cert.get('expires')
                    if expires and not result.ssl_expires:
                        result.ssl_expires = expires

                    # SANs
                    extensions = cert.get('extensions', [])
                    for ext in extensions:
                        if ext.get('name') == 'subjectAltName':
                            data = ext.get('data', '')
                            # Parse "DNS:example.com, DNS:www.example.com"
                            for part in data.split(','):
                                part = part.strip()
                                if part.startswith('DNS:'):
                                    san = part[4:]
                                    if san not in result.cert_san_domains:
                                        result.cert_san_domains.append(san)

    except shodan.APIError as e:
        result.error = f"Shodan API error: {e}"
    except Exception as e:
        result.error = f"Error: {e}"

    return result


def load_carriers(tier: int | None = None) -> list[str]:
    """Load carrier domains from seed file."""
    if not SEEDS_FILE.exists():
        return []

    with open(SEEDS_FILE) as f:
        data = json.load(f)

    carriers = data.get('carriers', [])
    if tier is not None:
        carriers = [c for c in carriers if c.get('tier') == tier]

    return [c['domain'].split('/')[0] for c in carriers]


def print_result(result: ShodanResult, verbose: bool = False):
    """Pretty print a Shodan result."""
    print(f"\n{'='*60}")
    print(f"Domain: {result.domain}")
    print(f"IP: {result.ip or 'N/A'}")

    if result.error:
        print(f"Error: {result.error}")
        return

    if not result.available:
        print("No Shodan data available")
        return

    print(f"Location: {result.city or '?'}, {result.country or '?'}")
    print(f"Hosting: {result.hosting_provider or 'N/A'}")
    print(f"ASN: {result.asn or 'N/A'}")
    print(f"ISP: {result.isp or 'N/A'}")

    if result.open_ports:
        print(f"Open ports: {', '.join(map(str, sorted(result.open_ports)))}")

    if result.server_software:
        print(f"Software: {', '.join(result.server_software[:5])}")

    if result.http_server:
        print(f"HTTP Server: {result.http_server}")

    if result.ssl_issuer:
        print(f"SSL Issuer: {result.ssl_issuer}")
        if result.ssl_expires:
            print(f"SSL Expires: {result.ssl_expires}")

    if result.cert_san_domains:
        print(f"Cert SANs: {', '.join(result.cert_san_domains[:10])}")

    if result.known_vulns:
        print(f"⚠️  Known vulns: {', '.join(result.known_vulns[:5])}")

    if result.tags:
        print(f"Tags: {', '.join(result.tags)}")

    if verbose and result.hostnames:
        print(f"Hostnames: {', '.join(result.hostnames[:10])}")


def print_dns_result(result: DnsResult):
    """Pretty print DNS result."""
    print(f"\n{'='*60}")
    print(f"Domain: {result.domain}")

    if result.error:
        print(f"Error: {result.error}")
        return

    if result.ip_addresses:
        print(f"IPs: {', '.join(result.ip_addresses)}")

    if result.cert_subdomains:
        print(f"Cert SANs: {', '.join(result.cert_subdomains)}")


def main():
    parser = argparse.ArgumentParser(
        description='Shodan reconnaissance for domains',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s jbhunt.com
    %(prog)s --tier 1 --limit 5
    %(prog)s jbhunt.com -o results.json
    %(prog)s jbhunt.com --dns-only  # No Shodan, just DNS + cert
        """
    )
    parser.add_argument('domains', nargs='*', help='Domains to scan')
    parser.add_argument('--tier', type=int, help='Load domains from seed file by tier')
    parser.add_argument('--limit', type=int, help='Max domains to scan')
    parser.add_argument('-o', '--output', help='Save results to JSON file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--dns-only', action='store_true',
                       help='Only do DNS + cert lookup (no Shodan API needed)')
    args = parser.parse_args()

    # Collect domains
    domains = list(args.domains) if args.domains else []

    if args.tier is not None:
        tier_domains = load_carriers(args.tier)
        domains.extend(tier_domains)
        print(f"Loaded {len(tier_domains)} tier-{args.tier} carriers from seed file")

    if not domains:
        parser.print_help()
        print("\nError: No domains specified")
        sys.exit(1)

    # Apply limit
    if args.limit:
        domains = domains[:args.limit]

    print(f"Scanning {len(domains)} domain(s)...")

    # DNS-only mode
    if args.dns_only:
        results = []
        for domain in domains:
            result = dns_recon(domain)
            print_dns_result(result)
            results.append(asdict(result))

        if args.output:
            Path(args.output).write_text(json.dumps(results, indent=2))
            print(f"\nSaved to {args.output}")
        return

    # Full Shodan mode
    if not SHODAN_AVAILABLE:
        print("Error: shodan library not installed")
        print("Install with: pip install shodan")
        print("Or use --dns-only for basic recon without Shodan")
        sys.exit(1)

    api_key = os.environ.get('SHODAN_API_KEY')
    if not api_key:
        print("Error: SHODAN_API_KEY environment variable not set")
        print("Get your API key from https://account.shodan.io")
        print("Then: export SHODAN_API_KEY='your-key-here'")
        print("\nOr use --dns-only for basic recon without Shodan")
        sys.exit(1)

    api = shodan.Shodan(api_key)

    # Check API info
    try:
        info = api.info()
        print(f"Shodan API: {info.get('plan', 'unknown')} plan, "
              f"{info.get('query_credits', 0)} query credits remaining")
    except shodan.APIError as e:
        print(f"API key error: {e}")
        sys.exit(1)

    # Scan domains
    results = []
    for domain in domains:
        result = shodan_recon(domain, api)
        print_result(result, verbose=args.verbose)
        results.append(asdict(result))

    # Save results
    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"\n{'='*60}")
        print(f"Saved {len(results)} results to {args.output}")

    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    successful = [r for r in results if r.get('available')]
    print(f"  Successful lookups: {len(successful)}/{len(results)}")

    if successful:
        all_ports = set()
        for r in successful:
            all_ports.update(r.get('open_ports', []))
        print(f"  Unique ports seen: {sorted(all_ports)}")

        providers = [r.get('hosting_provider') for r in successful if r.get('hosting_provider')]
        if providers:
            from collections import Counter
            top = Counter(providers).most_common(3)
            print(f"  Top providers: {', '.join(f'{p}({c})' for p,c in top)}")


if __name__ == '__main__':
    main()
