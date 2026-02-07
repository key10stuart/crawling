# CHH: Cyborg Hardness Harness

## Purpose

Define practical techniques for focused data access, extraction, and labeling when ingesting high-friction social URLs (for example, single-post `x.com/.../status/...` targets) where fully automated crawling is unreliable.

The harness is intentionally hybrid:
- machine does queueing, state, evidence capture, and guardrails
- operator handles difficult extraction and semantic labeling

## Scope

In-scope:
- single-URL processing (no thread traversal by default)
- per-item extraction and labeling
- audit-ready evidence and provenance
- batch operation with resumable progress

Out-of-scope (MVP):
- broad graph crawl or discovery
- autonomous thread reconstruction
- model-only labeling without human review

## Technique 1: Focused Access Strategy

### Single-resource targeting
- Process canonical single-post URLs only.
- Normalize to stable pattern before work starts.
- Drop malformed rows into a repair queue.

### Adaptive fetch ladder (bounded)
- Attempt order example: `visible -> stealth -> js -> manual`.
- Use strict max attempts per URL.
- Record outcome class per attempt (success, soft block, challenge, timeout, etc.).

### Human-presence simulation
- Prefer real browser profile/session for defended platforms.
- Use natural delays and bounded pacing.
- Preserve existing politeness and retry ceilings.

### Evidence fallback
- If text extraction fails, capture screenshot and keep item actionable.
- Never mark success without either structured text or explicit manual acceptance.

## Technique 2: Queueing and Batching

### Queue model
Each row has at least:
- `url`, `status`, `attempt_count`, `last_attempt_ts`
- `assigned_to`, `lock_ts`
- `extracted_text`, `label`, `notes`
- `evidence_path`, `error_code`

### States
Recommended state machine:
- `pending`
- `in_progress`
- `done`
- `needs_review`
- `blocked`
- `skipped`

### Batch sessions
- Claim fixed-size batches (example: 25 items).
- Lock rows while active.
- Auto-checkpoint on every transition.
- Release stale locks after timeout.

## Technique 3: Operator Loop (Cyborg UX)

### Active-row workflow
1. Claim next row.
2. Open URL.
3. Capture/extract (auto if possible).
4. Route clipboard paste to active row.
5. Prompt for label/tag.
6. Save and advance.

### Clipboard routing
- Clipboard writes should only apply to the active row id.
- Require explicit confirm before commit.
- Keep prior value history for rollback.

### Navigation shortcuts
- `accept + next`
- `mark blocked + next`
- `skip + next`
- `back`
- `reopen evidence`

### Mandatory label prompt
- Require at least one controlled tag before marking `done`.
- Support `uncertain` tag to avoid forced low-quality decisions.

## Technique 4: Extraction Design

### Multi-source extraction
Store three text fields when possible:
- `text_auto` (parser/extractor output)
- `text_operator` (human correction)
- `text_final` (chosen canonical value)

### Quality checks
- Reject empty/near-empty final text.
- Flag likely truncated content.
- Detect duplicate text hashes across different URLs.

### Provenance
For each final row, preserve:
- source URL
- extraction method
- timestamp
- operator id (if manual touched)
- evidence pointer (screenshot/html path)

## Technique 5: Labeling Strategy

### Controlled vocabulary first
- Use a short tag taxonomy with explicit definitions.
- Keep free-text notes secondary.

### Two-pass labeling
- Pass 1: fast triage labels (high recall).
- Pass 2: review labels for precision.

### Confidence and review
- Add `label_confidence` and `review_state`.
- Route low-confidence or ambiguous items to review queue.

## Technique 6: Reliability and Safety

### Idempotency
- Upsert by canonical URL + stable id (tweet id).
- Keep append-only attempt log separate from latest state table.

### Crash safety
- Persist after each state transition.
- On restart, resume from `in_progress` locks owned by current operator only.

### Observability
Track at minimum:
- throughput (items/hour)
- success rate by method
- blocked/challenge rate
- manual intervention rate
- review rework rate

## Technique 7: Implementation Shape

### Recommended MVP stack
- Local harness (Python CLI/TUI) + browser opener.
- CSV or SQLite backend (SQLite preferred for locking/history).
- Existing crawler components reused for capture/extract when possible.

### Why not extension-first
A browser extension can help later, but MVP should avoid extension complexity:
- auth/session edge cases
- browser API maintenance
- harder reproducibility than local queue engine

## Suggested Output Tables

### `target_queue` (latest state)
- `item_id`, `url`, `canonical_id`, `status`, `assigned_to`, `lock_ts`
- `attempt_count`, `last_method`, `last_error`, `last_attempt_ts`
- `text_final`, `label`, `label_confidence`, `review_state`
- `evidence_path`, `updated_at`

### `target_attempts` (append-only)
- `attempt_id`, `item_id`, `started_at`, `ended_at`, `method`
- `outcome`, `error_code`, `text_auto`, `evidence_path`, `operator`

### `target_reviews` (optional)
- `review_id`, `item_id`, `reviewer`, `decision`, `notes`, `reviewed_at`

## Rollout Plan

1. Build queue normalizer and canonicalizer.
2. Implement batch claim/lock + active-row loop.
3. Add clipboard commit + tag prompt + next-item automation.
4. Integrate capture/extract + screenshot fallback.
5. Add review queue and metrics dashboard/report.

## Success Criteria

- High-friction URLs are processed with bounded retries.
- Every accepted row has provenance and evidence.
- Manual effort is focused only where automation fails.
- Progress is measurable, resumable, and auditable.
