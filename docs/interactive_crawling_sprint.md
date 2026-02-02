# Interactive Crawling Sprint Plan (Parallel Agents)

Sprint Goal
-----------
Implement an interactive crawling layer (Playwright agent) that safely reveals
JS-hidden content and improves extraction quality without aggressive crawling.

Constraints
-----------
- Avoid file collisions by clearly partitioning ownership.
- Keep interactions bounded and deterministic.
- Maintain compatibility with existing `fetch/` + `crawl.py` pipeline.


Agent Split (No File Collisions)
-------------------------------

### Agent A (Codex) — Core Implementation + Integration
**Primary files (owned by Codex):**
- `cyberspace/pt1/crawling/fetch/interactive.py` (new)
- `cyberspace/pt1/crawling/fetch/__init__.py` (export + call path)
- `cyberspace/pt1/crawling/scripts/crawl.py` (flag wiring)
- `cyberspace/pt1/crawling/docs/interactive_crawling.md` (small integration notes)

**Tasks**
1) **Create `fetch/interactive.py`**
   - Implement `interactive_fetch(url, config)` using Playwright.
   - Start with baseline `fetch_source` (non-interactive).
   - If baseline fails quality gate, run interaction plan.
   - Return best extraction (highest quality + word count).

2) **Add CLI flag in `crawl.py`**
   - `--interactive` to enable interactive fetch for low-quality pages.
   - Route to `interactive_fetch` only when baseline extraction is weak.

3) **Interaction Plan v0**
   - Accordions/details: click collapsed items.
   - Tabs/carousels: click 1–3 next controls.
   - Load-more: click once or twice.
   - Stop on no-content-change.

4) **Quality Gate Integration**
   - Use existing `check_quality` and word_count deltas.
   - Stop interactions if delta < threshold.

5) **Logging**
   - Add `interaction_log` field to result (optional).
   - Record actions taken + whether content improved.


### Agent B (Claude) — Heuristics + Tests + Fixtures
**Primary files (owned by Claude):**
- `cyberspace/pt1/crawling/fetch/interaction_plan.py` (new)
- `cyberspace/pt1/crawling/eval/fixtures/interactive/` (new fixtures)
- `cyberspace/pt1/crawling/docs/interactive_crawling.md` (appendix only)

**Tasks**
1) **Interaction selectors + heuristics**
   - Build selector list (ARIA roles, class patterns, semantic HTML).
   - Provide helper functions: `find_accordions`, `find_tabs`, `find_load_more`.

2) **Content delta detection**
   - Implement `content_delta(before_html, after_html)` (word diff).
   - Provide thresholds (e.g., 20 new words = improvement).

3) **Test Fixtures**
   - Create synthetic HTML fixtures with accordions/tabs/carousels.
   - Provide before/after HTML snapshots for golden tests.

4) **Doc appendix**
   - Add a short appendix in `interactive_crawling.md` listing selectors + heuristics.


Milestones
----------
**M1 (End of Day 1)**
- `interactive_fetch` implemented (Codex)
- Selector heuristics + delta detection drafted (Claude)

**M2 (End of Day 2)**
- `crawl.py --interactive` wiring (Codex)
- Fixtures added (Claude)

**M3 (End of Day 3)**
- Integration test on one JS-heavy carrier homepage
- Updated docs + state-of-play note


Notes on Coordination
---------------------
- Codex owns integration + runtime wiring.
- Claude owns heuristic definition + fixtures.
- Avoid touching the same files in the same sprint phase to prevent conflicts.


Review Notes (2026-01-25)
-------------------------

### What's Good
- Clean file ownership - no collision risk
- Separation of concerns (runtime vs heuristics)
- Incremental milestones
- Builds on existing `fetch/` infrastructure

### Interface Contract Needed

Agent A consumes Agent B's heuristics. Define the contract upfront:

```python
# interaction_plan.py should export:

def find_expandables(page) -> list[Locator]:
    """Return accordion/details/collapse elements that are currently closed."""

def find_tabs(page) -> list[Locator]:
    """Return tab controls (not currently active)."""

def find_load_more(page) -> list[Locator]:
    """Return 'load more' / 'show more' buttons."""

def content_delta(before: str, after: str) -> int:
    """Return number of new words in after vs before."""

DELTA_THRESHOLD = 20  # Minimum new words to count as improvement
MAX_INTERACTIONS = 6  # Total interaction budget per page
```

Agent A codes against this interface. Agent B implements it.


### Async vs Sync Playwright

Decide upfront: `playwright.sync_api` or `playwright.async_api`?

- `crawl.py` is currently sync
- async would be faster for parallel interactions but adds complexity
- Recommend: **sync for v0**, refactor to async later if needed


### Quality Gate Threshold

"Baseline fails quality gate" needs a number:

```python
INTERACTIVE_THRESHOLD = 100  # words
# If baseline extraction < 100 words, try interactive
```

Or use confidence score from `fetch/quality.py`.


### M1 Scope Risk

"interactive_fetch implemented" by end of Day 1 is ambitious. Suggest:

**M1 (Day 1)**: Scaffolding
- `interactive.py` exists with placeholder
- `interaction_plan.py` exports interface (stubs ok)
- Can run `interactive_fetch(url)` and get baseline back

**M1.5 (Day 2 AM)**: First interaction
- One interaction type working (accordions)
- Delta detection working


### Test Strategy Gap

Fixtures are good, but how do we run tests?

Option A: Playwright against local HTML fixtures (spin up local server)
Option B: Mock Playwright's page object
Option C: Integration tests only (slow, against real sites)

Recommend: **Option A** - `python -m http.server` + Playwright against localhost


### Target Site for M3

Specify which JS-heavy site to test:
- J.B. Hunt homepage (known sparse extraction)
- Or create a synthetic test page with all widget types

Synthetic is more controlled, real site is more realistic. Maybe both.


### Missing: Timeout Budget

Interactive crawling is slower. Add a timeout budget:

```python
INTERACTIVE_TIMEOUT_SEC = 30  # Max time for all interactions on one page
```

If we hit the budget, return best extraction so far.


### Missing: Retry/Backoff

What if Playwright crashes mid-interaction? Need:
- Graceful fallback to baseline
- Don't retry interactions that failed
- Log failures for debugging

