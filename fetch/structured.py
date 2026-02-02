"""
Structured data extraction (JSON-LD, Schema.org).

Extracts:
- Organization: name, logo, address, contactPoint
- LocalBusiness: same + geo, openingHours
- WebSite: name, url, searchAction
- Service: name, description, provider
- BreadcrumbList: navigation path

Usage:
    from fetch.structured import extract_jsonld, aggregate_structured

    # Single page
    data = extract_jsonld(html)

    # Aggregate across site
    site_data = aggregate_structured(pages)
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from bs4 import BeautifulSoup


@dataclass
class StructuredData:
    """Extracted structured data from a page."""
    raw_jsonld: list[dict] = field(default_factory=list)
    organization: dict | None = None
    website: dict | None = None
    services: list[dict] = field(default_factory=list)
    breadcrumbs: list[str] = field(default_factory=list)
    local_business: dict | None = None
    products: list[dict] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def extract_jsonld(html: str) -> StructuredData:
    """
    Extract JSON-LD structured data from HTML.

    Args:
        html: Raw HTML content

    Returns:
        StructuredData with parsed schema.org objects
    """
    result = StructuredData()

    soup = BeautifulSoup(html, 'lxml')

    # Find all JSON-LD script tags
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            content = script.string
            if not content:
                continue

            # Clean up common issues
            content = content.strip()

            # Parse JSON
            data = json.loads(content)

            # Handle @graph wrapper
            if isinstance(data, dict) and '@graph' in data:
                items = data['@graph']
            elif isinstance(data, list):
                items = data
            else:
                items = [data]

            for item in items:
                if not isinstance(item, dict):
                    continue

                result.raw_jsonld.append(item)
                _process_item(item, result)

        except json.JSONDecodeError as e:
            result.errors.append(f"JSON parse error: {e}")
        except Exception as e:
            result.errors.append(f"Processing error: {e}")

    return result


def _get_type(item: dict) -> str | None:
    """Get schema.org type from item."""
    t = item.get('@type')
    if isinstance(t, list):
        return t[0] if t else None
    return t


def _process_item(item: dict, result: StructuredData):
    """Process a single JSON-LD item into result."""
    item_type = _get_type(item)
    if not item_type:
        return

    item_type_lower = item_type.lower()

    if item_type_lower in ('organization', 'corporation', 'company'):
        result.organization = _extract_organization(item)

    elif item_type_lower in ('localbusiness', 'store', 'restaurant'):
        result.local_business = _extract_local_business(item)

    elif item_type_lower == 'website':
        result.website = _extract_website(item)

    elif item_type_lower == 'service':
        result.services.append(_extract_service(item))

    elif item_type_lower in ('product', 'offer'):
        result.products.append(_extract_product(item))

    elif item_type_lower == 'breadcrumblist':
        result.breadcrumbs = _extract_breadcrumbs(item)

    elif item_type_lower == 'faqpage':
        result.faq = _extract_faq(item)


def _extract_organization(item: dict) -> dict:
    """Extract Organization schema fields."""
    return {
        'type': _get_type(item),
        'name': item.get('name'),
        'url': item.get('url'),
        'logo': _get_image_url(item.get('logo')),
        'description': item.get('description'),
        'address': _extract_address(item.get('address')),
        'telephone': item.get('telephone'),
        'email': item.get('email'),
        'contact_points': _extract_contact_points(item.get('contactPoint')),
        'same_as': item.get('sameAs', []),  # Social links
        'founding_date': item.get('foundingDate'),
        'number_of_employees': _extract_employees(item.get('numberOfEmployees')),
    }


def _extract_local_business(item: dict) -> dict:
    """Extract LocalBusiness schema fields."""
    org = _extract_organization(item)
    org.update({
        'geo': _extract_geo(item.get('geo')),
        'opening_hours': item.get('openingHoursSpecification'),
        'price_range': item.get('priceRange'),
    })
    return org


def _extract_website(item: dict) -> dict:
    """Extract WebSite schema fields."""
    search_action = item.get('potentialAction')
    search_url = None
    if isinstance(search_action, dict) and search_action.get('@type') == 'SearchAction':
        search_url = search_action.get('target')

    return {
        'name': item.get('name'),
        'url': item.get('url'),
        'search_url': search_url,
    }


def _extract_service(item: dict) -> dict:
    """Extract Service schema fields."""
    return {
        'name': item.get('name'),
        'description': item.get('description'),
        'url': item.get('url'),
        'provider': item.get('provider', {}).get('name') if isinstance(item.get('provider'), dict) else None,
        'service_type': item.get('serviceType'),
        'area_served': item.get('areaServed'),
    }


def _extract_product(item: dict) -> dict:
    """Extract Product schema fields."""
    offers = item.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    return {
        'name': item.get('name'),
        'description': item.get('description'),
        'url': item.get('url'),
        'image': _get_image_url(item.get('image')),
        'sku': item.get('sku'),
        'brand': item.get('brand', {}).get('name') if isinstance(item.get('brand'), dict) else item.get('brand'),
        'price': offers.get('price'),
        'currency': offers.get('priceCurrency'),
    }


def _extract_breadcrumbs(item: dict) -> list[str]:
    """Extract BreadcrumbList items."""
    breadcrumbs = []
    elements = item.get('itemListElement', [])

    for elem in sorted(elements, key=lambda x: x.get('position', 0)):
        name = elem.get('name')
        if not name:
            item_obj = elem.get('item', {})
            if isinstance(item_obj, dict):
                name = item_obj.get('name')
            elif isinstance(item_obj, str):
                name = item_obj

        if name:
            breadcrumbs.append(name)

    return breadcrumbs


def _extract_faq(item: dict) -> list[dict]:
    """Extract FAQPage questions and answers."""
    faqs = []
    main_entity = item.get('mainEntity', [])

    if not isinstance(main_entity, list):
        main_entity = [main_entity]

    for qa in main_entity:
        if not isinstance(qa, dict):
            continue
        question = qa.get('name')
        answer = qa.get('acceptedAnswer', {})
        if isinstance(answer, dict):
            answer_text = answer.get('text')
        else:
            answer_text = None

        if question:
            faqs.append({
                'question': question,
                'answer': answer_text,
            })

    return faqs


def _extract_address(address: Any) -> dict | None:
    """Extract PostalAddress fields."""
    if not address:
        return None
    if isinstance(address, str):
        return {'formatted': address}
    if isinstance(address, dict):
        return {
            'street': address.get('streetAddress'),
            'city': address.get('addressLocality'),
            'state': address.get('addressRegion'),
            'postal_code': address.get('postalCode'),
            'country': address.get('addressCountry'),
        }
    return None


def _extract_geo(geo: Any) -> dict | None:
    """Extract GeoCoordinates."""
    if not geo or not isinstance(geo, dict):
        return None
    return {
        'latitude': geo.get('latitude'),
        'longitude': geo.get('longitude'),
    }


def _extract_contact_points(contacts: Any) -> list[dict]:
    """Extract ContactPoint list."""
    if not contacts:
        return []
    if not isinstance(contacts, list):
        contacts = [contacts]

    return [
        {
            'type': c.get('contactType'),
            'telephone': c.get('telephone'),
            'email': c.get('email'),
            'area_served': c.get('areaServed'),
        }
        for c in contacts if isinstance(c, dict)
    ]


def _extract_employees(employees: Any) -> int | None:
    """Extract number of employees."""
    if not employees:
        return None
    if isinstance(employees, int):
        return employees
    if isinstance(employees, dict):
        return employees.get('value')
    return None


def _get_image_url(image: Any) -> str | None:
    """Extract image URL from various formats."""
    if not image:
        return None
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        return image.get('url') or image.get('@id')
    if isinstance(image, list) and image:
        return _get_image_url(image[0])
    return None


def aggregate_structured(pages: list[dict]) -> dict:
    """
    Aggregate structured data across multiple pages.

    Args:
        pages: List of page dicts with 'structured_data' key

    Returns:
        Aggregated structured data for site
    """
    result = {
        'organization': None,
        'website': None,
        'local_business': None,
        'services': [],
        'products': [],
        'faq': [],
        'social_links': [],
    }

    seen_services = set()
    seen_products = set()
    seen_faqs = set()

    for page in pages:
        sd = page.get('structured_data', {})
        if not sd:
            continue

        # Take first organization found
        if not result['organization'] and sd.get('organization'):
            result['organization'] = sd['organization']
            # Extract social links
            same_as = sd['organization'].get('same_as', [])
            if isinstance(same_as, list):
                result['social_links'] = same_as

        # Take first website found
        if not result['website'] and sd.get('website'):
            result['website'] = sd['website']

        # Take first local_business found
        if not result['local_business'] and sd.get('local_business'):
            result['local_business'] = sd['local_business']

        # Aggregate services (dedupe by name)
        for svc in sd.get('services', []):
            name = svc.get('name')
            if name and name not in seen_services:
                seen_services.add(name)
                result['services'].append(svc)

        # Aggregate products (dedupe by name)
        for prod in sd.get('products', []):
            name = prod.get('name')
            if name and name not in seen_products:
                seen_products.add(name)
                result['products'].append(prod)

        # Aggregate FAQ (dedupe by question)
        for faq in sd.get('faq', []):
            q = faq.get('question')
            if q and q not in seen_faqs:
                seen_faqs.add(q)
                result['faq'].append(faq)

    return result


def structured_to_dict(data: StructuredData) -> dict:
    """Convert StructuredData to JSON-serializable dict."""
    return {
        'organization': data.organization,
        'website': data.website,
        'local_business': data.local_business,
        'services': data.services,
        'products': data.products,
        'breadcrumbs': data.breadcrumbs,
        'faq': data.faq,
        'raw_count': len(data.raw_jsonld),
        'errors': data.errors if data.errors else None,
    }
