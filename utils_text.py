"""
Text Utilities for DealFinder - v7.2
====================================
- Whitespace normalization
- Variant extraction (storage, year, color, size)
- Accessory detection (HARDCODED + query-aware + category-aware)
- Defect detection (no AI needed!)
- PLZ extraction

v7.2 CHANGES:
- is_accessory_title() now accepts query and category parameters
- Query-aware: If user searches for "Armband", don't filter armbands!
- Category-aware: For fitness, "set" is NOT an accessory (bundles!)
- Position-aware: "Armband für Garmin" vs "Garmin mit Armband"
- Added get_accessory_keywords() and get_defect_keywords() exports
"""

import re
from typing import Optional, Dict, Tuple, List


def normalize_whitespace(s: str) -> str:
    """Normalizes whitespace in string"""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s, flags=re.S).strip()


def contains_excluded_terms(text: str, terms: List[str]) -> bool:
    """Checks if text contains any excluded terms"""
    t = (text or "").lower()
    return any(term.lower() in t for term in (terms or []))


def extract_plz(location_text: str) -> Optional[str]:
    """Extracts Swiss postal code (4 digits) from text"""
    if not location_text:
        return None
    m = re.search(r"\b(\d{4})\b", location_text)
    return m.group(1) if m else None


# ==============================================================================
# VARIANT EXTRACTION
# ==============================================================================

def extract_storage_gb(title: str) -> Optional[int]:
    """Extracts storage size in GB from title."""
    if not title:
        return None
    match = re.search(r'(\d+)\s*GB', title, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_year(title: str) -> Optional[int]:
    """Extracts year from title."""
    if not title:
        return None
    match = re.search(r'\b(19|20)\d{2}\b', title)
    if match:
        year = int(match.group(0))
        if 1990 <= year <= 2030:
            return year
    return None


def extract_size(title: str) -> Optional[str]:
    """Extracts size from title."""
    if not title:
        return None
    
    match = re.search(r'(?:gr[öo]sse|size|gr\.?)\s*(\d+)', title, re.IGNORECASE)
    if match:
        return match.group(1)
    
    match = re.search(r'\b(XXS|XS|S|M|L|XL|XXL|XXXL)\b', title, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None


def extract_weight_kg(title: str) -> Optional[float]:
    """Extracts weight in kg from title."""
    if not title:
        return None
    
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', title, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(',', '.'))
        except ValueError:
            pass
    return None


def extract_variant_attributes(title: str, critical_attributes: List[str]) -> Dict[str, any]:
    """Extracts variant attributes from title based on what's critical."""
    result = {}
    
    for attr in critical_attributes:
        if attr == "storage_gb":
            result[attr] = extract_storage_gb(title)
        elif attr == "year":
            result[attr] = extract_year(title)
        elif attr == "size":
            result[attr] = extract_size(title)
        elif attr == "weight_kg":
            result[attr] = extract_weight_kg(title)
        elif attr == "color":
            colors = [
                "schwarz", "black", "weiss", "white", "blau", "blue",
                "rot", "red", "grün", "green", "gelb", "yellow",
                "silber", "silver", "gold", "rosa", "pink", "purple", "lila",
                "grau", "grey", "gray", "orange", "braun", "brown",
                "minze", "mint", "coral", "navy"
            ]
            title_lower = title.lower()
            for color in colors:
                if color in title_lower:
                    result[attr] = color
                    break
            else:
                result[attr] = None
        else:
            result[attr] = None
    
    return result


def build_variant_key(base_product: str, variant_attrs: Dict[str, any]) -> Optional[str]:
    """Builds variant key from extracted attributes."""
    if not base_product:
        return None
    
    if not variant_attrs:
        return base_product
    
    present_attrs = {k: v for k, v in variant_attrs.items() if v is not None}
    
    if len(present_attrs) == 0:
        return base_product
    
    parts = [base_product]
    for key, value in sorted(present_attrs.items()):
        if key == "storage_gb":
            parts.append(f"{value}GB")
        elif key == "year":
            parts.append(str(value))
        elif key == "size":
            parts.append(f"Size{value}")
        elif key == "weight_kg":
            parts.append(f"{value}kg")
        else:
            parts.append(str(value))
    
    return "|".join(parts)


# ==============================================================================
# ACCESSORY DETECTION - v7.2 HARDCODED + SMART LOGIC
# ==============================================================================

# Base hardcoded accessory keywords - apply to most product categories
ACCESSORY_KEYWORDS = [
    # Hüllen & Schutz
    "hülle", "case", "cover", "bumper", "etui", "tasche",
    "folie", "schutzfolie", "schutzhülle", "skin",
    "panzerglas", "schutzglas", "displayschutz",
    
    # Kabel & Ladegeräte
    "kabel", "ladekabel", "usb-c", "lightning",
    "ladegerät", "charger", "netzteil", "adapter", "ladestation",
    
    # Halterungen
    "halterung", "halter", "ständer", "stand", "dock",
    "wandhalterung",
    
    # Uhren/Smartwatch-Zubehör (KRITISCH für Garmin!)
    "armband", "ersatzarmband", "uhrenarmband",
    "band", "strap", "bracelet",
    "silikon",  # "Silikon Band" etc.
    
    # Sonstiges Zubehör
    "ersatzteil", "ersatzteile",
    "zubehör", "accessoire",
    "powerbank", "ersatzakku",
    "speicherkarte", "sd-karte",
    "stylus", "stift", "pen",
    "tastatur", "keyboard",
    "maus", "mouse",
    "kopfhörer", "earbuds",  # Note: AirPods can be main product
]

# Keywords that should NEVER be treated as accessory for FITNESS category
FITNESS_NOT_ACCESSORY = [
    "set",      # Hantelscheiben-Sets sind wertvoll!
    "stange",   # Langhantelstangen sind Hauptprodukte
    "scheibe",  # Hantelscheiben = Hauptprodukt
    "bumper",   # Bumper Plates = Hauptprodukt (100kg = ~300 CHF!)
    "plate",    # Weight plates = Hauptprodukt
    "hantel",   # Hanteln = Hauptprodukt
    "gewicht",  # Gewichte = Hauptprodukt
]

# v8.0: CLOTHING PRODUCT TYPES (markenagnostisch!)
# Diese definieren die Kategorie "clothing" - NICHT Marken!
CLOTHING_PRODUCT_TYPES = [
    "jacke", "jacket", "parka", "mantel", "coat", "blazer", "weste",
    "pullover", "sweater", "hoodie", "sweatshirt", "cardigan",
    "hemd", "shirt", "bluse", "polo", "t-shirt", "top",
    "hose", "jeans", "pants", "shorts", "chino", "jogger",
    "kleid", "dress", "rock", "skirt",
    "tasche", "handtasche", "bag", "shopper", "rucksack", "backpack",
    "schuhe", "shoes", "sneaker", "stiefel", "boots", "sandalen",
    "gürtel", "belt", "schal", "scarf", "mütze", "cap", "hat",
]

# v8.0: Bei Clothing sind Taschen/Accessoires HAUPTPRODUKTE (nicht Zubehör!)
# Diese werden aus ACCESSORY_KEYWORDS gefiltert wenn category=clothing
CLOTHING_MAIN_PRODUCTS = [
    "tasche", "handtasche", "bag", "shopper", "tote",
    "rucksack", "backpack",
    "gürtel", "belt",
    "schal", "scarf", "tuch",
    "mütze", "cap", "hat", "hut", "beanie",
    "geldbörse", "wallet", "portemonnaie",
]

# Main product keywords - if present, need position check
MAIN_PRODUCT_KEYWORDS = [
    # Smartphones
    "iphone", "samsung", "galaxy", "pixel", "huawei", "xiaomi", "oneplus",
    "handy", "smartphone", "telefon", "mobile",
    # Tablets
    "tablet", "ipad",
    # Laptops
    "laptop", "notebook", "macbook", "thinkpad",
    # Watches
    "watch", "uhr", "smartwatch", "apple watch",
    "garmin", "fenix", "forerunner", "vivoactive", "venu", "instinct",
    "fitbit", "polar", "suunto", "coros",
    # Vehicles
    "auto", "car", "pkw", "fahrzeug",
    "bike", "fahrrad", "velo", "e-bike",
    # Gaming
    "konsole", "playstation", "xbox", "nintendo", "switch",
    # Camera
    "kamera", "camera", "dslr", "spiegelreflex",
    # TV/Monitor
    "tv", "fernseher", "monitor", "bildschirm",
    # Printer
    "drucker", "printer",
    # Fitness (so bundles aren't filtered)
    "hantelscheiben", "langhantel", "kurzhantel",
]

# Fitness category indicators
FITNESS_INDICATORS = [
    "hantel", "gewicht", "fitness", "gym", "training",
    "langhantel", "kurzhantel", "scheibe", "plate",
    "kettlebell", "dumbbell", "barbell",
]


def get_accessory_keywords() -> List[str]:
    """Returns the hardcoded accessory keywords list."""
    return ACCESSORY_KEYWORDS.copy()


def get_defect_keywords() -> List[str]:
    """Returns combined defect keywords list."""
    return DEFECT_KEYWORDS_STRONG + DEFECT_KEYWORDS_WEAK


def detect_category(query: str) -> str:
    """
    Detects product category from query based on PRODUCT TYPES, not brands!
    
    v8.0: Markenagnostisch - erkennt Kategorie aus Produkttypen im Query.
    """
    query_lower = (query or "").lower()
    
    # v8.0: Clothing = Produkttypen (NICHT Marken!)
    if any(pt in query_lower for pt in CLOTHING_PRODUCT_TYPES):
        return "clothing"
    
    if any(ind in query_lower for ind in FITNESS_INDICATORS):
        return "fitness"
    
    if any(kw in query_lower for kw in ["garmin", "smartwatch", "fitbit", "polar", "apple watch"]):
        return "smartwatch"
    
    if any(kw in query_lower for kw in ["iphone", "samsung", "handy", "smartphone", "pixel"]):
        return "smartphone"
    
    return "general"


def is_accessory_title(title: str, query: str = "", category: str = "") -> bool:
    """
    Detects if title is clearly an accessory (not the main product).
    
    v7.2 LOGIC:
    1. If query itself contains accessory keyword → DON'T filter (user wants accessories!)
    2. If fitness category and "set/stange/scheibe" → DON'T filter (bundles!)
    3. If accessory keyword found but no main product → Filter
    4. If accessory keyword + main product → Check position:
       - "Armband für Garmin" → Filter (accessory first)
       - "Garmin mit Armband" → DON'T filter (bundle!)
    
    Args:
        title: The listing title to check
        query: The search query (optional, for query-aware filtering)
        category: The product category (optional, for category-specific rules)
    
    Returns:
        True if listing should be SKIPPED (is accessory)
    """
    if not title:
        return False
    
    title_lower = title.lower()
    query_lower = (query or "").lower()
    
    # Auto-detect category if not provided
    if not category and query:
        category = detect_category(query)
    category_lower = (category or "").lower()
    
    # Build effective accessory keywords list
    effective_keywords = ACCESSORY_KEYWORDS.copy()
    
    # RULE 1: If query contains accessory keyword → user WANTS accessories!
    for kw in effective_keywords:
        if kw in query_lower:
            return False  # Don't filter - user is searching for this!
    
    # RULE 2a: Clothing category exception - bags, belts, etc. are main products!
    if category_lower in ["clothing", "fashion", "mode"]:
        effective_keywords = [kw for kw in effective_keywords 
                             if kw not in CLOTHING_MAIN_PRODUCTS]
    
    # RULE 2b: Fitness category exception for bundles
    if category_lower in ["fitness", "sport"]:
        # Remove bundle-related keywords for fitness
        effective_keywords = [kw for kw in effective_keywords 
                             if kw not in FITNESS_NOT_ACCESSORY]
    
    # Check if title contains any accessory keyword
    found_accessory_kw = None
    for kw in effective_keywords:
        if kw in title_lower:
            found_accessory_kw = kw
            break
    
    if not found_accessory_kw:
        return False  # No accessory keyword found
    
    # Check if title also contains a main product keyword
    has_main_product = any(kw in title_lower for kw in MAIN_PRODUCT_KEYWORDS)
    
    # RULE 3: Accessory keyword but NO main product → definitely accessory
    if not has_main_product:
        return True
    
    # RULE 4: Both present → check which comes first
    # "Armband für Garmin Fenix" → accessory (Armband at position 0)
    # "Garmin Fenix mit Armband" → bundle (Garmin at position 0)
    
    accessory_pos = title_lower.find(found_accessory_kw)
    
    main_product_pos = len(title_lower)  # Default to end
    for kw in MAIN_PRODUCT_KEYWORDS:
        pos = title_lower.find(kw)
        if pos != -1 and pos < main_product_pos:
            main_product_pos = pos
    
    # If accessory keyword comes first → it's about the accessory
    if accessory_pos < main_product_pos:
        return True
    
    # Main product comes first → likely a bundle "Garmin mit Armband"
    return False


# ==============================================================================
# DEFECT DETECTION
# ==============================================================================

DEFECT_KEYWORDS_STRONG = [
    "defekt", "defekter", "defekte", "defektes",
    "kaputt", "kaputter", "kaputte",
    "ersatzteil", "ersatzteile", "für ersatzteile",
    "ausschlachten", "zum ausschlachten",
    "bastler", "für bastler", "bastlerware",
    "wackelkontakt",
    "funktioniert nicht", "geht nicht",
    "startet nicht", "bootet nicht",
    "display defekt", "bildschirm defekt", "screen defekt",
    "wasserschaden", "water damage",
    "sturzschaden",
    "motherboard defekt", "mainboard defekt",
    "totalschaden",
    "not working", "doesn't work", "broken",
    "for parts", "für teile",
]

DEFECT_KEYWORDS_WEAK = [
    "akku hält nicht", "akku schwach", "batterie schwach",
    "lädt nicht", "lädt langsam",
    "fehlt", "ohne zubehör", "ohne ladegerät", "ohne kabel",
    "nur abholung", "keine garantie", "ohne garantie",
    "ungetestet", "nicht getestet", "keine ahnung",
    "as is", "wie gesehen",
    "kleine kratzer", "gebrauchsspuren",
    "pixelfehler", "tote pixel",
    "riss", "sprung", "crack",
    "lautsprecher defekt", "mikrofon defekt",
    "kamera defekt", "blitz defekt",
    "touch reagiert nicht",
]


def detect_defect_keywords(title: str, description: str = "") -> Tuple[bool, str, str]:
    """
    Detects defect indicators in title and description.
    
    Returns: (is_defect, severity, reason)
    """
    text = f"{title or ''} {description or ''}".lower()
    
    for keyword in DEFECT_KEYWORDS_STRONG:
        if keyword in text:
            return (True, "DEFECT", f"Keyword: '{keyword}'")
    
    weak_matches = []
    for keyword in DEFECT_KEYWORDS_WEAK:
        if keyword in text:
            weak_matches.append(keyword)
    
    if weak_matches:
        if len(weak_matches) >= 2:
            return (True, "DEFECT", f"Multiple issues: {', '.join(weak_matches[:3])}")
        else:
            return (False, "UNCLEAR", f"Possible issue: {weak_matches[0]}")
    
    return (False, "OK", "No defect indicators found")


def is_defect_title(title: str, description: str = "") -> bool:
    """Simple check if listing is definitely defective."""
    is_defect, severity, _ = detect_defect_keywords(title, description)
    return is_defect and severity == "DEFECT"


# ==============================================================================
# COMBINED PRE-FILTER
# ==============================================================================

def should_skip_listing(
    title: str, 
    description: str = "", 
    query: str = "", 
    category: str = ""
) -> Tuple[bool, str]:
    """
    Combined pre-filter: checks for accessories AND defects.
    
    v7.2: Now query-aware and category-aware!
    
    Returns: (should_skip, reason)
    """
    # Check accessory first (with query/category awareness)
    if is_accessory_title(title, query=query, category=category):
        return (True, "accessory")
    
    # Then check defects
    is_defect, severity, reason = detect_defect_keywords(title, description)
    if is_defect:
        return (True, f"defect: {reason}")
    
    return (False, "")