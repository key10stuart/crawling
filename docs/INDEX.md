# Crawling Docs Index

Guide to documentation in this folder.

## Current State

- `stateofplay.txt`
  Current system status, what works, known issues, next steps. Start here.

- `actof.md`
  Famous crawler references + project ethos for building a top-tier, scrappy system.

- `model_understanding_of_core_intent.txt`
  Core intent: capture ALL text/images/code, tagged and reliable, ~99% success.

## Operational Guides

- `access_runbook.md`
  How to run crawls, handle blocked sites, process monkey queue. Commands that work.

- `access_slos.md`
  Service level objectives and thresholds for access layer health.

- `docker_crawling.md`
  Running crawls in Docker containers (headless and Xvfb modes).

- `human_eval_guide.md`
  How to run human evaluation on extraction quality.

- `monkey_integration.md`
  How the monkey (human-in-loop) system integrates with the crawler.

## Implementation Plans (Div Series)

Historical implementation plans. Status markers may be stale — check `stateofplay.txt` for current state.

| Doc | Focus |
|-----|-------|
| `div1.txt` | Core crawl pipeline, profiles, nav coverage |
| `div2.txt` | Sitemap, robots.txt, structured data, exports |
| `div3.txt` | Compensation packages monitoring |
| `div4.txt` | Universal access layer (main vision doc) |
| `div4a.txt` | Per-site config, recon, cookies |
| `div4b.txt` | Playbooks, analytics, behavior controls |
| `div4c.txt` | Learning loop, drift detection |
| `div4d.txt` | Governance, SLOs, proxy strategy |
| `div4e.txt` | Monkey system (human-in-loop) |
| `div4f.txt` | Docker support |
| `div4g.txt` | Pro-grade audit gaps |
| `div4h.txt` | Full system evaluation harness |
| `div4i.txt` | Capture/extract refactor |
| `div4j.txt` | Closeout plan |
| `div4k.txt` | Orchestrator refactor + QA |
| `div40.txt` | Agent parallelization plan |
| `div4i0.txt` | Capture/extract parallelization |

## Educational

- `edu/` folder contains explanatory docs on web crawling concepts:
  - `00_what_is_a_website.md` - Basics
  - `01_the_arms_race.md` - Bot detection landscape
  - `02_anatomy_of_html.md` - HTML structure
  - `03_dynamic_content.md` - JS rendering, SPAs
  - `04_infrastructure.md` - CDNs, WAFs
  - `05_information_theory.md` - Signal vs noise

## Historical / Research

These were design docs from early development. Implementation has evolved.

- `fetch_proposal.txt` - Original fetch+extract design
- `suggestion.txt` - Early architecture proposal
- `bettercrawling.txt` - Extraction research notes
- `lit.txt` - Literature review
- `notes.txt` - Development log
- `interactive_crawling.md` - Interaction layer design
- `interactive_crawling_sprint.md` - Sprint plan for interactions
