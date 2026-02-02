# Infrastructure: What's Behind the URL

When you visit a corporate website, you're not connecting to one computer.
You're hitting a complex stack of services, caches, and protections.

## The Modern Web Stack

```
                              Your Browser
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                         DNS                                   │
│  "What IP is www.jbhunt.com?" → 104.18.23.55                 │
│  (Often returns CDN IP, not origin)                          │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    CDN Edge Server                            │
│  Cloudflare, Akamai, Fastly, StackPath                       │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ • Serves cached content (fast!)                      │    │
│  │ • Terminates TLS (HTTPS)                             │    │
│  │ • Runs WAF rules (blocks attacks)                    │    │
│  │ • Bot detection / CAPTCHA                            │    │
│  │ • DDoS protection                                    │    │
│  │ • Geographic routing (nearest server)                │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (cache miss)
┌──────────────────────────────────────────────────────────────┐
│                      Load Balancer                            │
│  Distributes traffic across multiple origin servers          │
└──────────────────────────────────────────────────────────────┘
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐
│      Web Server 1           │  │      Web Server 2           │
│  (Nginx, Apache, Node)      │  │  (Nginx, Apache, Node)      │
└─────────────────────────────┘  └─────────────────────────────┘
                          │                 │
                          └────────┬────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    Application Server                         │
│  The actual website code (WordPress, React app, custom)      │
│  Languages: PHP, Python, Node.js, Java, .NET                 │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                        Database                               │
│  MySQL, PostgreSQL, MongoDB, etc.                            │
│  Stores: content, users, orders, everything                  │
└──────────────────────────────────────────────────────────────┘
```

## CDN: The Gatekeepers

Most corporate sites use a CDN. Here's what we see:

| CDN | Detection | Common Protection |
|-----|-----------|-------------------|
| Cloudflare | `cf-ray` header, `__cf_bm` cookie | JS challenge, Turnstile |
| Akamai | `akamai` in headers | Bot Manager |
| StackPath | `x-sp-*` headers | SecureCDN |
| Fastly | `fastly` headers | Signal Sciences |
| AWS CloudFront | `x-amz-cf-*` headers | AWS WAF |

Our recon detects these:

```python
from fetch.recon import recon_site
r = recon_site('https://www.knight-swift.com')
print(r.cdn)  # 'stackpath'
print(r.waf)  # 'stackpath'
```

## Shodan: X-Ray Vision for the Internet

Shodan indexes every device connected to the internet. We can see:

```bash
python scripts/shodan_recon.py --domain jbhunt.com

# Output:
# IP: 104.18.23.55
# Ports: 80, 443, 8080
# Hosting: Cloudflare
# SSL Cert: *.jbhunt.com (Let's Encrypt)
# Last seen: 2024-01-15
```

This reveals:
- What ports are open
- What services are running
- SSL certificate details
- Hosting provider
- Historical data

## Common Tech Stacks We See

### Enterprise CMS
```
Adobe Experience Manager (AEM)
├── Java-based
├── Massive XML configs
├── /content/dam/* paths
└── Used by: J.B. Hunt, FedEx, many Fortune 500
```

### WordPress
```
WordPress + WP Engine
├── PHP-based
├── /wp-content/* paths
├── /wp-json/wp/v2/* API
└── Easy to identify, common vulnerabilities
```

### Modern SPA
```
React/Next.js + Vercel
├── JavaScript-based
├── _next/static/* paths
├── Server-side rendering optional
└── Schneider uses this
```

### Angular
```
Angular + Azure
├── TypeScript-based
├── main.*.js bundles
├── <app-root> shell
└── Saia uses this
```

## What We Learn From Headers

HTTP response headers reveal a lot:

```http
HTTP/2 200
server: cloudflare           ← CDN
cf-ray: abc123-IAD           ← Cloudflare datacenter (IAD = Virginia)
x-powered-by: WP Engine      ← Hosting platform
x-cache: HIT                 ← Served from cache
cache-control: max-age=600   ← Cached for 10 minutes
set-cookie: __cf_bm=...      ← Bot management cookie
```

Our recon captures all of this.

## The Corporate Website Lifecycle

How do companies manage their sites?

```
1. Marketing team writes content (often in Word/Google Docs)
            │
            ▼
2. Uploaded to CMS (WordPress, AEM, Contentful)
            │
            ▼
3. Reviewed and approved (staging environment)
            │
            ▼
4. Published to production
            │
            ▼
5. CDN caches it (stays cached for hours/days)
            │
            ▼
6. You visit → get cached version from nearest edge server
```

This is why:
- Content may be hours old (cache TTL)
- Different regions may see different versions (edge caching)
- Changes take time to propagate

## Exercise: Trace a Request

Use curl with verbose output:

```bash
curl -v https://www.jbhunt.com 2>&1 | head -50

# Look for:
# * Trying 104.18.23.55:443...      ← IP address
# * SSL connection using TLSv1.3    ← Encryption
# < server: cloudflare              ← CDN
# < cf-ray: abc123-ATL              ← Edge location (Atlanta)
```

## Next: Information Theory - Signal vs. Noise

How do we extract meaning from the chaos of the web?

→ [05_information_theory.md](05_information_theory.md)
