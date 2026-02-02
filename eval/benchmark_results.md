# Article Extraction Benchmark Results

Evaluated on ScrapingHub article-extraction-benchmark (181 articles).
Benchmark: https://github.com/scrapinghub/article-extraction-benchmark

## Results

| Config | favor_recall | extract_fallback | F1 | Precision | Recall | Accuracy |
|--------|--------------|------------------|-----|-----------|--------|----------|
| default | False | False | 0.958 | 0.938 | 0.978 | 0.293 |
| precision | False | False | 0.955 | 0.939 | 0.971 | 0.293 |
| balanced | True | False | 0.954 | 0.932 | 0.977 | 0.282 |
| recall | True | True | 0.953 | 0.931 | 0.977 | 0.276 |

## Honest Assessment

The `default` config matches trafilatura's benchmark score exactly (F1=0.958) because **it is trafilatura**. With `favor_recall=False, extract_fallback=False`, our pipeline is just a thin wrapper - 180/181 articles went straight through trafilatura with no modification.

### What trafilatura provides (F1=0.958)
- Article body extraction
- The actual extraction quality on this benchmark

### What our pipeline adds
- Fetch fallback chain: requests → playwright → stealth (not tested here - benchmark uses pre-fetched HTML)
- Extract fallback chain: trafilatura → readability → density (triggered once on 181 articles)
- Image extraction with context/classification
- Code block extraction with language detection
- Confidence scoring
- Unified interface

### What this benchmark doesn't test
- JS-heavy sites requiring playwright
- Homepages and sparse pages (where density fallback helps)
- Sites that block requests (where stealth helps)
- Image/code extraction quality

## Leaderboard Context

| Rank | Extractor | F1 | Notes |
|------|-----------|-----|-------|
| 1 | AutoExtract | 0.970 | Commercial (Zyte) |
| 2 | go-trafilatura | 0.960 | Go port |
| 3 | **trafilatura** | **0.958** | **Our primary extractor** |
| 4 | Diffbot | 0.951 | Commercial |
| 5 | newspaper4k | 0.949 | |
| 6 | readability_js | 0.947 | Mozilla (our fallback) |
| 7 | readability-lxml | 0.922 | Our fallback |
| ... | ... | ... | |
| 24 | xpath-text | 0.394 | |

## Takeaway

For article extraction, trafilatura is doing the heavy lifting. Our value is in the fallback chains and unified interface for edge cases this benchmark doesn't cover. To properly evaluate our pipeline's added value, we'd need a benchmark with:
- JS-rendered pages
- Homepages / non-article pages
- Bot-blocked sites
- Mixed content (articles + code + images)

## Date

2026-01-25
