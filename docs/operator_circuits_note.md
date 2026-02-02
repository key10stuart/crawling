# Operator/Circuit Uses for Crawling

> **Status**: Planning notes for Div5. Current work through Div3 (comp packages monitoring).

This crawler already treats LLM work as optional enrichment layered on top of deterministic extraction. Operator + circuit wiring can make that layer safer, cheaper, and more auditable.

## Potential Uses

- **LLM extraction as operators**: wrap each LLM task (comp summary, page classification, change summary, competitive summary, corpus Q/A) as dedicated operators so prompts, models, and output contracts are centralized and versioned.
- **Batch enrichment circuits**: a circuit that runs lightweight extractors first, then selectively invokes operators on high-signal pages (e.g., comp-heavy, recruiting, or portal pages). This keeps LLM calls sparse and targeted.
- **Provenance and traceability**: circuits can record inputs/outputs per operator invocation (text hashes, model, prompt version), aligning with the crawler’s “trustable outputs” principle.
- **Caching and dedupe**: circuits can memoize on content hash so repeated crawls don’t re-run LLM ops for unchanged pages.
- **Change detection pipeline**: a circuit that compares prior vs current page text and runs a change-summary operator only when diffs exceed a threshold.
- **Schema validation gates**: operators can enforce JSON schemas and confidence thresholds before merging LLM results into site JSON.
- **Provider portability**: route all LLM calls through a single operator interface so Anthropic/OpenAI/Gemini swaps don’t touch crawler code.
- **Cost/rate limiting**: circuits can enforce per-run budgets and concurrency limits while preserving crawl throughput.

## Fit with Existing Principles

- Keep LLM work **optional** and **layered** behind deterministic extraction.
- Preserve **structure and provenance** by storing operator metadata alongside extracted fields.
- Favor **reproducibility**: prompt + model versioning in operator metadata.

---

## Core Principle: Mechanical First

When lower-resource or purely mechanical routes are available, always prefer them.

### Evaluation Tiers

| Tier | Method | Cost | Deterministic | Examples |
|------|--------|------|---------------|----------|
| 0 | Mechanical | $0 | ✅ | Regex, keyword lookup, set operations, difflib |
| 1 | Lightweight NLP | $0 | ✅ | Keyword density, lexicon sentiment, TF-IDF, n-gram similarity |
| 2 | LLM | $$$ | ❌ | Understanding, synthesis, judgment, Q&A |

### What We Already Have (Tier 0/1)

In `fetch/nlp.py`:
- `extract_money()` — regex for $X, X cpm, $X/hr
- `extract_dates()` — regex for date patterns
- `extract_locations()` — regex for US states
- `detect_comp_keywords()` — keyword lookup by category
- `detect_urgency()` — regex patterns
- `classify_audience()` — keyword density scoring
- `score_comp_mention()` — context-based confidence
- `simple_sentiment()` — lexicon-based pos/neg
- `text_similarity()` — n-gram Jaccard

### Mechanical Metrics to Add (from OC pattern)

- `salient_recall(source, output)` — % of top terms preserved
- `novel_numbers(source, output)` — hallucination detection
- `shannon_entropy(text)` — information density
- `extract_salient_terms(text)` — top non-stopwords

---

## When LLM is the Right Tool (Not a Fallback)

LLMs aren't just fallbacks for failed mechanical extraction. They're the primary tool for tasks that require **understanding**, not pattern matching.

### Core LLM Tasks

| Task | Why Mechanical Fails |
|------|----------------------|
| **Semantic understanding** | "Is this about driver pay or shipping rates?" requires reading comprehension |
| **Free-form Q&A** | "Which carriers emphasize work-life balance?" — arbitrary user questions |
| **Synthesis/Narrative** | Turning structured data into executive summary with appropriate emphasis |
| **Loss accounting** | Identifying what meaning was lost in compression, not just what words changed |
| **Ambiguity resolution** | "Up to $90K" — understanding ceiling vs typical, conditions attached |
| **Semantic comparison** | "How does JB Hunt position vs Schneider?" — value prop, not word diff |
| **Judgment calls** | "Is this change significant enough to alert?" — context-dependent |
| **Cross-document reasoning** | Connecting info across pages to draw conclusions |

### The Right Mental Model

```
MECHANICAL                  LLM
──────────                  ───
Pattern matching            Understanding
Extraction                  Interpretation
Measurement                 Judgment
Validation                  Reasoning
Counting                    Synthesis
Diffing (text)              Comparing (meaning)
Filtering                   Deciding

"What's there"              "What does it mean"
```

---

## Operator Taxonomy

### Extraction Operators

| Operator | Method | Output |
|----------|--------|--------|
| `extract_money` | Mechanical | `[{amount, unit, context}, ...]` |
| `extract_comp_structured` | LLM | `{cpm_range, sign_on, benefits, conditions, ...}` |
| `extract_locations` | Mechanical | `[state, ...]` |
| `extract_service_coverage` | LLM | `[{city, state, type, hours}, ...]` |
| `extract_pricing` | LLM | `{fuel_surcharge, accessorials, rate_type}` |
| `extract_announcements` | LLM | `[{date, type, summary}, ...]` |

### Classification Operators

| Operator | Method | Output |
|----------|--------|--------|
| `classify_page_type` | Mechanical (URL + keywords) | `recruiting | services | pricing | news` |
| `classify_audience` | Lightweight (keyword density) | `drivers | owner_ops | carriers | shippers` |
| `classify_intent` | LLM | `attract | inform | convert | support` |
| `classify_change_significance` | LLM | `{significant: bool, reason: str}` |

### Comparison Operators

| Operator | Method | Output |
|----------|--------|--------|
| `diff_text` | Mechanical (difflib) | `{added, removed, modified}` |
| `content_delta` | Mechanical (word sets) | `int` (new word count) |
| `summarize_changes` | LLM | prose summary of what changed |
| `compare_carriers` | LLM | semantic comparison |

### Validation Operators

| Operator | Method | Output |
|----------|--------|--------|
| `validate_numbers` | Mechanical | novel numbers not in source |
| `salient_recall` | Mechanical | % of key terms preserved |
| `validate_claims` | LLM | `{supported, unsupported, contradicted}` |

### Synthesis Operators

| Operator | Method | Output |
|----------|--------|--------|
| `aggregate` | Mechanical | ranges, averages, counts |
| `rank` | Mechanical | sorted by metric |
| `loss_notes` | LLM | what was omitted from compression |
| `synthesize_report` | LLM | narrative from structured data |
| `answer_question` | LLM | response with citations |

---

## Hybrid Pattern: Mechanical Scaffolding + LLM Core

Best approach for complex extraction:

```
page_text
    │
    ▼
┌─────────────────────────────────────┐
│ 1. MECHANICAL PRE-PROCESSING        │  ← cheap, fast
│    extract_money()                  │
│    detect_comp_keywords()           │
│    classify_audience()              │
└─────────────────┬───────────────────┘
                  │ hints
                  ▼
┌─────────────────────────────────────┐
│ 2. LLM CORE TASK                    │  ← understanding
│    llm_extract_comp(text, hints)    │
└─────────────────┬───────────────────┘
                  │ structured output
                  ▼
┌─────────────────────────────────────┐
│ 3. MECHANICAL POST-VALIDATION       │  ← catches hallucinations
│    novel_numbers()                  │
│    salient_recall()                 │
│    schema_compliance()              │
└─────────────────────────────────────┘
```

The LLM does the **core reasoning** (understanding compensation structure).
Mechanical methods handle **scaffolding** (pre-extraction hints, validation).

---

## Circuits for Crawling Workflows

### Page Enrichment Circuit

Runs on every crawled page:

```
page → classify_page_type (mechanical)
           │
           ├─ recruiting → extract_comp (hybrid) → classify_audience
           ├─ services  → extract_coverage (LLM) → extract_tech
           ├─ pricing   → extract_pricing (LLM)
           ├─ news      → extract_announcements (LLM)
           └─ other     → lightweight NLP only
           │
           ▼
       detect_features (mechanical)
           │
           ▼
       enriched page JSON
```

### Change Detection Circuit

```
new_crawl + previous_crawl
           │
           ▼
       diff_text (mechanical)
           │
           ├─ delta < threshold → log only
           │
           └─ delta >= threshold
                   │
                   ▼
           classify_change_significance (LLM)
                   │
                   ├─ not significant → log
                   │
                   └─ significant
                           │
                           ▼
                   summarize_changes (LLM)
                           │
                           ▼
                       alert
```

### Competitive Summary Circuit

```
corpus of site JSONs
           │
           ▼
       aggregate (mechanical) → market ranges, counts
           │
           ▼
       rank (mechanical) → top N by metric
           │
           ▼
       trend (mechanical) → vs previous period
           │
           ▼
       synthesize_report (LLM) → executive summary
```

### Question Answering Circuit

```
user_question
           │
           ▼
       parse_intent (LLM) → {field, filter, aggregation}
           │
           ▼
       retrieve_relevant (mechanical) → matching pages/sites
           │
           ▼
       extract_evidence (LLM) → quotes + URLs
           │
           ▼
       synthesize_answer (LLM) → response with citations
```

### Tiered Extraction Circuit

```
page_text
           │
           ▼
       mechanical_extract()
           │
           ▼
       score_confidence (mechanical)
           │
           ├─ confidence >= threshold → return mechanical
           │
           └─ confidence < threshold
                   │
                   ▼
               llm_extract()
                   │
                   ▼
               validate_mechanical() ← gates!
                   │
                   ▼
               return validated
```

---

## Implementation Notes

### Operator Contract Shape

```python
@dataclass
class OperatorConfig:
    model: str = "claude-haiku-4-20250514"
    max_tokens: int = 1000
    temperature: float = 0.3
    system_prompt_id: str = "comp:extract_v1"  # element reference
    budget_chars: int | None = None
    invariants: list[str] = field(default_factory=list)  # must preserve
    output_schema: dict | None = None  # JSON schema for validation

@dataclass
class OperatorResult:
    output: dict | str
    method: str  # 'mechanical' | 'llm' | 'hybrid'
    model: str | None
    prompt_id: str | None
    input_hash: str
    output_hash: str
    metrics: dict  # salient_recall, novel_numbers, etc.
    confidence: float
```

### Provenance Tracking

Every LLM invocation records:
- Input content hash
- Output content hash
- Model + prompt version
- Mechanical metrics on output
- Timestamp

This enables:
- Reproducibility audits
- Regression detection when prompts change
- Cost tracking per operator

### Cost Control

```python
class CircuitBudget:
    max_llm_calls: int = 100
    max_tokens: int = 50000
    max_cost_usd: float = 1.00

    def can_invoke(self, estimated_tokens: int) -> bool:
        ...
```

Circuits respect budgets — mechanical fallback when budget exhausted.
