# The Arms Race: Bots vs. Websites

Every website faces a choice: let everyone in, or try to filter out "bad" traffic.
This creates an ongoing arms race between bot operators and bot detectors.

## Why Block Bots?

**Legitimate reasons:**
- Prevent scraping of proprietary data (pricing, inventory)
- Stop credential stuffing attacks
- Reduce server load from aggressive crawlers
- Comply with licensing (e.g., news content)

**Less legitimate reasons:**
- Force users to visit ads
- Prevent price comparison
- Hide public information

## How Websites Detect Bots

### Level 1: User-Agent String

The simplest check. Your browser sends:
```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36
```

A basic Python script sends:
```
User-Agent: python-requests/2.28.0
```

**Detection:** Block anything that doesn't look like a real browser.

**Bypass:** Just lie about your User-Agent. Trivial.

```python
requests.get(url, headers={'User-Agent': 'Mozilla/5.0...'})
```

### Level 2: Request Patterns

Real humans:
- Click around slowly (seconds between pages)
- Follow links naturally
- Have session cookies
- Start at the homepage

Bots:
- Hit 100 pages per second
- Request URLs in alphabetical order
- No cookies
- Jump directly to deep pages

**Detection:** Rate limiting, behavioral analysis.

**Bypass:** Add delays, follow natural navigation, maintain sessions.

```python
time.sleep(random.uniform(2, 5))  # Human-like delays
```

### Level 3: JavaScript Challenges

The page loads with JavaScript that:
- Checks if JS is enabled (bots often skip JS)
- Fingerprints your browser
- Sets a cookie proving JS ran

Example (Cloudflare):
```html
<script>
  // Complex obfuscated JS that:
  // 1. Checks window.navigator properties
  // 2. Runs WebGL fingerprinting
  // 3. Sets __cf_bm cookie
  // 4. Redirects to actual content
</script>
```

**Detection:** No JS execution = no cookie = blocked.

**Bypass:** Use a real browser (Playwright, Puppeteer).

```python
from playwright.sync_api import sync_playwright
browser.new_page().goto(url)  # Executes JS
```

### Level 4: Browser Fingerprinting

Even with a real browser, they can detect automation:

```javascript
// Headless Chrome detection
navigator.webdriver  // true in automated browsers
navigator.plugins.length  // 0 in headless
window.chrome  // undefined in some headless setups

// Canvas fingerprinting
canvas.toDataURL()  // Unique per GPU/driver

// WebGL fingerprinting
gl.getParameter(gl.VENDOR)  // "Google Inc." vs real GPU
```

**Detection:** Automation flags, impossible fingerprints.

**Bypass:** Stealth plugins that patch these tells.

```python
# playwright-stealth patches navigator.webdriver, etc.
from playwright_stealth import stealth_sync
stealth_sync(page)
```

### Level 5: CAPTCHAs

When all else fails, make the user prove they're human:

- **reCAPTCHA:** "Click all the traffic lights"
- **hCaptcha:** Similar image challenges
- **Cloudflare Turnstile:** Invisible challenges

**Detection:** Definitive - only humans can solve (theoretically).

**Bypass options:**
1. CAPTCHA solving services (2captcha, Anti-Captcha) - $2-3 per 1000
2. Browser cookies from a solved session
3. Human-in-the-loop (our "monkey" system)

### Level 6: IP Reputation

Some IPs are just known bad:
- Datacenter IPs (AWS, GCP) - often blocked entirely
- IPs with abuse history
- Tor exit nodes
- Known proxy/VPN ranges

**Detection:** IP reputation databases (MaxMind, IPQualityScore).

**Bypass:** Residential proxies, rotating IPs, or just use home internet.

## Our Escalation Ladder

We implement this as an escalation strategy:

```
┌──────────────────────────────────────────────────────────────┐
│  requests        Simple HTTP - fast, cheap, works on ~40%   │
├──────────────────────────────────────────────────────────────┤
│  js              Playwright headless - handles JS/SPAs      │
├──────────────────────────────────────────────────────────────┤
│  stealth         Playwright + stealth patches - evades      │
│                  basic fingerprinting                       │
├──────────────────────────────────────────────────────────────┤
│  visible         Real visible browser window - defeats      │
│                  headless detection                         │
├──────────────────────────────────────────────────────────────┤
│  monkey          Human records a session, we replay it      │
│                  with their cookies and behavior            │
└──────────────────────────────────────────────────────────────┘
```

## The Ethics

**Legal:** Scraping public websites is generally legal (hiQ v. LinkedIn).
But terms of service violations can matter, and aggressive scraping can
be harassment or cause service disruption.

**Ethical guidelines we follow:**
1. Respect robots.txt (mostly)
2. Polite delays (3+ seconds between requests)
3. Identify ourselves in User-Agent
4. Don't overload servers
5. Only scrape public information
6. Stop if asked

## See It In Action

```bash
# Check what protection a site has
python -c "
from fetch.recon import recon_site
r = recon_site('https://www.knight-swift.com')
print(f'CDN: {r.cdn}')
print(f'WAF: {r.waf}')
print(f'Challenge detected: {r.challenge_detected}')
"

# Output:
# CDN: stackpath
# WAF: stackpath
# Challenge detected: True

# This site serves a CAPTCHA challenge page - we need the monkey system
```

## Next: What's Actually In The Page?

Once we get the HTML, how do we extract meaning from it?

→ [02_anatomy_of_html.md](02_anatomy_of_html.md)
