# Crawling Docs Index

Short guide to the docs in this folder and what each one is for.

- `stateofplay.txt`
  Timeline-style status log: what’s working, recent integrations (fetch, interactive, features),
  current debugging focus, and concrete next steps. Includes batch test results and crawl stats.

- `model_understanding_of_core_intent.txt`
  Canonical statement of intent: build a structured corpus with *all* text/images/code, tagged
  and reliable, plus site capabilities and provenance. Target success rate ~99%.

- `div1.txt`
  Implementation plan for “core-model-guided crawling”: SiteCore object, nav/category coverage,
  priority queue rules, UI structure capture, and evaluation metrics. Includes progress notes.

- `fetch_proposal.txt`
  Design for unified fetch+extract: requests→Playwright→stealth, trafilatura→readability→density,
  quality gates, hashing/archiving, confidence scoring, and integration path into crawl.py/oc.

- `interactive_crawling.md`
  Interaction layer design: ordered UI actions (accordions/tabs/load-more), stop conditions,
  delta detection, anti‑bot constraints, and page-type heuristics. Includes implementation notes.

- `interactive_crawling_sprint.md`
  Sprint plan with parallel agent ownership, interface contract, milestones, and testing strategy
  for the interactive layer.

- `bettercrawling.txt`
  Research notes on extraction methods (density/link ratios, tag ratios), benchmarks, and the
  “what big labs do vs what we need” rationale. Practical recommendations for this crawler.

- `lit.txt`
  Literature + pro-grade extraction checklist: papers, tools, benchmarks, failure modes,
  and production pipeline recommendations.

- `notes.txt`
  Development log with early crawl experiments (e.g., jbhunt.com failures), fixes applied,
  and key findings.

- `suggestion.txt`
  Full architecture proposal: greedy extraction layer → transform layer → structured object
  model (Text/Image/Code blocks), quality signals, navigation APIs, and future file layout.
