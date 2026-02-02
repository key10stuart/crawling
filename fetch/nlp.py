"""
NLP utilities for competitive intelligence extraction.

Includes:
- Lightweight regex-based extractors (no external deps)
- LLM-based analysis (Claude API)
- Text similarity and deduplication
"""

import re
import json
from dataclasses import dataclass, field, asdict
from typing import Any
from collections import Counter


# =============================================================================
# Lightweight Extractors (No LLM Required)
# =============================================================================

@dataclass
class MoneyMention:
    """Extracted monetary value."""
    amount: float
    raw: str
    unit: str  # 'dollar', 'per_mile', 'per_hour', 'percent'
    context: str  # surrounding text


@dataclass
class DateMention:
    """Extracted date reference."""
    raw: str
    normalized: str | None  # ISO format if parseable
    context: str


@dataclass
class EntityMention:
    """Extracted named entity."""
    text: str
    type: str  # 'company', 'location', 'person', 'program'
    context: str


# Money patterns
MONEY_PATTERNS = [
    # $X,XXX or $X.XX
    (r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:k|K|thousand|million|M))?\b', 'dollar'),
    # X cents per mile, $X.XX/mile
    (r'[\d.]+\s*(?:cents?|¢)\s*(?:per\s+)?(?:mile|mi)\b', 'per_mile'),
    (r'\$[\d.]+\s*/\s*(?:mile|mi)\b', 'per_mile'),
    # CPM patterns
    (r'[\d.]+\s*(?:cpm|CPM)\b', 'per_mile'),
    # Per hour
    (r'\$[\d.]+\s*(?:/\s*hr|/\s*hour|per\s+hour)\b', 'per_hour'),
    # Percentages
    (r'\d+(?:\.\d+)?\s*%', 'percent'),
]

# Date patterns
DATE_PATTERNS = [
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b',
    r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
    r'\b\d{4}-\d{2}-\d{2}\b',
    r'\b(?:Q[1-4]|first|second|third|fourth)\s+(?:quarter|qtr)(?:\s+\d{4})?\b',
]

# Location patterns (US states, major cities)
US_STATES = r'\b(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West\s+Virginia|Wisconsin|Wyoming|AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b'

# Compensation-related keywords
COMP_KEYWORDS = {
    'sign_on_bonus': ['sign-on', 'sign on', 'signing bonus', 'welcome bonus', 'hiring bonus'],
    'pay_per_mile': ['cpm', 'cents per mile', 'per mile', '/mile', 'mileage pay'],
    'hourly': ['per hour', '/hour', 'hourly', '/hr'],
    'benefits': ['401k', '401(k)', 'health insurance', 'medical', 'dental', 'vision', 'pto', 'paid time off', 'vacation'],
    'home_time': ['home time', 'home weekly', 'home daily', 'weekends off', 'regional'],
    'equipment': ['new equipment', 'new trucks', 'late model', 'assigned truck'],
    'quick_pay': ['quick pay', 'fast pay', 'same day pay', 'instant pay', 'daily pay'],
    'fuel': ['fuel discount', 'fuel card', 'fuel surcharge', 'fuel bonus'],
    'training': ['cdl training', 'paid training', 'tuition', 'cdl school'],
    'lease': ['lease purchase', 'lease-to-own', 'lease program', 'owner operator'],
}

# Recruiting urgency signals (patterns, not exact matches)
URGENCY_PATTERNS = [
    r'hiring\s+(?:\w+\s+)?immediately',
    r'urgent(?:ly)?',
    r'hiring\s+now',
    r'immediate\s+openings?',
    r'spots?\s+available',
    r'limited\s+positions?',
    r'apply\s+today',
    r'start\s+(?:this|next)\s+week',
    r'high\s+demand',
    r'critical\s+need',
    r'now\s+hiring',
    r'immediate(?:ly)?\s+(?:hiring|need)',
]


def extract_money(text: str, context_chars: int = 50) -> list[MoneyMention]:
    """Extract monetary values from text."""
    mentions = []
    for pattern, unit in MONEY_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            raw = match.group()

            # Parse amount
            amount = None
            clean = re.sub(r'[,$%]', '', raw.lower())
            clean = re.sub(r'\s*(cpm|per mile|/mile|/hr|per hour|/hour|cents?|¢|k|thousand|million|m)\s*', '', clean)
            try:
                amount = float(clean)
                # Handle k/thousand/million
                if 'k' in raw.lower() or 'thousand' in raw.lower():
                    amount *= 1000
                elif 'million' in raw.lower() or raw.lower().endswith('m'):
                    amount *= 1000000
                # Convert cents to dollars for per_mile
                if unit == 'per_mile' and 'cent' in raw.lower():
                    amount /= 100
            except ValueError:
                pass

            mentions.append(MoneyMention(
                amount=amount,
                raw=raw,
                unit=unit,
                context=text[start:end].strip(),
            ))
    return mentions


def extract_dates(text: str, context_chars: int = 30) -> list[DateMention]:
    """Extract date mentions from text."""
    mentions = []
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            mentions.append(DateMention(
                raw=match.group(),
                normalized=None,  # Could add dateutil parsing
                context=text[start:end].strip(),
            ))
    return mentions


def extract_locations(text: str) -> list[str]:
    """Extract US state/location mentions."""
    # Filter out false positives (common words that match state abbrevs)
    false_positives = {'in', 'or', 'me', 'hi', 'oh', 'ok', 'co', 'de', 'la', 'ma', 'md', 'mo', 'ne', 'pa'}
    matches = re.findall(US_STATES, text, re.IGNORECASE)
    return list(set(m for m in matches if m.lower() not in false_positives or len(m) > 2))


def detect_comp_keywords(text: str) -> dict[str, list[str]]:
    """Detect compensation-related keywords by category."""
    text_lower = text.lower()
    found = {}
    for category, keywords in COMP_KEYWORDS.items():
        matches = [kw for kw in keywords if kw in text_lower]
        if matches:
            found[category] = matches
    return found


def detect_urgency(text: str) -> tuple[bool, list[str]]:
    """Detect recruiting urgency signals."""
    text_lower = text.lower()
    found = []
    for pattern in URGENCY_PATTERNS:
        if re.search(pattern, text_lower):
            found.append(pattern.replace(r'\s+', ' ').replace(r'(?:\w+\s+)?', '').replace(r'(?:ly)?', ''))
    return bool(found), list(set(found))


def simple_sentiment(text: str) -> dict:
    """
    Simple lexicon-based sentiment (no ML).
    Returns positive/negative word counts and ratio.
    """
    positive = [
        'best', 'great', 'excellent', 'top', 'leading', 'premier', 'award',
        'guaranteed', 'reliable', 'trusted', 'professional', 'dedicated',
        'competitive', 'generous', 'comprehensive', 'flexible', 'modern',
    ]
    negative = [
        'required', 'must', 'mandatory', 'minimum', 'only', 'limited',
        'subject to', 'restrictions', 'fees', 'deductions', 'penalty',
    ]

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)

    pos_count = sum(1 for w in words if w in positive)
    neg_count = sum(1 for w in words if w in negative)
    total = pos_count + neg_count

    return {
        'positive_count': pos_count,
        'negative_count': neg_count,
        'ratio': pos_count / total if total > 0 else 0.5,
        'tone': 'positive' if pos_count > neg_count else 'negative' if neg_count > pos_count else 'neutral',
    }


def text_similarity(text1: str, text2: str, ngram: int = 3) -> float:
    """
    Simple n-gram based text similarity (Jaccard).
    Returns 0-1 score.
    """
    def get_ngrams(text, n):
        words = re.findall(r'\b\w+\b', text.lower())
        return set(tuple(words[i:i+n]) for i in range(len(words) - n + 1))

    ng1 = get_ngrams(text1, ngram)
    ng2 = get_ngrams(text2, ngram)

    if not ng1 or not ng2:
        return 0.0

    intersection = len(ng1 & ng2)
    union = len(ng1 | ng2)
    return intersection / union if union > 0 else 0.0


# =============================================================================
# Precision/Recall Improvements for Comp Buckets
# =============================================================================

# Context words that indicate a money mention is truly comp-related
COMP_CONTEXT_POSITIVE = [
    'driver', 'trucker', 'cdl', 'otr', 'regional', 'local',
    'pay', 'earn', 'make', 'salary', 'compensation', 'wage',
    'bonus', 'benefit', 'sign-on', 'signing', 'retention',
    'per mile', 'cpm', 'per hour', 'hourly', 'weekly', 'annual',
    'home time', 'guaranteed', 'average', 'top',
    'owner operator', 'lease', 'settlement', 'revenue',
]

# Context words that suggest a money mention is NOT comp-related (false positive)
COMP_CONTEXT_NEGATIVE = [
    'revenue', 'profit', 'stock', 'share', 'investor', 'market cap',
    'cost', 'expense', 'price', 'fee', 'charge', 'liability',
    'loan', 'debt', 'mortgage', 'financing', 'credit',
    'shipping cost', 'freight rate', 'quote', 'estimate',
    'donation', 'charity', 'foundation', 'grant',
]


def score_comp_mention(mention: MoneyMention, page_text: str) -> float:
    """
    Score how likely a money mention is truly compensation-related.

    Returns 0.0-1.0 confidence score.
    """
    context_lower = mention.context.lower()
    page_lower = page_text.lower()

    score = 0.5  # neutral start

    # Boost for positive context
    positive_hits = sum(1 for w in COMP_CONTEXT_POSITIVE if w in context_lower)
    score += positive_hits * 0.1

    # Penalty for negative context
    negative_hits = sum(1 for w in COMP_CONTEXT_NEGATIVE if w in context_lower)
    score -= negative_hits * 0.15

    # Boost if page overall is comp-focused
    page_comp_density = sum(1 for w in COMP_CONTEXT_POSITIVE if w in page_lower)
    if page_comp_density > 5:
        score += 0.1

    # Per-mile and per-hour are very likely comp
    if mention.unit in ('per_mile', 'per_hour'):
        score += 0.2

    # Large dollar amounts more likely comp (bonuses, salaries)
    if mention.amount and mention.amount >= 1000:
        score += 0.1

    return max(0.0, min(1.0, score))


def filter_comp_mentions(
    mentions: list[MoneyMention],
    page_text: str,
    min_confidence: float = 0.4,
) -> tuple[list[MoneyMention], list[dict]]:
    """
    Filter money mentions to those likely compensation-related.

    Returns:
        (filtered_mentions, scored_mentions_with_confidence)
    """
    scored = []
    filtered = []
    for m in mentions:
        conf = score_comp_mention(m, page_text)
        scored.append({**asdict(m), 'comp_confidence': conf})
        if conf >= min_confidence:
            filtered.append(m)
    return filtered, scored


def dedupe_mentions(mentions: list[MoneyMention]) -> list[MoneyMention]:
    """
    Deduplicate money mentions by raw value.

    Keeps the one with longest context.
    """
    seen = {}
    for m in mentions:
        key = (m.raw.lower().strip(), m.unit)
        if key not in seen or len(m.context) > len(seen[key].context):
            seen[key] = m
    return list(seen.values())


def classify_audience(text: str) -> str:
    """
    Classify the target audience of a page.

    Returns: 'drivers', 'owner_operators', 'carriers', 'shippers', 'general'
    """
    text_lower = text.lower()

    driver_signals = ['cdl', 'driver', 'trucker', 'otr', 'regional driver', 'local driver', 'company driver']
    oo_signals = ['owner operator', 'o/o', 'lease purchase', 'independent contractor', 'settlement', 'your truck']
    carrier_signals = ['carrier', 'fleet', 'trucking company', 'motor carrier', 'partner with us', 'haul for us']
    shipper_signals = ['shipper', 'ship with us', 'get a quote', 'freight', 'logistics solution', 'supply chain']

    driver_count = sum(1 for s in driver_signals if s in text_lower)
    oo_count = sum(1 for s in oo_signals if s in text_lower)
    carrier_count = sum(1 for s in carrier_signals if s in text_lower)
    shipper_count = sum(1 for s in shipper_signals if s in text_lower)

    counts = {
        'drivers': driver_count,
        'owner_operators': oo_count,
        'carriers': carrier_count,
        'shippers': shipper_count,
    }

    if max(counts.values()) == 0:
        return 'general'

    return max(counts, key=counts.get)


def extract_all_lightweight(text: str, filter_comp: bool = True) -> dict:
    """
    Run all lightweight extractors on text.

    Args:
        text: Page text content
        filter_comp: If True, filter money mentions to likely comp-related

    Returns:
        Dict with extractions and metadata
    """
    is_urgent, urgency_signals = detect_urgency(text)
    money_mentions = extract_money(text)

    # Apply precision filtering
    if filter_comp:
        money_mentions = dedupe_mentions(money_mentions)
        filtered_money, scored_money = filter_comp_mentions(money_mentions, text)
    else:
        filtered_money = money_mentions
        scored_money = [asdict(m) for m in money_mentions]

    audience = classify_audience(text)

    return {
        'money': [asdict(m) for m in filtered_money],
        'money_all_scored': scored_money,  # includes confidence scores
        'dates': [asdict(d) for d in extract_dates(text)],
        'locations': extract_locations(text),
        'comp_keywords': detect_comp_keywords(text),
        'urgency': {'is_urgent': is_urgent, 'signals': urgency_signals},
        'sentiment': simple_sentiment(text),
        'audience': audience,
    }


# =============================================================================
# LLM-Based Analysis (Claude API)
# =============================================================================

def get_anthropic_client():
    """Get Anthropic client (lazy import)."""
    try:
        import anthropic
        return anthropic.Anthropic()
    except ImportError:
        raise ImportError("pip install anthropic")


def llm_extract(
    text: str,
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> str:
    """Generic LLM extraction."""
    client = get_anthropic_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": f"{prompt}\n\n---\n\n{text}"}],
    )
    return response.content[0].text


def llm_extract_json(
    text: str,
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> dict | list | None:
    """LLM extraction with JSON output."""
    full_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown or explanation."
    result = llm_extract(text, full_prompt, model, max_tokens)

    # Try to parse JSON from response
    try:
        # Handle markdown code blocks
        if '```json' in result:
            result = result.split('```json')[1].split('```')[0]
        elif '```' in result:
            result = result.split('```')[1].split('```')[0]
        return json.loads(result.strip())
    except json.JSONDecodeError:
        return None


def llm_summarize_comp(text: str, model: str = "claude-haiku-4-20250514") -> dict | None:
    """Extract structured compensation data via LLM."""
    prompt = """Extract compensation information from this trucking company page.

Return JSON with:
{
  "has_comp_info": true/false,
  "driver_pay": {
    "cpm_range": [min, max] or null,
    "hourly_range": [min, max] or null,
    "annual_range": [min, max] or null,
    "sign_on_bonus": amount or null,
    "other_bonuses": ["list of mentioned bonuses"]
  },
  "benefits": ["list of benefits mentioned"],
  "home_time": "description or null",
  "equipment": "description or null",
  "requirements": ["list of requirements"],
  "target_audience": "company_driver|owner_operator|carrier|shipper|unknown"
}"""
    return llm_extract_json(text, prompt, model)


def llm_summarize_changes(old_text: str, new_text: str, model: str = "claude-haiku-4-20250514") -> str:
    """Summarize changes between two versions of a page."""
    prompt = f"""Compare these two versions of a trucking company webpage and summarize what changed.
Focus on: compensation, benefits, services, requirements, messaging tone.

OLD VERSION:
{old_text[:3000]}

NEW VERSION:
{new_text[:3000]}

Summarize the key changes in 3-5 bullet points. If no significant changes, say "No significant changes detected."
"""
    return llm_extract("", prompt, model, max_tokens=512)


def llm_classify_page(text: str, model: str = "claude-haiku-4-20250514") -> dict | None:
    """Classify page type and target audience."""
    prompt = """Classify this trucking company webpage.

Return JSON:
{
  "page_type": "recruiting|services|about|pricing|technology|news|careers|other",
  "target_audience": "company_drivers|owner_operators|carriers|shippers|investors|general",
  "intent": "attract|inform|convert|support",
  "key_topics": ["list of 3-5 main topics"],
  "confidence": 0.0-1.0
}"""
    return llm_extract_json(text[:4000], prompt, model)


def llm_competitive_summary(text: str, company: str, model: str = "claude-haiku-4-20250514") -> str:
    """Generate competitive intelligence summary."""
    prompt = f"""You are a competitive intelligence analyst. Summarize {company}'s positioning based on this webpage content.

Include:
1. Value proposition (1 sentence)
2. Key differentiators (3 bullets)
3. Target customer/driver profile
4. Notable claims or stats
5. Gaps or weaknesses implied

Be concise and analytical."""
    return llm_extract(text[:4000], prompt, model, max_tokens=512)


def llm_answer_question(corpus_text: str, question: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Answer a question based on corpus text."""
    prompt = f"""Based on the following trucking company website content, answer this question:

QUESTION: {question}

Cite specific evidence from the text. If the answer isn't in the content, say so.

CONTENT:
{corpus_text[:6000]}"""
    return llm_extract("", prompt, model, max_tokens=1024)


# =============================================================================
# Batch Processing
# =============================================================================

def enrich_page(page: dict, use_llm: bool = False, llm_model: str = "claude-haiku-4-20250514") -> dict:
    """
    Enrich a page dict with NLP extractions.

    Args:
        page: Page dict from site JSON (must have 'full_text' or 'main_content')
        use_llm: Whether to run LLM-based analysis
        llm_model: Model to use for LLM calls

    Returns:
        Page dict with added 'nlp' key
    """
    text = page.get('full_text') or page.get('main_content') or ''
    if not text:
        return page

    # Lightweight extraction (always run)
    nlp = extract_all_lightweight(text)

    # LLM extraction (optional)
    if use_llm:
        try:
            nlp['llm_comp'] = llm_summarize_comp(text, llm_model)
            nlp['llm_classification'] = llm_classify_page(text, llm_model)
        except Exception as e:
            nlp['llm_error'] = str(e)

    page['nlp'] = nlp
    return page


def enrich_site(site: dict, use_llm: bool = False, llm_model: str = "claude-haiku-4-20250514") -> dict:
    """Enrich all pages in a site JSON."""
    for page in site.get('pages', []):
        enrich_page(page, use_llm, llm_model)
    return site
