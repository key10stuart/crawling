# Anatomy of HTML: Structure and Semantics

HTML isn't just random tags. There's a grammar, a structure, and meaning
embedded in how pages are built.

## The Document Tree

HTML is a tree structure:

```
                        html
                       /    \
                    head    body
                   /    \      \
               title  meta    ...
```

Every element has:
- A **tag** (what it is): `<div>`, `<p>`, `<nav>`
- **Attributes** (properties): `class="hero"`, `id="main"`
- **Content** (text or child elements)

## Semantic HTML5

Modern HTML has meaningful tags that tell you what content IS:

```html
<header>     <!-- Top of page: logo, primary nav -->
<nav>        <!-- Navigation links -->
<main>       <!-- Primary content (one per page) -->
<article>    <!-- Self-contained content piece -->
<section>    <!-- Thematic grouping -->
<aside>      <!-- Sidebar, tangential content -->
<footer>     <!-- Bottom: copyright, secondary links -->
```

**Why this matters for extraction:**

```
┌─────────────────────────────────────────────────────────┐
│ <header>  Logo, Search, Account links                   │
├─────────────────────────────────────────────────────────┤
│ <nav>  Services | About | Careers | Contact             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ <main>                                                  │
│   <article>                                             │
│     <h1>Driving the Future</h1>                         │
│     <p>Lorem ipsum...</p>  ← THIS IS THE CONTENT        │
│   </article>                                            │
│                                                         │
├───────────────────────────────┬─────────────────────────┤
│ <aside>                       │                         │
│   Quick Links                 │                         │
│   Related Articles            │                         │
└───────────────────────────────┴─────────────────────────┤
│ <footer>  © 2024 | Privacy | Terms                      │
└─────────────────────────────────────────────────────────┘
```

Our extractor tags blocks by their semantic container:
- `nav_block` - navigation content
- `hero_block` - prominent top section
- `main_block` - primary content
- `footer_block` - footer content

## The Reality: Div Soup

Unfortunately, many sites don't use semantic HTML:

```html
<div class="header-wrapper">
  <div class="nav-container">
    <div class="nav-inner">
      <ul class="nav-list">
        ...
      </ul>
    </div>
  </div>
</div>
<div class="main-content-area">
  <div class="content-wrapper">
    <div class="content-inner">
      <div class="text-block">
        <p>Actual content here</p>
      </div>
    </div>
  </div>
</div>
```

Same structure, but with meaningless `<div>` tags. Now we need heuristics:
- Classes with "nav", "header", "footer" → probably that section
- Large text blocks → probably content
- Lots of links → probably navigation

## Content vs. Chrome

**Chrome** (not the browser): The UI wrapper around content.
- Headers, footers, sidebars
- Navigation menus
- Cookie banners, popups
- Ads, newsletter signups

**Content**: The actual information you came for.
- Article text
- Product descriptions
- Service explanations

The challenge: extract content, ignore chrome.

### The Boilerplate Problem

Most pages on a site share ~80% of their HTML:
- Same header/footer
- Same sidebar
- Same scripts/styles

Only ~20% is unique content. Extraction algorithms must separate these.

## How We Extract

### Method 1: Trafilatura

Academic-grade extraction library. Uses:
- DOM structure analysis
- Text density scoring
- Language detection
- Date/author extraction

```python
import trafilatura
result = trafilatura.extract(html)
# Returns clean article text
```

### Method 2: Readability

Mozilla's algorithm (used in Firefox Reader View):
- Scores elements by text/link ratio
- Finds the "content" container
- Strips everything else

```python
from readability import Document
doc = Document(html)
content = doc.summary()
```

### Method 3: Our Tagged Block Approach

Instead of throwing away chrome, we label everything:

```python
{
    "tagged_blocks": [
        {"block_type": "nav_block", "content": "Services About Careers"},
        {"block_type": "hero_block", "content": "Driving the Future"},
        {"block_type": "main_block", "content": "Lorem ipsum..."},
        {"block_type": "footer_block", "content": "© 2024 Privacy Terms"}
    ],
    "main_content": {
        "text": "Lorem ipsum...",
        "word_count": 450
    }
}
```

This preserves structure for later analysis while still identifying main content.

## Structured Data: JSON-LD

Smart websites embed machine-readable data:

```html
<script type="application/ld+json">
{
  "@type": "Organization",
  "name": "J.B. Hunt Transport",
  "url": "https://www.jbhunt.com",
  "logo": "https://www.jbhunt.com/logo.png",
  "address": {
    "@type": "PostalAddress",
    "addressLocality": "Lowell",
    "addressRegion": "AR"
  }
}
</script>
```

This is a gift for extractors - structured data with clear meaning.

## Exercise: Inspect Any Page

1. Open your browser's Developer Tools (F12)
2. Go to Elements tab
3. Look at the structure:
   - Is it semantic (`<nav>`, `<main>`) or div soup?
   - Where is the actual content?
   - How much is chrome vs. content?

4. Check for JSON-LD:
   - Search for `application/ld+json` in the HTML
   - What structured data is embedded?

## Next: Lazy Loading and Interactive Content

Modern pages don't load everything at once. Content appears as you scroll,
click, or wait.

→ [03_dynamic_content.md](03_dynamic_content.md)
