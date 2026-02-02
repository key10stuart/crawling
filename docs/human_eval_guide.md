# Human Evaluation Guide: Comp Packages Extraction

## Purpose

Verify that our automated extraction of compensation packages matches what a human sees on trucking company websites. This evaluation ensures the system accurately captures driver pay, owner-operator programs, and carrier inducements across the three audience buckets.

## Quick Start

```bash
# 1. Generate a sample set (20 sites stratified by type)
python scripts/human_eval.py --sample --out eval/sample_$(date +%Y-%m-%d).json

# 2. Generate your worksheet
python scripts/human_eval.py --worksheet eval/sample_$(date +%Y-%m-%d).json \
    --out eval/worksheet_$(date +%Y-%m-%d).md

# 3. Complete evaluation (see process below)

# 4. Enter scores and run report
python scripts/human_eval.py --score eval/scores_$(date +%Y-%m-%d).json
```

---

## Sampling Strategy

The sample includes three types of sites:

| Type | Count | Purpose |
|------|-------|---------|
| Random | 10 | Unbiased coverage across tiers |
| Targeted | 5 | Sites likely to have rich recruiting/owner-op content |
| Edge cases | 5 | JS-heavy sites (AEM, Next.js) that stress the system |

Sites are stratified across tiers:
- **Tier 1**: Major carriers (JB Hunt, Schneider, XPO, etc.)
- **Tier 2**: Regional/specialized carriers
- **Tier 3**: Smaller/niche carriers

---

## Evaluation Process

### For Each Site

1. **Open our extraction output**
   ```bash
   # View the comp packages report section for this site
   cat corpus/reports/comp_packages_latest.md | grep -A 50 "domain.com"

   # Or view raw JSON
   cat corpus/sites/domain_com.json | python -m json.tool | less
   ```

2. **Visit the live website** in your browser

3. **Navigate to key pages**:
   - Careers / Drive for Us / Join Our Team
   - Owner Operators / Lease Purchase
   - Carriers / Partner With Us / Haul For Us
   - Benefits / Compensation / Pay

4. **Compare what you see vs. what we captured**

5. **Score using the rubric below**

6. **Record notes on any issues**

---

## What to Look For

### Bucket 1: Drivers (Company Drivers)

Look for and verify we captured:

| Item | Examples |
|------|----------|
| Pay rates | "$0.55-0.65 CPM", "$25/hour", "$70K-$90K annual" |
| Sign-on bonuses | "$5,000 sign-on bonus", "Up to $15K welcome bonus" |
| Other bonuses | Safety bonus, referral bonus, performance bonus |
| Benefits | Medical, dental, vision, 401(k), life insurance |
| Home time | "Home weekly", "Regional - home every weekend" |
| PTO/Vacation | "2 weeks PTO", "Paid holidays" |
| Equipment | "New Freightliner Cascadias", "Assigned trucks" |
| Requirements | "1 year experience", "Clean MVR", "CDL-A" |

### Bucket 2: Owner-Operators

Look for and verify we captured:

| Item | Examples |
|------|----------|
| Revenue/settlement | "85% of linehaul", "$2.50/mile average" |
| Lease purchase terms | "$800/week, walk-away lease" |
| Fuel programs | "Fuel discounts at pilot/loves", "Fuel card" |
| Quick/fast pay | "Same-day pay available", "Weekly settlements" |
| Plate/insurance programs | "Plate program available", "Cargo insurance provided" |
| Trailer programs | "Free trailer use", "Drop and hook available" |
| Requirements | "2 years experience", "Own authority or lease on" |

### Bucket 3: Carriers (B2B / Partner Programs)

Look for and verify we captured:

| Item | Examples |
|------|----------|
| Quick pay | "2-day quick pay", "Fuel advance available" |
| Load board access | "Dedicated load board", "Priority freight" |
| Onboarding speed | "Same-day setup", "Get loads within 24 hours" |
| Fuel programs | "Fuel discounts for partners" |
| Technology | "Free ELD", "Tracking integration" |
| Payment terms | "Net 30", "Factoring available" |

---

## Scoring Rubric

### Coverage (0-3)

How much of the visible compensation content did we capture?

| Score | Description | Guidance |
|-------|-------------|----------|
| 0 | None | No comp items captured at all |
| 1 | Partial | Some items captured, but major gaps (e.g., missed entire benefits section) |
| 2 | Good | Most items captured, only minor gaps (e.g., missed one bonus type) |
| 3 | Complete | All visible comp items captured |

**Tips:**
- Check all three buckets separately
- "Major gap" = missing a whole category (e.g., all benefits, all O/O terms)
- "Minor gap" = missing individual items within a captured category

### Precision (0-3)

How accurate is what we captured? Are there false positives?

| Score | Description | Guidance |
|-------|-------------|----------|
| 0 | Many FPs | >50% of captured items are wrong/irrelevant |
| 1 | Some FPs | 25-50% of captured items are wrong |
| 2 | Few FPs | <25% of captured items are wrong |
| 3 | Clean | No false positives |

**Common false positives to watch for:**
- Stock prices or market cap tagged as "money"
- Shipping quotes tagged as driver pay
- Loan/financing amounts tagged as bonuses
- Footer phone numbers tagged as pay rates
- Investor relations content in comp buckets

### Recency (0-2)

Did we capture recent/current information vs. stale content?

| Score | Description | Guidance |
|-------|-------------|----------|
| 0 | Stale | Captured outdated info, missed current offers |
| 1 | Partial | Mix of current and outdated |
| 2 | Current | Captured current/recent comp items |

**Tips:**
- Check if site shows "2024" or "2025" rates and we captured them
- Look for "limited time" or "new" offers
- If site hasn't changed, score 2 by default

---

## Pass/Fail Criteria

| Criterion | Threshold |
|-----------|-----------|
| Average score | ≥ 6/8 |
| Minimum score | No site < 4/8 |

**Both conditions must be met to pass.**

---

## Recording Your Scores

Create a JSON file with your scores:

```json
{
  "evaluator": "Your Name",
  "date": "2026-01-26",
  "notes": "Evaluation of sample_2026-01-26",
  "scores": [
    {
      "domain": "jbhunt.com",
      "coverage": 3,
      "precision": 2,
      "recency": 2,
      "notes": "Good coverage. One FP: stock price captured as money mention."
    },
    {
      "domain": "schneider.com",
      "coverage": 2,
      "precision": 3,
      "recency": 2,
      "notes": "Missed lease purchase details in accordion. No FPs."
    }
  ]
}
```

Save as `eval/scores_YYYY-MM-DD.json` and run:

```bash
python scripts/human_eval.py --score eval/scores_2026-01-26.json
```

---

## Checklist Template (Per Site)

Copy this for each site you evaluate:

```
Site: ___________________
Tier: ___  Sample type: _______________

DRIVERS
[ ] Pay rates captured?
[ ] Sign-on bonus captured?
[ ] Benefits captured?
[ ] Home time captured?
[ ] Requirements captured?
Notes:

OWNER-OPERATORS
[ ] Revenue/settlement captured?
[ ] Lease terms captured?
[ ] Fuel programs captured?
[ ] Quick pay captured?
Notes:

CARRIERS
[ ] Quick pay / payment terms captured?
[ ] Load board / freight access captured?
[ ] Onboarding / setup captured?
Notes:

ISSUES
[ ] Any obvious misses?
[ ] Any false positives?
[ ] Any stale/outdated content?
Notes:

SCORES
Coverage:  ___/3
Precision: ___/3
Recency:   ___/2
TOTAL:     ___/8
```

---

## Troubleshooting

### Site not in corpus
```bash
# Check if site was crawled
ls corpus/sites/ | grep domain_name

# If missing, run crawl
python scripts/crawl.py --domain domain.com --profile comp_packages --js-auto
```

### Can't find comp content on live site
- Try searching for "careers", "drivers", "owner operator"
- Check hamburger menu on mobile-optimized sites
- Some sites hide comp behind "Apply Now" flows (out of scope)

### Content behind login/application
- Mark as N/A for that bucket
- Note in comments: "Comp details require application"
- Don't penalize coverage score for login-gated content

### JS-heavy site looks empty in our data
- Check if crawled with `--js` flag
- Re-crawl: `python scripts/crawl.py --domain X --js --profile comp_packages`
- Note in comments if JS rendering issue

---

## Questions?

- Check `docs/div3.txt` for full implementation plan
- Check `docs/stateofplay.txt` for current system status
- Reach out to the team with specific site issues
