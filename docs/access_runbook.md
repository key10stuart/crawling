# Access Layer Runbook

Troubleshooting and incident response for the adaptive access layer.

---

## Quick Reference

### Common Commands

```bash
# Check crawl status
python scripts/access_report.py --summary

# View blocked sites
python scripts/access_report.py --blocked

# Check monkey queue
python scripts/monkey.py --list

# Process monkey queue
python scripts/monkey.py --next

# Test single site access
python scripts/crawl.py --domain example.com --depth 0 --js-auto

# Run recon only (no crawl)
python scripts/crawl.py --domain example.com --recon-only

# Bootstrap cookies for blocked site
python scripts/bootstrap_cookies.py --domain example.com
```

### Key Files

| File | Purpose |
|------|---------|
| `corpus/sites/*.json` | Crawl outputs |
| `~/.crawl/cookies/*.json` | Saved cookies |
| `~/.crawl/monkey_queue.json` | Sites needing human attention |
| `~/.crawl/flows/*.flow.json` | Recorded browsing flows |
| `profiles/access_playbooks.yaml` | Per-site strategy overrides |

---

## Incident Response Procedures

### Tier-1 Success Rate Drop

**Symptoms:**
- SLO: Tier-1 success rate <90%
- Multiple Tier-1 sites showing 0 pages or blocked status

**Diagnosis:**

1. Identify affected sites:
   ```bash
   python scripts/access_report.py --tier 1 --failed
   ```

2. Check if it's a single site or widespread:
   - Single site → likely site-specific protection change
   - Multiple sites → possible IP reputation issue or shared CDN change

3. For each affected site, check recon:
   ```bash
   python scripts/crawl.py --domain affected-site.com --recon-only
   ```

**Resolution:**

| Cause | Action |
|-------|--------|
| New CAPTCHA on one site | Add to monkey queue, bootstrap cookies |
| CDN blocking our IP range | Try from different network, consider proxy |
| Strategy not escalating | Check recon signals, update playbook |
| Site redesign broke extraction | Not an access issue - escalate to extraction team |

**Escalation:** If >3 Tier-1 sites blocked simultaneously, page on-call lead.

---

### High Block Rate

**Symptoms:**
- SLO: Block rate >20%
- Many 403s or CAPTCHA pages in logs

**Diagnosis:**

1. Check block distribution:
   ```bash
   python scripts/access_report.py --blocks-by-cdn
   ```

2. Identify if blocks are from specific CDN:
   - Cloudflare-heavy → stealth may be detected
   - StackPath-heavy → cookies likely expired
   - Akamai-heavy → may need residential proxy

3. Check recent changes:
   - Did we recently increase crawl rate?
   - Did we change user-agent or fingerprint?

**Resolution:**

| Cause | Action |
|-------|--------|
| Rate too aggressive | Increase delays, reduce parallelism |
| Fingerprint burned | Rotate browser fingerprint in stealth config |
| Cookies expired | Re-bootstrap for affected sites |
| New WAF rules | Update recon detection, adjust strategy |

**Immediate Mitigation:**
```bash
# Reduce crawl rate
python scripts/crawl.py --tier 1 --delay 10 --jobs 2

# Or enable patient mode
python scripts/crawl.py --tier 1 --patient
```

---

### Monkey Queue Backlog

**Symptoms:**
- SLO: >5 sites in monkey queue for >48h
- Human processing not keeping up

**Diagnosis:**

1. Check queue status:
   ```bash
   python scripts/monkey.py --list
   ```

2. Identify queue composition:
   - Are these new sites or repeat offenders?
   - Are they high-priority (Tier-1)?

**Resolution:**

1. Prioritize Tier-1 sites:
   ```bash
   python scripts/monkey.py --next  # Processes highest priority first
   ```

2. Batch process if backlogged:
   ```bash
   # Process top 5 in queue
   for i in {1..5}; do python scripts/monkey.py --next; done
   ```

3. If sites keep returning to queue (perpetual manual):
   - Check if they're flagged as perpetual
   - Consider if site is worth the manual effort
   - Update seeds with `skip: true` if not worth it

**Prevention:**
- Schedule regular monkey processing (e.g., 30 min twice weekly)
- Set calendar reminder for queue check

---

### Stale Crawls

**Symptoms:**
- SLO: Tier-1 sites not crawled in >30 days
- `--freshen` skipping too many sites

**Diagnosis:**

1. List stale sites:
   ```bash
   python scripts/seed_coverage.py --tier 1 --max-age 30d --stale-only
   ```

2. Check why they weren't crawled:
   - In monkey queue waiting?
   - Marked skip?
   - Crawl job not running?

**Resolution:**

| Cause | Action |
|-------|--------|
| In monkey queue | Process queue |
| Marked skip | Review if skip still valid |
| Crawl job not scheduled | Check cron/scheduler |
| Crawl failing silently | Check logs for errors |

**Force refresh:**
```bash
# Crawl specific stale site
python scripts/crawl.py --domain stale-site.com --js-auto

# Force crawl all tier-1 ignoring freshness
python scripts/crawl.py --tier 1 --js-auto  # No --freshen flag
```

---

### Cookie Expiration

**Symptoms:**
- Site that previously worked now returns CAPTCHA
- monkey_do replay failing

**Diagnosis:**

1. Check cookie expiry:
   ```bash
   python scripts/cookie_inspect.py --domain example.com
   ```

2. Look for `expires` timestamp in cookie file:
   ```bash
   cat ~/.crawl/cookies/example_com.json | jq '.[].expires'
   ```

**Resolution:**

1. Re-bootstrap cookies:
   ```bash
   python scripts/bootstrap_cookies.py --domain example.com
   ```

2. After solving CAPTCHA in browser, press Enter to save

3. Verify new cookies work:
   ```bash
   python scripts/crawl.py --domain example.com --depth 0
   ```

**Prevention:**
- Set up cookie expiry monitoring
- Schedule re-bootstrap before expiry for critical sites

---

### Extraction Quality Drop

**Symptoms:**
- SLO: Human eval score <60%
- Word counts lower than expected
- Missing content in reports

**Diagnosis:**

1. Run targeted eval:
   ```bash
   python scripts/eval_interactive.py --limit 5
   ```

2. Compare extraction vs live site:
   ```bash
   ./test_render.sh corpus/sites/example_com.json 0
   ```

3. Check if it's access or extraction issue:
   - Low word count + blocked signals → access issue
   - Normal word count but missing content → extraction issue

**Resolution:**

| Cause | Action |
|-------|--------|
| Access issue | Follow block rate procedure |
| JS content not rendering | Ensure JS method being used |
| Carousel/tabs not expanded | Check interaction coverage |
| Site redesign | Update extraction selectors |

**Escalation:** Extraction issues go to Agent B (extraction team).

---

## Operational Procedures

### Daily Checklist

- [ ] Check access dashboard for SLO violations
- [ ] Review any new blocks from overnight crawl
- [ ] Check monkey queue depth

### Weekly Procedures

1. **Block Rate Review**
   ```bash
   python scripts/access_report.py --weekly-summary
   ```

2. **Cookie Health Check**
   ```bash
   python scripts/cookie_inspect.py --all --expiring-soon 7d
   ```

3. **Process Monkey Queue**
   - Target: Queue depth <3 by end of week

### Monthly Procedures

1. **Human Evaluation Run**
   ```bash
   python scripts/eval_interactive.py --limit 15
   ```

2. **SLO Review**
   - Check all SLO metrics against targets
   - Document any threshold adjustments needed

3. **Playbook Cleanup**
   - Remove obsolete per-site overrides
   - Update strategies based on learned history

---

## Adding a New Blocked Site

When a new site is blocked and needs manual handling:

1. **Attempt automatic methods first:**
   ```bash
   python scripts/crawl.py --domain newsite.com --js-auto --stealth
   ```

2. **If blocked, run recon:**
   ```bash
   python scripts/crawl.py --domain newsite.com --recon-only
   ```

3. **Based on recon, try appropriate method:**

   | Recon Result | Try This |
   |--------------|----------|
   | Cloudflare challenge | `--stealth --patient` |
   | StackPath sgcaptcha | Bootstrap cookies first |
   | Akamai bot manager | `--stealth --no-headless` |
   | JS required | `--js` (may just need rendering) |

4. **If all auto methods fail, add to monkey queue:**
   ```bash
   python scripts/monkey.py --see newsite.com
   ```

5. **After successful monkey_see, update playbook:**
   ```yaml
   # profiles/access_playbooks.yaml
   newsite.com:
     strategy: stealth
     cookies: newsite.com
     notes: "StackPath - requires cookie bootstrap"
   ```

---

## Emergency Procedures

### All Crawls Failing

1. **Check network connectivity:**
   ```bash
   curl -I https://www.google.com
   ```

2. **Check if IP is blacklisted:**
   ```bash
   # Try from different network/VPN
   ```

3. **Check system resources:**
   ```bash
   # Playwright may fail if out of memory
   free -h
   ps aux | grep chromium
   ```

4. **Restart with minimal config:**
   ```bash
   python scripts/crawl.py --domain google.com --depth 0
   ```

### Monkey Queue Corrupted

1. **Backup current state:**
   ```bash
   cp ~/.crawl/monkey_queue.json ~/.crawl/monkey_queue.json.bak
   ```

2. **Validate JSON:**
   ```bash
   python -m json.tool ~/.crawl/monkey_queue.json
   ```

3. **If invalid, reset:**
   ```bash
   echo '{"queue": [], "completed": []}' > ~/.crawl/monkey_queue.json
   ```

### Cookie Store Corrupted

1. **Backup:**
   ```bash
   cp -r ~/.crawl/cookies ~/.crawl/cookies.bak
   ```

2. **Identify bad files:**
   ```bash
   for f in ~/.crawl/cookies/*.json; do
     python -m json.tool "$f" > /dev/null 2>&1 || echo "Bad: $f"
   done
   ```

3. **Remove bad files and re-bootstrap affected sites**

---

## Contacts & Escalation

| Issue Type | First Contact | Escalation |
|------------|---------------|------------|
| Access/blocking | On-call (Agent 1) | Tech lead |
| Extraction quality | Agent B | Tech lead |
| Infrastructure | Ops | Platform team |
| Monkey queue backlog | Scheduled processor | Anyone available |

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-01-26 | Initial runbook | Agent 3 |
