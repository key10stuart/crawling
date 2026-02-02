# Access Layer SLOs

Service Level Objectives for the adaptive access layer.

## Overview

These SLOs define acceptable performance for the crawl access system. They guide alerting thresholds, inform capacity planning, and establish quality gates for releases.

---

## SLO 1: Tier-1 Crawl Success Rate

**Target:** ≥95% of Tier-1 carriers crawlable by some method

**Definition:**
- Denominator: Total Tier-1 carriers in seeds
- Numerator: Tier-1 carriers with successful crawl (≥1 page, ≥100 words)

**Measurement:**
```bash
# After a full tier-1 crawl run:
python scripts/access_report.py --tier 1 --metric success_rate
```

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | ≥95% | Normal |
| Yellow | 90-95% | Investigate new blocks |
| Red | <90% | Incident - immediate investigation |

**Exclusions:**
- Sites marked `manual_only` in seeds (already known blocked)
- Sites with `skip: true` in fetch config

---

## SLO 2: Block Rate

**Target:** <10% of crawl attempts result in hard blocks

**Definition:**
- Hard block: 403, CAPTCHA page, or challenge that cannot be bypassed
- Soft block: Rate limit (429) that resolves with backoff - not counted

**Measurement:**
```bash
python scripts/access_report.py --metric block_rate
```

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | <10% | Normal |
| Yellow | 10-20% | Review strategy selection |
| Red | >20% | Incident - possible IP/fingerprint burn |

---

## SLO 3: Method Efficiency

**Target:** ≥60% of successful crawls use HTTP-only (no Playwright)

**Rationale:** Playwright is expensive (CPU, memory, time). If too many sites require JS/stealth, investigate whether recon is over-escalating.

**Definition:**
- Numerator: Successful crawls using `method=http`
- Denominator: All successful crawls

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | ≥60% | Normal |
| Yellow | 40-60% | Review JS detection tuning |
| Red | <40% | Investigate over-escalation |

---

## SLO 4: Crawl Freshness

**Target:** 100% of Tier-1 sites crawled within 30 days

**Definition:**
- For each Tier-1 carrier, check `crawl_start` timestamp
- Site is "stale" if last crawl >30 days ago

**Measurement:**
```bash
python scripts/seed_coverage.py --tier 1 --max-age 30d
```

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | 100% fresh | Normal |
| Yellow | 1-3 stale | Schedule catch-up crawl |
| Red | >3 stale | Incident - crawl pipeline broken |

---

## SLO 5: Monkey Queue Depth

**Target:** Monkey queue depth <5 sites for >48 hours

**Rationale:** Sites in monkey queue need human attention. If queue grows, human processing isn't keeping up.

**Definition:**
- Count of sites in `~/.crawl/monkey_queue.json` with `added` >48h ago

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | 0-2 aged items | Normal |
| Yellow | 3-5 aged items | Schedule monkey session |
| Red | >5 aged items | Backlog alert - prioritize processing |

---

## SLO 6: Content Quality

**Target:** ≥70% average score on human evaluation

**Definition:**
- Based on `scripts/eval_interactive.py` results
- Score = (coverage + precision + recency) / max_possible

**Measurement:**
```bash
# After eval run:
cat eval/interactive_*.json | jq '.overall.avg_pct'
```

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | ≥70% | Normal |
| Yellow | 60-70% | Review extraction quality |
| Red | <60% | Incident - extraction regression |

**Frequency:** Run human eval monthly on 10-20 site sample.

---

## SLO 7: Crawl Duration

**Target:** Tier-1 full crawl completes in <4 hours

**Rationale:** Predictable runtime enables scheduling. If crawls take too long, parallelism or strategy may need tuning.

**Definition:**
- Wall-clock time from crawl start to completion
- Tier-1 only (~24 sites), depth 2, parallel jobs 4

**Thresholds:**
| Level | Value | Action |
|-------|-------|--------|
| Green | <4h | Normal |
| Yellow | 4-6h | Review slow sites |
| Red | >6h | Investigate bottlenecks |

---

## Alerting Integration

### Recommended Alert Rules

```yaml
# alerts.yaml (example format)
alerts:
  - name: tier1_success_rate_low
    metric: tier1_crawl_success_rate
    threshold: < 0.90
    severity: critical
    runbook: docs/access_runbook.md#tier-1-success-rate-drop

  - name: block_rate_high
    metric: crawl_block_rate
    threshold: > 0.20
    severity: critical
    runbook: docs/access_runbook.md#high-block-rate

  - name: monkey_queue_backlog
    metric: monkey_queue_aged_count
    threshold: > 5
    severity: warning
    runbook: docs/access_runbook.md#monkey-queue-backlog

  - name: crawl_stale
    metric: tier1_stale_count
    threshold: > 3
    severity: warning
    runbook: docs/access_runbook.md#stale-crawls
```

---

## Dashboard Metrics

Recommended metrics to surface in access dashboard:

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| Tier-1 success rate | access_report.py | Per crawl run |
| Block rate | access_report.py | Per crawl run |
| Method distribution | access_report.py | Per crawl run |
| Monkey queue depth | monkey_queue.json | Real-time |
| Sites by last crawl age | corpus/sites/*.json | Daily |
| Avg words per site | corpus/sites/*.json | Per crawl run |
| Human eval score | eval/interactive_*.json | Monthly |

---

## Review Cadence

| Review | Frequency | Participants |
|--------|-----------|--------------|
| SLO dashboard check | Daily | On-call |
| Block rate analysis | Weekly | Crawl team |
| Human eval run | Monthly | QA + Crawl team |
| SLO threshold review | Quarterly | Tech lead |

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-01-26 | Initial SLO definition | Agent 3 |
