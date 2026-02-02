# Interactive Crawling Test Fixtures

Synthetic HTML pages for testing interactive crawling heuristics.

## Fixtures

| File | Elements | Content Hidden |
|------|----------|----------------|
| `accordion.html` | ARIA accordions, `<details>` | ~150 words in 5 collapsed sections |
| `tabs.html` | ARIA tabs | ~200 words across 4 tab panels |
| `carousel.html` | Carousel with next/prev, indicators | ~250 words across 4 slides |
| `load_more.html` | Load more button | ~200 words in 2 hidden batches |
| `combined_homepage.html` | All of the above | ~400 words total hidden |

## Running Tests

Start a local server:

```bash
cd /Users/Shared/projects/cyberspace/pt1/crawling/eval/fixtures/interactive
python -m http.server 8080
```

Then run interactive fetch against `http://localhost:8080/combined_homepage.html`.

## Expected Results

### combined_homepage.html

**Baseline extraction** (no interactions):
- Hero text, visible tab panel (Truckload), first testimonial, visible FAQ questions, visible news cards
- Approximate: ~300 words

**After interactions**:
- All tab panels revealed: +150 words
- All FAQ answers revealed: +200 words
- All testimonials cycled: +100 words
- Load more clicked: +100 words
- **Total: ~850 words**

## Content Delta Thresholds

Each interaction should reveal at least 20 new words to count as "improved":

| Interaction | New Words Expected |
|-------------|-------------------|
| Click accordion | 30-50 |
| Switch tab | 40-60 |
| Carousel next | 20-40 |
| Load more | 50-100 |
