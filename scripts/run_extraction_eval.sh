#!/bin/bash
# Run extraction evaluation on tier-1 carriers and output extractions for review
#
# Usage:
#   ./scripts/run_extraction_eval.sh           # Default: 10 pages per site
#   ./scripts/run_extraction_eval.sh 20        # 20 pages per site
#   ./scripts/run_extraction_eval.sh 10 2      # 10 pages, tier 2

set -e

SAMPLE_SIZE=${1:-10}
TIER=${2:-1}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="corpus/extraction_test_${TIMESTAMP}"

echo ""
echo "========================================"
echo "  TIER-${TIER} EXTRACTION EVALUATION"
echo "========================================"
echo ""
echo "  Sample size: ${SAMPLE_SIZE} pages per site"
echo "  Output dir:  ${OUTPUT_DIR}"
echo ""

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Run the auto evaluation
python scripts/eval_extraction.py --auto --tier ${TIER} --sample ${SAMPLE_SIZE} --jobs 4

# Now extract samples to the test directory for human review
echo ""
echo "========================================"
echo "  EXPORTING EXTRACTIONS FOR REVIEW"
echo "========================================"
echo ""

python -c "
import json
import random
from pathlib import Path

# Load seeds to get tier-${TIER} domains
seeds_file = Path('seeds/trucking_carriers.json')
with open(seeds_file) as f:
    carriers = json.load(f).get('carriers', [])

tier_domains = [c['domain'] for c in carriers if c.get('tier') == ${TIER}]
print(f'Tier-${TIER} domains: {len(tier_domains)}')

# For each domain, export sample extractions
output_dir = Path('${OUTPUT_DIR}')
corpus_raw = Path('corpus/raw')

from fetch.extractor import extract_content
from fetch.config import FetchConfig

config = FetchConfig()
total_exported = 0

for domain in tier_domains:
    domain_raw = corpus_raw / domain
    if not domain_raw.exists():
        print(f'  {domain}: no raw files')
        continue

    html_files = list(domain_raw.glob('*.html'))
    if not html_files:
        continue

    # Sample up to ${SAMPLE_SIZE} files
    sample = random.sample(html_files, min(${SAMPLE_SIZE}, len(html_files)))

    # Create domain output dir
    domain_out = output_dir / domain
    domain_out.mkdir(parents=True, exist_ok=True)

    for html_file in sample:
        try:
            html = html_file.read_text(errors='replace')
            result = extract_content(html, config)

            # Save original HTML
            (domain_out / f'{html_file.stem}_original.html').write_text(html)

            # Save extracted text
            (domain_out / f'{html_file.stem}_extracted.txt').write_text(result.text or '(empty)')

            # Save metadata
            meta = {
                'file': html_file.name,
                'method': result.method,
                'link_density': result.link_density,
                'word_count': len(result.text.split()) if result.text else 0,
                'title': result.title,
            }
            (domain_out / f'{html_file.stem}_meta.json').write_text(json.dumps(meta, indent=2))

            total_exported += 1
        except Exception as e:
            print(f'  Error on {html_file}: {e}')

    print(f'  {domain}: exported {len(sample)} pages')

print(f'')
print(f'Total exported: {total_exported} pages')
print(f'Output directory: ${OUTPUT_DIR}')
"

echo ""
echo "========================================"
echo "  DONE"
echo "========================================"
echo ""
echo "  Review extractions in: ${OUTPUT_DIR}/"
echo ""
echo "  Each domain folder contains:"
echo "    *_original.html  - Original HTML"
echo "    *_extracted.txt  - Extracted text"
echo "    *_meta.json      - Extraction metadata"
echo ""
echo "  Quick compare:"
echo "    diff ${OUTPUT_DIR}/*/index_original.html ${OUTPUT_DIR}/*/index_extracted.txt"
echo ""
