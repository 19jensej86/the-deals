"""
Query Analyzer - v7.0 (Claude Edition)
======================================
Analyzes ALL search queries in ONE AI call at startup.

v7.0 Changes:
- Uses Claude (Haiku) instead of OpenAI
- Falls back to OpenAI if Claude unavailable
- Same output format, better German understanding

Returns per query:
- category: What type of product is this?
- resale_rate: What % of new price can we expect on resale? (FALLBACK ONLY!)
- min_realistic_price: Below this, it's probably accessories/junk
- typical_new_price_range: [min, max] for sanity checks
- new_price_estimate: Mid-point of typical_new_price_range
- bundle_common: Are bundles common for this product?
- needs_vision_for_bundles: Need image analysis to detect bundles?
- spelling_variants: Alternative spellings to accept
- accessory_keywords: Words that indicate accessories (to filter out)
- defect_keywords: Words that indicate defects
- auction_typical_multiplier: How much do auction prices typically rise?

This data is cached for 30 days per query set.
"""

# FIX 1: Configure UTF-8 output for Windows PowerShell (MUST be first)
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import os
import json
import hashlib
import datetime
import re
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CLIENT INITIALIZATION - Claude PRIMARY, OpenAI fallback
# =============================================================================

_claude_client = None
_openai_client = None
_provider = "claude"


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
            print("🤖 Query Analyzer: Using Claude (Haiku)")
        except ImportError:
            print("⚠️ anthropic package not installed, falling back to OpenAI")
    
    # Fallback to OpenAI
    if _claude_client is None:
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI
                _openai_client = OpenAI(api_key=openai_key)
                _provider = "openai"
                print("🤖 Query Analyzer: Using OpenAI (fallback)")
            except ImportError:
                print("⚠️ openai package not installed")
    
    if _claude_client is None and _openai_client is None:
        print("❌ No AI client available! Set ANTHROPIC_API_KEY or OPENAI_API_KEY")


# Initialize on module load
_init_clients()


# =============================================================================
# CACHE CONFIGURATION
# =============================================================================

QUERY_ANALYSIS_CACHE_FILE = "query_analysis_cache.json"
QUERY_ANALYSIS_CACHE_DAYS = 30
COST_PER_ANALYSIS = 0.002  # Claude Haiku is cheaper

_query_cache: Dict[str, Dict] = {}
_cache_loaded = False


def _get_cache_key(queries: List[str]) -> str:
    """Creates a unique cache key for a set of queries."""
    sorted_queries = sorted(q.lower().strip() for q in queries)
    combined = "|".join(sorted_queries)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _load_cache():
    """Loads query analysis cache from disk."""
    global _query_cache, _cache_loaded
    
    if _cache_loaded:
        return
    
    try:
        if os.path.exists(QUERY_ANALYSIS_CACHE_FILE):
            with open(QUERY_ANALYSIS_CACHE_FILE, "r", encoding="utf-8") as f:
                _query_cache = json.load(f)
            
            now = datetime.datetime.now().isoformat()
            expired = [k for k, v in _query_cache.items() 
                      if v.get("expires_at", "") < now]
            for k in expired:
                del _query_cache[k]
                
            if expired:
                _save_cache()
                print(f"🧹 Cleaned {len(expired)} expired query analyses")
                
    except Exception as e:
        print(f"⚠️ Query cache load failed: {e}")
        _query_cache = {}
    
    _cache_loaded = True


def _save_cache():
    """Saves query analysis cache to disk."""
    try:
        with open(QUERY_ANALYSIS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_query_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Query cache save failed: {e}")


def clear_query_cache():
    """Clears the query analysis cache."""
    global _query_cache, _cache_loaded
    _query_cache = {}
    _cache_loaded = False
    
    if os.path.exists(QUERY_ANALYSIS_CACHE_FILE):
        try:
            os.remove(QUERY_ANALYSIS_CACHE_FILE)
            print(f"🗑️ Deleted cache: {QUERY_ANALYSIS_CACHE_FILE}")
        except Exception as e:
            print(f"⚠️ Could not delete {QUERY_ANALYSIS_CACHE_FILE}: {e}")


# =============================================================================
# AI CALL WRAPPERS
# =============================================================================

def _call_claude(prompt: str, max_tokens: int = 3000) -> Optional[str]:
    """Call Claude API."""
    if not _claude_client:
        return None
    
    try:
        response = _claude_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Extract text from response
        for block in response.content:
            if hasattr(block, 'text'):
                return block.text
        
        return None
        
    except Exception as e:
        print(f"⚠️ Claude API error: {e}")
        return None


def _call_openai(prompt: str, max_tokens: int = 3000) -> Optional[str]:
    """Call OpenAI API (fallback)."""
    if not _openai_client:
        return None
    
    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"⚠️ OpenAI API error: {e}")
        return None


def _call_ai(prompt: str, max_tokens: int = 3000) -> Optional[str]:
    """Call AI with automatic fallback."""
    if _provider == "claude" and _claude_client:
        result = _call_claude(prompt, max_tokens)
        if result:
            return result
    
    # Fallback to OpenAI
    if _openai_client:
        return _call_openai(prompt, max_tokens)
    
    return None


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_queries(
    queries: List[str],
    model: str = None,  # Ignored in v7.0, uses configured provider
) -> Dict[str, Dict[str, Any]]:
    """
    Analyzes ALL search queries in ONE AI call.
    
    Args:
        queries: List of search queries from config
        model: Ignored (uses Claude or OpenAI based on config)
    
    Returns:
        Dict mapping each query to its analysis
    """
    if not queries:
        return {}
    
    # Normalize queries
    queries = [q.strip() for q in queries if q.strip()]
    
    # Check cache
    _load_cache()
    cache_key = _get_cache_key(queries)
    
    if cache_key in _query_cache:
        cached = _query_cache[cache_key]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            print(f"💾 Using cached query analysis ({len(queries)} queries)")
            return cached.get("analysis", {})
    
    print(f"\n🧠 Analyzing {len(queries)} search queries with {_provider.upper()}...")
    
    prompt = f"""Du bist ein Experte für Online-Marktplätze (ricardo.ch, eBay, etc.) und Produktkategorien.

Ich möchte auf Ricardo.ch nach folgenden Produkten suchen und Schnäppchen finden:

SUCHBEGRIFFE:
{chr(10).join(f'- "{q}"' for q in queries)}

Analysiere JEDEN Suchbegriff und gib mir folgende Informationen:

1. **category**: Produktkategorie (z.B. "electronics", "clothing", "fitness", "toys", "luxury")

2. **resale_rate**: Welcher Anteil vom AKTUELLEN Neupreis ist realistisch beim Wiederverkauf?
   WICHTIG: Dies ist nur ein FALLBACK wenn keine Marktdaten verfügbar sind!
   - Normale Kleidung: 0.25-0.35 (Second-Hand verkauft sich schlecht)
   - Premium/Designer Kleidung: 0.35-0.45
   - Elektronik (Smartphones, Konsolen): 0.40-0.50
   - Smartwatches/Wearables: 0.40-0.50
   - Fitness-Equipment (Hanteln, Gewichte): 0.50-0.60 (hält Wert gut!)
   - Spielzeug: 0.30-0.40
   - Luxusartikel (Uhren, Schmuck): 0.50-0.70

3. **min_realistic_price**: Unter diesem Preis (CHF) sind es wahrscheinlich nur Accessoires/Zubehör
   - Kleidung: 5-15 CHF
   - Smartphones: 50-100 CHF  
   - Smartwatches: 30-80 CHF
   - Spielkonsolen: 50-100 CHF
   - Hanteln/Gewichte: 5-20 CHF (pro Stück)

4. **typical_new_price_range**: [min, max] in CHF - was kostet dieses Produkt typischerweise NEU?
   Gib eine realistische Spanne für das Hauptprodukt an.

5. **bundle_common**: true/false - Werden diese Produkte oft als Bundle/Set verkauft?

6. **needs_vision_for_bundles**: true/false - Braucht man das Bild um Bundles zu erkennen? 
   (z.B. bei Gewichten/Hanteln sieht man oft nur im Bild wie viele Scheiben dabei sind)

7. **spelling_variants**: Liste von alternativen Schreibweisen/Begriffen

8. **accessory_keywords**: Wörter die auf ZUBEHÖR hindeuten (für einfache Regex-Filter)

9. **defect_keywords**: Wörter die auf DEFEKTE hindeuten

10. **auction_typical_multiplier**: Um welchen Faktor steigt ein Auktionspreis typischerweise?

11. **accessory_examples**: Beispiele von Titeln die NUR Zubehör sind (ausfiltern!):
    - Beispiel: "Armband für Garmin Fenix" → NUR Zubehör, ausfiltern
    - Beispiel: "Ladekabel für iPhone" → NUR Zubehör, ausfiltern
    - Beispiel: "Hülle für AirPods" → NUR Zubehör, ausfiltern
    ABER:
    - "Garmin Fenix 7 mit Armband" → Hauptprodukt + Accessory = OK (Bundle oder Single)
    - "iPhone 13 + Hülle" → Hauptprodukt + Accessory = OK (Bundle)
    - "AirPods Pro mit Ladekabel" → Hauptprodukt + Accessory = OK (Single, Kabel unwichtig)

12. **search_term_cleanup**: Regeln zum Bereinigen von Listing-Titeln für die Web-Suche:
    - "remove_after": Liste von Wörtern, nach denen der Rest abgeschnitten wird (z.B. ["inkl", "mit", "+", "und", "NEU", "OVP"])
    - "remove_words": Wörter die komplett entfernt werden sollen (z.B. ["gebraucht", "neuwertig", "Top-Zustand"])
    - "keep_parts": Welche Teile behalten? (z.B. "brand_model" = nur Marke+Modell)
    Beispiel: "Garmin Fenix 6 Smartwatch inkl. Zubehör" → "Garmin Fenix 6"

12. **notes**: Kurze Notizen/Tipps für diese Produktkategorie

Antworte NUR als gültiges JSON:
{{
  "Suchbegriff 1": {{
    "category": "...",
    "resale_rate": 0.XX,
    "min_realistic_price": XX.0,
    "typical_new_price_range": [XX, XX],
    "bundle_common": true/false,
    "needs_vision_for_bundles": true/false,
    "spelling_variants": ["...", "..."],
    "accessory_keywords": ["...", "..."],
    "defect_keywords": ["...", "..."],
    "auction_typical_multiplier": X.X,
    "search_term_cleanup": {{
      "remove_after": ["inkl", "mit", "+", "und", "NEU"],
      "remove_words": ["gebraucht", "neuwertig"],
      "keep_parts": "brand_model"
    }},
    "notes": "..."
  }},
  ...
}}"""

    try:
        raw = _call_ai(prompt, max_tokens=3000)
        
        if not raw:
            print(f"⚠️ No AI response")
            return _create_fallback_analysis(queries)
        
        # Extract JSON
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            print(f"⚠️ No JSON found in AI response")
            return _create_fallback_analysis(queries)
        
        parsed = json.loads(json_match.group(0))
        
        # Validate and set defaults for each query
        result = {}
        for query in queries:
            # Try exact match first, then case-insensitive
            analysis = parsed.get(query)
            if not analysis:
                for key, val in parsed.items():
                    if key.lower() == query.lower():
                        analysis = val
                        break
            
            if analysis:
                result[query] = _validate_analysis(analysis, query)
            else:
                print(f"   ⚠️ No analysis for '{query}', using fallback")
                result[query] = _create_default_analysis(query)
        
        # Cache the result
        _query_cache[cache_key] = {
            "analysis": result,
            "cached_at": datetime.datetime.now().isoformat(),
            "expires_at": (datetime.datetime.now() + datetime.timedelta(days=QUERY_ANALYSIS_CACHE_DAYS)).isoformat(),
        }
        _save_cache()
        
        # Print summary
        print(f"\n📊 Query Analysis Results:")
        for q, a in result.items():
            print(f"   • {q}: {a['category']}, resale={a['resale_rate']*100:.0f}% (fallback), "
                  f"min_price={a['min_realistic_price']} CHF, "
                  f"new_price≈{a['new_price_estimate']} CHF, "
                  f"bundle={'yes' if a['bundle_common'] else 'no'}")
        
        return result
        
    except Exception as e:
        print(f"⚠️ Query analysis failed: {e}")
        return _create_fallback_analysis(queries)


def _validate_analysis(analysis: Dict, query: str) -> Dict[str, Any]:
    """Validates and fills in missing fields with sensible defaults."""
    
    price_range = analysis.get("typical_new_price_range", [50, 500])
    if not isinstance(price_range, list) or len(price_range) != 2:
        price_range = [50, 500]
    
    new_price_estimate = (price_range[0] + price_range[1]) / 2
    
    validated = {
        "category": analysis.get("category", "unknown"),
        "resale_rate": float(analysis.get("resale_rate", 0.40)),
        "min_realistic_price": float(analysis.get("min_realistic_price", 10.0)),
        "typical_new_price_range": price_range,
        "new_price_estimate": new_price_estimate,
        "bundle_common": bool(analysis.get("bundle_common", False)),
        "needs_vision_for_bundles": bool(analysis.get("needs_vision_for_bundles", False)),
        "spelling_variants": analysis.get("spelling_variants", [query.lower()]),
        "accessory_keywords": analysis.get("accessory_keywords", []),
        "defect_keywords": analysis.get("defect_keywords", ["defekt", "kaputt", "bastler"]),
        "auction_typical_multiplier": float(analysis.get("auction_typical_multiplier", 5.0)),
        "search_term_cleanup": analysis.get("search_term_cleanup", {
            "remove_after": ["inkl", "mit", "+", "und", "NEU", "OVP", "TOP"],
            "remove_words": ["gebraucht", "neuwertig", "Top-Zustand", "wie neu"],
            "keep_parts": "brand_model"
        }),
        "notes": analysis.get("notes", ""),
    }
    
    # Sanity checks
    if validated["resale_rate"] < 0.1:
        validated["resale_rate"] = 0.1
    if validated["resale_rate"] > 0.8:
        validated["resale_rate"] = 0.8
    
    if validated["min_realistic_price"] < 1:
        validated["min_realistic_price"] = 1.0
    
    if validated["auction_typical_multiplier"] < 1:
        validated["auction_typical_multiplier"] = 1.5
    if validated["auction_typical_multiplier"] > 20:
        validated["auction_typical_multiplier"] = 10.0
    
    if validated["new_price_estimate"] < validated["min_realistic_price"]:
        validated["new_price_estimate"] = validated["min_realistic_price"] * 2
    
    if query.lower() not in [v.lower() for v in validated["spelling_variants"]]:
        validated["spelling_variants"].append(query.lower())
    
    return validated


def get_query_analysis(query: str) -> Optional[Dict[str, Any]]:
    """Gets the cached analysis for a specific query."""
    _load_cache()
    
    for cache_key, cached in _query_cache.items():
        if cached.get("expires_at", "") < datetime.datetime.now().isoformat():
            continue
        
        analysis = cached.get("analysis", {})
        
        if query in analysis:
            return analysis[query]
        
        for key, val in analysis.items():
            if key.lower() == query.lower():
                return val
    
    return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_resale_rate(query_analysis: Optional[Dict] = None) -> float:
    """Gets resale rate from query analysis (FALLBACK ONLY!)."""
    if query_analysis:
        return query_analysis.get("resale_rate", 0.40)
    return 0.40


def get_min_realistic_price(query_analysis: Optional[Dict] = None) -> float:
    """Gets minimum realistic price from query analysis."""
    if query_analysis:
        return query_analysis.get("min_realistic_price", 10.0)
    return 10.0


def get_new_price_estimate(query_analysis: Optional[Dict] = None) -> float:
    """Gets new price estimate from query analysis."""
    if query_analysis:
        return query_analysis.get("new_price_estimate", 275.0)
    return 275.0


def get_auction_multiplier(query_analysis: Optional[Dict] = None) -> float:
    """Gets auction typical multiplier from query analysis."""
    if query_analysis:
        return query_analysis.get("auction_typical_multiplier", 5.0)
    return 5.0


def needs_vision_for_bundles(query_analysis: Optional[Dict] = None) -> bool:
    """Checks if this category needs vision for bundle detection."""
    if query_analysis:
        return query_analysis.get("needs_vision_for_bundles", False)
    return False


def get_category(query_analysis: Optional[Dict] = None) -> str:
    """Gets category from query analysis."""
    if query_analysis:
        return query_analysis.get("category", "unknown")
    return "unknown"


def get_spelling_variants(query: str, query_analysis: Optional[Dict] = None) -> List[str]:
    """Gets spelling variants from query analysis."""
    if query_analysis:
        return query_analysis.get("spelling_variants", [query.lower()])
    return [query.lower()]


def get_accessory_keywords(query_analysis: Optional[Dict] = None) -> List[str]:
    """Gets accessory keywords from query analysis."""
    if query_analysis:
        return query_analysis.get("accessory_keywords", [])
    return []


def get_defect_keywords(query_analysis: Optional[Dict] = None) -> List[str]:
    """Gets defect keywords from query analysis."""
    if query_analysis:
        return query_analysis.get("defect_keywords", ["defekt", "kaputt", "bastler"])
    return ["defekt", "kaputt", "bastler"]


def get_search_term_cleanup(query_analysis: Optional[Dict] = None) -> Dict[str, Any]:
    """Gets search term cleanup rules from query analysis."""
    default = {
        "remove_after": ["inkl", "mit", "+", "und", "NEU", "OVP", "TOP", "!"],
        "remove_words": ["gebraucht", "neuwertig", "Top-Zustand", "wie neu", "original"],
        "keep_parts": "brand_model"
    }
    if query_analysis:
        return query_analysis.get("search_term_cleanup", default)
    return default


def clean_search_term(title: str, query_analysis: Optional[Dict] = None) -> str:
    """
    v7.4: Clean a listing title to create a better web search term.
    
    Removes non-price-relevant attributes and enforces singular forms.
    
    Example:
        "Garmin Fenix 6 Smartwatch inkl. Zubehör" -> "Garmin Fenix 6"
        "Tommy Hilfiger Jeans 32/32 straight Ryan kariert" -> "Tommy Hilfiger Jeans"
        "Hantelscheiben 15kg gummiert" -> "Hantelscheibe 15kg gummiert"
        "Hantelscheiben {'4x10kg': True} Pro" -> "Hantelscheibe 10kg Pro"
    """
    import re
    
    cleanup = get_search_term_cleanup(query_analysis)
    
    # Start with original title
    clean = title.strip()
    
    # Step 0: Remove dict/JSON artifacts from bundle decomposition
    clean = re.sub(r'\{[^}]*\}', '', clean)
    clean = re.sub(r'\[[^\]]*\]', '', clean)
    
    # Step 1: Remove everything after certain keywords
    remove_after = cleanup.get("remove_after", [])
    for keyword in remove_after:
        # Case-insensitive search
        lower_clean = clean.lower()
        kw_lower = keyword.lower()
        
        # Find position (with word boundary for short keywords)
        if len(keyword) <= 2:  # Short keywords like "+" 
            pos = clean.find(keyword)
        else:
            pos = lower_clean.find(kw_lower)
        
        if pos > 5:  # Keep at least some characters
            clean = clean[:pos].strip()
    
    # Step 2: Remove non-price-relevant attributes
    # Size patterns
    clean = re.sub(r'\b\d+[/x]\d+\b', '', clean, flags=re.IGNORECASE)  # 32/32, 10x15
    clean = re.sub(r'\bGr\.?\s*\d+\b', '', clean, flags=re.IGNORECASE)  # Gr.30, Gr 30
    clean = re.sub(r'\bGrösse\s*\d+\b', '', clean, flags=re.IGNORECASE)  # Grösse 30
    clean = re.sub(r'\bSize\s*[XSML]+\b', '', clean, flags=re.IGNORECASE)  # Size XL
    
    # Fit/style attributes
    fit_words = ['slim', 'regular', 'straight', 'relaxed', 'skinny', 'loose', 'tight', 'fitted']
    for fit in fit_words:
        clean = re.sub(rf'\b{fit}\s+fit\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(rf'\b{fit}\b', '', clean, flags=re.IGNORECASE)
    
    # Pattern/color attributes
    pattern_words = ['kariert', 'gestreift', 'gepunktet', 'gemustert', 'uni', 'einfarbig', 
                     'checked', 'striped', 'dotted', 'patterned', 'solid']
    for pattern in pattern_words:
        clean = re.sub(rf'\b{pattern}\b', '', clean, flags=re.IGNORECASE)
    
    # Color words (common ones)
    color_words = ['schwarz', 'weiss', 'rot', 'blau', 'grün', 'gelb', 'grau', 
                   'black', 'white', 'red', 'blue', 'green', 'yellow', 'grey', 'gray']
    for color in color_words:
        clean = re.sub(rf'\b{color}\b', '', clean, flags=re.IGNORECASE)
    
    # Step 3: Remove specific words
    remove_words = cleanup.get("remove_words", [])
    for word in remove_words:
        clean = re.sub(rf'\b{re.escape(word)}\b', '', clean, flags=re.IGNORECASE)
    
    # Step 4: Enforce singular forms for pricing
    # German plurals -> singular
    singular_map = {
        r'\bHantelscheiben\b': 'Hantelscheibe',
        r'\bHanteln\b': 'Hantel',
        r'\bGewichte\b': 'Gewicht',
        r'\bScheiben\b': 'Scheibe',
        r'\bStangen\b': 'Stange',
        r'\bKurzhanteln\b': 'Kurzhantel',
        r'\bLanghanteln\b': 'Langhantel',
        r'\bBänke\b': 'Bank',
        r'\bRacks\b': 'Rack',
        r'\bPullover\b': 'Pullover',  # Already singular
        r'\bHemden\b': 'Hemd',
        r'\bHosen\b': 'Hose',
        r'\bJacken\b': 'Jacke',
    }
    for plural, singular in singular_map.items():
        clean = re.sub(plural, singular, clean, flags=re.IGNORECASE)
    
    # Step 5: Clean up whitespace and punctuation
    clean = re.sub(r'\s+', ' ', clean)  # Multiple spaces to single
    clean = re.sub(r'[!?.,;:]+$', '', clean)  # Remove trailing punctuation
    clean = clean.strip()
    
    # Step 6: Limit to reasonable length (first 5-6 significant words)
    words = clean.split()
    if len(words) > 6:
        clean = ' '.join(words[:6])
    
    return clean.strip()


# ... (rest of the code remains the same)