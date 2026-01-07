"""
AI Filter & Evaluation - v7.0 (Claude Edition)
==============================================
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

COST_CLAUDE_HAIKU = 0.001
COST_CLAUDE_SONNET = 0.003
COST_CLAUDE_WEB_SEARCH = 0.01
COST_OPENAI_TEXT = 0.001
COST_VISION = 0.007

DAILY_COST_LIMIT = 1.50
DAILY_VISION_LIMIT = 100
DAILY_WEB_SEARCH_LIMIT = 50

WEB_SEARCH_COUNT_TODAY: int = 0
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

RUN_COST_USD: float = 0.0
DAY_COST_FILE = "ai_cost_day.txt"

VARIANT_CACHE_FILE = "variant_cache.json"
COMPONENT_CACHE_FILE = "component_cache.json"
CLUSTER_CACHE_FILE = "variant_cluster_cache.json"

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
# v7.0: REAL WEB SEARCH FOR NEW PRICES (THE GAME CHANGER!)
# ==============================================================================

def search_web_for_new_price(
    variant_key: str,
    search_terms: List[str],
    category: str = "unknown"
) -> Optional[Dict[str, Any]]:
    """
    v7.0: REAL WEB SEARCH using Claude + web_search tool.
    
    This actually searches Swiss online shops and returns real prices!
    
    Args:
        variant_key: Product variant identifier
        search_terms: List of search terms
        category: Product category (for shop selection)
    
    Returns:
        {
            "new_price": float,
            "price_source": "web_digitec" | "web_galaxus" | etc,
            "shop_name": str,
            "confidence": float,
        }
    """
    global RUN_COST_USD, WEB_SEARCH_COUNT_TODAY
    
    # Check budget
    if is_budget_exceeded():
        return None
    
    if WEB_SEARCH_COUNT_TODAY >= DAILY_WEB_SEARCH_LIMIT:
        print("🚫 Daily web search limit reached")
        return None
    
    # Check cache first
    cached = get_cached_web_price(variant_key)
    if cached:
        print(f"   💾 Web price cached: {cached['new_price']} CHF ({cached['price_source']})")
        return cached
    
    # Claude with web search required
    if not _claude_client:
        print("   ⚠️ Web search requires Claude API")
        return None
    
    print(f"   🌐 Web searching: {variant_key}")
    
    # Determine shops based on category
    if category == "clothing":
        shops = "Zalando.ch, AboutYou.ch, Manor.ch"
    elif category == "fitness":
        shops = "Decathlon.ch, SportXX.ch, Galaxus.ch"
    else:
        shops = "Digitec.ch, Galaxus.ch, Brack.ch, Interdiscount.ch"
    
    search_query = " ".join(search_terms[:3]) if search_terms else variant_key
    
    prompt = f"""Finde den AKTUELLEN Neupreis in CHF für dieses Produkt in der Schweiz.

PRODUKT: {variant_key}
SUCHBEGRIFFE: {search_query}
KATEGORIE: {category}
SHOPS: {shops}

WICHTIG:
- Suche bei den angegebenen Schweizer Online-Shops
- Gib den AKTUELLEN Verkaufspreis zurück, nicht historische UVP
- Bei mehreren Ergebnissen: nimm den günstigsten verfügbaren Preis
- Bei Unsicherheit: gib null zurück

Antworte NUR als JSON:
{{
  "new_price": XXX.XX oder null,
  "shop_name": "Digitec" oder "Galaxus" oder null,
  "product_found": "Exakter Produktname wie gefunden",
  "confidence": 0.0-1.0,
  "reasoning": "Kurz: wo gefunden oder warum nicht"
}}"""

    try:
        raw = _call_claude(
            prompt=prompt,
            max_tokens=500,
            use_web_search=True,  # This enables the web_search tool!
        )
        
        if not raw:
            print("   ⚠️ No response from Claude web search")
            return None
        
        # Track cost
        add_cost(COST_CLAUDE_WEB_SEARCH)
        WEB_SEARCH_COUNT_TODAY += 1
        
        # Parse JSON response
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            print(f"   ⚠️ No JSON in web search response")
            return None
        
        parsed = json.loads(json_match.group(0))
        
        new_price = parsed.get("new_price")
        shop_name = parsed.get("shop_name")
        confidence = parsed.get("confidence", 0.5)
        reasoning = parsed.get("reasoning", "")
        
        # Only accept if confidence > 60%
        if new_price and new_price > 0 and confidence >= 0.6:
            price_source = f"web_{shop_name.lower().replace('.ch', '')}" if shop_name else "web_search"
            
            result = {
                "new_price": float(new_price),
                "price_source": price_source,
                "shop_name": shop_name,
                "confidence": confidence,
            }
            
            # Cache it (60 days)
            set_cached_web_price(variant_key, result["new_price"], price_source, shop_name)
            
            print(f"   ✅ Web price: {new_price} CHF ({shop_name}, confidence={confidence:.0%})")
            return result
        else:
            print(f"   ⚠️ Low confidence ({confidence:.0%}): {reasoning}")
            return None
        
    except Exception as e:
        print(f"   ⚠️ Web search failed: {e}")
        return None


# ==============================================================================
# v6.8: WEIGHT-BASED PRICING VALIDATION (unchanged)
# ==============================================================================

WEIGHT_PRICING = {
    "gusseisen": {
        "max_resale_per_kg": 2.0,
        "typical_resale_per_kg": 1.5,
        "new_price_per_kg": 3.5,
        "keywords": ["guss", "gusseisen", "cast iron", "eisen"],
    },
    "bumper": {
        "max_resale_per_kg": 3.5,
        "typical_resale_per_kg": 2.75,
        "new_price_per_kg": 6.0,
        "keywords": ["bumper", "gummi", "rubber", "urethane", "competition"],
    },
    "olympic_steel": {
        "max_resale_per_kg": 2.5,
        "typical_resale_per_kg": 2.0,
        "new_price_per_kg": 4.5,
        "keywords": ["50mm", "olympic", "olympia", "stahl", "steel", "chrom"],
    },
    "standard": {
        "max_resale_per_kg": 2.0,
        "typical_resale_per_kg": 1.5,
        "new_price_per_kg": 3.5,
        "keywords": ["30mm", "standard", "hantelscheibe", "gewicht"],
    },
}

WEIGHT_PLATE_KEYWORDS = [
    "hantelscheibe", "hantelscheiben", "gewichtsscheibe", "gewichtsscheiben",
    "scheibe", "scheiben", "plate", "plates", "bumper", "weight",
]


def detect_weight_type(name: str) -> str:
    """v6.8: Detect weight plate type from name."""
    name_lower = name.lower()
    for weight_type, config in WEIGHT_PRICING.items():
        if any(kw in name_lower for kw in config["keywords"]):
            return weight_type
    return "standard"


def extract_weight_kg(name: str) -> Optional[float]:
    """v6.8: Extract weight in kg from name."""
    name_lower = name.lower()
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', name_lower)
    if match:
        return float(match.group(1).replace(',', '.'))
    return None


def is_weight_plate(name: str) -> bool:
    """v6.8: Check if item is a weight plate."""
    return any(kw in name.lower() for kw in WEIGHT_PLATE_KEYWORDS)


def validate_weight_price(name: str, price: float, is_resale: bool = True) -> Tuple[float, str]:
    """v6.8: Validate and cap weight plate prices based on realistic CHF/kg."""
    if not is_weight_plate(name):
        return price, "not_weight_plate"
    
    weight_kg = extract_weight_kg(name)
    if not weight_kg or weight_kg <= 0:
        return price, "no_weight_detected"
    
    weight_type = detect_weight_type(name)
    config = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])
    
    if is_resale:
        max_per_kg = config["max_resale_per_kg"]
        typical_per_kg = config["typical_resale_per_kg"]
    else:
        max_per_kg = config["new_price_per_kg"]
        typical_per_kg = config["new_price_per_kg"] * 0.85
    
    max_realistic = weight_kg * max_per_kg
    typical_price = weight_kg * typical_per_kg
    
    if price > max_realistic:
        print(f"      ⚠️ WEIGHT VALIDATION: {name}")
        print(f"         Price {price:.0f} CHF > max {max_realistic:.0f} CHF ({weight_kg}kg × {max_per_kg} CHF/kg)")
        print(f"         → Capping to typical: {typical_price:.0f} CHF")
        return typical_price, f"capped_{weight_type}_{weight_kg}kg"
    
    return price, f"valid_{weight_type}_{weight_kg}kg"


def calculate_weight_based_price(weight_kg: float, weight_type: str = "standard", is_resale: bool = True) -> float:
    """v6.8: Calculate realistic price for weight plates."""
    config = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])
    if is_resale:
        return weight_kg * config["typical_resale_per_kg"]
    else:
        return weight_kg * config["new_price_per_kg"]


# ==============================================================================
# v6.6: FITNESS VISION EXCEPTION (unchanged)
# ==============================================================================

FITNESS_KEYWORDS = [
    "hantelscheiben", "hantelscheibe", "gewichte", "gewicht",
    "hantel", "langhantel", "kurzhantel", "kettlebell", "bumper",
    "plates", "plate", "hantelset", "gewichtsscheibe", "gewichtsscheiben",
    "olympia", "50mm", "30mm",
]

QUANTITY_INDICATORS = [
    "2x", "2×", "3x", "4x", "5x", "6x", "8x", "10x",
    "paar", "set", "stück", "stk", " + ", " und ",
    "2 x", "3 x", "4 x", "komplett",
]


def needs_fitness_vision(title: str, category: str) -> bool:
    """v6.6: Force vision for fitness equipment when quantity is ambiguous."""
    title_lower = title.lower()
    if category.lower() != "fitness":
        return False
    has_fitness = any(kw in title_lower for kw in FITNESS_KEYWORDS)
    if not has_fitness:
        return False
    has_quantity = any(q in title_lower for q in QUANTITY_INDICATORS)
    if not has_quantity:
        print(f"   🏋️ FITNESS VISION: No quantity in title → forcing vision check")
        return True
    return False


# ==============================================================================
# HELPER: Get values from query_analysis
# ==============================================================================

def _get_resale_rate(query_analysis: Optional[Dict] = None) -> float:
    if query_analysis:
        return query_analysis.get("resale_rate", 0.40)
    return 0.40


def _get_min_realistic_price(query_analysis: Optional[Dict] = None) -> float:
    if query_analysis:
        return query_analysis.get("min_realistic_price", 10.0)
    return 10.0


def _get_new_price_estimate(query_analysis: Optional[Dict] = None) -> float:
    if query_analysis:
        return query_analysis.get("new_price_estimate", 275.0)
    return 275.0


def _get_auction_multiplier(query_analysis: Optional[Dict] = None) -> float:
    if query_analysis:
        return query_analysis.get("auction_typical_multiplier", 5.0)
    return 5.0


def _needs_vision_for_bundles(query_analysis: Optional[Dict] = None) -> bool:
    if query_analysis:
        return query_analysis.get("needs_vision_for_bundles", False)
    return False


def _get_category(query_analysis: Optional[Dict] = None) -> str:
    if query_analysis:
        return query_analysis.get("category", "unknown")
    return "unknown"


# ==============================================================================
# CONFIGURATION LOADER
# ==============================================================================

def apply_config(cfg):
    """Apply configuration from Cfg object."""
    global RICARDO_FEE_PERCENT, SHIPPING_COST_CHF, MIN_PROFIT_THRESHOLD
    global BUNDLE_ENABLED, BUNDLE_DISCOUNT_PERCENT, BUNDLE_MIN_COMPONENT_VALUE, BUNDLE_USE_VISION
    global CACHE_ENABLED, VARIANT_CACHE_DAYS, COMPONENT_CACHE_DAYS, CLUSTER_CACHE_DAYS, WEB_PRICE_CACHE_DAYS
    global DAILY_COST_LIMIT, DAILY_VISION_LIMIT, DAILY_WEB_SEARCH_LIMIT
    global VISION_RATE, USE_VISION, DEFAULT_CAR_MODEL
    global MODEL_FAST, MODEL_WEB, MODEL_OPENAI

    if hasattr(cfg, 'profit'):
        RICARDO_FEE_PERCENT = cfg.profit.ricardo_fee_percent
        SHIPPING_COST_CHF = cfg.profit.shipping_cost_chf
        MIN_PROFIT_THRESHOLD = cfg.profit.min_profit_threshold

    if hasattr(cfg, 'bundle'):
        BUNDLE_ENABLED = cfg.bundle.enabled
        BUNDLE_DISCOUNT_PERCENT = cfg.bundle.discount_percent
        BUNDLE_MIN_COMPONENT_VALUE = cfg.bundle.min_component_value
        BUNDLE_USE_VISION = cfg.bundle.use_vision_for_unclear

    if hasattr(cfg, 'cache'):
        CACHE_ENABLED = cfg.cache.enabled
        VARIANT_CACHE_DAYS = cfg.cache.variant_cache_days
        COMPONENT_CACHE_DAYS = cfg.cache.component_cache_days
        CLUSTER_CACHE_DAYS = cfg.cache.cluster_cache_days
        WEB_PRICE_CACHE_DAYS = cfg.cache.web_price_cache_days

    if hasattr(cfg, 'ai'):
        ai = cfg.ai
        USE_VISION = ai.use_ai_vision
        VISION_RATE = ai.adaptive_vision_rate
        
        # v7.0: Claude models
        if hasattr(ai, 'claude_model_fast'):
            MODEL_FAST = ai.claude_model_fast
        if hasattr(ai, 'claude_model_web'):
            MODEL_WEB = ai.claude_model_web
        if hasattr(ai, 'openai_model'):
            MODEL_OPENAI = ai.openai_model
        
        # Budget
        if ai.budget:
            DAILY_COST_LIMIT = ai.budget.get("daily_cost_usd_max", DAILY_COST_LIMIT)
            DAILY_VISION_LIMIT = ai.budget.get("daily_vision_calls_max", DAILY_VISION_LIMIT)
            DAILY_WEB_SEARCH_LIMIT = ai.budget.get("daily_web_search_max", DAILY_WEB_SEARCH_LIMIT)

    if hasattr(cfg, 'general'):
        DEFAULT_CAR_MODEL = cfg.general.car_model

    print(f"[AI-CONFIG] Provider={_provider.upper()}, Fee={RICARDO_FEE_PERCENT*100:.0f}%, "
          f"Bundle={BUNDLE_ENABLED}, Cache={CACHE_ENABLED}")


def apply_ai_budget_from_cfg(ai_cfg: Any):
    """Legacy function for backward compatibility."""
    global DAILY_COST_LIMIT, DAILY_VISION_LIMIT, VISION_RATE, USE_VISION

    try:
        if isinstance(ai_cfg, dict):
            USE_VISION = ai_cfg.get("use_ai_vision", True)
            VISION_RATE = ai_cfg.get("adaptive_vision_rate", 0.10)
            budget = ai_cfg.get("budget", {}) or {}
            DAILY_COST_LIMIT = budget.get("daily_cost_usd_max", DAILY_COST_LIMIT)
            DAILY_VISION_LIMIT = budget.get("daily_vision_calls_max", DAILY_VISION_LIMIT)
        else:
            USE_VISION = getattr(ai_cfg, "use_ai_vision", True)
            VISION_RATE = getattr(ai_cfg, "adaptive_vision_rate", 0.10)
            budget = getattr(ai_cfg, "budget", None) or {}
            if isinstance(budget, dict):
                DAILY_COST_LIMIT = budget.get("daily_cost_usd_max", DAILY_COST_LIMIT)
                DAILY_VISION_LIMIT = budget.get("daily_vision_calls_max", DAILY_VISION_LIMIT)
    except Exception as e:
        print(f"⚠️ AI-Budget load failed: {e}")

    print(f"[AI-BUDGET] VISION={USE_VISION}, RATE={VISION_RATE}, DAILY_LIMIT=${DAILY_COST_LIMIT}")


# ==============================================================================
# COST TRACKING
# ==============================================================================

def reset_run_cost():
    global RUN_COST_USD, WEB_SEARCH_COUNT_TODAY
    RUN_COST_USD = 0.0
    WEB_SEARCH_COUNT_TODAY = 0


def _load_day_cost() -> float:
    if not os.path.exists(DAY_COST_FILE):
        return 0.0
    try:
        with open(DAY_COST_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return 0.0
            date_str, cost_str = content.split("|")
            if date_str == datetime.date.today().isoformat():
                return float(cost_str)
    except Exception:
        pass
    return 0.0


def _save_day_cost(value: float):
    with open(DAY_COST_FILE, "w", encoding="utf-8") as f:
        f.write(f"{datetime.date.today().isoformat()}|{value:.4f}")


def add_cost(cost: float):
    global RUN_COST_USD
    RUN_COST_USD += cost
    day_cost = _load_day_cost() + cost
    _save_day_cost(day_cost)


def get_run_cost_summary():
    return RUN_COST_USD, datetime.date.today().isoformat()


def get_day_cost_summary():
    return _load_day_cost()


def is_budget_exceeded() -> bool:
    return _load_day_cost() >= DAILY_COST_LIMIT


# ==============================================================================
# CACHE MANAGEMENT
# ==============================================================================

_variant_cache: Dict[str, Dict] = {}
_component_cache: Dict[str, Dict] = {}
_cluster_cache: Dict[str, Dict] = {}
_cache_loaded = False


def clear_all_caches():
    global _variant_cache, _component_cache, _cluster_cache, _web_price_cache, _cache_loaded
    _variant_cache = {}
    _component_cache = {}
    _cluster_cache = {}
    _web_price_cache = {}
    _cache_loaded = False
    for f in [VARIANT_CACHE_FILE, COMPONENT_CACHE_FILE, CLUSTER_CACHE_FILE, WEB_PRICE_CACHE_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"🗑️ Deleted cache: {f}")
            except Exception as e:
                print(f"⚠️ Could not delete {f}: {e}")
    print("🧹 All caches cleared")


def _load_caches():
    global _variant_cache, _component_cache, _cluster_cache, _cache_loaded
    if _cache_loaded:
        return
    if not CACHE_ENABLED:
        _cache_loaded = True
        return
    now = datetime.datetime.now().isoformat()

    try:
        if os.path.exists(VARIANT_CACHE_FILE):
            with open(VARIANT_CACHE_FILE, "r", encoding="utf-8") as f:
                _variant_cache = json.load(f)
            expired = [k for k, v in _variant_cache.items() if v.get("expires_at", "") < now]
            for k in expired:
                del _variant_cache[k]
    except Exception as e:
        print(f"⚠️ Variant cache load failed: {e}")
        _variant_cache = {}

    try:
        if os.path.exists(COMPONENT_CACHE_FILE):
            with open(COMPONENT_CACHE_FILE, "r", encoding="utf-8") as f:
                _component_cache = json.load(f)
            expired = [k for k, v in _component_cache.items() if v.get("expires_at", "") < now]
            for k in expired:
                del _component_cache[k]
    except Exception as e:
        print(f"⚠️ Component cache load failed: {e}")
        _component_cache = {}

    try:
        if os.path.exists(CLUSTER_CACHE_FILE):
            with open(CLUSTER_CACHE_FILE, "r", encoding="utf-8") as f:
                _cluster_cache = json.load(f)
            expired = [k for k, v in _cluster_cache.items() if v.get("expires_at", "") < now]
            for k in expired:
                del _cluster_cache[k]
    except Exception as e:
        print(f"⚠️ Cluster cache load failed: {e}")
        _cluster_cache = {}

    _cache_loaded = True
    total = len(_variant_cache) + len(_component_cache) + len(_cluster_cache)
    if total > 0:
        print(f"💾 Loaded caches: {len(_variant_cache)} variants, {len(_component_cache)} components, {len(_cluster_cache)} clusters")


def _save_variant_cache():
    if not CACHE_ENABLED:
        return
    try:
        with open(VARIANT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_variant_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _save_component_cache():
    if not CACHE_ENABLED:
        return
    try:
        with open(COMPONENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_component_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _save_cluster_cache():
    if not CACHE_ENABLED:
        return
    try:
        with open(CLUSTER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cluster_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ==============================================================================
# WEB PRICE CACHE
# ==============================================================================

def _load_web_price_cache():
    """v7.0: Loads web price cache from disk."""
    global _web_price_cache
    
    try:
        if os.path.exists(WEB_PRICE_CACHE_FILE):
            with open(WEB_PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                _web_price_cache = json.load(f)
            
            now = datetime.datetime.now().isoformat()
            expired = [k for k, v in _web_price_cache.items() 
                      if v.get("expires_at", "") < now]
            for k in expired:
                del _web_price_cache[k]
            
            if expired:
                _save_web_price_cache()
                
    except Exception as e:
        print(f"⚠️ Web price cache load failed: {e}")
        _web_price_cache = {}


def _save_web_price_cache():
    """v7.0: Saves web price cache to disk."""
    if not CACHE_ENABLED:
        return
    try:
        with open(WEB_PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_web_price_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Web price cache save failed: {e}")


def get_cached_web_price(variant_key: str) -> Optional[Dict[str, Any]]:
    """v7.0: Gets cached web price for a variant."""
    if not variant_key or not CACHE_ENABLED:
        return None
    
    _load_web_price_cache()
    entry = _web_price_cache.get(variant_key)
    
    if not entry:
        return None
    
    if entry.get("expires_at", "") < datetime.datetime.now().isoformat():
        del _web_price_cache[variant_key]
        return None
    
    return {
        "new_price": entry.get("new_price"),
        "price_source": entry.get("price_source", "web_unknown"),
        "shop_name": entry.get("shop_name"),
        "confidence": entry.get("confidence", 0.7),
    }


def set_cached_web_price(variant_key: str, new_price: float, price_source: str, shop_name: str = None):
    """v7.0: Caches a web-searched price."""
    if not variant_key or not CACHE_ENABLED:
        return
    
    _load_web_price_cache()
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(days=WEB_PRICE_CACHE_DAYS)
    
    _web_price_cache[variant_key] = {
        "new_price": new_price,
        "price_source": price_source,
        "shop_name": shop_name,
        "cached_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }
    
    _save_web_price_cache()
    print(f"💾 Cached web price: {variant_key} = {new_price} CHF ({price_source}, {WEB_PRICE_CACHE_DAYS}d)")


# ==============================================================================
# VARIANT CACHE FUNCTIONS
# ==============================================================================

def get_cached_variant_info(variant_key: str) -> Optional[Dict[str, Any]]:
    if not variant_key or not CACHE_ENABLED:
        return None
    _load_caches()
    entry = _variant_cache.get(variant_key)
    if not entry:
        return None
    if entry.get("expires_at", "") < datetime.datetime.now().isoformat():
        del _variant_cache[variant_key]
        return None
    return {
        "new_price": entry.get("new_price"),
        "transport_car": entry.get("transport_car", True),
        "resale_price": entry.get("resale_price"),
        "market_based": entry.get("market_based", False),
        "market_sample_size": entry.get("market_sample_size", 0),
    }


def set_cached_variant_info(variant_key: str, new_price: float, transport_car: bool, resale_price: float, market_based: bool = False, market_sample_size: int = 0):
    if not variant_key or not CACHE_ENABLED:
        return
    _load_caches()
    now = datetime.datetime.now()
    cache_days = 7 if market_based else VARIANT_CACHE_DAYS
    expires = now + datetime.timedelta(days=cache_days)
    _variant_cache[variant_key] = {
        "new_price": new_price, "transport_car": transport_car, "resale_price": resale_price,
        "market_based": market_based, "market_sample_size": market_sample_size,
        "cached_at": now.isoformat(), "expires_at": expires.isoformat()
    }
    _save_variant_cache()


# ==============================================================================
# COMPONENT CACHE FUNCTIONS
# ==============================================================================

def get_cached_component_price(component_name: str) -> Optional[Dict[str, Any]]:
    if not component_name or not CACHE_ENABLED:
        return None
    _load_caches()
    key = component_name.lower().strip()
    entry = _component_cache.get(key)
    if not entry:
        return None
    if entry.get("expires_at", "") < datetime.datetime.now().isoformat():
        del _component_cache[key]
        return None
    return {
        "median_price": entry.get("median_price"),
        "sample_size": entry.get("sample_size", 0),
        "search_query": entry.get("search_query"),
        "price_source": entry.get("price_source", "unknown"),
        "has_auction_data": entry.get("has_auction_data", False),
    }


def set_cached_component_price(component_name: str, median_price: float, sample_size: int, search_query: str, price_source: str = "unknown", has_auction_data: bool = False):
    if not component_name or not CACHE_ENABLED:
        return
    _load_caches()
    key = component_name.lower().strip()
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(days=COMPONENT_CACHE_DAYS)
    _component_cache[key] = {
        "median_price": median_price, "sample_size": sample_size, "search_query": search_query,
        "price_source": price_source, "has_auction_data": has_auction_data,
        "cached_at": now.isoformat(), "expires_at": expires.isoformat(),
    }
    _save_component_cache()
    print(f"💾 Cached component: {component_name} = {median_price} CHF (n={sample_size}, {price_source})")


# ==============================================================================
# GLOBAL SANITY CHECK
# ==============================================================================

def apply_global_sanity_check(resale_price: float, new_price: Optional[float], is_bundle: bool = False, context: str = "") -> float:
    if not resale_price or resale_price <= 0:
        return resale_price
    if not new_price or new_price <= 0:
        return resale_price
    max_ratio = MAX_BUNDLE_RESALE_PERCENT_OF_NEW if is_bundle else MAX_RESALE_PERCENT_OF_NEW
    max_allowed = new_price * max_ratio
    if resale_price > max_allowed:
        print(f"   🚨 SANITY CHECK: {context} resale {resale_price:.0f} > {max_ratio*100:.0f}% of new ({new_price:.0f})")
        print(f"      → Capping to {max_allowed:.0f} CHF")
        return round(max_allowed, 2)
    return resale_price


# ==============================================================================
# HELPER FUNCTION
# ==============================================================================

def to_float(val: Any) -> Optional[float]:
    """Safely convert value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
# ==============================================================================
# TITLE EXTRACTION (v7.0 - uses unified call_ai)
# ==============================================================================

def extract_clean_search_terms(title: str, category: str = "unknown") -> Dict[str, Any]:
    """v7.0: Extracts clean, searchable product names from listing titles."""
    if is_budget_exceeded():
        clean = re.sub(r'[!*🔥⭐✨💥]+', '', title)
        clean = re.sub(r'\b(top zustand|neuwertig|wie neu|zu verkaufen|günstig|ovp|np \d+|uvp)\b', '', clean, flags=re.I)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return {"search_terms": [clean], "main_product": clean, "brand": None, "corrections": [], "reasoning": "Budget fallback"}

    prompt = f"""Extrahiere suchbare Produktnamen aus diesem Ricardo-Titel.

TITEL: "{title}"
KATEGORIE: "{category}"

REGELN:
- Entferne: Emojis, "wie neu", "top zustand", "NP xxx", Preisangaben
- Behalte: Marke, Modell, wichtige Spezifikationen (Grösse, Speicher, etc.)
- Löse Abkürzungen auf: TH=Tommy Hilfiger, AW=Apple Watch, etc.
- Bei mehreren Produkten: Liste alle separat

Antworte NUR als JSON:
{{
  "search_terms": ["Suchbegriff1", "Suchbegriff2"],
  "main_product": "Hauptprodukt für Preissuche",
  "brand": "Erkannte Marke oder null",
  "corrections": ["Korrekturen die gemacht wurden"],
  "reasoning": "Kurze Erklärung"
}}"""

    try:
        raw = call_ai(prompt, max_tokens=500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                parsed.setdefault("search_terms", [title])
                parsed.setdefault("main_product", title)
                parsed.setdefault("brand", None)
                parsed.setdefault("corrections", [])
                parsed.setdefault("reasoning", "")
                if parsed.get("corrections"):
                    print(f"   📝 Title normalized: {parsed['corrections']}")
                return parsed
    except Exception as e:
        print(f"⚠️ Title extraction failed: {e}")
    
    return {"search_terms": [title], "main_product": title, "brand": None, "corrections": [], "reasoning": "Fallback"}


# ==============================================================================
# REALISTIC PRICE FILTERING (unchanged from v6.8)
# ==============================================================================

def is_realistic_auction_price(current_price: float, bids_count: int, hours_remaining: float, reference_price: float, for_market_calculation: bool = True) -> Tuple[bool, str]:
    """v6.5: TRUST BIDDERS! 20+ bids = FULLY trusted."""
    if not current_price or current_price <= 0:
        return False, "no_price"
    if not reference_price or reference_price <= 0:
        reference_price = 100.0
    price_ratio = current_price / reference_price if reference_price > 0 else 0

    if bids_count >= VERY_HIGH_ACTIVITY_BID_THRESHOLD:
        return True, "very_high_activity_trusted"
    if bids_count >= HIGH_ACTIVITY_BID_THRESHOLD:
        if price_ratio >= HIGH_ACTIVITY_MIN_PRICE_RATIO:
            return True, "high_activity_validated"
        else:
            return True, f"high_activity_low_price_{price_ratio*100:.0f}pct"

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


def calculate_confidence_weight(bids: int, hours: float) -> float:
    weight = 0.5
    if bids >= 30: weight += 0.5
    elif bids >= 20: weight += 0.45
    elif bids >= 15: weight += 0.4
    elif bids >= 10: weight += 0.3
    elif bids >= 5: weight += 0.2
    elif bids >= 2: weight += 0.1
    if hours < 1: weight += 0.3
    elif hours < 6: weight += 0.2
    elif hours < 24: weight += 0.1
    return min(weight, 1.0)


def weighted_median(samples: List[Dict]) -> float:
    if not samples:
        return 0.0
    sorted_samples = sorted(samples, key=lambda x: x.get("price", 0))
    total_weight = sum(s.get("weight", 1.0) for s in sorted_samples)
    if total_weight <= 0:
        prices = [s.get("price", 0) for s in sorted_samples]
        return statistics.median(prices) if prices else 0.0
    cumulative = 0
    for s in sorted_samples:
        cumulative += s.get("weight", 1.0)
        if cumulative >= total_weight / 2:
            return s.get("price", 0)
    return sorted_samples[-1].get("price", 0)


# ==============================================================================
# AUCTION PRICE PREDICTION
# ==============================================================================

def predict_final_auction_price(current_price: float, bids_count: int, hours_remaining: float, median_price: Optional[float] = None, new_price: Optional[float] = None, typical_multiplier: float = 5.0) -> Dict[str, Any]:
    if not current_price or current_price <= 0:
        return {"predicted_final_price": current_price or 0, "confidence": 1.0, "method": "no_auction"}

    predicted = current_price
    confidence = 0.5
    method = "unknown"
    anchor = median_price if median_price and median_price > 0 else (new_price * 0.45 if new_price else None)

    if bids_count >= VERY_HIGH_ACTIVITY_BID_THRESHOLD:
        predicted = current_price * 1.15
        confidence = 0.85
        method = "very_high_activity"
    elif bids_count >= HIGH_ACTIVITY_BID_THRESHOLD:
        if anchor:
            predicted = max(current_price * 1.3, anchor * 0.85)
            confidence = 0.75
            method = "high_activity_anchor"
        else:
            predicted = current_price * 1.4
            confidence = 0.6
            method = "high_activity_growth"
    elif bids_count < 5 and hours_remaining > 24:
        if anchor:
            predicted = anchor * 0.75
            confidence = 0.4
            method = "early_stage_anchor"
        else:
            predicted = current_price * typical_multiplier
            confidence = 0.35
            method = "early_stage_multiplier"
    elif bids_count >= 20 or hours_remaining < 2:
        if anchor:
            predicted = anchor * 0.90
            confidence = 0.8
            method = "hot_auction_anchor"
        else:
            predicted = current_price * (typical_multiplier * 0.7)
            confidence = 0.6
            method = "hot_auction_multiplier"
    else:
        if anchor:
            weight = min(bids_count / 20, 0.8)
            multiplier_estimate = current_price * typical_multiplier * 0.8
            anchor_estimate = anchor * 0.80
            predicted = (multiplier_estimate * (1 - weight)) + (anchor_estimate * weight)
            confidence = 0.6 + (weight * 0.2)
            method = "mid_stage_blend"
        else:
            predicted = current_price * (typical_multiplier * 0.8)
            confidence = 0.5
            method = "mid_stage_multiplier"

    if hours_remaining < 6 and hours_remaining > 0:
        urgency_boost = 1.10 + (0.05 * (6 - hours_remaining) / 6)
        predicted *= urgency_boost
        method += "_with_urgency"

    if median_price and median_price > 0 and predicted > median_price:
        predicted = median_price
        method += "_capped_market"

    if new_price and new_price > 0:
        max_realistic = new_price * 0.55
        if predicted > max_realistic:
            predicted = max_realistic
            method += "_capped_new"

    if predicted < current_price:
        predicted = current_price
        method += "_floor"

    return {"predicted_final_price": round(predicted, 2), "confidence": round(confidence, 2), "method": method}


# ==============================================================================
# BUNDLE DETECTION (v7.0 - uses unified call_ai)
# ==============================================================================

BUNDLE_KEYWORDS = [
    "set", "bundle", "paket", "komplett", "komplettes", "mit", "+",
    "inklusive", "inkl.", "samt", "plus", "und", "konvolut",
    "sammlung", "lot", "alles", "zubehör dabei", "viel zubehör",
    "kg", "total", "zusammen", "paar", "2x", "4x", "6x", "8x",
]


def looks_like_bundle(title: str, description: str = "") -> bool:
    text = f"{title} {description}".lower()
    for kw in BUNDLE_KEYWORDS:
        if kw in text:
            return True
    if re.search(r'\d+\s*x\s', text) or re.search(r'\d+\s*(stück|stk)', text):
        return True
    if re.search(r'\d+\s*kg', text):
        return True
    return False


def detect_bundle_with_ai(title: str, description: str, query: str, image_url: Optional[str] = None, use_vision: bool = False, query_analysis: Optional[Dict] = None) -> Dict[str, Any]:
    """v7.0: Bundle detection using Claude."""
    if is_budget_exceeded():
        return {"is_bundle": False, "contains_main_product": True, "components": [], "reasoning": "Budget exceeded"}

    min_price = _get_min_realistic_price(query_analysis)
    category = _get_category(query_analysis)
    force_vision = _needs_vision_for_bundles(query_analysis)
    force_fitness_vision = needs_fitness_vision(title, category)
    actually_use_vision = use_vision or force_fitness_vision or (force_vision and image_url and BUNDLE_USE_VISION)

    prompt = f"""Du analysierst ein Ricardo-Inserat für: "{query}"

Titel: {title}
Beschreibung: {description or '(keine)'}

AUFGABE: Ist das ein BUNDLE mit MEHREREN verkaufbaren Produkten (je > {min_price} CHF)?

REGELN:
- Bundle = MEHRERE separat verkaufbare Produkte
- KEIN Bundle: Hauptprodukt + Kabel/Hülle/Originalzubehör
- Bei Gewichten: Gusseisen = 1.5-2.0 CHF/kg, Bumper = 2.5-3.5 CHF/kg

Antworte NUR als JSON:
{{
  "is_bundle": true/false,
  "contains_main_product": true/false,
  "components": [{{"name": "Produkt", "qty": 1, "estimated_value": XX}}],
  "reasoning": "Kurz"
}}"""

    try:
        if actually_use_vision and image_url:
            raw = call_ai(prompt, max_tokens=500, image_url=image_url)
            add_cost(COST_VISION)
            print(f"   👁️ Using vision for bundle detection")
        else:
            raw = call_ai(prompt, max_tokens=500)
            add_cost(COST_CLAUDE_HAIKU)
        
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                parsed.setdefault("is_bundle", False)
                parsed.setdefault("contains_main_product", True)
                parsed.setdefault("components", [])
                parsed.setdefault("reasoning", "")
                
                if parsed["components"]:
                    parsed["components"] = [c for c in parsed["components"] 
                                           if c.get("estimated_value", 0) >= max(BUNDLE_MIN_COMPONENT_VALUE, min_price * 0.5)]
                if not parsed["components"]:
                    parsed["is_bundle"] = False
                return parsed
    except Exception as e:
        print(f"⚠️ Bundle detection failed: {e}")
    
    return {"is_bundle": False, "contains_main_product": True, "components": [], "reasoning": "Error"}


def calculate_bundle_new_price(components: List[Dict]) -> float:
    """Calculate new price for bundle components."""
    if not components:
        return 0.0
    total = 0.0
    for comp in components:
        qty = comp.get("qty", 1)
        name = comp.get("name", "")
        market_price = comp.get("market_price", 0)
        ai_estimate = comp.get("estimated_value", 0)
        
        if is_weight_plate(name):
            weight_kg = extract_weight_kg(name)
            if weight_kg:
                weight_type = detect_weight_type(name)
                component_new = calculate_weight_based_price(weight_kg, weight_type, is_resale=False)
                total += component_new * qty
                continue
        
        if market_price and market_price > 0:
            component_new = market_price * 1.8
        elif ai_estimate and ai_estimate > 0:
            component_new = ai_estimate * 2.0
        else:
            component_new = BUNDLE_MIN_COMPONENT_VALUE * 2
        total += component_new * qty
    return round(total, 2)


def calculate_bundle_resale(components: List[Dict], bundle_new_price: Optional[float] = None) -> float:
    if not components:
        return 0.0
    total = sum(c.get("market_price", 0) * c.get("qty", 1) for c in components 
                if c.get("price_source") != "ai_estimate" or c.get("qty", 1) == 1)
    discounted = total * (1 - BUNDLE_DISCOUNT_PERCENT)
    if bundle_new_price and bundle_new_price > 0:
        max_bundle = bundle_new_price * MAX_BUNDLE_RESALE_PERCENT_OF_NEW
        if discounted > max_bundle:
            discounted = max_bundle
    return round(discounted, 2)


def price_bundle_components(components: List[Dict], base_product: str, context=None, ua: str = None, query_analysis: Optional[Dict] = None) -> List[Dict]:
    """Price bundle components using market data or AI estimates."""
    priced_components = []
    min_price = _get_min_realistic_price(query_analysis)
    category = _get_category(query_analysis)

    for comp in components:
        name = comp.get("name", "")
        qty = comp.get("qty", 1)
        ai_estimate = comp.get("estimated_value", 0)

        # Weight validation for fitness equipment
        if is_weight_plate(name):
            weight_kg = extract_weight_kg(name)
            if weight_kg:
                weight_type = detect_weight_type(name)
                realistic_price = calculate_weight_based_price(weight_kg, weight_type, is_resale=True)
                priced_components.append({
                    **comp, 
                    "market_price": realistic_price, 
                    "price_source": f"weight_based_{weight_type}",
                    "sample_size": 0,
                    "has_auction_data": False,
                })
                continue

        # Check cache first
        cached = get_cached_component_price(name)
        if cached and cached.get("median_price"):
            median = cached["median_price"]
            validated_price, _ = validate_weight_price(name, median, is_resale=True)
            priced_components.append({
                **comp, 
                "market_price": validated_price, 
                "price_source": f"cache_{cached.get('price_source', 'unknown')}", 
                "sample_size": cached.get("sample_size", 0),
                "has_auction_data": cached.get("has_auction_data", False)
            })
            continue

        # Fallback to AI estimate
        final_estimate = max(ai_estimate, min_price) if ai_estimate < min_price else ai_estimate
        validated_estimate, _ = validate_weight_price(name, final_estimate, is_resale=True)
        priced_components.append({
            **comp, 
            "market_price": validated_estimate, 
            "price_source": "ai_estimate", 
            "sample_size": 0, 
            "has_auction_data": False
        })

    return priced_components


# ==============================================================================
# VARIANT CLUSTERING (v7.0 - uses unified call_ai)
# ==============================================================================

def cluster_variants_from_titles(titles: List[str], base_product: str, category: str = "unknown", query_analysis: Optional[Dict] = None) -> Dict[str, Any]:
    """v7.0: Cluster titles into variants using Claude."""
    if not titles:
        return {"variants": [], "title_to_variant": {}}
    
    unique_titles = list(dict.fromkeys(titles))
    cache_key = f"{base_product}|{len(unique_titles)}"
    _load_caches()
    
    if CACHE_ENABLED and cache_key in _cluster_cache:
        cached = _cluster_cache[cache_key]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            print(f"💾 Using cached clustering for '{base_product}'")
            return cached
    
    print(f"\n🔍 Clustering {len(unique_titles)} titles...")
    
    if is_budget_exceeded():
        return {"reasoning": "Budget exceeded", "variants": [], "title_to_variant": {t: None for t in unique_titles}}
    
    if query_analysis:
        category = query_analysis.get("category", category)
    
    prompt = f"""Gruppiere diese Ricardo-Listings nach PREIS-RELEVANTER Variante.

Suchbegriff: "{base_product}"
Kategorie: "{category}"

LISTINGS:
{chr(10).join(f'{i+1}. "{t}"' for i, t in enumerate(unique_titles[:50]))}

REGELN:
- Variant-Key Format: "{base_product}|[Variante]"
- Nur preis-relevante Unterschiede (Speicher, Grösse, Modell)
- Unklare Listings → null

Antworte NUR als JSON:
{{
  "reasoning": "Strategie",
  "variants": ["{base_product}|Var1", "{base_product}|Var2"],
  "title_to_variant": {{"Titel1": "{base_product}|Var1", "Unklarer": null}}
}}"""

    try:
        raw = call_ai(prompt, max_tokens=2500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                # Clean up variant mappings
                cleaned = {}
                for title, variant in parsed.get("title_to_variant", {}).items():
                    if variant in ("null", None):
                        cleaned[title] = None
                    elif variant:
                        if not variant.startswith(f"{base_product}|"):
                            variant = f"{base_product}|{variant.split('|')[-1]}" if "|" in variant else f"{base_product}|{variant}"
                        cleaned[title] = variant
                    else:
                        cleaned[title] = None
                
                parsed["title_to_variant"] = cleaned
                parsed["variants"] = list(set(v for v in cleaned.values() if v))
                
                # Cache
                if CACHE_ENABLED:
                    parsed["expires_at"] = (datetime.datetime.now() + datetime.timedelta(days=CLUSTER_CACHE_DAYS)).isoformat()
                    _cluster_cache[cache_key] = parsed
                    _save_cluster_cache()
                
                classified = sum(1 for v in parsed["title_to_variant"].values() if v)
                print(f"   ✅ {len(parsed['variants'])} variants, {classified} classified")
                
                return parsed
    except Exception as e:
        print(f"⚠️ Clustering failed: {e}")
    
    return {"reasoning": "Error", "variants": [], "title_to_variant": {t: None for t in unique_titles}}


def get_variant_for_title(title: str, cluster_result: Dict[str, Any], base_product: str) -> Optional[str]:
    title_to_variant = cluster_result.get("title_to_variant", {})
    if title in title_to_variant:
        return title_to_variant[title]
    title_lower = title.lower().strip()
    for cached_title, variant in title_to_variant.items():
        cached_lower = cached_title.lower().strip()
        if cached_lower in title_lower or title_lower in cached_lower:
            return variant
    return None


def variant_key_to_search_term(variant_key: str) -> str:
    if not variant_key:
        return ""
    return variant_key.replace("|", " ").strip()


# ==============================================================================
# MARKET PRICE CALCULATION (unchanged from v6.8)
# ==============================================================================

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
        
        if buy_now and buy_now > unrealistic_floor:
            if buy_now_ceiling is None or buy_now < buy_now_ceiling:
                buy_now_ceiling = buy_now
        
        if not current or current <= 0 or bids == 0:
            continue
        
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
    
    if not price_samples:
        if buy_now_ceiling and buy_now_ceiling > unrealistic_floor:
            resale = buy_now_ceiling * 0.85
            if sanity_reference:
                resale = apply_global_sanity_check(resale, sanity_reference, False, "buy_now_ceiling")
            return {
                "resale_price": round(resale, 2),
                "market_value": round(buy_now_ceiling, 2),
                "source": "buy_now_ceiling_fallback",
                "sample_size": 0,
                "market_based": True,
                "buy_now_ceiling": buy_now_ceiling,
                "confidence": 0.35,
            }
        return None
    
    if len(price_samples) < MIN_SAMPLES_FOR_MARKET_PRICE:
        simple_median = statistics.median([s["price"] for s in price_samples])
        has_very_high = any(s.get("bids", 0) >= VERY_HIGH_ACTIVITY_BID_THRESHOLD for s in price_samples)
        has_high = any(s.get("bids", 0) >= HIGH_ACTIVITY_BID_THRESHOLD for s in price_samples)
        
        if has_very_high:
            resale_price, confidence, source = simple_median * 0.95, 0.70, "very_high_activity_single"
        elif has_high:
            resale_price, confidence, source = simple_median * 0.90, 0.55, "high_activity_single"
        else:
            resale_price, confidence, source = simple_median * 0.85, 0.4, "auction_demand_low_confidence"
        
        if buy_now_ceiling and buy_now_ceiling > simple_median and resale_price > buy_now_ceiling * 0.95:
            resale_price = buy_now_ceiling * 0.95
        
        if sanity_reference:
            resale_price = apply_global_sanity_check(resale_price, sanity_reference, False, source)
        
        return {
            "resale_price": round(resale_price, 2),
            "market_value": round(simple_median, 2),
            "source": source,
            "sample_size": len(price_samples),
            "market_based": True,
            "buy_now_ceiling": buy_now_ceiling,
            "confidence": confidence,
        }
    
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
            results[vk] = {
                "new_price": cached.get("new_price") if cached else None,
                "transport_car": cached.get("transport_car", True) if cached else True,
                "resale_price": market_data["resale_price"],
                "market_based": True,
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
    
    # v7.0: Use REAL web search for new prices!
    if need_new_price:
        print(f"\n🌐 v7.0: Web searching new prices for {len(need_new_price)} variants...")
        
        for vk in need_new_price:
            # Extract search terms
            clean_name = vk.replace("|", " ").strip()
            clean_result = extract_clean_search_terms(clean_name, category)
            search_terms = clean_result.get("search_terms", [clean_name])
            
            # Try web search first (THE GAME CHANGER!)
            web_result = search_web_for_new_price(vk, search_terms, category)
            
            if web_result and web_result.get("new_price"):
                new_price = web_result["new_price"]
                price_source = web_result.get("price_source", "web_search")
                
                # Calculate resale
                resale_price = new_price * resale_rate
                max_resale = new_price * MAX_RESALE_PERCENT_OF_NEW
                if resale_price > max_resale:
                    resale_price = max_resale
                
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
                
                print(f"   ✅ {vk}: {new_price} CHF ({price_source})")
            else:
                # Fallback to AI estimate
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
{chr(10).join(f"- {vk}" for vk in variant_keys)}

Antworte NUR als JSON:
{{"Produkt|Variante": {{"new_price": X, "resale_price": X, "transport": true/false}}, ...}}"""

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
        return ("skip", f"Profit {profit:.0f} CHF unter Minimum ({MIN_PROFIT_THRESHOLD:.0f})")
    if has_buy_now and profit >= 80:
        return ("buy_now", f"🔥 Sofort kaufen! Profit {profit:.0f} CHF")
    if has_buy_now and profit >= 40:
        return ("buy_now", f"Kaufen empfohlen, Profit {profit:.0f} CHF")
    if is_auction:
        if bids >= 15:
            return ("watch", f"⚠️ Heiss umkämpft ({bids} Gebote)")
        if hours < 2 and profit >= 40:
            return ("bid_now", f"🔥 Endet bald! Max {profit:.0f} CHF Profit möglich")
        if hours < 6 and profit >= 30:
            return ("bid", f"Bieten empfohlen, endet in {hours:.0f}h")
        if hours < 24 and profit >= 40:
            return ("bid", f"Heute bieten, Profit {profit:.0f} CHF")
        if profit >= 60:
            return ("watch", f"Beobachten, guter Profit ({profit:.0f} CHF)")
        return ("watch", f"Beobachten, {hours:.0f}h verbleibend")
    if profit >= 30:
        return ("watch", f"Anfragen, Profit {profit:.0f} CHF")
    return ("watch", f"Beobachten, Profit {profit:.0f} CHF")


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
        hours = hours_remaining or 999
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
    
    return max(0.0, min(10.0, round(score, 1)))


# ==============================================================================
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
        bundle_result = detect_bundle_with_ai(
            title=title,
            description=description,
            query=query,
            image_url=image_url,
            use_vision=random.random() < VISION_RATE if image_url else False,
            query_analysis=query_analysis,
        )
        
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
# HELPER FOR MAIN.PY COMPATIBILITY
# ==============================================================================

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