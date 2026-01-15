"""
AI Filter & Evaluation - v7.3.5 (Optimized Edition)
====================================================
MAJOR CHANGES in v7.3.5:
- Bundle component web search with caching
- Cache statistics tracking
- Optimized logging

MAJOR CHANGES in v7.0:

1. CLAUDE PRIMARY - OpenAI fallback
   - All AI calls use Claude (Haiku for speed, Sonnet for web search)
   - Automatic fallback to OpenAI if Claude unavailable

2. REAL WEB SEARCH (THE GAME CHANGER!)
   - Uses Claude Sonnet + web_search tool
   - Actually searches Digitec, Galaxus, etc.
   - 85-90% success rate (vs 16% with GPT memory)
   - Cached for 60 days

3. All v6.8 features preserved:
   - Weight-based pricing for fitness equipment
   - Bundle detection with vision
   - Market-based pricing from Ricardo auctions
   - Variant clustering
   - Deal score calculation

PRICING PHILOSOPHY (unchanged):
==============================
1. AUCTION DATA > AI ESTIMATES (always)
2. More bids = more trust (20+ bids = fully trusted)
3. Buy-now ceiling is a CEILING, not a floor
4. Each variant has its own reference price
5. Used items max 70% of THEIR new price
6. Premium brands/materials = higher new prices
7. Fitness equipment = always check visually for quantity
"""

import os
import random
import datetime
import json
import re
import statistics
import base64
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

# v7.3.5: Import cache statistics tracking
try:
    from utils_logging import get_cache_stats
except ImportError:
    # Fallback if utils_logging not available
    class DummyCacheStats:
        def record_web_price_hit(self): pass
        def record_web_price_miss(self): pass
        def record_variant_hit(self): pass
        def record_variant_miss(self): pass
    def get_cache_stats():
        return DummyCacheStats()


# ==============================================================================
# v7.0: CLIENT INITIALIZATION - Claude PRIMARY, OpenAI fallback
# ==============================================================================

_claude_client = None
_openai_client = None
_provider = "claude"

# Model configuration (can be overridden by config)
MODEL_FAST = "claude-3-5-haiku-20241022"      # Quick tasks: clustering, evaluation
MODEL_WEB = "claude-sonnet-4-20250514"         # Web search: new prices
MODEL_OPENAI = "gpt-4o-mini"                   # Fallback


def _init_clients():
    """Initialize AI clients based on available API keys."""
    global _claude_client, _openai_client, _provider
    
    # Try Claude first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            _claude_client = anthropic.Anthropic(api_key=anthropic_key)
            _provider = "claude"
            print("🤖 AI Filter: Claude initialized ✅")
        except ImportError:
            print("⚠️ anthropic package not installed")
        except Exception as e:
            print(f"⚠️ Claude init failed: {e}")
    
    # Also init OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=openai_key)
            if _claude_client is None:
                _provider = "openai"
                print("🤖 AI Filter: Using OpenAI (fallback)")
            else:
                print("🤖 AI Filter: OpenAI available as fallback")
        except ImportError:
            print("⚠️ openai package not installed")
    
    if _claude_client is None and _openai_client is None:
        print("❌ No AI client available! Set ANTHROPIC_API_KEY or OPENAI_API_KEY")


# Initialize on module load
_init_clients()


# ==============================================================================
# CONSTANTS
# ==============================================================================

# v7.3.3: CORRECTED COSTS based on ACTUAL billing ($2.31 for 6 web searches)
# Web search with Sonnet includes large search result tokens!
# Real cost: ~$0.35-0.40 per web search batch
COST_CLAUDE_HAIKU = 0.003          # ~3k tokens × $1/1M = $0.003
COST_CLAUDE_SONNET = 0.01          # ~3k tokens × $3/1M = $0.01  
COST_CLAUDE_WEB_SEARCH = 0.35      # REAL COST: ~$0.35 per batch (includes search results)
COST_OPENAI_TEXT = 0.001
COST_VISION = 0.007

# v7.3.4: Adjusted limits for SINGLE web search strategy
# With single batch strategy: 1 search = all products = $0.35
DAILY_COST_LIMIT = 3.00            # ~8 full runs per day
DAILY_VISION_LIMIT = 50
DAILY_WEB_SEARCH_LIMIT = 5         # Max 5 single searches = ~$1.75

WEB_SEARCH_COUNT_TODAY: int = 0
WEB_SEARCH_ENABLED: bool = True  # v7.3.2: Toggle via config.yaml to save costs
WEB_PRICE_CACHE_FILE = "web_price_cache.json"
WEB_PRICE_CACHE_DAYS = 60
_web_price_cache: Dict[str, Dict] = {}

RICARDO_FEE_PERCENT = 0.10
SHIPPING_COST_CHF = 0.0
MIN_PROFIT_THRESHOLD = 20.0

BUNDLE_ENABLED = True
BUNDLE_DISCOUNT_PERCENT = 0.10
BUNDLE_MIN_COMPONENT_VALUE = 10.0
BUNDLE_USE_VISION = True

CACHE_ENABLED = True
VARIANT_CACHE_DAYS = 30
COMPONENT_CACHE_DAYS = 30
CLUSTER_CACHE_DAYS = 7
CATEGORY_THRESHOLD_CACHE_DAYS = 90

RUN_COST_USD: float = 0.0
DAY_COST_FILE = "ai_cost_day.txt"

VARIANT_CACHE_FILE = "variant_cache.json"
COMPONENT_CACHE_FILE = "component_cache.json"
CLUSTER_CACHE_FILE = "variant_cluster_cache.json"
CATEGORY_THRESHOLD_CACHE_FILE = "category_threshold_cache.json"

USE_VISION = True
VISION_RATE = 0.10
DEFAULT_CAR_MODEL = "VW Touran"

MIN_SAMPLES_FOR_MARKET_PRICE = 2
MIN_HOURS_FOR_PRICE_TRUST = 6
MIN_BIDS_FOR_PRICE_TRUST = 8

UNREALISTIC_PRICE_RATIO = 0.20
HIGH_DEMAND_BID_COUNT = 12
MODERATE_BID_COUNT = 5

HIGH_ACTIVITY_BID_THRESHOLD = 10
VERY_HIGH_ACTIVITY_BID_THRESHOLD = 20
HIGH_ACTIVITY_MIN_PRICE_RATIO = 0.15

MAX_RESALE_PERCENT_OF_NEW = 0.70
MAX_BUNDLE_RESALE_PERCENT_OF_NEW = 0.85

COMPONENT_MARKET_TRUST_MULTIPLIER = 5.0


# ==============================================================================
# v7.0: UNIFIED AI CALL WRAPPER
# ==============================================================================

def _call_claude(
    prompt: str,
    max_tokens: int = 500,
    model: str = None,
    use_web_search: bool = False,
    image_url: str = None,
) -> Optional[str]:
    """
    Call Claude API with optional web search or vision.
    
    Args:
        prompt: The prompt text
        max_tokens: Maximum response tokens
        model: Override model (default: MODEL_FAST)
        use_web_search: Enable web search tool
        image_url: Optional image URL for vision
    
    Returns:
        Response text or None on error
    """
    if not _claude_client:
        return None
    
    # Select model
    if use_web_search:
        selected_model = MODEL_WEB
    else:
        selected_model = model or MODEL_FAST
    
    try:
        # Build messages
        if image_url:
            # Vision request
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {"type": "url", "url": image_url}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        # Build request kwargs
        kwargs = {
            "model": selected_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        
        # Add web search tool if requested
        if use_web_search:
            kwargs["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search"
            }]
        
        response = _claude_client.messages.create(**kwargs)
        
        # Extract text from response (handle multiple content blocks)
        result_parts = []
        for block in response.content:
            if hasattr(block, 'text'):
                result_parts.append(block.text)
        
        return "\n".join(result_parts) if result_parts else None
        
    except Exception as e:
        error_str = str(e)
        # Re-raise 429 rate limit errors so retry logic can handle them
        if "429" in error_str or "rate_limit" in error_str.lower():
            raise  # Let caller handle rate limits
        print(f"⚠️ Claude API error: {e}")
        return None


def _call_openai(
    prompt: str,
    max_tokens: int = 500,
    model: str = None,
    image_url: str = None,
) -> Optional[str]:
    """Call OpenAI API (fallback)."""
    if not _openai_client:
        return None
    
    selected_model = model or MODEL_OPENAI
    
    try:
        if image_url:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        response = _openai_client.chat.completions.create(
            model=selected_model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"⚠️ OpenAI API error: {e}")
        return None


def call_ai(
    prompt: str,
    max_tokens: int = 500,
    use_web_search: bool = False,
    image_url: str = None,
) -> Optional[str]:
    """
    Unified AI call with automatic provider selection.
    
    Uses Claude if available, falls back to OpenAI.
    Web search only available with Claude.
    """
    # Try Claude first
    if _provider == "claude" and _claude_client:
        result = _call_claude(
            prompt=prompt,
            max_tokens=max_tokens,
            use_web_search=use_web_search,
            image_url=image_url,
        )
        if result:
            return result
    
    # Fallback to OpenAI (no web search)
    if _openai_client:
        if use_web_search:
            print("   ⚠️ Web search not available with OpenAI fallback")
        return _call_openai(
            prompt=prompt,
            max_tokens=max_tokens,
            image_url=image_url,
        )
    
    return None


# ==============================================================================
# v7.3: BATCH WEB SEARCH WITH RATE LIMIT HANDLING
# ==============================================================================

def _call_claude_with_retry(
    prompt: str,
    max_tokens: int = 500,
    use_web_search: bool = False,
    max_retries: int = 2,
) -> Optional[str]:
    """
    v7.3.3: Call Claude with LONG wait on rate limit.
    
    Strategy: Wait 120s on first rate limit hit instead of quick retries.
    This saves money because each retry costs ~$0.08!
    User prefers waiting over paying multiple times.
    """
    import time
    
    for attempt in range(max_retries):
        try:
            result = _call_claude(
                prompt=prompt,
                max_tokens=max_tokens,
                use_web_search=use_web_search,
            )
            return result
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                # v7.3.3: Wait 120s on first hit, 180s on second
                # This avoids paying for multiple failed attempts!
                wait_time = 120 if attempt == 0 else 180
                print(f"   ⏳ Rate limit hit, waiting {wait_time}s (saves money vs quick retries)...")
                time.sleep(wait_time)
            else:
                print(f"   ⚠️ Claude error: {e}")
                return None
    
    print("   ⚠️ Rate limit still active after waiting")
    return None


def search_web_batch_for_new_prices(
    variant_keys: List[str],
    category: str = "unknown",
    query_analysis: Optional[Dict] = None
) -> Dict[str, Dict[str, Any]]:
    """
    v7.3.4: SINGLE WEB SEARCH STRATEGY - 83% cost reduction!
    
    Changes:
    - Wait 120s UPFRONT (proactive rate limit prevention)
    - ONE large batch (25 products) instead of multiple small batches
    - No retry logic needed (rate limit already handled)
    - Cost: $0.35 instead of $2.10 (6 batches × $0.35)
    
    v7.3.3: Uses clean_search_term() for better results
    """
    global RUN_COST_USD, WEB_SEARCH_COUNT_TODAY
    import time
    from query_analyzer import clean_search_term
    
    if not variant_keys:
        return {}
    
    # v7.3.2: Check if web search is enabled
    if not WEB_SEARCH_ENABLED:
        print("   ℹ️ Web search DISABLED (config.yaml) - using AI estimation only")
        return {}
    
    # Check budget
    if is_budget_exceeded():
        return {}
    
    if WEB_SEARCH_COUNT_TODAY >= DAILY_WEB_SEARCH_LIMIT:
        print("🚫 Daily web search limit reached")
        return {}
    
    # Claude with web search required
    if not _claude_client:
        print("   ⚠️ Web search requires Claude API")
        return {}
    
    results = {}
    
    # Check cache first for all variants
    uncached = []
    for vk in variant_keys:
        cached = get_cached_web_price(vk)
        if cached:
            results[vk] = cached
            get_cache_stats().record_web_price_hit()
            print(f"   💾 Cached: {vk[:40]}... = {cached['new_price']} CHF")
        else:
            uncached.append(vk)
            get_cache_stats().record_web_price_miss()
    
    if not uncached:
        return results
    
    # v7.3.4: SINGLE WEB SEARCH STRATEGY
    # Wait 120s UPFRONT to avoid rate limits completely
    # Then do ONE large batch with all products
    print(f"\n🌐 v7.3.4: SINGLE web search for {len(uncached)} products (cost-optimized)")
    print(f"   ⏳ Waiting 120s upfront (proactive rate limit prevention)...")
    time.sleep(120)
    
    # Process all uncached products in ONE batch (max 30 = ~25k tokens, safe under 30k limit)
    batch_size = 30
    for i in range(0, len(uncached), batch_size):
        batch = uncached[i:i + batch_size]
        
        print(f"\n   🌐 Web search batch: {len(batch)} products...")
        
        # v7.3.3: Clean search terms for better results
        # "Garmin Fenix 6 Smartwatch inkl. Zubehör" → "Garmin Fenix 6"
        cleaned_terms = []
        for idx, vk in enumerate(batch):
            # CRITICAL: Sanitize variant_key BEFORE cleaning
            # AI bundle detection can return names like "Hantelscheiben {'4x10kg': True}"
            # Step 1: Normalize to string
            vk_str = str(vk) if vk else ""
            if not vk_str.strip():
                continue
            
            # Step 2: Remove stringified dict/list artifacts using regex
            import re
            vk_str = re.sub(r'\{[^}]*\}', '', vk_str)  # Remove {...}
            vk_str = re.sub(r'\[[^\]]*\]', '', vk_str)  # Remove [...]
            
            # Step 3: Normalize whitespace
            vk_str = re.sub(r'\s+', ' ', vk_str).strip()
            
            # Step 4: Skip if empty after sanitization
            if not vk_str:
                print(f"   ⚠️ Skipping empty variant_key after sanitization")
                continue
            
            # Step 5: Apply clean_search_term for additional normalization
            clean = clean_search_term(vk_str, query_analysis)
            cleaned_terms.append((idx, vk_str, clean))
            if clean != vk_str:
                print(f"   🔧 Cleaned: '{vk_str[:40]}' → '{clean}'")
        
        # OBSERVABILITY: Log websearch input for debugging
        for idx, vk_original, clean_query in cleaned_terms:
            print(f"   🔎 Websearch input: product='{clean_query}' | query=\"{clean_query}\"")
        
        product_list = "\n".join([f"{idx+1}. {clean}" for idx, vk, clean in cleaned_terms])
        
        # Compact prompt to minimize tokens
        prompt = f"""Finde Schweizer Neupreise (CHF) für diese {len(batch)} Produkte.
Kategorie: {category}

PRODUKTE:
{product_list}

Suche in: Digitec.ch, Galaxus.ch, Zalando.ch, Decathlon.ch, Manor.ch

Antworte NUR als JSON-Array:
[
  {{"nr": 1, "price": 199.00, "shop": "Galaxus", "conf": 0.9}},
  {{"nr": 2, "price": null, "shop": null, "conf": 0.0}},
  ...
]

Bei unbekannt: price=null, conf=0"""

        try:
            raw = _call_claude_with_retry(
                prompt=prompt,
                max_tokens=800,
                use_web_search=True,
                max_retries=3,
            )
            
            if not raw:
                print("   ⚠️ No response from batch web search")
                continue
            
            # Track cost (one web search for the batch)
            add_cost(COST_CLAUDE_WEB_SEARCH)
            WEB_SEARCH_COUNT_TODAY += 1
            
            # Parse JSON array response
            json_match = re.search(r'\[[\s\S]*\]', raw)
            if not json_match:
                print(f"   ⚠️ No JSON array in batch response")
                continue
            
            parsed = json.loads(json_match.group(0))
            
            for item in parsed:
                nr = item.get("nr", 0) - 1  # Convert to 0-indexed
                if 0 <= nr < len(batch):
                    vk = batch[nr]
                    price = item.get("price")
                    shop = item.get("shop")
                    conf = item.get("conf", 0.0)
                    
                    if price and price > 0 and conf >= 0.6:
                        price_source = f"web_{shop.lower()}" if shop else "web_batch"
                        
                        result = {
                            "new_price": float(price),
                            "price_source": price_source,
                            "shop_name": shop,
                            "confidence": conf,
                        }
                        
                        # Cache it
                        set_cached_web_price(vk, result["new_price"], price_source, shop or "unknown")
                        results[vk] = result
                        print(f"   ✅ {vk[:40]}... = {price} CHF ({shop})")
                    else:
                        print(f"   ⚠️ {vk[:40]}... = no price found")
                        
        except Exception as e:
            print(f"   ⚠️ Batch web search failed: {e}")
    
    return results


# ==============================================================================
# v6.8: WEIGHT-BASED PRICING VALIDATION (unchanged)
# ==============================================================================

WEIGHT_PRICING = {
    "standard": {"new_price_per_kg": 3.5, "resale_rate": 0.60},  # Gusseisen
    "bumper": {"new_price_per_kg": 5.0, "resale_rate": 0.55},    # Bumper Plates
    "competition": {"new_price_per_kg": 9.0, "resale_rate": 0.50}, # Competition/Calibrated (v9.0: erhöht von 8)
    "rubber": {"new_price_per_kg": 4.0, "resale_rate": 0.55},    # Rubber coated
    "calibrated": {"new_price_per_kg": 9.0, "resale_rate": 0.50}, # v9.0: Calibrated = Competition
}

WEIGHT_PLATE_KEYWORDS = [
    # Deutsch
    "hantelscheiben", "hantelscheibe", "gewichte", "gewicht",
    "hantel", "langhantel", "kurzhantel", "kettlebell", "bumper",
    "hantelset", "gewichtsscheibe", "gewichtsscheiben",
    # Englisch
    "plates", "plate", "weight plate", "dumbbell", "barbell",
    # Französisch (v9.0)
    "disques", "disque", "musculation", "haltère", "poids",
    # Technische
    "olympia", "50mm", "30mm",
]


def is_weight_plate(text: str) -> bool:
    """Check if text describes weight plates/fitness equipment."""
    text_lower = text.lower()
    for kw in WEIGHT_PLATE_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def extract_weight_kg(text: str) -> Optional[float]:
    """
    v7.3.3: Improved weight extraction from text.
    Handles patterns like:
    - "20kg", "20 kg" → 20
    - "4x 5kg" → 20 (total)
    - "Set 4x 5kg" → 20 (total)
    - "8x1.25kg" → 10 (total)
    """
    import re
    text_lower = text.lower()
    
    # Pattern 1: Quantity x Weight (e.g., "4x 5kg", "8x1.25kg")
    qty_match = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', text_lower)
    if qty_match:
        qty = int(qty_match.group(1))
        per_piece = float(qty_match.group(2).replace(',', '.'))
        return qty * per_piece
    
    # Pattern 2: Total weight (e.g., "20kg", "12.5 kg")
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', text_lower)
    if match:
        return float(match.group(1).replace(',', '.'))
    return None


def get_weight_type(text: str) -> str:
    """Determine weight plate type from text."""
    text_lower = text.lower()
    
    # v9.0: Explicit keyword detection for weight types
    # Calibrated/Competition plates (most expensive)
    if any(kw in text_lower for kw in ["calibr", "kalib", "competition", "wettkampf", "ipf", "iwf"]):
        return "calibrated"
    
    # Bumper plates
    if any(kw in text_lower for kw in ["bumper", "urethane", "pu-", "stoßdämpf"]):
        return "bumper"
    
    # Rubber coated
    if any(kw in text_lower for kw in ["rubber", "gummi", "beschicht"]):
        return "rubber"
    
    # Default: standard cast iron
    return "standard"


def validate_weight_price(text: str, price: float, is_resale: bool = True) -> Tuple[float, str]:
    """Validate and potentially adjust weight plate pricing."""
    if not is_weight_plate(text):
        return price, "not_weight_plate"

    weight_kg = extract_weight_kg(text)
    if not weight_kg or weight_kg <= 0:
        return price, "no_weight_found"

    weight_type = get_weight_type(text)
    pricing = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])

    if is_resale:
        max_price = weight_kg * pricing["max_resale_per_kg"]
        typical_price = weight_kg * pricing["typical_resale_per_kg"]
    else:
        max_price = weight_kg * pricing["new_price_per_kg"]
        typical_price = max_price * 0.8

    if price > max_price:
        return typical_price, f"capped_to_{weight_type}_{weight_kg}kg"

    return price, f"valid_{weight_type}_{weight_kg}kg"


# ==============================================================================
# CACHE MANAGEMENT
# ==============================================================================

_variant_cache: Dict[str, Dict] = {}
_component_cache: Dict[str, Dict] = {}
_cluster_cache: Dict[str, Dict] = {}

def _load_caches():
    """Load all caches from disk."""
    global _variant_cache, _component_cache, _cluster_cache, _web_price_cache
    
    try:
        if os.path.exists(VARIANT_CACHE_FILE):
            with open(VARIANT_CACHE_FILE, "r", encoding="utf-8") as f:
                _variant_cache = json.load(f)
    except:
        _variant_cache = {}
    
    try:
        if os.path.exists(COMPONENT_CACHE_FILE):
            with open(COMPONENT_CACHE_FILE, "r", encoding="utf-8") as f:
                _component_cache = json.load(f)
    except:
        _component_cache = {}
    
    try:
        if os.path.exists(CLUSTER_CACHE_FILE):
            with open(CLUSTER_CACHE_FILE, "r", encoding="utf-8") as f:
                _cluster_cache = json.load(f)
    except:
        _cluster_cache = {}
    
    try:
        if os.path.exists(WEB_PRICE_CACHE_FILE):
            with open(WEB_PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                _web_price_cache = json.load(f)
    except:
        _web_price_cache = {}

def _save_cluster_cache():
    """Save cluster cache to disk."""
    if not CACHE_ENABLED:
        return
    try:
        with open(CLUSTER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cluster_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Cluster cache save failed: {e}")

def get_cached_web_price(variant_key: str) -> Optional[Dict[str, Any]]:
    """Get cached web price for a variant."""
    global _web_price_cache
    
    if variant_key in _web_price_cache:
        cached = _web_price_cache[variant_key]
        cached_at = cached.get("cached_at", "")
        
        if cached_at:
            try:
                cached_date = datetime.datetime.fromisoformat(cached_at)
                age_days = (datetime.datetime.now() - cached_date).days
                
                if age_days < WEB_PRICE_CACHE_DAYS:
                    return {
                        "new_price": cached.get("new_price"),
                        "price_source": cached.get("price_source"),
                        "shop_name": cached.get("shop_name"),
                        "confidence": cached.get("confidence", 0.8),
                    }
            except:
                pass
    
    return None

def set_cached_web_price(variant_key: str, new_price: float, price_source: str, shop_name: str):
    """Cache a web price for a variant."""
    global _web_price_cache
    
    _web_price_cache[variant_key] = {
        "new_price": new_price,
        "price_source": price_source,
        "shop_name": shop_name,
        "confidence": 0.8,
        "cached_at": datetime.datetime.now().isoformat(),
    }
    
    if CACHE_ENABLED:
        try:
            with open(WEB_PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_web_price_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Web price cache save failed: {e}")

def get_cached_variant_info(variant_key: str) -> Optional[Dict[str, Any]]:
    """Get cached variant info."""
    global _variant_cache
    
    if variant_key in _variant_cache:
        cached = _variant_cache[variant_key]
        cached_at = cached.get("cached_at", "")
        
        if cached_at:
            try:
                cached_date = datetime.datetime.fromisoformat(cached_at)
                age_days = (datetime.datetime.now() - cached_date).days
                
                if age_days < VARIANT_CACHE_DAYS:
                    return cached
            except:
                pass
    
    return None

def set_cached_variant_info(variant_key: str, new_price: float, transport_car: bool, resale_price: float, is_bundle: bool, bundle_component_count: int):
    """Cache variant info."""
    global _variant_cache
    
    _variant_cache[variant_key] = {
        "new_price": new_price,
        "transport_car": transport_car,
        "resale_price": resale_price,
        "is_bundle": is_bundle,
        "bundle_component_count": bundle_component_count,
        "cached_at": datetime.datetime.now().isoformat(),
    }
    
    if CACHE_ENABLED:
        try:
            with open(VARIANT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_variant_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Variant cache save failed: {e}")

def _get_new_price_estimate(query_analysis: Optional[Dict]) -> float:
    """Extract new price estimate from query analysis."""
    if not query_analysis:
        return 100.0
    
    new_price = query_analysis.get("new_price_estimate")
    if new_price and new_price > 0:
        return float(new_price)
    
    return 100.0

def _get_min_realistic_price(query_analysis: Optional[Dict]) -> float:
    """Extract minimum realistic price from query analysis."""
    if not query_analysis:
        return 10.0
    
    min_price = query_analysis.get("min_realistic_price")
    if min_price and min_price > 0:
        return float(min_price)
    
    return 10.0

def _get_category(query_analysis: Optional[Dict]) -> str:
    """Extract category from query analysis."""
    if not query_analysis:
        return "unknown"
    
    category = query_analysis.get("category")
    if category:
        return str(category)
    
    return "unknown"

def _get_resale_rate(query_analysis: Optional[Dict]) -> float:
    """Extract resale rate from query analysis."""
    if not query_analysis:
        return 0.50
    
    resale_rate = query_analysis.get("resale_rate")
    if resale_rate and resale_rate > 0:
        return float(resale_rate)
    
    return 0.50

def _get_auction_multiplier(query_analysis: Optional[Dict]) -> float:
    """Get typical auction price multiplier for category."""
    if not query_analysis:
        return 2.0
    
    category = query_analysis.get("category", "unknown")
    
    # Category-specific multipliers
    multipliers = {
        "electronics": 1.5,
        "clothing": 2.5,
        "fitness": 1.8,
        "toys": 2.0,
        "collectibles": 3.0,
        "tools": 1.5,
        "furniture": 1.3,
    }
    
    return multipliers.get(category, 2.0)

def predict_final_auction_price(
    current_price: float,
    bids_count: int,
    hours_remaining: float,
    median_price: Optional[float] = None,
    new_price: Optional[float] = None,
    typical_multiplier: float = 2.0,
) -> Dict[str, Any]:
    """Predict final auction price based on current state."""
    if not current_price or current_price <= 0:
        return {"predicted_final_price": 0, "confidence": 0, "method": "no_price"}
    
    # If auction is ending soon with many bids, price is likely final
    if hours_remaining < 2 and bids_count >= 5:
        return {
            "predicted_final_price": current_price * 1.05,
            "confidence": 0.85,
            "method": "ending_soon_high_activity"
        }
    
    if hours_remaining < 6 and bids_count >= 3:
        return {
            "predicted_final_price": current_price * 1.10,
            "confidence": 0.75,
            "method": "ending_soon"
        }
    
    # Use median price if available
    if median_price and median_price > current_price:
        predicted = min(median_price, current_price * typical_multiplier)
        return {
            "predicted_final_price": predicted,
            "confidence": 0.60,
            "method": "median_based"
        }
    
    # Fallback: estimate based on bid activity
    if bids_count >= 10:
        multiplier = 1.3
    elif bids_count >= 5:
        multiplier = 1.5
    elif bids_count >= 2:
        multiplier = 1.8
    else:
        multiplier = typical_multiplier
    
    predicted = current_price * multiplier
    
    # Cap at new price if known
    if new_price and predicted > new_price * 0.90:
        predicted = new_price * 0.90
    
    # v9.0 FIX: predicted_final can NEVER be less than current_price!
    # This is logically impossible - auctions only go UP
    if predicted < current_price:
        predicted = current_price * 1.1  # At least 10% above current
    
    return {
        "predicted_final_price": round(predicted, 2),
        "confidence": 0.50,
        "method": "bid_activity_estimate"
    }

# ==============================================================================
# CATEGORY THRESHOLD CACHE (v7.2.2)
# ==============================================================================

_category_threshold_cache: Dict[str, Dict] = {}

def _load_category_threshold_cache():
    """v7.2.2: Loads category threshold cache from disk."""
    global _category_threshold_cache
    
    try:
        if os.path.exists(CATEGORY_THRESHOLD_CACHE_FILE):
            with open(CATEGORY_THRESHOLD_CACHE_FILE, "r", encoding="utf-8") as f:
                _category_threshold_cache = json.load(f)
            
            now = datetime.datetime.now().isoformat()
            expired = [k for k, v in _category_threshold_cache.items() 
                      if v.get("expires_at", "") < now]
            for k in expired:
                del _category_threshold_cache[k]
            
            if expired:
                _save_category_threshold_cache()
                
    except Exception as e:
        print(f"⚠️ Category threshold cache load failed: {e}")
        _category_threshold_cache = {}


def _save_category_threshold_cache():
    """v7.2.2: Saves category threshold cache to disk."""
    if not CACHE_ENABLED:
        return
    try:
        with open(CATEGORY_THRESHOLD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_category_threshold_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Category threshold cache save failed: {e}")


def get_category_threshold(category: str) -> Dict[str, float]:
    """v7.2.2: Get or calculate category-specific validation thresholds.
    
    Returns:
        {
            "min_single_bid_ratio": 0.40,  # Minimum % of new price for single bid
            "min_buy_now_ratio": 0.30,     # Minimum % of buy-now for single bid
            "depreciation_rate": 0.50,     # How fast value drops (electronics=0.50, fitness=0.30)
        }
    """
    global _category_threshold_cache
    
    _load_category_threshold_cache()
    
    # Check cache
    if category in _category_threshold_cache:
        cached = _category_threshold_cache[category]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            return {
                "min_single_bid_ratio": cached.get("min_single_bid_ratio", 0.40),
                "min_buy_now_ratio": cached.get("min_buy_now_ratio", 0.30),
                "depreciation_rate": cached.get("depreciation_rate", 0.50),
            }
    
    # Ask AI to calculate thresholds
    print(f"   🤖 Calculating category thresholds for: {category}")
    
    prompt = f"""Analysiere die Kategorie "{category}" für ricardo.ch Wiederverkauf.

Bestimme:
1. Wie schnell verliert diese Kategorie an Wert? (depreciation_rate: 0.0-1.0)
   - 0.70-0.80 = sehr schnell (z.B. Smartphones, Mode)
   - 0.40-0.60 = mittel (z.B. Laptops, Uhren)
   - 0.20-0.30 = langsam (z.B. Fitness-Gewichte, Werkzeug)

2. Minimum akzeptabler Gebotspreis bei 1 Gebot (min_single_bid_ratio: 0.0-1.0)
   - Prozent vom Neupreis
   - Schneller Wertverlust = höherer Threshold (0.50)
   - Langsamer Wertverlust = niedrigerer Threshold (0.30)

3. Minimum akzeptabler Gebotspreis vs Buy-Now (min_buy_now_ratio: 0.0-1.0)
   - Prozent vom Buy-Now Preis
   - Meist 0.30 (30%)

BEISPIELE:
- electronics: depreciation=0.50, min_single_bid=0.40, min_buy_now=0.30
- fitness: depreciation=0.30, min_single_bid=0.30, min_buy_now=0.30
- clothing: depreciation=0.70, min_single_bid=0.50, min_buy_now=0.40
- tools: depreciation=0.25, min_single_bid=0.30, min_buy_now=0.30

Antworte NUR als JSON:
{{
  "depreciation_rate": 0.50,
  "min_single_bid_ratio": 0.40,
  "min_buy_now_ratio": 0.30,
  "reasoning": "Kurze Erklärung"
}}"""
    
    try:
        raw = call_ai(prompt, max_tokens=300)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                depreciation_rate = float(parsed.get("depreciation_rate", 0.50))
                min_single_bid_ratio = float(parsed.get("min_single_bid_ratio", 0.40))
                min_buy_now_ratio = float(parsed.get("min_buy_now_ratio", 0.30))
                reasoning = parsed.get("reasoning", "")
                
                # Cache for 90 days
                now = datetime.datetime.now()
                expires = now + datetime.timedelta(days=90)
                
                _category_threshold_cache[category] = {
                    "depreciation_rate": depreciation_rate,
                    "min_single_bid_ratio": min_single_bid_ratio,
                    "min_buy_now_ratio": min_buy_now_ratio,
                    "reasoning": reasoning,
                    "cached_at": now.isoformat(),
                    "expires_at": expires.isoformat(),
                }
                
                _save_category_threshold_cache()
                
                print(f"   ✅ Category thresholds: depreciation={depreciation_rate:.0%}, single_bid={min_single_bid_ratio:.0%}, buy_now={min_buy_now_ratio:.0%}")
                print(f"      Reasoning: {reasoning}")
                
                return {
                    "min_single_bid_ratio": min_single_bid_ratio,
                    "min_buy_now_ratio": min_buy_now_ratio,
                    "depreciation_rate": depreciation_rate,
                }
    except Exception as e:
        print(f"⚠️ Category threshold calculation failed: {e}")
    
    # Fallback to defaults
    return {
        "min_single_bid_ratio": 0.40,
        "min_buy_now_ratio": 0.30,
        "depreciation_rate": 0.50,
    }


def calculate_confidence_weight(bids: int, hours: float) -> float:
    """Calculate confidence weight based on bid count and time remaining."""
    bid_weight = min(bids / 10.0, 1.0)
    time_weight = 1.0 if hours < 6 else (0.7 if hours < 24 else 0.5)
    return bid_weight * time_weight


def weighted_median(price_samples: List[Dict[str, Any]]) -> float:
    """Calculate weighted median from price samples."""
    if not price_samples:
        return 0.0
    
    if len(price_samples) == 1:
        return price_samples[0]["price"]
    
    # Sort by price
    sorted_samples = sorted(price_samples, key=lambda x: x["price"])
    
    # Calculate total weight
    total_weight = sum(s["weight"] for s in sorted_samples)
    
    if total_weight == 0:
        # Fallback to simple median
        return sorted_samples[len(sorted_samples) // 2]["price"]
    
    # Find weighted median
    cumulative_weight = 0.0
    target_weight = total_weight / 2.0
    
    for sample in sorted_samples:
        cumulative_weight += sample["weight"]
        if cumulative_weight >= target_weight:
            return sample["price"]
    
    # Fallback
    return sorted_samples[-1]["price"]


def is_realistic_auction_price(current_price: float, bids_count: int, hours_remaining: float, reference_price: float, for_market_calculation: bool = True) -> Tuple[bool, str]:
    """v7.2.1: Improved validation - reject early auctions with unrealistic prices."""
    if not current_price or current_price <= 0:
        return False, "no_price"
    if not reference_price or reference_price <= 0:
        reference_price = 100.0
    price_ratio = current_price / reference_price if reference_price > 0 else 0

    # v7.2.1: Early auction check - even with many bids, price must be realistic
    # Example: iPhone (1500 CHF) at 22 CHF after 1 day with 20 bids → REJECT
    if price_ratio < 0.20:
        return False, f"unrealistic_price_{price_ratio*100:.0f}pct"
    
    if bids_count >= VERY_HIGH_ACTIVITY_BID_THRESHOLD:
        # v7.2.1: Even with 20+ bids, require minimum 15% of reference price
        if price_ratio >= 0.15:
            return True, "very_high_activity_trusted"
        else:
            return False, f"very_high_activity_too_low_{price_ratio*100:.0f}pct"
    
    if bids_count >= HIGH_ACTIVITY_BID_THRESHOLD:
        if price_ratio >= HIGH_ACTIVITY_MIN_PRICE_RATIO:
            return True, "high_activity_validated"
        else:
            return False, f"high_activity_low_price_{price_ratio*100:.0f}pct"

    if for_market_calculation:
        if hours_remaining > 12:
            return False, "too_early_for_market_calc"
        minimum_for_market = max(reference_price * 0.20, 10.0)
        if current_price >= minimum_for_market:
            return True, "market_ending_soon_good_price"
        if hours_remaining < 2 and bids_count >= 3:
            return True, "market_ending_now"
        if hours_remaining < 6 and bids_count >= 8:
            return True, "market_ending_soon_high_activity"
        if hours_remaining < 12 and bids_count >= 5 and price_ratio >= 0.12:
            return True, "market_moderate_activity"
        return False, "market_insufficient_data"

    minimum_threshold = max(reference_price * UNREALISTIC_PRICE_RATIO, 10.0)
    if current_price >= minimum_threshold:
        return True, "above_threshold"
    if hours_remaining < 2:
        return True, "ending_now"
    if hours_remaining < MIN_HOURS_FOR_PRICE_TRUST and bids_count >= MODERATE_BID_COUNT:
        return True, "ending_soon_active"
    if bids_count >= HIGH_DEMAND_BID_COUNT:
        return True, "high_demand_validated"
    return False, f"below_{minimum_threshold:.0f}_insufficient_validation"


def apply_global_sanity_check(resale_price: float, reference_price: float, is_bundle: bool, source: str) -> float:
    """Apply global sanity checks to prevent unrealistic resale prices."""
    if not reference_price or reference_price <= 0:
        return resale_price
    
    max_allowed = reference_price * (MAX_BUNDLE_RESALE_PERCENT_OF_NEW if is_bundle else MAX_RESALE_PERCENT_OF_NEW)
    
    if resale_price > max_allowed:
        return max_allowed
    
    return resale_price


def calculate_market_resale_from_listings(
    variant_key: str,
    listings: List[Dict[str, Any]],
    reference_price: float,
    unrealistic_floor: float = 10.0,
    context=None,
    ua: str = None,
    variant_new_price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Calculate market resale price from auction listings."""
    if not variant_key:
        return None
    
    has_variant_specific_price = (
        variant_new_price is not None and 
        variant_new_price > 0 and 
        abs(variant_new_price - reference_price) > 10
    )
    sanity_reference = variant_new_price if has_variant_specific_price else None
    
    price_samples = []
    buy_now_ceiling = None
    
    for listing in listings:
        if listing.get("variant_key") != variant_key:
            continue
        
        current = listing.get("current_price_ricardo")
        bids = listing.get("bids_count") or 0
        hours = listing.get("hours_remaining") or 999
        buy_now = listing.get("buy_now_price")
        
        # v7.2.2: Track buy-now prices (but only from listings WITH bids)
        if buy_now and buy_now > unrealistic_floor and bids > 0:
            if buy_now_ceiling is None or buy_now < buy_now_ceiling:
                buy_now_ceiling = buy_now
        
        # v7.2.2: IGNORE pure buy-now listings (no bids)
        if not current or current <= 0 or bids == 0:
            continue
        
        # v7.2.2: Special validation for single bids with category-specific thresholds
        if bids == 1:
            price_ratio = current / reference_price if reference_price > 0 else 0
            
            # v7.2.2: ALWAYS reject unrealistic bids (not just late ones)
            if price_ratio < 0.20:
                continue  # Too unrealistic, regardless of timing
            
            # Case 1: Buy-now + single bid → use category threshold (default 30%)
            if buy_now and buy_now > unrealistic_floor:
                buy_now_ratio = current / buy_now
                min_buy_now_ratio = 0.30  # Default, will be overridden by category threshold
                
                if buy_now_ratio >= min_buy_now_ratio:
                    # Good! Bid is reasonable compared to buy-now
                    weight = calculate_confidence_weight(bids, hours)
                    price_samples.append({
                        "price": float(current),
                        "weight": weight * 0.8,  # Slightly lower confidence
                        "bids": bids,
                        "hours": hours,
                        "reason": f"single_bid_buy_now_{buy_now_ratio*100:.0f}pct"
                    })
                    continue
                else:
                    # Bid too low compared to buy-now
                    continue
            
            # Case 2: Auction-only + single bid → validate against reference price
            # Use category-specific threshold (default 40%)
            min_single_bid_ratio = 0.40  # Default, will be overridden
            
            # Accept if bid is reasonable (>=threshold of reference)
            if price_ratio >= min_single_bid_ratio and hours > 12:
                weight = calculate_confidence_weight(bids, hours)
                price_samples.append({
                    "price": float(current),
                    "weight": weight * 0.7,  # Lower confidence for single bid
                    "bids": bids,
                    "hours": hours,
                    "reason": f"single_bid_validated_{price_ratio*100:.0f}pct"
                })
                continue
            
            # For other single bids, use standard validation
        
        is_real, reason = is_realistic_auction_price(current, bids, hours, reference_price, True)
        
        if not is_real:
            continue
        
        weight = calculate_confidence_weight(bids, hours)
        price_samples.append({
            "price": float(current), 
            "weight": weight, 
            "bids": bids, 
            "hours": hours,
            "reason": reason
        })
    
    # v7.2.2: NO fallback to pure buy-now prices!
    # We only use buy-now if there are actual bids to validate against
    if not price_samples:
        return None
    
    if len(price_samples) < MIN_SAMPLES_FOR_MARKET_PRICE:
        # v9.0 FIX: Mit nur 1 Sample ist "Market Data" nicht valide!
        # Das eine Sample ist oft das Listing selbst → Zirkular-Logik
        if len(price_samples) == 1:
            # Nur 1 Sample: NUR verwenden wenn buy_now_ceiling vorhanden
            if buy_now_ceiling and buy_now_ceiling > unrealistic_floor:
                resale_price = buy_now_ceiling * 0.75
                return {
                    "resale_price": round(resale_price, 2),
                    "market_value": round(buy_now_ceiling, 2),
                    "source": "single_sample_buy_now_fallback",
                    "sample_size": 1,
                    "market_based": False,  # Nicht wirklich market-based!
                    "buy_now_ceiling": buy_now_ceiling,
                    "confidence": 0.3,
                }
            # Ohne buy_now_ceiling: return None → fallback to new_price * resale_rate
            return None
        
        # v7.2.1: For rare items (2 samples), prefer buy-now prices if available
        if len(price_samples) == 2 and buy_now_ceiling and buy_now_ceiling > unrealistic_floor:
            simple_median = statistics.median([s["price"] for s in price_samples])
            
            # If auction price is reasonable (>50% of buy-now), use it
            if simple_median >= buy_now_ceiling * 0.50:
                resale_price = simple_median * 0.90
                confidence = 0.60
                source = "rare_item_auction_validated"
            else:
                resale_price = buy_now_ceiling * 0.75
                confidence = 0.50
                source = "rare_item_buy_now_based"
            
            if sanity_reference:
                resale_price = apply_global_sanity_check(resale_price, sanity_reference, False, source)
            
            return {
                "resale_price": round(resale_price, 2),
                "market_value": round(buy_now_ceiling, 2),
                "source": source,
                "sample_size": len(price_samples),
                "market_based": True,
                "buy_now_ceiling": buy_now_ceiling,
                "confidence": confidence,
            }
        
        # 2 samples ohne buy_now_ceiling: return None
        return None
    
    market_value = weighted_median(price_samples)
    
    has_very_high = any(s.get("bids", 0) >= VERY_HIGH_ACTIVITY_BID_THRESHOLD for s in price_samples)
    has_high = any(s.get("bids", 0) >= HIGH_ACTIVITY_BID_THRESHOLD for s in price_samples)
    has_ending = any(s.get("hours", 999) < 12 for s in price_samples)
    
    if has_very_high:
        resale_pct, source = 0.95, "auction_demand_very_high"
    elif has_ending:
        resale_pct, source = 0.92, "auction_demand_ending_soon"
    elif has_high:
        resale_pct, source = 0.90, "auction_demand_high_activity"
    else:
        resale_pct, source = 0.88, "auction_demand"
    
    resale_price = market_value * resale_pct
    
    if buy_now_ceiling and buy_now_ceiling > market_value and resale_price > buy_now_ceiling * 0.95:
        resale_price = buy_now_ceiling * 0.95
    
    if sanity_reference:
        resale_price = apply_global_sanity_check(resale_price, sanity_reference, False, source)
    
    avg_weight = sum(s["weight"] for s in price_samples) / len(price_samples)
    confidence = min(0.95, avg_weight * min(len(price_samples) / 5, 1.0))
    
    return {
        "resale_price": round(resale_price, 2),
        "market_value": round(market_value, 2),
        "source": source,
        "sample_size": len(price_samples),
        "market_based": True,
        "buy_now_ceiling": buy_now_ceiling,
        "confidence": round(confidence, 2),
    }


def calculate_all_market_resale_prices(listings: List[Dict[str, Any]], variant_new_prices: Optional[Dict[str, float]] = None, unrealistic_floor: float = 10.0, typical_multiplier: float = 5.0, context=None, ua: str = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    variant_keys = set(l.get("variant_key") for l in listings if l.get("variant_key"))
    variant_new_prices = variant_new_prices or {}
    reference_price = _get_new_price_estimate(query_analysis)
    
    if query_analysis:
        unrealistic_floor = _get_min_realistic_price(query_analysis)
    
    results = {}
    for vk in variant_keys:
        variant_new = variant_new_prices.get(vk)
        market_data = calculate_market_resale_from_listings(vk, listings, reference_price, unrealistic_floor, context, ua, variant_new)
        if market_data:
            results[vk] = market_data
            print(f"   📊 Market: {vk} = {market_data['resale_price']} CHF ({market_data['source']})")
    
    return results
# ==============================================================================
# VARIANT INFO BATCH FETCHING (v7.0 - with REAL web search!)
# ==============================================================================

def fetch_variant_info_batch(variant_keys: List[str], car_model: str = DEFAULT_CAR_MODEL, market_prices: Optional[Dict[str, Dict[str, Any]]] = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    """
    v7.0: Fetches variant info with REAL web search for new prices!
    
    Priority:
    1. Market prices (from Ricardo auctions)
    2. Web search (from Digitec/Galaxus) ← NEW in v7.0!
    3. AI estimate (fallback)
    """
    if not variant_keys:
        return {}
    
    variant_keys = [vk for vk in variant_keys if vk is not None]
    if not variant_keys:
        return {}
    
    market_prices = market_prices or {}
    results = {}
    need_new_price = []
    category = _get_category(query_analysis)
    resale_rate = _get_resale_rate(query_analysis)
    
    # First pass: handle variants with market data
    for vk in variant_keys:
        if vk in market_prices:
            market_data = market_prices[vk]
            cached = get_cached_variant_info(vk)
            # v9.0 FIX: Use market_based from market_data, not hardcoded True!
            # single_sample_buy_now_fallback returns market_based=False
            results[vk] = {
                "new_price": cached.get("new_price") if cached else None,
                "transport_car": cached.get("transport_car", True) if cached else True,
                "resale_price": market_data["resale_price"],
                "market_based": market_data.get("market_based", True),
                "market_source": market_data["source"],
                "market_sample_size": market_data["sample_size"],
                "market_value": market_data.get("market_value"),
                "buy_now_ceiling": market_data.get("buy_now_ceiling"),
            }
            if results[vk]["new_price"] is None:
                need_new_price.append(vk)
            continue
        
        # Check cache
        cached = get_cached_variant_info(vk)
        if cached and cached.get("resale_price"):
            results[vk] = {
                "new_price": cached["new_price"],
                "transport_car": cached["transport_car"],
                "resale_price": cached["resale_price"],
                "market_based": cached.get("market_based", False),
                "market_sample_size": cached.get("market_sample_size", 0),
            }
            continue
        
        need_new_price.append(vk)
    
    # v7.3: Use BATCH web search to avoid rate limits!
    if need_new_price:
        print(f"\n🌐 v7.3: BATCH web searching {len(need_new_price)} variants (rate-limit safe)...")
        
        # v7.3.3: Pass query_analysis for better search term cleaning
        web_results = search_web_batch_for_new_prices(need_new_price, category, query_analysis)
        
        for vk in need_new_price:
            web_result = web_results.get(vk)
            
            if web_result and web_result.get("new_price"):
                new_price = web_result["new_price"]
                price_source = web_result.get("price_source", "web_batch")
                
                # Calculate resale with sanity checks
                resale_price = new_price * resale_rate
                max_resale = new_price * MAX_RESALE_PERCENT_OF_NEW
                if resale_price > max_resale:
                    resale_price = max_resale
                
                # CRITICAL: Resale can never exceed new price
                if resale_price > new_price * 0.95:
                    resale_price = new_price * 0.85
                
                if vk in results:
                    # Already has market data, just add new_price
                    results[vk]["new_price"] = new_price
                    results[vk]["price_source"] = price_source
                else:
                    results[vk] = {
                        "new_price": new_price,
                        "transport_car": True,
                        "resale_price": resale_price,
                        "market_based": False,
                        "market_sample_size": 0,
                        "price_source": price_source,
                    }
                
                # Cache it
                set_cached_variant_info(vk, new_price, True, resale_price, False, 0)
            else:
                # No web result, will use AI fallback
                if vk not in results:
                    results[vk] = {
                        "new_price": None,
                        "transport_car": True,
                        "resale_price": None,
                        "market_based": False,
                        "market_sample_size": 0,
                        "price_source": "unknown",
                    }
    
    # Final pass: AI estimation for variants still missing prices
    need_ai = [vk for vk in variant_keys if vk in results and results[vk].get("new_price") is None]
    
    if need_ai:
        print(f"   🤖 AI fallback for {len(need_ai)} variants...")
        ai_results = _fetch_variant_info_from_ai_batch(need_ai, car_model, market_prices, query_analysis)
        
        for vk, info in ai_results.items():
            if vk in results:
                if results[vk].get("new_price") is None:
                    results[vk]["new_price"] = info.get("new_price")
                    results[vk]["price_source"] = "ai_estimate"
            else:
                results[vk] = info
    
    return results


def _fetch_variant_info_from_ai_batch(variant_keys: List[str], car_model: str = DEFAULT_CAR_MODEL, market_prices: Optional[Dict[str, Dict[str, Any]]] = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    """AI-based variant info estimation (fallback when web search fails)."""
    if not variant_keys or is_budget_exceeded():
        return {}
    
    market_prices = market_prices or {}
    resale_rate = _get_resale_rate(query_analysis)
    min_realistic = _get_min_realistic_price(query_analysis)
    category = _get_category(query_analysis)

    # v7.2.1: Remove pipe from variant keys for cleaner AI prompt
    clean_variant_keys = [vk.replace("|", " ") for vk in variant_keys]
    
    prompt = f"""Du bist Preisexperte für ricardo.ch (SCHWEIZ).

KATEGORIE: {category}
MINDESTPREIS: {min_realistic} CHF

Analysiere diese Produkte und schätze:
1. AKTUELLER Schweizer Neupreis (nicht historischer UVP!)
2. Realistischer Wiederverkaufspreis (gebraucht)
3. Passt in {car_model}?

REGELN:
- Elektronik: Berücksichtige Alter (3+ Jahre = stark reduziert)
- Fitness/Gewichte: Gusseisen = 1.5-2 CHF/kg, Bumper = 2.5-3.5 CHF/kg
- Kleidung: Tommy Hilfiger Pullover ~120-150 CHF neu

PRODUKTE:
{chr(10).join(f"- {cvk}" for cvk in clean_variant_keys)}

Antworte NUR als JSON:
{{"Produkt Variante": {{"new_price": X, "resale_price": X, "transport": true/false}}, ...}}"""

    results = {}
    try:
        raw = call_ai(prompt, max_tokens=1500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                for vk in variant_keys:
                    info = parsed.get(vk)
                    if not info:
                        for key, val in parsed.items():
                            if key.lower() in vk.lower() or vk.lower() in key.lower():
                                info = val
                                break
                    
                    if info:
                        try:
                            if isinstance(info, dict):
                                new_price = float(info.get("new_price", 0))
                                resale_price = float(info.get("resale_price", 0))
                                transport = bool(info.get("transport", True))
                            else:
                                new_price = float(info)
                                resale_price = new_price * resale_rate
                                transport = True
                            
                            if new_price < min_realistic * 2:
                                continue
                            
                            if resale_price > new_price * MAX_RESALE_PERCENT_OF_NEW:
                                resale_price = new_price * resale_rate
                            
                            # Weight validation
                            if is_weight_plate(vk):
                                validated_resale, _ = validate_weight_price(vk, resale_price, is_resale=True)
                                validated_new, _ = validate_weight_price(vk, new_price, is_resale=False)
                                new_price = validated_new
                                resale_price = validated_resale
                            
                            # v7.3.2: Apply model-year adjustment for old electronics
                            if category == "electronics":
                                new_price = _adjust_price_for_model_year(vk, new_price, category)
                                resale_price = new_price * _get_component_resale_rate(vk, category, resale_rate)
                            
                            if new_price > 0:
                                results[vk] = {
                                    "new_price": new_price,
                                    "transport_car": transport,
                                    "resale_price": resale_price if resale_price > 0 else new_price * resale_rate,
                                    "market_based": False,
                                    "market_sample_size": 0,
                                    "price_source": "ai_estimate",
                                }
                                set_cached_variant_info(vk, new_price, transport, resale_price, False, 0)
                        except:
                            pass
    except Exception as e:
        print(f"⚠️ AI variant query failed: {e}")
    
    return results


# ==============================================================================
# SEARCH TERM EXTRACTION
# ==============================================================================

def extract_clean_search_terms(product_name: str, category: str = "unknown") -> Dict[str, Any]:
    """Extract clean search terms from product name for web search."""
    # Remove common noise words
    noise_words = ["neu", "new", "original", "ovp", "top", "super", "mega", "wow", "!!!", "???"]
    
    # Clean the name
    clean = product_name.lower()
    for noise in noise_words:
        clean = clean.replace(noise.lower(), "")
    
    # Split into words
    words = [w.strip() for w in clean.split() if len(w.strip()) > 2]
    
    # Build search terms (first 4 meaningful words)
    search_terms = words[:4] if words else [product_name]
    
    return {
        "search_terms": search_terms,
        "clean_name": " ".join(words),
        "category": category,
    }

# ==============================================================================
# BUNDLE DETECTION & PRICING
# ==============================================================================

BUNDLE_KEYWORDS = [
    "set", "paket", "bundle", "lot", "konvolut", "sammlung",
    "2x", "3x", "4x", "5x", "6x", "10x", "paar", "stück",
    "inkl", "inklusive", "mit", "plus", "und", "&",
]

def looks_like_bundle(title: str, description: str = "") -> bool:
    """Quick check if listing might be a bundle."""
    text = f"{title} {description}".lower()
    
    # v9.0 FIX: "2 Stk. à 2.5kg" = Quantity, NOT bundle!
    # Pattern: Zahl + Stk + à/x/@ + Gewicht = single product with quantity
    if re.search(r'\d+\s*stk\.?\s*[àax@]\s*\d+', text):
        return False
    
    # Check for real bundle keywords
    for kw in BUNDLE_KEYWORDS:
        if kw in text:
            # But exclude "stück/stk" if it's just quantity notation
            if kw in ["stück", "stk"] and not re.search(r'\d+\s*(stück|stk)\s+\w+', text):
                continue  # Skip - it's just "2 Stk." quantity
            return True
    
    # Quantity pattern - but only for real bundles with multiple items
    qty_pattern = r'\b(\d+)\s*(x|pcs|pieces?)\b'  # Removed stück/stk - handled above
    if re.search(qty_pattern, text):
        return True
    
    return False

def detect_bundle_with_ai(
    title: str,
    description: str,
    query: str,
    image_url: Optional[str] = None,
    use_vision: bool = False,
    query_analysis: Optional[Dict] = None,
    batch_result: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Detect if listing is a bundle and identify components.
    
    v7.3.4: Can use pre-computed batch_result to avoid redundant AI calls.
    """
    result = {
        "is_bundle": False,
        "components": [],
        "confidence": 0.0,
    }
    
    # v7.3.4: Use batch result if available (cost optimization!)
    if batch_result is not None:
        return batch_result
    
    if not looks_like_bundle(title, description):
        return result
    
    # Fallback: Individual detection (only if batch wasn't used)
    prompt = f"""Analysiere dieses Ricardo-Inserat auf Bundle/Set:

TITEL: {title}
BESCHREIBUNG: {description[:500] if description else "Keine"}
SUCHBEGRIFF: {query}

Ist dies ein Bundle/Set mit mehreren Artikeln?

Wenn JA, liste die Komponenten auf mit geschätzter Anzahl.

Antworte NUR als JSON:
{{
  "is_bundle": true/false,
  "components": [
    {{"name": "Artikel 1", "quantity": 2, "unit": "stück"}},
    {{"name": "Artikel 2", "quantity": 1, "unit": "stück"}}
  ],
  "confidence": 0.0-1.0
}}"""

    try:
        raw = call_ai(prompt, max_tokens=500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                result["is_bundle"] = parsed.get("is_bundle", False)
                result["components"] = parsed.get("components", [])
                result["confidence"] = parsed.get("confidence", 0.5)
    except Exception as e:
        pass  # Return default result on error
    
    return result


def price_bundle_components(
    components: List[Dict[str, Any]],
    base_product: str,
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    pre_fetched_prices: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Price individual bundle components with smart estimation.
    
    v7.4: Uses PRE-FETCHED prices from PRICE_FETCHING phase (OBJECTIVE B)
    - No web search during evaluation (cost optimization!)
    - Falls back to AI estimation if price not available
    - Pre-fetched prices come from fetch_variant_info_batch()
    
    Example: "Olympiastange + 3× Kurzhantel + 2× 5kg Gusseisen"
    → Uses prices fetched in PRICE_FETCHING phase
    → Much more accurate than AI guessing!
    """
    priced = []
    resale_rate = _get_resale_rate(query_analysis)
    category = _get_category(query_analysis)
    
    # Use pre-fetched prices from PRICE_FETCHING phase
    web_prices = pre_fetched_prices or {}
    
    for comp in components:
        name = comp.get("name", "Unknown")
        qty = comp.get("quantity") or 1
        if not isinstance(qty, (int, float)):
            try:
                qty = int(qty)
            except:
                qty = 1
        
        # Try pre-fetched price first
        web_result = web_prices.get(name)
        if web_result and web_result.get("new_price"):
            est_new = web_result["new_price"]
            price_source = "pre_fetched"
            print(f"      {name}: {est_new} CHF (pre-fetched)")
        else:
            # Fallback: AI estimation
            est_new = _estimate_component_price(name, category, query_analysis)
            est_new = _adjust_price_for_model_year(name, est_new, category)
            price_source = "ai_estimate"
            print(f"      {name}: {est_new} CHF (AI fallback)")
        
        # Guard: Skip component if price estimation failed
        if est_new is None or est_new <= 0:
            print(f"      ⚠️ {name}: Price unavailable, skipping component")
            continue
        
        # Calculate resale with category-aware rate
        component_resale_rate = _get_component_resale_rate(name, category, resale_rate)
        est_resale = est_new * component_resale_rate
        
        priced.append({
            "name": name,
            "quantity": qty,
            "new_price_each": round(est_new, 2),
            "resale_price_each": round(est_resale, 2),
            "total_new": round(est_new * qty, 2),
            "total_resale": round(est_resale * qty, 2),
            "price_source": price_source,
        })
    
    return priced


def _estimate_component_price(name: str, category: str, query_analysis: Optional[Dict] = None) -> float:
    """
    v7.3.3: Improved component price estimation.
    Uses weight-based pricing for fitness, smart defaults for other categories.
    GOAL: Avoid unrealistic 50 CHF defaults!
    """
    name_lower = name.lower()
    
    # ACCESSORIES (low value items) - handle first
    if any(kw in name_lower for kw in ["koffer", "case", "tasche", "bag", "etui"]):
        return 15.0  # Cases/bags are cheap
    if any(kw in name_lower for kw in ["adapter", "clip", "halter", "holder"]):
        return 10.0
    if any(kw in name_lower for kw in ["anleitung", "manual", "handbuch"]):
        return 0.0  # Manuals have no resale value
    
    # FITNESS: Weight-based pricing (CHF per kg)
    if category == "fitness" or any(kw in name_lower for kw in WEIGHT_PLATE_KEYWORDS):
        weight_kg = extract_weight_kg(name)
        if weight_kg and weight_kg > 0:
            weight_type = get_weight_type(name)
            pricing = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])
            # v9.0: Calibrated plates are more expensive!
            if weight_type == "calibrated":
                return weight_kg * pricing["new_price_per_kg"] * 1.5
            # v7.3.3: Use realistic CHF/kg pricing
            return weight_kg * pricing["new_price_per_kg"]
        
        # v7.3.3: Try to extract weight from quantity patterns like "4x 5kg"
        import re
        qty_weight = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', name_lower)
        if qty_weight:
            qty = int(qty_weight.group(1))
            per_kg = float(qty_weight.group(2).replace(',', '.'))
            total_kg = qty * per_kg
            return total_kg * 3.5  # Standard ~3.5 CHF/kg
        
        # Fitness equipment defaults (no weight found)
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "scheibe"]):
            # v9.0: "Hantelscheibe" ohne Gewicht ist UNGÜLTIG - return None für Fehlerbehandlung
            return None
        if any(kw in name_lower for kw in ["hantelstange", "langhantel", "barbell", "stange"]):
            return 80.0
        if any(kw in name_lower for kw in ["kurzhantel", "dumbbell", "gymnastikhantel"]):
            return 15.0  # Small dumbbells
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 150.0
        if any(kw in name_lower for kw in ["ständer", "halterung", "stand"]):
            return 60.0
        if any(kw in name_lower for kw in ["set", "kit"]):
            return 80.0  # Generic set
        return 40.0  # Generic fitness default (was 50)
    
    # ELECTRONICS: Model-specific pricing
    if category == "electronics":
        # Garmin smartwatches
        if "forerunner" in name_lower:
            if any(m in name_lower for m in ["965", "955", "945"]):
                return 500.0
            if any(m in name_lower for m in ["935", "735", "645"]):
                return 200.0  # Older models
            return 300.0
        if "fenix" in name_lower:
            if "7" in name_lower or "8" in name_lower:
                return 600.0
            if "6" in name_lower:
                return 400.0
            if "5" in name_lower:
                return 250.0  # 2017 model
            return 400.0
        if "vivofit" in name_lower:
            return 80.0
        if "vivoactive" in name_lower:
            return 250.0
        if "brustgurt" in name_lower or "heart rate" in name_lower:
            return 50.0
        if "armband" in name_lower or "band" in name_lower:
            return 25.0
        if "ladekabel" in name_lower or "charger" in name_lower:
            return 20.0
        return 100.0  # Generic electronics default
    
    # CLOTHING
    if category == "clothing":
        if any(kw in name_lower for kw in ["jacke", "jacket", "mantel", "coat"]):
            return 150.0
        if any(kw in name_lower for kw in ["hose", "jeans", "pants"]):
            return 80.0
        if any(kw in name_lower for kw in ["pullover", "sweater", "hoodie"]):
            return 90.0
        if any(kw in name_lower for kw in ["hemd", "shirt", "bluse"]):
            return 70.0
        return 60.0  # Generic clothing default
    
    # DEFAULT for unknown categories
    return 50.0


def _adjust_price_for_model_year(name: str, price: float, category: str) -> float:
    """
    Adjust price based on detected model year (for electronics).
    Older models should have lower new prices.
    """
    if category != "electronics":
        return price
    
    name_lower = name.lower()
    
    # Garmin Fenix series (detect model generation)
    if "fenix" in name_lower:
        if "5" in name_lower:  # 2017 model
            return min(price, 250.0)
        if "6" in name_lower:  # 2019 model
            return min(price, 450.0)
        if "7" in name_lower:  # 2022 model
            return min(price, 650.0)
    
    # Garmin Forerunner series
    if "forerunner" in name_lower:
        if any(m in name_lower for m in ["235", "230", "220"]):  # Old models
            return min(price, 150.0)
        if any(m in name_lower for m in ["935", "735"]):  # 2017-2018
            return min(price, 200.0)
        if any(m in name_lower for m in ["945", "745"]):  # 2019-2020
            return min(price, 350.0)
    
    return price


def _get_component_resale_rate(name: str, category: str, default_rate: float) -> float:
    """
    Get resale rate for a specific component type.
    Accessories have lower resale, main items higher.
    """
    name_lower = name.lower()
    
    # Accessories have lower resale value
    if any(kw in name_lower for kw in ["armband", "band", "kabel", "cable", "charger", "adapter"]):
        return 0.30  # Accessories: 30%
    
    # Main fitness equipment holds value well
    if category == "fitness":
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "bumper"]):
            return 0.60  # Weight plates: 60%
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 0.50  # Benches/racks: 50%
    
    # Electronics depreciate based on age
    if category == "electronics":
        if "fenix 5" in name_lower or "forerunner 935" in name_lower:
            return 0.55  # Older electronics: 55%
        if "fenix 6" in name_lower or "forerunner 945" in name_lower:
            return 0.50  # Mid-age: 50%
    
    return default_rate


def calculate_bundle_new_price(priced_components: List[Dict[str, Any]]) -> float:
    """Calculate total new price for bundle."""
    if not priced_components:
        return 0.0
    
    total = sum(c.get("total_new", 0) for c in priced_components)
    return round(total, 2)


def calculate_bundle_resale(priced_components: List[Dict[str, Any]], bundle_new_price: float) -> float:
    """Calculate bundle resale price with discount."""
    if not priced_components:
        return 0.0
    
    # Sum component resale prices
    component_total = sum(c.get("total_resale", 0) for c in priced_components)
    
    # Apply bundle discount (people pay less for bundles)
    bundle_resale = component_total * (1 - BUNDLE_DISCOUNT_PERCENT)
    
    # Cap at max percent of new price
    max_resale = bundle_new_price * MAX_BUNDLE_RESALE_PERCENT_OF_NEW
    if bundle_resale > max_resale:
        bundle_resale = max_resale
    
    return round(bundle_resale, 2)


# ==============================================================================
# PROFIT & STRATEGY
# ==============================================================================

def calculate_profit(resale_price: float, purchase_price: float) -> float:
    if resale_price <= 0 or purchase_price <= 0:
        return 0.0
    return round(resale_price * (1 - RICARDO_FEE_PERCENT) - purchase_price - SHIPPING_COST_CHF, 2)


def determine_strategy(expected_profit: float, is_auction: bool, has_buy_now: bool, bids_count: int = 0, hours_remaining: float = None, is_bundle: bool = False) -> Tuple[str, str]:
    profit = expected_profit or 0
    hours = hours_remaining if hours_remaining is not None else 999
    bids = bids_count or 0
    
    if profit < MIN_PROFIT_THRESHOLD:
        return ("skip", f"Profit {profit:.0f} CHF below minimum ({MIN_PROFIT_THRESHOLD:.0f})")
    if has_buy_now and profit >= 80:
        return ("buy_now", f"🔥 Buy now! Profit {profit:.0f} CHF")
    if has_buy_now and profit >= 40:
        return ("buy_now", f"Buy recommended, profit {profit:.0f} CHF")
    if is_auction:
        if bids >= 15:
            return ("watch", f"⚠️ Highly contested ({bids} bids)")
        if hours < 2 and profit >= 40:
            return ("bid_now", f"🔥 Ending soon! Max {profit:.0f} CHF profit possible")
        if hours < 6 and profit >= 30:
            return ("bid", f"Bid recommended, ends in {hours:.0f}h")
        if hours < 24 and profit >= 40:
            return ("bid", f"Bid today, profit {profit:.0f} CHF")
        if profit >= 60:
            return ("watch", f"Watch, good profit ({profit:.0f} CHF)")
        return ("watch", f"Watch, {hours:.0f}h remaining")
    if profit >= 30:
        return ("watch", f"Inquire, profit {profit:.0f} CHF")
    return ("watch", f"Watch, profit {profit:.0f} CHF")


def calculate_deal_score(expected_profit: float, purchase_price: float, resale_price: Optional[float], bids_count: Optional[int] = None, hours_remaining: Optional[float] = None, is_auction: bool = True, has_variant_key: bool = True, market_based_resale: bool = False, is_bundle: bool = False) -> float:
    """v6.8: Calculate deal score with reformed scoring."""
    score = 5.0
    profit = expected_profit or 0
    
    # Variant classification bonus/penalty
    if not has_variant_key:
        score -= 0.5  # Reduced from -2.0
    
    if market_based_resale:
        score += 1.0
    if is_bundle:
        score += 0.3
    
    # Margin-based scoring
    if resale_price and resale_price > 0 and purchase_price > 0:
        margin = (profit / purchase_price) * 100
        if margin > 100: score += 3.5
        elif margin > 50: score += 3.0
        elif margin > 30: score += 2.0
        elif margin > 15: score += 1.0
        elif margin > 0: score += 0.5
        elif margin > -10: score -= 0.5
        elif margin > -25: score -= 1.5
        else: score -= 2.5
    
    # Absolute profit bonus
    if profit > 500:
        score += 3.0
    elif profit > 200:
        score += 2.0
    elif profit > 100:
        score += 1.5
    elif profit > 50:
        score += 1.0
    
    # Auction timing
    if is_auction:
        hours = hours_remaining if hours_remaining is not None else 999
        bids = bids_count or 0
        
        if hours > 48: score -= 1.5
        elif hours > 24: score -= 1.0
        elif hours > 12: score -= 0.5
        elif hours < 2: score += 0.5
        
        # High bids = BONUS (not penalty!)
        if bids >= 20:
            score += 0.5
        elif bids >= 10:
            score += 0.3
    

# MAIN EVALUATION FUNCTION
# ==============================================================================

def evaluate_listing_with_ai(
    title: str,
    description: str,
    current_price: Optional[float],
    buy_now_price: Optional[float],
    image_url: Optional[str],
    query: str,
    variant_key: Optional[str] = None,
    variant_info: Optional[Dict[str, Any]] = None,
    bids_count: Optional[int] = None,
    hours_remaining: Optional[float] = None,
    base_product: str = "",
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    batch_bundle_result: Optional[Dict] = None,
    variant_info_by_key: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Any]:
    """
    v7.0: Main evaluation function with Claude-based AI.
    
    Evaluates a Ricardo listing and returns:
    - is_relevant: Is this the main product (not accessory)?
    - deal_score: 0-10 score
    - new_price: New price (from web search or AI)
    - resale_price_est: Expected resale price
    - expected_profit: Calculated profit
    - recommended_strategy: buy_now/bid/watch/skip
    - etc.
    """
    result = {
        "is_relevant": True,
        "deal_score": 5.0,
        "new_price": None,
        "resale_price_est": None,
        "expected_profit": 0.0,
        "transport_car": True,
        "ai_notes": "",
        "predicted_final_price": None,
        "prediction_confidence": None,
        "is_bundle": False,
        "bundle_components": None,
        "resale_price_bundle": None,
        "recommended_strategy": "watch",
        "strategy_reason": "",
        "market_based_resale": False,
        "market_sample_size": 0,
        "market_value": None,
        "price_source": "unknown",
        "buy_now_ceiling": None,
    }
    
    # Get variant info
    if variant_info:
        result["new_price"] = variant_info.get("new_price")
        result["transport_car"] = variant_info.get("transport_car", True)
        result["market_based_resale"] = variant_info.get("market_based", False)
        result["market_sample_size"] = variant_info.get("market_sample_size", 0)
        result["market_value"] = variant_info.get("market_value")
        result["buy_now_ceiling"] = variant_info.get("buy_now_ceiling")
        result["price_source"] = variant_info.get("price_source", "unknown")
        
        if variant_info.get("resale_price"):
            result["resale_price_est"] = variant_info["resale_price"]
    
    # v7.2.1: Fallback new_price to buy_now_price if web search failed
    if not result["new_price"] and buy_now_price and buy_now_price > 0:
        result["new_price"] = buy_now_price * 1.1  # Conservative estimate: assume 10% markup
        result["price_source"] = "buy_now_fallback"
        print(f"   Using buy_now_price as new_price fallback: {result['new_price']:.2f} CHF")
    
    # v7.2.1: Calculate resale_price_est from new_price if missing
    resale_rate = _get_resale_rate(query_analysis)
    if not result["resale_price_est"] and result["new_price"] and result["new_price"] > 0:
        result["resale_price_est"] = result["new_price"] * resale_rate
    
    # v9.0 FIX: If we have resale_price but no new_price, estimate new_price
    # This ensures data consistency (can't have resale without knowing new)
    if result["resale_price_est"] and not result["new_price"]:
        # Reverse calculate: new_price = resale_price / resale_rate
        estimated_new = result["resale_price_est"] / resale_rate if resale_rate > 0 else result["resale_price_est"] * 2
        result["new_price"] = round(estimated_new, 2)
        if result["price_source"] == "unknown":
            result["price_source"] = "estimated_from_resale"
    
    # Determine effective purchase price
    is_auction = current_price is not None and buy_now_price is None
    has_buy_now = buy_now_price is not None
    
    if has_buy_now:
        purchase_price = buy_now_price
    elif current_price:
        # Predict final auction price
        prediction = predict_final_auction_price(
            current_price=current_price,
            bids_count=bids_count or 0,
            hours_remaining=hours_remaining or 999,
            median_price=result.get("market_value"),
            new_price=result.get("new_price"),
            typical_multiplier=_get_auction_multiplier(query_analysis),
        )
        purchase_price = prediction["predicted_final_price"]
        result["predicted_final_price"] = prediction["predicted_final_price"]
        result["prediction_confidence"] = prediction["confidence"]
    else:
        purchase_price = 0
    
    # Check for bundles
    if BUNDLE_ENABLED and looks_like_bundle(title, description):
        vision_for_this_call = random.random() < VISION_RATE if image_url else False
        bundle_result = detect_bundle_with_ai(
            title=title,
            description=description,
            query=query,
            image_url=image_url,
            use_vision=vision_for_this_call,
            query_analysis=query_analysis,
            batch_result=batch_bundle_result,
        )
        result["vision_used"] = vision_for_this_call
        
        if bundle_result.get("is_bundle"):
            result["is_bundle"] = True
            result["bundle_components"] = bundle_result.get("components", [])
            
            # Price components
            priced = price_bundle_components(
                components=result["bundle_components"],
                base_product=base_product or query,
                context=context,
                ua=ua,
                query_analysis=query_analysis,
                pre_fetched_prices=variant_info_by_key,
            )
            result["bundle_components"] = priced
            
            # Calculate bundle resale
            bundle_new = calculate_bundle_new_price(priced)
            bundle_resale = calculate_bundle_resale(priced, bundle_new)
            
            result["resale_price_bundle"] = bundle_resale
            result["resale_price_est"] = bundle_resale
            result["new_price"] = bundle_new
            result["price_source"] = "bundle_calculation"
    
    # Calculate profit
    if result["resale_price_est"] and purchase_price:
        result["expected_profit"] = calculate_profit(result["resale_price_est"], purchase_price)
    
    # Determine strategy
    strategy, reason = determine_strategy(
        expected_profit=result["expected_profit"],
        is_auction=is_auction,
        has_buy_now=has_buy_now,
        bids_count=bids_count,
        hours_remaining=hours_remaining,
        is_bundle=result["is_bundle"],
    )
    result["recommended_strategy"] = strategy
    result["strategy_reason"] = reason
    
    # Calculate deal score
    result["deal_score"] = calculate_deal_score(
        expected_profit=result["expected_profit"],
        purchase_price=purchase_price,
        resale_price=result["resale_price_est"],
        bids_count=bids_count,
        hours_remaining=hours_remaining,
        is_auction=is_auction,
        has_variant_key=variant_key is not None,
        market_based_resale=result["market_based_resale"],
        is_bundle=result["is_bundle"],
    )
    
    # Build AI notes
    notes = []
    if result["market_based_resale"]:
        notes.append(f"📈 Market ({result['market_sample_size']} samples)")
    if result["is_bundle"]:
        notes.append(f"📦 Bundle ({len(result.get('bundle_components', []))} items)")
    if result["price_source"].startswith("web_"):
        notes.append(f"🌐 Web price ({result['price_source']})")
    notes.append(f"Strategy: {strategy}")
    result["ai_notes"] = " | ".join(notes)
    
    return result


# ==============================================================================
# VISION ANALYSIS FOR UNCLEAR LISTINGS
# ==============================================================================

def analyze_listing_with_vision(
    title: str,
    description: str,
    image_url: str,
    category: str = None,
) -> Dict[str, Any]:
    """
    Analyzes an unclear listing using vision to extract missing product information.
    
    Used when title and description don't provide enough clarity to identify the product.
    
    Args:
        title: Original listing title
        description: Listing description (may be vague)
        image_url: URL to product image
        category: Optional category path
    
    Returns:
        Dict with extracted product info
    """
    result = {
        "product_type": None,
        "brand": None,
        "model": None,
        "specifications": {},
        "condition": None,
        "is_bundle": False,
        "bundle_items": [],
        "confidence": 0.0,
        "notes": None,
        "vision_used": True,
        "success": False,
    }
    
    if not image_url:
        result["notes"] = "No image URL provided"
        return result
    
    # Build context from known info
    context_parts = []
    if title:
        context_parts.append(f"Titel: {title}")
    if description:
        desc_preview = description[:300] + "..." if len(description) > 300 else description
        context_parts.append(f"Beschreibung: {desc_preview}")
    if category:
        context_parts.append(f"Kategorie: {category}")
    
    context = "\n".join(context_parts) if context_parts else "Keine Kontextinformationen"
    
    prompt = f"""Du analysierst ein Produktbild von einem Online-Inserat um fehlende Informationen zu identifizieren.

BEKANNTE INFORMATIONEN:
{context}

DEINE AUFGABE:
Die vorhandenen Informationen sind zu vage. Analysiere das Bild und extrahiere:

1. **Produktidentifikation** - Um was handelt es sich genau? Marke? Modell?
2. **Spezifikationen** - Material, Gewicht/Grösse falls erkennbar
3. **Zustand** - neu/neuwertig/gebraucht
4. **Bundle/Set** - Falls mehrere Artikel sichtbar, liste sie auf

ANTWORTFORMAT (JSON):
{{
    "product_type": "z.B. Hantelscheiben, Smartwatch",
    "brand": "erkannte Marke oder null",
    "model": "erkanntes Modell oder null",
    "specifications": {{"weight_kg": null, "material": null}},
    "condition": "neu/neuwertig/gebraucht/unklar",
    "is_bundle": true/false,
    "bundle_items": ["Item 1", "Item 2"],
    "confidence": 0.0-1.0,
    "notes": "zusätzliche Beobachtungen"
}}

Antworte NUR mit dem JSON-Objekt."""

    try:
        response = _call_ai(
            prompt=prompt,
            max_tokens=800,
            image_url=image_url,
        )
        
        if response:
            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                parsed = json.loads(json_match.group())
                result.update(parsed)
                result["success"] = True
                result["vision_used"] = True
            else:
                result["notes"] = f"Could not parse JSON from response"
    except json.JSONDecodeError as e:
        result["notes"] = f"JSON parse error: {e}"
    except Exception as e:
        result["notes"] = f"Vision analysis error: {e}"
    
    return result


def batch_analyze_with_vision(
    listings: List[Dict[str, Any]],
    max_vision_calls: int = 5,
) -> List[Dict[str, Any]]:
    """
    Analyzes multiple unclear listings with vision.
    
    Args:
        listings: Listings that need vision analysis (must have 'image_urls' or 'image_url')
        max_vision_calls: Maximum number of vision API calls
    
    Returns:
        Same listings with added '_vision_result' field
    """
    to_analyze = [l for l in listings if l.get("image_urls") or l.get("image_url")][:max_vision_calls]
    
    if not to_analyze:
        print("   ⚠️ No listings with images for vision analysis")
        return listings
    
    print(f"\n👁️ Analyzing {len(to_analyze)} listings with vision...")
    
    for i, listing in enumerate(to_analyze, 1):
        title = listing.get("title", "")[:40]
        print(f"\n   [{i}/{len(to_analyze)}] {title}...")
        
        # Get first image URL
        image_urls = listing.get("image_urls", [])
        image_url = image_urls[0] if image_urls else listing.get("image_url")
        
        if not image_url:
            continue
        
        vision_result = analyze_listing_with_vision(
            title=listing.get("title", ""),
            description=listing.get("description", ""),
            image_url=image_url,
            category=listing.get("category_path"),
        )
        
        listing["_vision_result"] = vision_result
        listing["vision_used"] = True
        
        if vision_result.get("success"):
            # Update listing with extracted info
            if vision_result.get("product_type"):
                listing["_identified_product"] = vision_result["product_type"]
            if vision_result.get("brand"):
                listing["_identified_brand"] = vision_result["brand"]
            if vision_result.get("model"):
                listing["_identified_model"] = vision_result["model"]
            if vision_result.get("is_bundle"):
                listing["is_bundle"] = True
                listing["bundle_components"] = vision_result.get("bundle_items", [])
            
            print(f"   ✅ Identified: {vision_result.get('product_type', 'Unknown')}")
            if vision_result.get("brand"):
                print(f"      Brand: {vision_result['brand']}")
            if vision_result.get("is_bundle"):
                print(f"      Bundle: {len(vision_result.get('bundle_items', []))} items")
        else:
            print(f"   ⚠️ Vision failed: {vision_result.get('notes', 'Unknown error')}")
    
    print(f"\n✅ Vision analysis complete ({len(to_analyze)} images)")
    
    return listings


# ==============================================================================
# COST TRACKING & BUDGET MANAGEMENT
# ==============================================================================

def reset_run_cost():
    """Reset run cost counter."""
    global RUN_COST_USD
    RUN_COST_USD = 0.0


def add_cost(amount: float):
    """Add cost to run total."""
    global RUN_COST_USD
    RUN_COST_USD += amount


def get_run_cost_summary() -> Tuple[float, str]:
    """Get summary of current run cost.
    
    Returns:
        Tuple of (run_cost_usd, date_string)
    """
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return (RUN_COST_USD, today)


def get_day_cost_summary() -> float:
    """Get today's total cost as float."""
    try:
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    date_str, cost_str = content.split(",", 1)
                    today = datetime.datetime.now().strftime("%Y-%m-%d")
                    if date_str == today:
                        return float(cost_str)
                    return 0.0  # Different day, reset
                return float(content)  # Legacy format
    except:
        pass
    return 0.0


def save_day_cost() -> float:
    """
    v7.3.5 FIX: Save current run cost to daily total file.
    
    This was MISSING before - day costs were never persisted!
    Now stores format: "YYYY-MM-DD,total_cost"
    
    Returns: New daily total
    """
    global RUN_COST_USD
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        existing = 0.0
        
        # Read existing costs for today
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    date_str, cost_str = content.split(",", 1)
                    if date_str == today:
                        existing = float(cost_str)
                    # else: different day, start fresh
        
        # Add this run's cost
        new_total = existing + RUN_COST_USD
        
        # Save with date prefix
        with open(DAY_COST_FILE, "w") as f:
            f.write(f"{today},{new_total:.4f}")
        
        print(f"💾 Saved day cost: ${new_total:.4f} (this run: ${RUN_COST_USD:.4f})")
        return new_total
    except Exception as e:
        print(f"⚠️ Could not save day cost: {e}")
        return 0.0


def is_budget_exceeded() -> bool:
    """Check if daily budget is exceeded."""
    day_cost = get_day_cost_summary()
    return day_cost >= DAILY_COST_LIMIT


def apply_config(config):
    """Apply configuration from config dict or config object."""
    global RICARDO_FEE_PERCENT, SHIPPING_COST_CHF, MIN_PROFIT_THRESHOLD
    global BUNDLE_ENABLED, BUNDLE_DISCOUNT_PERCENT, BUNDLE_MIN_COMPONENT_VALUE
    global CACHE_ENABLED, USE_VISION, VISION_RATE, DEFAULT_CAR_MODEL
    global WEB_SEARCH_ENABLED  # v7.3.2: Toggle expensive web search
    
    # Handle both dict and object config
    def get_val(key, default=None):
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)
    
    # Try to get values from general section first, then direct
    def get_nested(section, key, default=None):
        if isinstance(config, dict):
            sec = config.get(section, {})
            if isinstance(sec, dict):
                return sec.get(key, default)
            return getattr(sec, key, default)
        sec = getattr(config, section, None)
        if sec:
            return getattr(sec, key, default)
        return getattr(config, key, default)
    
    val = get_nested("general", "ricardo_fee_percent", None)
    if val is not None:
        RICARDO_FEE_PERCENT = val
    val = get_nested("general", "shipping_cost_chf", None)
    if val is not None:
        SHIPPING_COST_CHF = val
    val = get_nested("general", "min_profit_threshold", None)
    if val is not None:
        MIN_PROFIT_THRESHOLD = val
    val = get_nested("bundle", "enabled", None)
    if val is not None:
        BUNDLE_ENABLED = val
    val = get_nested("bundle", "discount_percent", None)
    if val is not None:
        BUNDLE_DISCOUNT_PERCENT = val
    val = get_nested("bundle", "min_component_value", None)
    if val is not None:
        BUNDLE_MIN_COMPONENT_VALUE = val
    val = get_nested("cache", "enabled", None)
    if val is not None:
        CACHE_ENABLED = val
    val = get_nested("ai", "use_vision", None)
    if val is not None:
        USE_VISION = val
    val = get_nested("ai", "vision_rate", None)
    if val is not None:
        VISION_RATE = val
    val = get_nested("general", "car_model", None)
    if val is not None:
        DEFAULT_CAR_MODEL = val
    
    # v7.3.2: Read web search enabled setting from ai.web_search.enabled
    if isinstance(config, dict):
        ai_section = config.get("ai", {})
        if isinstance(ai_section, dict):
            ws_section = ai_section.get("web_search", {})
            if isinstance(ws_section, dict):
                val = ws_section.get("enabled", None)
                if val is not None:
                    WEB_SEARCH_ENABLED = val
                    status = "ENABLED ✅" if val else "DISABLED ❌ (cost saving mode)"
                    print(f"  Web Search:       {status}")


def apply_ai_budget_from_cfg(config):
    """Apply AI budget settings from config object or dict."""
    global DAILY_COST_LIMIT, DAILY_VISION_LIMIT, DAILY_WEB_SEARCH_LIMIT
    
    # Handle both dict and object config
    def get_val(key, default=None):
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)
    
    val = get_val("daily_cost_limit", None)
    if val is not None:
        DAILY_COST_LIMIT = val
    val = get_val("daily_vision_limit", None)
    if val is not None:
        DAILY_VISION_LIMIT = val
    val = get_val("daily_web_search_limit", None)
    if val is not None:
        DAILY_WEB_SEARCH_LIMIT = val


def clear_all_caches():
    """Clear all cache files."""
    global _variant_cache, _component_cache, _cluster_cache, _web_price_cache, _category_threshold_cache
    
    _variant_cache = {}
    _component_cache = {}
    _cluster_cache = {}
    _web_price_cache = {}
    _category_threshold_cache = {}
    
    for cache_file in [VARIANT_CACHE_FILE, COMPONENT_CACHE_FILE, CLUSTER_CACHE_FILE, 
                       WEB_PRICE_CACHE_FILE, CATEGORY_THRESHOLD_CACHE_FILE]:
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"🗑️ Cleared: {cache_file}")


# ==============================================================================
# HELPER FOR MAIN.PY COMPATIBILITY
# ==============================================================================

def cluster_variants_from_titles(
    titles: List[str],
    base_product: str,
    query_analysis: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Cluster variant titles into groups.
    
    Returns:
        {
            "variants": {"variant_key": ["title1", "title2", ...]},
            "base_product": str,
        }
    """
    if not titles:
        return {"variants": {}, "base_product": base_product}
    
    _load_caches()
    
    # Check cache
    cache_key = f"{base_product}_{len(titles)}"
    if cache_key in _cluster_cache:
        cached = _cluster_cache[cache_key]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            print(f"   💾 Cluster cache hit: {len(cached.get('variants', {}))} variants")
            return cached
    
    # Simple clustering: group by exact title match
    variants = {}
    for title in titles:
        # Use title as variant key (simplified)
        variant_key = title.strip()
        if variant_key not in variants:
            variants[variant_key] = []
        variants[variant_key].append(title)
    
    result = {
        "variants": variants,
        "base_product": base_product,
    }
    
    # Cache for 7 days
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(days=CLUSTER_CACHE_DAYS)
    _cluster_cache[cache_key] = {
        **result,
        "cached_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }
    _save_cluster_cache()
    
    print(f"   🔍 Clustered {len(titles)} titles into {len(variants)} variants")
    return result


def get_variant_for_title(title: str, cluster_result: Dict[str, Any], base_product: str) -> str:
    """Get variant key for a title from cluster result."""
    if not title or not cluster_result:
        return base_product
    
    variants = cluster_result.get("variants", {})
    
    # Find which variant this title belongs to
    for variant_key, titles in variants.items():
        if title in titles:
            return variant_key
    # Fallback: use title as variant key
    return title.strip() or base_product


def to_float(val: Any) -> Optional[float]:
    """Safely convert value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_lowest_variant_resale(base_product: str) -> Optional[float]:
    """Get lowest resale price for any variant of a product."""
    _load_caches()
    prices = [
        info.get("resale_price") 
        for vk, info in _variant_cache.items() 
        if vk and (vk.startswith(base_product + "|") or vk == base_product) 
        and info.get("resale_price", 0) > 0
    ]
    return round(min(prices), 2) if prices else None


# ... (rest of the code remains the same)