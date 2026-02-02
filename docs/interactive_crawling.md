# Interactive Crawling (Playwright Agent Layer)

Goal
----
Add a deliberate, ordered, *interactive* crawl layer on top of `fetch/` + `crawl.py`
that can expand carousels, open accordions, paginate, and expose JS-hidden content
without aggressive bot-like behavior.

This is **not** a replacement for `fetch/`. It is a controlled **browser-driven
interaction plan** that runs only when needed (e.g., JS-heavy sites, homepages
with tabbed content, pages that render content after clicks).


What We Have Today
------------------
- `fetch/`: single-URL fetch + extract (requests → Playwright fallback), text/images/code.
- `scripts/crawl.py`: BFS crawl with link discovery and rate limiting.

Missing: structured, ethical UI interactions that reveal content beyond static
HTML (carousels, tabs, accordions, pagination, “load more”, etc.).


Design Principles
-----------------
1) **Deliberate, Ordered Interaction**
   - Never “click everything”; follow a small, deterministic plan.
   - Stop early if content stops changing (content hash / word delta).

2) **Polite + Low-Frequency**
   - Respect robots.txt (for batch). Honor request delay.
   - Limit interactions per page (e.g., max 5-10).

3) **Change-Detection Driven**
   - Only keep new content when extraction improves meaningfully.
   - Use content hashes to detect real deltas.

4) **Single-Page Scope**
   - Interactions stay on the current page. Navigation must be explicit
     (pagination is allowed if it’s on-page and expected).

5) **Fallback to Non-Interactive**
   - If interactions fail or block, return baseline fetch extraction.


Core Architecture
-----------------
```
interactive_fetch(url)
│
├─ baseline = fetch_source(url)
│
├─ if baseline quality is good: return baseline
│
├─ open Playwright page
│   ├─ wait until network idle
│   ├─ snapshot HTML + extract (fetch/extract pipeline)
│
├─ run InteractionPlan (bounded)
│   ├─ expand accordions
│   ├─ cycle carousel / tabs
│   ├─ click “load more” once or twice
│   ├─ capture new content after each action
│
└─ return best extraction (highest word_count + quality)
```


Interaction Plan (Ordered)
--------------------------
1) **Expand Accordions / Details**
   - Targets: `details`, `.accordion`, `.collapse`, `[aria-expanded]`
   - Actions: click only collapsed items (aria-expanded=false).
   - Max: 3-5 clicks.

2) **Tabs / Carousels**
   - Targets: `.tab`, `.tabs`, `.carousel`, `.slider`
   - Actions: click next tab/slide 1-3 times.
   - Max: 3-5 interactions.

3) **“Load more” / Pagination (in-page)**
   - Targets: buttons with text: "load more", "show more", "next"
   - Actions: click once or twice if new content appears.
   - Max: 2 interactions.

4) **Stop Conditions**
   - If extraction word count doesn’t increase by >10-20% after an action,
     stop further interactions of that type.
   - If content hash repeats, stop.


Quality Gate + Selection
------------------------
After each interaction:
- Run the existing `fetch/extract` pipeline on page HTML.
- Score by: word_count, link_density, boilerplate patterns.
- Keep the best extraction seen.


Data Model Additions
--------------------
Add to FetchResult (optional):
- `interaction_log`: list of actions taken
- `interaction_count`: number of UI actions
- `html_snapshots`: optional paths if archival needed

Example action log entry:
```
{"action": "click", "target": ".accordion .item:nth-child(2)", "result": "improved"}
```


Crawler Integration
-------------------
- Add flag in `crawl.py` (e.g., `--interactive`) to enable Playwright interactions.
- Use `interactive_fetch` for JS-heavy pages *only* (low baseline quality).
- Keep default crawl behavior for most pages.


Anti-Bot & Ethics
-----------------
- Respect robots.txt for batch crawling.
- Don’t solve captchas or bypass logins.
- Use a clear user agent string.
- Rate limit interactions per domain.


Implementation Phases
---------------------
1) **Phase 1: Minimal Interactions**
   - Accordions + tabs + simple load-more.
   - Keep interaction count <= 6.

2) **Phase 2: Heuristic Expansion**
   - Use DOM role attributes and ARIA to identify UI widgets.

3) **Phase 3: Page-Type-Specific Plans**
   - Homepages vs docs vs news pages.
   - Tunable action plan per site category.


Success Criteria
----------------
- Improves extraction quality for JS-heavy homepages (e.g., J.B. Hunt).
- Does not increase block rate or trigger anti-bot defenses.
- Keeps crawl time within 2–3x baseline for interactive pages.
- Maintains stable content hashes and reproducible outputs.


Current Integration (2026-01-25)
--------------------------------
- `fetch/interactive.py` implements `interactive_fetch(...)` (Playwright actions + quality gate).
- `crawl.py` exposes `--interactive` to enable the interactive layer for low-quality pages.


Implementation Notes (added 2026-01-25)
---------------------------------------

### Selector Strategy

Generic CSS selectors will miss site-specific patterns. Consider a layered approach:

```
1. ARIA roles (most reliable):
   [role="tablist"], [role="tab"], [aria-expanded], [aria-controls]

2. Common class patterns (broad coverage):
   .accordion, .collapse, .tab, .carousel, .slider, .expandable
   [class*="accordion"], [class*="collapse"], [class*="expand"]

3. Semantic HTML:
   <details>, <summary>, <dialog>

4. Text-based (last resort, high false positive):
   button:has-text("Load more"), button:has-text("Show all")
```

Playwright's `locator` API handles most of this well. Avoid XPath.


### State Detection Before/After Click

Don't just click blindly - check state first:

```python
# Before clicking
is_expanded = await el.get_attribute('aria-expanded') == 'true'
if is_expanded:
    continue  # Already open, skip

# Click and wait for content change
content_before = await page.content()
await el.click()
await page.wait_for_timeout(500)  # Let animations settle
content_after = await page.content()

if content_after == content_before:
    # Click had no effect, stop this interaction type
```


### Content Delta Detection

Word count delta is coarse. Consider:

```python
def content_delta(before_html, after_html):
    before_text = extract_text(before_html)
    after_text = extract_text(after_html)

    before_words = set(before_text.split())
    after_words = set(after_text.split())

    new_words = after_words - before_words
    return len(new_words)

# Threshold: at least 20 new words to count as "improved"
```


### Interaction Timeout + Error Handling

UI interactions are flaky. Wrap everything:

```python
async def safe_click(el, timeout_ms=3000):
    try:
        await el.click(timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception as e:
        # Element detached, page navigated, etc.
        log.debug(f"Click failed: {e}")
        return False
```


### Carousel/Slider Edge Cases

Carousels are tricky:
- Some auto-advance (need to pause first)
- Some loop infinitely (need to track seen content)
- Some lazy-load images only (no new text)

Approach:
```python
seen_hashes = set()
for i in range(max_slides):
    html = await page.content()
    h = hash(html)
    if h in seen_hashes:
        break  # Looped back to start
    seen_hashes.add(h)
    await click_next_slide()
```


### Infinite Scroll Alternative

For "load more" that's actually infinite scroll:

```python
async def scroll_and_wait(page, max_scrolls=3):
    for _ in range(max_scrolls):
        prev_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break  # No new content loaded
```


### MutationObserver for Smarter Waiting

Instead of fixed timeouts, inject a MutationObserver to detect when content actually changes:

```javascript
// Inject before interaction
window._contentChanged = false;
const observer = new MutationObserver(() => { window._contentChanged = true; });
observer.observe(document.body, { childList: true, subtree: true });

// After click, wait for change or timeout
await page.wait_for_function("window._contentChanged", timeout=3000)
```


### Page Type Heuristics

Different page types need different interaction plans:

| Page Type | Primary Interactions |
|-----------|---------------------|
| Homepage | Carousels, hero tabs, service accordions |
| Service page | Feature tabs, pricing toggles, FAQ accordions |
| News/blog | Load more, pagination |
| About | Leadership carousels, timeline expanders |
| Docs | Sidebar nav, code tabs, collapsible sections |


### Testing Strategy

Hard to unit test UI interactions. Suggest:

1. **Golden file tests**: Save before/after HTML for known sites, replay offline
2. **Synthetic test pages**: Create HTML fixtures with accordions/tabs
3. **Visual regression**: Screenshot comparison (optional, heavy)
4. **Content delta assertions**: "Interaction X should reveal Y words"


### Open Questions

1. **Shadow DOM**: Some frameworks (Salesforce, Shopify) use shadow DOM heavily.
   Playwright can pierce it with `>>` selector, but extraction pipeline may not see content.

2. **iframes**: Embedded content (maps, videos, forms) - worth extracting or skip?

3. **Cookie consent**: Many sites hide content behind consent modals.
   Click "Accept" as first interaction? Ethical considerations?

4. **Authentication walls**: "Sign up to read more" - out of scope, but common.

5. **Site-specific overrides**: Some sites will need custom interaction plans.
   Config file per domain? Or learn from failures?


Appendix: Selector Reference (from interaction_plan.py)
-------------------------------------------------------

### Accordion / Expandable Selectors

```css
/* ARIA (most reliable) */
[aria-expanded="false"]
[role="button"][aria-controls]
button[aria-expanded="false"]

/* Semantic HTML */
details:not([open]) > summary

/* Common class patterns */
.accordion:not(.active) > .accordion-header
.accordion-item:not(.active) > .accordion-trigger
.collapse-trigger:not(.active)
.expandable:not(.expanded) > .expandable-header
[class*="accordion"]:not([class*="open"]):not([class*="active"]) > [class*="header"]
[class*="collapsible"]:not([class*="open"]) > [class*="trigger"]

/* FAQ patterns */
.faq-question
.faq-item:not(.active) > .faq-header
```

### Tab Selectors

```css
/* ARIA (most reliable) */
[role="tab"][aria-selected="false"]
[role="tablist"] > [role="tab"]:not([aria-selected="true"])

/* Common class patterns */
.tab:not(.active)
.tabs > .tab-item:not(.active)
.tab-button:not(.active)
[class*="tab"]:not([class*="active"]):not([class*="content"])

/* Nav tabs */
.nav-tabs > li:not(.active) > a
.nav-tabs > .nav-item:not(.active) > .nav-link
```

### Carousel / Slider Selectors

```css
/* ARIA */
[role="tablist"][aria-label*="slide"] [role="tab"]

/* Next/prev buttons */
.carousel-next
.carousel-control-next
.slider-next
.swiper-button-next
[class*="carousel"] [class*="next"]
[class*="slider"] [class*="next"]
button[aria-label*="next slide" i]
button[aria-label*="next item" i]

/* Dots/indicators */
.carousel-indicators > li:not(.active)
.carousel-dots > button:not(.active)
.swiper-pagination-bullet:not(.swiper-pagination-bullet-active)
```

### Load More Selectors

```css
/* ARIA */
button[aria-label*="load more" i]
button[aria-label*="show more" i]

/* Text content (Playwright :has-text) */
button:has-text("Load more")
button:has-text("Show more")
button:has-text("View more")
button:has-text("See more")
a:has-text("Load more")

/* Class patterns */
.load-more
.show-more
[class*="load-more"]
[class*="show-more"]
```

### Configuration Constants

```python
DELTA_THRESHOLD = 20       # Min new words to count as improvement
MAX_INTERACTIONS = 6       # Total interaction budget per page
INTERACTIVE_MIN_WORDS = 100  # Below this, try interactive fetch
INTERACTION_TIMEOUT_MS = 3000  # Timeout per interaction
SETTLE_DELAY_MS = 500      # Wait for animations after click
INTERACTIVE_TIMEOUT_SEC = 30   # Max total time for all interactions
```

### Test Fixtures

Located in `eval/fixtures/interactive/`:

| Fixture | Tests |
|---------|-------|
| `accordion.html` | ARIA accordions, `<details>` elements |
| `tabs.html` | ARIA tabs with 4 panels |
| `carousel.html` | Carousel with next/prev and indicators |
| `load_more.html` | Load more button with 2 hidden batches |
| `combined_homepage.html` | All element types in realistic homepage |

Run fixtures locally:
```bash
cd eval/fixtures/interactive && python -m http.server 8080
# Then test against http://localhost:8080/combined_homepage.html
```
