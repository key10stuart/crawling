# Dynamic Content: The Page That Keeps Changing

In the old web, you requested a URL and got HTML. Done.

Modern pages are alive - content loads, changes, and reacts as you interact.

## Types of Dynamic Content

### 1. Lazy Loading

Images and content that load only when visible:

```html
<!-- Not loaded until you scroll down -->
<img data-src="/heavy-image.jpg" class="lazy">

<!-- Intersection Observer triggers load when visible -->
<script>
  observer.observe(img);
  // When visible: img.src = img.dataset.src
</script>
```

**Problem for crawlers:** If you don't scroll, you don't see the content.

**Our solution:** `scroll_to_bottom()` in lazy_expander.py

```python
def scroll_to_bottom(page):
    while not at_bottom:
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(0.5)  # Let content load
```

### 2. Infinite Scroll

Content that keeps loading as you scroll (Twitter, LinkedIn):

```
Scroll → API call → More content added → Scroll → API call → ...
```

**Problem:** Where does the page "end"?

**Our approach:** Scroll until height stabilizes (3 checks with no change).

### 3. Accordions and Tabs

Content hidden behind clicks:

```html
<div class="accordion">
  <button>Driver Benefits ▼</button>
  <div class="panel" style="display: none">
    <!-- Hidden until clicked -->
    <p>Health insurance, 401k, paid time off...</p>
  </div>
</div>
```

**Problem:** Content exists in DOM but isn't visible/indexable.

**Our solution:** `expand_accordions()` clicks expandable elements

```python
selectors = [
    '[class*="accordion"]',
    '[class*="expand"]',
    '[class*="collapse"]',
    'details:not([open])',
]
for el in page.query_selector_all(selectors):
    el.click()
```

### 4. Client-Side Routing (SPAs)

Single Page Applications load once, then JavaScript handles navigation:

```
/services         → JS updates DOM, URL changes
/about           → JS updates DOM, URL changes
/contact         → JS updates DOM, URL changes
```

The server never sees these requests - it all happens in the browser.

**Problem:** Traditional crawlers only see the initial page.

**Our approach:**
1. Detect SPA via recon (framework detection)
2. Use Playwright to render
3. Follow links and let JS handle routing

### 5. API-Driven Content

The page fetches data from APIs and renders it:

```javascript
fetch('/api/services')
  .then(r => r.json())
  .then(services => {
    services.forEach(s => {
      document.getElementById('services').innerHTML +=
        `<div>${s.name}: ${s.description}</div>`;
    });
  });
```

**Problem:** Content doesn't exist in initial HTML.

**Our approach:** Wait for network idle (no pending requests for 500ms).

```python
page.goto(url, wait_until='networkidle')
```

## The Timing Problem

When is a page "done" loading?

```
Time 0ms:    Initial HTML received
Time 100ms:  CSS loaded, basic layout
Time 500ms:  Main JavaScript loaded
Time 1000ms: API calls started
Time 2000ms: API responses received
Time 2500ms: DOM updated with content
Time 3000ms: Images lazy-loaded
Time ???:    Infinite scroll content...
```

There's no perfect answer. We use heuristics:

```python
# Wait strategies
page.goto(url, wait_until='domcontentloaded')  # HTML parsed
page.goto(url, wait_until='load')              # All resources
page.goto(url, wait_until='networkidle')       # No requests for 500ms

# Plus manual waits
page.wait_for_selector('main article')         # Wait for specific element
page.wait_for_timeout(2000)                    # Just wait 2 seconds
```

## Interaction Logging

When we expand content, we log what we did:

```python
{
    "interaction_log": [
        {"action": "scroll", "position": 1500, "new_height": 4200},
        {"action": "click", "selector": ".accordion-btn", "revealed": 342},
        {"action": "scroll", "position": 3000, "new_height": 4200},
    ],
    "expansion_stats": {
        "scroll_steps": 8,
        "elements_expanded": 3,
        "content_revealed_chars": 1247
    }
}
```

This creates an audit trail: what did we do to get this content?

## Exercise: Watch Network Traffic

1. Open Developer Tools → Network tab
2. Load a modern site (linkedin.com, twitter.com)
3. Watch requests fire as you scroll
4. Filter by XHR/Fetch to see API calls
5. Click on a request to see the JSON data

You're watching the page "build itself" from API responses.

## Next: The Infrastructure Layer

What's actually running when you visit a website? Servers, databases,
CDNs, containers...

→ [04_infrastructure.md](04_infrastructure.md)
