"""
Ricardo SERP Scraper - v6.3 (v7.1 compatible)
=============================================
CRITICAL FIX from v6.0:
- NEW: search_ricardo_for_component_prices() - prefers AUCTIONS WITH BIDS!
- Buy-now prices are ASKING prices (often inflated, never sell)
- Only auctions WITH BIDS represent ACTUAL market transactions

Features:
- Robust title extraction with fallbacks
- Proper image lazy-loading support
- Accurate bid count extraction
- Rating popup auto-close
- End time parsing with 3 FALLBACK methods
- Market price search for variants
- Market DATA search for auction-based pricing
- v6.3: Component price search with auction preference
"""

import re
import statistics
from datetime import datetime
from typing import Iterator, Dict, Any, Optional, List
from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout, Page

PRICE_RE = re.compile(r"\d[\d'' .]*", re.I)
BIDS_RE = re.compile(r"\((\d+)\s*Gebot", re.I)


def _accept_cookies(page: Page):
    """Accepts cookie consent banner if present"""
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=1500)
        page.wait_for_timeout(300)
    except Exception:
        pass


def _close_rating_popup(page: Page):
    """Closes Ricardo's rating popup if it appears."""
    try:
        close_selectors = [
            "button:has-text('Schliessen')",
            "button:has-text('Nicht jetzt')",
            "button:has-text('Später')",
            "[data-testid='rating-close']",
            ".rating-popup button.close",
            "[aria-label='Schliessen']",
            "[aria-label='Close']",
        ]
        
        for selector in close_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1000)
                    page.wait_for_timeout(300)
                    print("   ✅ Closed rating popup")
                    return True
            except Exception:
                continue
        
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
            
    except Exception:
        pass
    
    return False


def _lazy_scroll(page: Page, steps: int = 80, pause_ms: int = 250):
    """Scrolls page to trigger lazy loading of images."""
    last_h, same = 0, 0
    
    for _ in range(steps):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)
        h = page.evaluate("() => document.body.scrollHeight")
        same = same + 1 if h == last_h else 0
        last_h = h
        if same >= 4:
            break
    
    page.wait_for_timeout(1500)
    
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    
    for i in range(5):
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
        page.wait_for_timeout(400)
        _close_rating_popup(page)
    
    page.wait_for_timeout(1500)


# ==============================================================================
# JAVASCRIPT EXTRACTION - WITH 3 FALLBACK METHODS FOR END_TIME!
# ==============================================================================

JS_EXTRACT = r"""
() => {
  const out = [];
  const anchors = document.querySelectorAll("a.style_link__Z7mz9[href*='/de/a/']");
  const seen = new Set();

  const lidFromHref = (href) => {
    const m = href.match(/(\d+)(?:\/)?$/);
    return m ? m[1] : null;
  };

  for (const a of anchors) {
    const href = a.getAttribute("href");
    if (!href) continue;
    const lid = lidFromHref(href);
    if (!lid || seen.has(lid)) continue;
    seen.add(lid);

    // TITLE EXTRACTION
    let title = "";
    
    const headerBox = a.querySelector(".MuiBox-root.mui-19e7n7j");
    if (headerBox) {
      const titleSpan = headerBox.querySelector("span.MuiTypography-root");
      if (titleSpan && titleSpan.innerText) {
        title = titleSpan.innerText.trim();
      }
    }

    if (!title) {
      const allSpans = a.querySelectorAll("span.MuiTypography-root");
      for (const sp of allSpans) {
        const txt = (sp.innerText || "").trim();
        if (txt.length > 10 && 
            !/CHF/i.test(txt) && 
            !/Gebot/i.test(txt) && 
            !/Sofort/i.test(txt) && 
            !/Heute/i.test(txt) && 
            !/Morgen/i.test(txt)) {
          title = txt;
          break;
        }
      }
    }

    if (!title) {
      const imgAlt = a.querySelector("img[alt]");
      if (imgAlt) {
        const alt = (imgAlt.getAttribute("alt") || "").trim();
        if (alt && alt.length > 5 && !/boost/i.test(alt) && !/ricardo ai icon/i.test(alt)) {
          title = alt;
        }
      }
    }

    if (!title) continue;

    // IMAGE EXTRACTION
    let imgUrl = null;
    
    const imgElements = a.querySelectorAll("img");
    for (const imgEl of imgElements) {
      const src = imgEl.getAttribute("src") || "";
      if (src.includes("data:image") || src.includes("placeholder")) continue;
      if (src.includes("/icons/") || src.endsWith(".svg")) continue;
      
      if (src && src.includes("ricardostatic.ch")) {
        imgUrl = src;
        break;
      }
      
      const dataSrc = imgEl.getAttribute("data-src");
      if (dataSrc && dataSrc.includes("ricardostatic.ch")) {
        imgUrl = dataSrc;
        break;
      }
      
      const srcset = imgEl.getAttribute("srcset");
      if (srcset) {
        const firstUrl = srcset.split(",")[0].split(" ")[0].trim();
        if (firstUrl && firstUrl.includes("ricardostatic.ch")) {
          imgUrl = firstUrl;
          break;
        }
      }
      
      if (!imgUrl && src && src.startsWith("http") && !src.includes("data:")) {
        imgUrl = src;
      }
    }
    
    if (!imgUrl) {
      const bgEl = a.querySelector("[style*='background-image']");
      if (bgEl) {
        const st = bgEl.getAttribute("style") || "";
        const m = st.match(/background-image:\s*url\(['"]?(.*?)['"]?\)/i);
        if (m && m[1] && !m[1].includes("data:image")) {
          imgUrl = m[1];
        }
      }
    }

    // PRICE + BID COUNT EXTRACTION
    let currentBidPrice = null;
    let buyNowPrice = null;
    let bidCount = 0;
    
    const priceBox = a.querySelector(".MuiBox-root.mui-f0tus0");
    if (priceBox) {
      const priceRows = priceBox.querySelectorAll(".MuiBox-root");
      
      for (const row of priceRows) {
        const spans = row.querySelectorAll("span.MuiTypography-root");
        if (spans.length < 2) continue;
        
        const priceText = (spans[0].innerText || "").trim();
        const modeText = (spans[1].innerText || "").trim().toLowerCase();
        
        if (!/^\d/.test(priceText.replace(/[^\d]/g, ''))) continue;
        
        if (modeText.includes("sofort")) {
          buyNowPrice = priceText;
        } else if (modeText.includes("gebot")) {
          currentBidPrice = priceText;
          
          const bidMatch = modeText.match(/\((\d+)\s*gebot/i);
          if (bidMatch) {
            bidCount = parseInt(bidMatch[1], 10);
          }
        }
      }
      
      if (!currentBidPrice && !buyNowPrice) {
        const allSpans = priceBox.querySelectorAll("span");
        for (let i = 0; i < allSpans.length - 1; i++) {
          const priceText = (allSpans[i].innerText || "").trim();
          const modeText = (allSpans[i + 1].innerText || "").trim().toLowerCase();
          
          if (/^\d+[.,']?\d*$/.test(priceText.replace(/\s/g, ""))) {
            if (modeText.includes("sofort")) {
              buyNowPrice = priceText;
            } else if (modeText.includes("gebot")) {
              currentBidPrice = priceText;
              const bidMatch = modeText.match(/\((\d+)\s*gebot/i);
              if (bidMatch) {
                bidCount = parseInt(bidMatch[1], 10);
              }
            }
          }
        }
      }
    }

    // =========================================================================
    // END TIME EXTRACTION - 3 FALLBACK METHODS!
    // =========================================================================
    let endTimeText = null;
    
    // METHOD 1: Try specific MUI class
    const timeBox = a.querySelector(".MuiBox-root.mui-5bf3zv");
    if (timeBox && timeBox.innerText) {
      const parts = timeBox.innerText.trim().split("\n").filter(Boolean);
      if (parts.length > 0) {
        endTimeText = parts[0].trim();
      }
    }
    
    // METHOD 2: Search ALL MuiBox elements for German time patterns
    if (!endTimeText) {
      const allBoxes = a.querySelectorAll(".MuiBox-root");
      for (const box of allBoxes) {
        const txt = (box.innerText || "").trim();
        if (/^(Heute|Morgen|Mo|Di|Mi|Do|Fr|Sa|So),?\s*\d{1,2}[:.]\d{2}/i.test(txt)) {
          endTimeText = txt.split("\n")[0].trim();
          break;
        }
      }
    }
    
    // METHOD 3: Regex on entire card text
    if (!endTimeText) {
      const allText = a.innerText || "";
      const timePatterns = [
        /(Heute,?\s*\d{1,2}:\d{2})/i,
        /(Morgen,?\s*\d{1,2}:\d{2})/i,
        /([A-Za-z]{2},?\s*\d{1,2}\.?\s*[A-Za-zäöü]+\.?,?\s*\d{1,2}:\d{2})/i,
      ];
      
      for (const pattern of timePatterns) {
        const match = allText.match(pattern);
        if (match) {
          endTimeText = match[1].trim();
          break;
        }
      }
    }

    out.push({
      lid,
      href: href.startsWith("http") ? href : ("https://www.ricardo.ch" + href),
      title,
      imgUrl,
      currentBidPrice,
      buyNowPrice,
      bidCount,
      endTimeText,
    });
  }

  return out;
}
"""


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def parse_price(text: Optional[str]) -> Optional[float]:
    """Parses price string to float"""
    if not text:
        return None
    s = text
    s = s.replace("CHF", "").replace("chf", "")
    s = s.replace("'", "").replace("'", "").replace("\xa0", "").strip()
    s = s.replace(".–", "").replace(".-", "")
    s = s.replace(" ", "")
    s = s.replace(",", ".")
    m = PRICE_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def parse_bids_fallback(mode_text: Optional[str]) -> Optional[int]:
    """Fallback bid count extraction from mode text."""
    if not mode_text:
        return None
    m = BIDS_RE.search(mode_text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _calculate_hours_remaining(end_time_text: Optional[str]) -> float:
    """
    v6.0: Calculates hours remaining from end_time_text.
    
    Returns 999 if parsing fails (unknown).
    """
    if not end_time_text:
        return 999.0
    
    try:
        from utils_time import parse_ricardo_end_time
        
        end_time = parse_ricardo_end_time(end_time_text)
        if not end_time:
            return 999.0
        
        if hasattr(end_time, 'tzinfo') and end_time.tzinfo:
            from zoneinfo import ZoneInfo
            now = datetime.now(end_time.tzinfo)
        else:
            now = datetime.now()
        
        delta = end_time - now
        hours = delta.total_seconds() / 3600
        return max(0.0, hours)
        
    except Exception:
        return 999.0


# ==============================================================================
# MAIN SCRAPER
# ==============================================================================

def search_ricardo(
    query: str,
    context: BrowserContext,
    ua: Optional[str],
    timeout_sec: int = 18,
    max_pages: int = 2,
) -> Iterator[Dict[str, Any]]:
    """
    Scrapes Ricardo SERP for a search query.
    
    Yields listings with:
    - platform, listing_id, title, url
    - image_url
    - current_price_ricardo (auction) OR buy_now_price
    - bids_count
    - end_time_text
    - hours_remaining
    """
    page = context.new_page()
    if ua:
        page.set_extra_http_headers({"user-agent": ua})

    base = f"https://www.ricardo.ch/de/s/{query.replace(' ', '%20')}/"

    try:
        for pg in range(1, max_pages + 1):
            url = base if pg == 1 else f"{base}?page={pg}"
            print(f"🔍 Opening {url}")
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            except PWTimeout:
                print(f"⏳ Timeout – continuing (page {pg})")

            _accept_cookies(page)
            _close_rating_popup(page)
            _lazy_scroll(page)
            _close_rating_popup(page)

            try:
                rows = page.evaluate(JS_EXTRACT)
            except Exception as e:
                print(f"⚠️ JS extract error: {e}")
                rows = []

            print(f"📦 Extracted {len(rows)} cards")
            
            seen = set()
            for r in rows:
                lid = r.get("lid")
                if not lid or lid in seen:
                    continue
                seen.add(lid)

                img = r.get("imgUrl") or None
                title = r.get("title") or ""

                current_bid = parse_price(r.get("currentBidPrice"))
                buy_now = parse_price(r.get("buyNowPrice"))
                
                bid_count = r.get("bidCount", 0)
                
                end_time_text = r.get("endTimeText")
                hours_remaining = _calculate_hours_remaining(end_time_text)

                yield {
                    "platform": "ricardo",
                    "listing_id": lid,
                    "title": title,
                    "url": r.get("href"),
                    "image_url": img,
                    "current_price_ricardo": current_bid,
                    "buy_now_price": buy_now,
                    "bids_count": bid_count,
                    "end_time_text": end_time_text,
                    "hours_remaining": hours_remaining,
                    "description": "",
                    "location": None,
                    "postal_code": None,
                    "shipping": None,
                }
    finally:
        page.close()


# ==============================================================================
# MARKET PRICE SEARCH (v5.2 - buy-now only)
# ==============================================================================

def search_ricardo_for_prices(
    search_term: str,
    context: BrowserContext,
    ua: Optional[str] = None,
    max_results: int = 10,
    buy_now_only: bool = True,
    min_price: float = 10.0,
    timeout_sec: int = 15,
) -> List[float]:
    """
    Searches Ricardo for a specific term and returns buy-now prices.
    
    WARNING: Buy-now prices are ASKING prices, not SOLD prices!
    For more accurate pricing, use search_ricardo_for_component_prices().
    """
    prices = []
    page = context.new_page()
    
    if ua:
        page.set_extra_http_headers({"user-agent": ua})
    
    encoded = search_term.replace(" ", "%20").replace("|", "%20")
    url = f"https://www.ricardo.ch/de/s/{encoded}/"
    
    if buy_now_only:
        url += "?offer_type=fixed_price"
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
        
        _accept_cookies(page)
        _close_rating_popup(page)
        
        for _ in range(3):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(300)
        
        rows = page.evaluate(JS_EXTRACT)
        
        for r in rows:
            if len(prices) >= max_results:
                break
            
            buy_now = parse_price(r.get("buyNowPrice"))
            
            if buy_now and buy_now >= min_price:
                if buy_now_only:
                    current_bid = parse_price(r.get("currentBidPrice"))
                    if current_bid and current_bid > 0:
                        continue
                
                prices.append(buy_now)
        
    except Exception as e:
        print(f"   ⚠️ Market price search failed: {e}")
    
    finally:
        page.close()
    
    return prices


# ==============================================================================
# v6.0: MARKET DATA SEARCH
# ==============================================================================

def search_ricardo_for_market_data(
    search_term: str,
    context: BrowserContext,
    ua: Optional[str] = None,
    max_results: int = 15,
    min_price: float = 10.0,
    timeout_sec: int = 15,
) -> List[Dict[str, Any]]:
    """
    v6.0: Returns FULL listing data for market analysis.
    
    Returns all data needed for smart auction-based pricing:
    - current_price_ricardo (auction price)
    - bids_count (number of bids)
    - hours_remaining (time until auction ends)
    - buy_now_price (for ceiling calculation)
    """
    results = []
    page = context.new_page()
    
    if ua:
        page.set_extra_http_headers({"user-agent": ua})
    
    encoded = search_term.replace(" ", "%20").replace("|", "%20")
    url = f"https://www.ricardo.ch/de/s/{encoded}/"
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
        
        _accept_cookies(page)
        _close_rating_popup(page)
        
        for _ in range(4):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(350)
        
        rows = page.evaluate(JS_EXTRACT)
        
        for r in rows:
            if len(results) >= max_results:
                break
            
            current_bid = parse_price(r.get("currentBidPrice"))
            buy_now = parse_price(r.get("buyNowPrice"))
            bid_count = r.get("bidCount", 0)
            
            end_time_text = r.get("endTimeText")
            hours_remaining = _calculate_hours_remaining(end_time_text)
            
            if not current_bid and not buy_now:
                continue
            
            max_price = max(current_bid or 0, buy_now or 0)
            if max_price < min_price:
                continue
            
            results.append({
                "current_price_ricardo": current_bid,
                "buy_now_price": buy_now,
                "bids_count": bid_count,
                "hours_remaining": hours_remaining,
                "title": r.get("title", ""),
                "listing_id": r.get("lid"),
            })
    
    except Exception as e:
        print(f"   ⚠️ Market data search failed: {e}")
    
    finally:
        page.close()
    
    return results


# ==============================================================================
# v6.3: COMPONENT PRICE SEARCH (PREFERS AUCTIONS WITH BIDS!)
# ==============================================================================

def search_ricardo_for_component_prices(
    search_term: str,
    context: BrowserContext,
    ua: Optional[str] = None,
    max_results: int = 10,
    min_price: float = 5.0,
    timeout_sec: int = 15,
    prefer_auctions_with_bids: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    v6.3: Searches Ricardo for component prices, PREFERRING auctions with bids.
    
    CRITICAL INSIGHT:
    - Buy-now prices are ASKING prices (often inflated, never sell)
    - Auctions WITH BIDS represent ACTUAL market transactions
    - People don't bid on things they won't buy
    
    Priority order:
    1. Auctions with bids ending soon (< 24h) - price is almost final
    2. Auctions with 5+ bids (any time) - competitive bidding validates price
    3. Buy-now prices - FALLBACK only (apply 15% discount)
    
    Args:
        search_term: What to search (e.g., "Hantelscheibe 20kg")
        context: Playwright browser context
        ua: User agent
        max_results: Max listings to analyze
        min_price: Minimum price to include
        timeout_sec: Page load timeout
        prefer_auctions_with_bids: If True, prioritize auctions over buy-now
    
    Returns:
        Dict with:
        - median_price: float (the calculated fair price)
        - sample_size: int
        - price_source: str ("auction_with_bids" | "buy_now_fallback")
        - auction_prices: List[float] (if any)
        - buy_now_prices: List[float] (if any)
    """
    page = context.new_page()
    
    if ua:
        page.set_extra_http_headers({"user-agent": ua})
    
    encoded = search_term.replace(" ", "%20").replace("|", "%20")
    url = f"https://www.ricardo.ch/de/s/{encoded}/"
    
    auction_prices = []  # Prices from auctions WITH bids
    buy_now_prices = []  # Fallback prices from buy-now
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
        
        _accept_cookies(page)
        _close_rating_popup(page)
        
        # Scroll to load listings
        for _ in range(4):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(350)
        
        rows = page.evaluate(JS_EXTRACT)
        
        for r in rows:
            if len(auction_prices) + len(buy_now_prices) >= max_results:
                break
            
            current_bid = parse_price(r.get("currentBidPrice"))
            buy_now = parse_price(r.get("buyNowPrice"))
            bid_count = r.get("bidCount", 0)
            
            end_time_text = r.get("endTimeText")
            hours_remaining = _calculate_hours_remaining(end_time_text)
            
            # PRIORITY 1: Auctions with bids (validated by market!)
            if prefer_auctions_with_bids and current_bid and current_bid >= min_price and bid_count >= 1:
                # Weight by reliability:
                # - Ending soon (< 24h) = more reliable
                # - More bids = more reliable
                
                if hours_remaining < 24 or bid_count >= 5:
                    # High confidence - price is close to final
                    auction_prices.append(current_bid)
                elif hours_remaining < 72 and bid_count >= 2:
                    # Medium confidence
                    auction_prices.append(current_bid)
                # Otherwise skip - too early, price will change
            
            # PRIORITY 2: Buy-now prices (fallback)
            if buy_now and buy_now >= min_price:
                buy_now_prices.append(buy_now)
        
    except Exception as e:
        print(f"   ⚠️ Component price search failed: {e}")
        return None
    
    finally:
        page.close()
    
    # Calculate result
    if auction_prices and len(auction_prices) >= 2:
        # Use auction prices - they're validated by actual bidders!
        median_price = statistics.median(auction_prices)
        return {
            "median_price": round(median_price, 2),
            "sample_size": len(auction_prices),
            "price_source": "auction_with_bids",
            "auction_prices": auction_prices,
            "buy_now_prices": buy_now_prices,
        }
    
    if buy_now_prices and len(buy_now_prices) >= 2:
        # Fallback to buy-now, but apply discount (asking > selling)
        raw_median = statistics.median(buy_now_prices)
        # Apply 15% discount - buy-now prices are inflated
        median_price = raw_median * 0.85
        return {
            "median_price": round(median_price, 2),
            "sample_size": len(buy_now_prices),
            "price_source": "buy_now_discounted",
            "auction_prices": auction_prices,
            "buy_now_prices": buy_now_prices,
        }
    
    # Not enough data
    if auction_prices:
        return {
            "median_price": round(auction_prices[0], 2),
            "sample_size": 1,
            "price_source": "auction_single",
            "auction_prices": auction_prices,
            "buy_now_prices": buy_now_prices,
        }
    
    if buy_now_prices:
        return {
            "median_price": round(buy_now_prices[0] * 0.85, 2),
            "sample_size": 1,
            "price_source": "buy_now_single_discounted",
            "auction_prices": auction_prices,
            "buy_now_prices": buy_now_prices,
        }
    
    return None


def search_ricardo_for_component(
    component_name: str,
    context: BrowserContext,
    ua: Optional[str] = None,
    max_results: int = 10,
) -> List[float]:
    """
    Legacy function - searches Ricardo for a component and returns prices.
    
    For better results, use search_ricardo_for_component_prices() instead!
    """
    return search_ricardo_for_prices(
        search_term=component_name,
        context=context,
        ua=ua,
        max_results=max_results,
        buy_now_only=False,
        min_price=1.0,
    )