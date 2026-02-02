# Understanding the Web: An Educational Guide

This series explains what websites really are, how they work, and how to
programmatically extract information from them.

## The Curriculum

| # | Topic | Key Concepts |
|---|-------|--------------|
| 00 | [What Is A Website?](00_what_is_a_website.md) | DNS, HTTP, HTML, SPAs, browser rendering |
| 01 | [The Arms Race](01_the_arms_race.md) | Bot detection, CAPTCHAs, fingerprinting, evasion |
| 02 | [Anatomy of HTML](02_anatomy_of_html.md) | Semantic HTML, DOM structure, content extraction |
| 03 | [Dynamic Content](03_dynamic_content.md) | Lazy loading, SPAs, infinite scroll, APIs |
| 04 | [Infrastructure](04_infrastructure.md) | CDNs, WAFs, hosting, server stacks |
| 05 | [Information Theory](05_information_theory.md) | Signal vs noise, content density, extraction |

## Hands-On Exercises

Each doc includes exercises using our crawler tools:

```bash
# Recon a site
python -c "from fetch.recon import recon_site; print(recon_site('https://example.com'))"

# Check access status
python scripts/access_report.py

# Capture a page
python scripts/crawl.py --domain example.com --depth 0

# View extraction
python scripts/render_extraction.py --site corpus/sites/example_com.json
```

## The Big Picture

```
┌─────────────────────────────────────────────────────────────────┐
│                     THE INTERNET                                 │
│  Billions of machines connected via TCP/IP                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     THE WEB (HTTP)                               │
│  Documents linked via URLs, served over HTTP                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     WEBSITES                                     │
│  Collections of pages, assets, and applications                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     CONTENT                                      │
│  The actual information humans want to read                      │
└─────────────────────────────────────────────────────────────────┘
```

Our crawler navigates these layers to extract content programmatically.

## Philosophy

"My 10-year-old niece can visit any website. Our crawler should too."

If a human with a browser can see it, we should be able to capture it.
The question is always: how much effort is it worth?

## Related Docs

- [docs/stateofplay.txt](../stateofplay.txt) - Current system status
- [docs/div4k.txt](../div4k.txt) - Development roadmap
- [CLAUDE.md](../../CLAUDE.md) - System constraints
