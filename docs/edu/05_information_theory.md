# Information Theory: Signal vs. Noise

The web is mostly noise. Your job as an extractor is to find the signal.

## The Content Density Problem

A typical corporate webpage:

```
Total HTML: 150 KB
├── Scripts:     60 KB (40%)  ← Noise
├── Styles:      20 KB (13%)  ← Noise
├── Navigation:  15 KB (10%)  ← Chrome
├── Headers:     10 KB (7%)   ← Chrome
├── Footers:     10 KB (7%)   ← Chrome
├── Ads/Popups:  15 KB (10%)  ← Noise
└── Content:     20 KB (13%)  ← SIGNAL
```

**87% of the page is not content.** This is the extraction problem.

## Boilerplate: The Repeated Noise

Visit 10 pages on jbhunt.com. What's the same on every page?

```
┌─────────────────────────────────────────────────────────┐
│ [Logo] Services About Careers Investors Contact [Search]│  ← Same
├─────────────────────────────────────────────────────────┤
│                                                         │
│                  UNIQUE CONTENT HERE                    │  ← Different
│                                                         │
├─────────────────────────────────────────────────────────┤
│ © 2024 J.B. Hunt | Privacy | Terms | Accessibility     │  ← Same
└─────────────────────────────────────────────────────────┘
```

**Boilerplate ratio**: The percentage of a page that's repeated across the site.
Corporate sites often have 70-80% boilerplate.

## Text Density Scoring

One heuristic: **text-to-tag ratio**

```python
def text_density(element):
    text_length = len(element.get_text())
    tag_count = len(element.find_all())
    return text_length / (tag_count + 1)
```

High density = likely content (long text, few tags)
Low density = likely chrome (short text, many nested tags)

```html
<!-- Low density (navigation) -->
<nav>
  <ul>
    <li><a href="/a">A</a></li>
    <li><a href="/b">B</a></li>
    <li><a href="/c">C</a></li>
  </ul>
</nav>
<!-- 3 chars text, 7 tags = 0.4 density -->

<!-- High density (content) -->
<article>
  <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.
  Sed do eiusmod tempor incididunt ut labore et dolore magna
  aliqua. Ut enim ad minim veniam...</p>
</article>
<!-- 200 chars text, 2 tags = 100 density -->
```

## Link Density

Another signal: **link density**

```python
def link_density(element):
    text_length = len(element.get_text())
    link_text_length = sum(len(a.get_text()) for a in element.find_all('a'))
    return link_text_length / (text_length + 1)
```

High link density = navigation, blogroll, footer
Low link density = content (prose with occasional links)

## The Extraction Cascade

We try multiple methods, from most sophisticated to simplest:

```
1. Trafilatura (ML-based)
   │
   ├─ Success? → Use it
   │
   └─ Fail? ↓

2. Readability (heuristic)
   │
   ├─ Success? → Use it
   │
   └─ Fail? ↓

3. Density scorer (basic)
   │
   └─ Always produces something (may be garbage)
```

## Semantic Signals

Beyond density, we look for meaning:

**Positive signals (likely content):**
- `<article>`, `<main>` tags
- `itemprop="articleBody"`
- Classes: `content`, `post`, `entry`, `article`
- Long paragraphs with punctuation

**Negative signals (likely chrome):**
- `<nav>`, `<aside>`, `<footer>` tags
- Classes: `nav`, `menu`, `sidebar`, `widget`, `ad`
- Cookie banners, modals
- Lists of links

## Structured Data: The Cheat Code

Sometimes websites tell you what's important:

```html
<script type="application/ld+json">
{
  "@type": "Article",
  "headline": "J.B. Hunt Reports Q4 Earnings",
  "articleBody": "J.B. Hunt Transport Services reported...",
  "datePublished": "2024-01-15",
  "author": {"@type": "Person", "name": "John Smith"}
}
</script>
```

JSON-LD is structured data embedded in the page. When present, it's the
clearest signal of what content matters.

## Our Approach: Tag Everything

Instead of throwing away "noise," we label it:

```python
{
  "tagged_blocks": [
    {"block_type": "nav_block", "content": "...", "word_count": 50},
    {"block_type": "hero_block", "content": "...", "word_count": 30},
    {"block_type": "main_block", "content": "...", "word_count": 450},
    {"block_type": "footer_block", "content": "...", "word_count": 80}
  ],
  "main_content": {
    "text": "...",
    "word_count": 450,
    "method": "trafilatura"
  }
}
```

Why keep chrome?
- Navigation reveals site structure
- Footer has contact info, legal entities
- Headers show branding, CTAs
- All of it is signal for different questions

## Compression and Entropy

Information theory concept: **entropy** measures information content.

```
"the the the the the the"  → Low entropy (repetitive)
"J.B. Hunt Transport Inc"  → High entropy (unique info)
```

When we count "terms" in content, we're measuring unique, meaningful tokens:

```python
TRACKED_TERMS = [
    "intermodal", "truckload", "ltl", "drayage",
    "3pl", "supply chain", "logistics",
    "ai", "automation", "visibility"
]
```

A page mentioning many unique tracked terms = high information value.

## Quality Scoring

We score extractions:

```python
{
  "completeness": 4.2,     # How much content vs boilerplate?
  "accuracy": 3.8,         # Does extracted match visible?
  "structure": 4.5,        # Are sections properly tagged?
  "overall": 4.0           # Weighted average
}
```

These scores help us:
- Identify extraction failures
- Compare methods
- Prioritize sites for re-crawling

## The Fundamental Tradeoff

**Precision vs. Recall**

```
High Precision: Only extract what you're SURE is content
               → Miss some good content
               → Never include junk

High Recall:   Extract everything that MIGHT be content
               → Get all the content
               → Include some junk

We favor recall: extract everything, tag it, filter later.
```

## Exercise: Score a Page Yourself

1. Visit a company website
2. Mentally highlight what's "content" vs "chrome"
3. Estimate the content ratio
4. Check our extraction:
   ```bash
   python scripts/crawl.py --domain example.com --depth 0
   cat corpus/sites/example_com.json | python -c "
   import json,sys
   d=json.load(sys.stdin)
   p=d['pages'][0]
   print(f'Word count: {p[\"main_content\"][\"word_count\"]}')
   print(f'Blocks: {len(p[\"tagged_blocks\"])}')
   "
   ```
5. How close was the automatic extraction to your mental model?

## Summary

The web is noisy. Extraction is about:
1. **Detection** - Find the content containers
2. **Separation** - Distinguish content from chrome
3. **Labeling** - Tag everything by role
4. **Scoring** - Measure quality and completeness

Our philosophy: **Tag everything, discard nothing, analyze later.**

---

This concludes the educational series. You now understand:
- What websites are (URLs → HTTP → HTML → rendered pixels)
- The arms race between bots and detection
- How HTML encodes structure and meaning
- Dynamic content and why JavaScript matters
- The infrastructure stack behind websites
- How to extract signal from noise

Happy crawling.
