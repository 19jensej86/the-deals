"""
Ricardo Detail Page Scraper - v7.0
==================================
Scrapes additional data from Ricardo listing detail pages:
- seller_rating (100% etc.)
- shipping_cost (CHF)
- pickup_available (bool)
- Full description
- Location + postal code

Strategy:
1. Primary: JSON-LD structured data (stable, machine-readable)
2. Fallback: DOM selectors for data not in JSON-LD

Bot Avoidance:
- Max 5 detail pages per run
- Random delays 3-8 seconds between requests
- Human-like scrolling behavior
- Reuse browser context (cookies/session)
"""

import re
import json
import random
import time
from typing import Dict, Any, Optional, List
from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout


# ==============================================================================
# CONFIGURATION
# ==============================================================================

MIN_DELAY_SEC = 3.0
MAX_DELAY_SEC = 8.0
PAGE_TIMEOUT_MS = 15000


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _random_delay():
    """Human-like random delay between pages."""
    delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
    print(f"   ⏱️ Waiting {delay:.1f}s...")
    time.sleep(delay)


def _human_scroll(page: Page):
    """Simulates human-like scrolling behavior."""
    try:
        # Scroll down 3 times
        for i in range(3):
            page.evaluate(f"window.scrollBy(0, 300)")
            time.sleep(random.uniform(0.2, 0.6))
        
        # Scroll up a bit (human behavior)
        page.evaluate("window.scrollBy(0, -100)")
        time.sleep(random.uniform(0.3, 0.5))
        
    except Exception:
        pass


def _accept_cookies(page: Page):
    """Accepts cookie consent if present."""
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=1500)
        page.wait_for_timeout(300)
    except Exception:
        pass


def _extract_plz_from_text(text: str) -> Optional[str]:
    """Extracts Swiss postal code (4 digits) from text."""
    if not text:
        return None
    match = re.search(r"\b(\d{4})\b", text)
    return match.group(1) if match else None


def _extract_price_from_text(text: str) -> Optional[float]:
    """Extracts CHF price from text like 'CHF 9.00' or '9.00'."""
    if not text:
        return None
    # Remove CHF, handle Swiss formatting
    s = text.replace("CHF", "").replace("chf", "")
    s = s.replace("'", "").replace("'", "").replace("\xa0", "").strip()
    s = s.replace(" ", "").replace(",", ".")
    
    match = re.search(r"(\d+(?:\.\d{2})?)", s)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_rating_from_text(text: str) -> Optional[int]:
    """Extracts percentage rating from text like '100%' or '95%'."""
    if not text:
        return None
    match = re.search(r"(\d{1,3})%", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


# ==============================================================================
# JSON-LD EXTRACTION
# ==============================================================================

def _extract_json_ld(page: Page) -> Optional[Dict]:
    """
    Extracts JSON-LD structured data from the page.
    Ricardo uses schema.org Product data.
    """
    try:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        
        for script in scripts:
            try:
                content = script.inner_text()
                data = json.loads(content)
                
                # Handle @graph array (Ricardo uses this)
                if isinstance(data, dict) and "@graph" in data:
                    return data
                
                # Direct Product object
                if isinstance(data, dict) and data.get("@type") == "Product":
                    return {"@graph": [data]}
                
                # Array of objects
                if isinstance(data, list):
                    return {"@graph": data}
                    
            except json.JSONDecodeError:
                continue
        
        return None
        
    except Exception as e:
        print(f"   ⚠️ JSON-LD extraction failed: {e}")
        return None


def _find_in_graph(json_ld: Dict, type_name: str) -> Optional[Dict]:
    """Finds an object of specific @type in the @graph array."""
    if not json_ld or "@graph" not in json_ld:
        return None
    
    for item in json_ld["@graph"]:
        if isinstance(item, dict) and item.get("@type") == type_name:
            return item
    
    return None


# ==============================================================================
# DOM EXTRACTION (FALLBACK)
# ==============================================================================

def _extract_from_dom(page: Page) -> Dict[str, Any]:
    """
    Extracts data from DOM when JSON-LD is incomplete.
    Uses stable selectors and text patterns.
    """
    result = {
        "location": None,
        "postal_code": None,
        "shipping_method": None,
        "shipping_cost": None,
        "pickup_available": False,
        "seller_name": None,
        "seller_rating": None,
    }
    
    try:
        # Get full page text for pattern matching
        page_text = page.inner_text("body") or ""
        page_text_lower = page_text.lower()
        
        # --- PICKUP AVAILABLE ---
        if "abholung" in page_text_lower:
            result["pickup_available"] = True
        
        # --- SHIPPING ---
        # Look for patterns like "Paket B-Post, CHF 9.00"
        shipping_patterns = [
            r"(Paket[^,]+),\s*CHF\s*([\d.]+)",
            r"(Brief[^,]+),\s*CHF\s*([\d.]+)",
            r"(Einschreiben[^,]+),\s*CHF\s*([\d.]+)",
            r"Versand[^:]*:\s*CHF\s*([\d.]+)",
        ]
        
        for pattern in shipping_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    result["shipping_method"] = match.group(1).strip()
                    result["shipping_cost"] = _extract_price_from_text(match.group(2))
                else:
                    result["shipping_cost"] = _extract_price_from_text(match.group(1))
                break
        
        # --- LOCATION (from Google Maps link) ---
        try:
            location_link = page.query_selector("a[href*='maps.google']")
            if location_link:
                location_text = location_link.inner_text()
                result["location"] = location_text.strip()
                result["postal_code"] = _extract_plz_from_text(location_text)
        except Exception:
            pass
        
        # Fallback: Look for postal code pattern in page
        if not result["postal_code"]:
            # Pattern: 4 digits followed by city name
            plz_match = re.search(r"\b(\d{4})\s+([A-Za-zäöüÄÖÜ][A-Za-zäöüÄÖÜ\s-]+)", page_text)
            if plz_match:
                result["postal_code"] = plz_match.group(1)
                if not result["location"]:
                    result["location"] = f"{plz_match.group(1)} {plz_match.group(2).strip()}"
        
        # --- SELLER RATING ---
        # Look for percentage in green chip or seller section
        try:
            # Try common rating selectors
            rating_selectors = [
                ".MuiChip-root",
                "[class*='rating']",
                "[class*='seller'] span",
            ]
            
            for selector in rating_selectors:
                elements = page.query_selector_all(selector)
                for el in elements:
                    text = el.inner_text() or ""
                    rating = _extract_rating_from_text(text)
                    if rating and rating >= 50:  # Sanity check
                        result["seller_rating"] = rating
                        break
                if result["seller_rating"]:
                    break
            
            # Fallback: Search in page text
            if not result["seller_rating"]:
                rating_match = re.search(r"(\d{2,3})%\s*(?:positiv|Bewertung)", page_text, re.IGNORECASE)
                if rating_match:
                    result["seller_rating"] = int(rating_match.group(1))
                    
        except Exception:
            pass
        
        # --- SELLER NAME ---
        try:
            # Look for seller link pattern
            seller_link = page.query_selector("a[href*='/de/shop/']")
            if seller_link:
                result["seller_name"] = seller_link.inner_text().strip()
        except Exception:
            pass
        
    except Exception as e:
        print(f"   ⚠️ DOM extraction error: {e}")
    
    return result


# ==============================================================================
# MAIN DETAIL SCRAPER
# ==============================================================================

def scrape_detail_page(
    url: str,
    context: BrowserContext,
    add_delay: bool = True,
) -> Dict[str, Any]:
    """
    Scrapes a single Ricardo detail page.
    
    Returns:
        Dict with:
        - full_description: str
        - location: str (e.g., "3098 Schliern b. Köniz")
        - postal_code: str (e.g., "3098")
        - shipping_method: str (e.g., "Paket B-Post")
        - shipping_cost: float (e.g., 9.0)
        - pickup_available: bool
        - seller_name: str
        - seller_rating: int (e.g., 100)
        - scrape_success: bool
        - scrape_error: str | None
    """
    result = {
        "full_description": None,
        "location": None,
        "postal_code": None,
        "shipping_method": None,
        "shipping_cost": None,
        "pickup_available": False,
        "seller_name": None,
        "seller_rating": None,
        "scrape_success": False,
        "scrape_error": None,
    }
    
    if add_delay:
        _random_delay()
    
    page = context.new_page()
    
    try:
        print(f"   🔗 Loading detail page...")
        
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        
        _accept_cookies(page)
        _human_scroll(page)
        
        # --- 1. EXTRACT JSON-LD ---
        json_ld = _extract_json_ld(page)
        
        if json_ld:
            # Find Product object
            product = _find_in_graph(json_ld, "Product")
            
            if product:
                # Description
                result["full_description"] = product.get("description")
                
                # Offers (contains shipping info)
                offers = product.get("offers")
                if isinstance(offers, dict):
                    # Shipping details
                    shipping = offers.get("shippingDetails")
                    if isinstance(shipping, dict):
                        rate = shipping.get("shippingRate")
                        if isinstance(rate, dict):
                            result["shipping_cost"] = _extract_price_from_text(
                                str(rate.get("value", ""))
                            )
                    
                    # Seller info (sometimes embedded as string)
                    seller = offers.get("seller")
                    if isinstance(seller, dict):
                        result["seller_name"] = seller.get("name")
                    elif isinstance(seller, str):
                        # Try to parse seller name from string
                        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', seller)
                        if name_match:
                            result["seller_name"] = name_match.group(1)
        
        # --- 2. FILL GAPS FROM DOM ---
        dom_data = _extract_from_dom(page)
        
        # Only overwrite if we don't have the data yet
        if not result["location"]:
            result["location"] = dom_data.get("location")
        if not result["postal_code"]:
            result["postal_code"] = dom_data.get("postal_code")
        if not result["shipping_method"]:
            result["shipping_method"] = dom_data.get("shipping_method")
        if not result["shipping_cost"]:
            result["shipping_cost"] = dom_data.get("shipping_cost")
        if not result["seller_rating"]:
            result["seller_rating"] = dom_data.get("seller_rating")
        if not result["seller_name"]:
            result["seller_name"] = dom_data.get("seller_name")
        
        # Pickup is always from DOM
        result["pickup_available"] = dom_data.get("pickup_available", False)
        
        result["scrape_success"] = True
        
    except PWTimeout:
        result["scrape_error"] = "Timeout"
        print(f"   ⏳ Timeout loading detail page")
        
    except Exception as e:
        result["scrape_error"] = str(e)
        print(f"   ❌ Detail scrape error: {e}")
        
    finally:
        page.close()
    
    return result


# ==============================================================================
# BATCH PROCESSING
# ==============================================================================

def scrape_top_deals(
    deals: List[Dict[str, Any]],
    context: BrowserContext,
    max_pages: int = 5,
) -> List[Dict[str, Any]]:
    """
    Scrapes detail pages for top deals (by expected_profit).
    
    Args:
        deals: List of deal dicts (must have 'url' and 'expected_profit')
        context: Playwright browser context
        max_pages: Maximum number of detail pages to scrape
    
    Returns:
        Same list with added detail data (detail_scraped=True for scraped items)
    """
    if not deals:
        return deals
    
    # Sort by expected_profit (highest first)
    sorted_deals = sorted(
        [d for d in deals if d.get("url") and d.get("expected_profit")],
        key=lambda x: float(x.get("expected_profit") or 0),
        reverse=True,
    )
    
    # Take top N
    top_deals = sorted_deals[:max_pages]
    
    if not top_deals:
        print("   ⚠️ No deals with profit to scrape")
        return deals
    
    print(f"\n🔍 Scraping {len(top_deals)} detail pages (top by profit)...")
    
    # Create lookup by listing_id for updating
    deals_by_id = {d.get("listing_id"): d for d in deals if d.get("listing_id")}
    
    for i, deal in enumerate(top_deals, 1):
        url = deal.get("url")
        listing_id = deal.get("listing_id")
        title = deal.get("title", "")[:40]
        profit = deal.get("expected_profit", 0)
        
        print(f"\n   [{i}/{len(top_deals)}] {title}... (Profit: {profit:.0f} CHF)")
        
        # Scrape detail page
        detail_data = scrape_detail_page(
            url=url,
            context=context,
            add_delay=(i > 1),  # No delay for first page
        )
        
        if detail_data.get("scrape_success"):
            print(f"   ✅ Got: Rating={detail_data.get('seller_rating')}%, "
                  f"Shipping={detail_data.get('shipping_cost')} CHF, "
                  f"Pickup={detail_data.get('pickup_available')}")
        else:
            print(f"   ⚠️ Scrape failed: {detail_data.get('scrape_error')}")
        
        # Update original deal in the list
        if listing_id and listing_id in deals_by_id:
            original_deal = deals_by_id[listing_id]
            
            # Add detail data
            original_deal["detail_scraped"] = True
            original_deal["seller_rating"] = detail_data.get("seller_rating")
            original_deal["shipping_cost"] = detail_data.get("shipping_cost")
            original_deal["pickup_available"] = detail_data.get("pickup_available")
            
            # Update existing fields if we got better data
            if detail_data.get("full_description"):
                original_deal["description"] = detail_data["full_description"]
            if detail_data.get("location"):
                original_deal["location"] = detail_data["location"]
            if detail_data.get("postal_code"):
                original_deal["postal_code"] = detail_data["postal_code"]
            if detail_data.get("shipping_method"):
                original_deal["shipping"] = detail_data["shipping_method"]
    
    print(f"\n✅ Detail scraping complete ({len(top_deals)} pages)")
    
    return deals


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    """Test with a single Ricardo listing."""
    from playwright.sync_api import sync_playwright
    
    TEST_URL = "https://www.ricardo.ch/de/a/garmin-fenix-7-sapphire-solar-1307525408/"
    
    print(f"🧪 Testing detail scraper with: {TEST_URL}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        
        result = scrape_detail_page(
            url=TEST_URL,
            context=context,
            add_delay=False,
        )
        
        print("\n📋 Results:")
        for key, value in result.items():
            if key == "full_description" and value:
                print(f"   {key}: {value[:100]}...")
            else:
                print(f"   {key}: {value}")
        
        browser.close()