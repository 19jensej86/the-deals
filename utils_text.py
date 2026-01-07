"""
Text Utilities for DealFinder - v5.0
====================================
- Whitespace normalization
- Variant extraction (storage, year, color, size)
- Accessory detection (no AI needed!)
- Defect detection (no AI needed!)
- PLZ extraction

v5.0: Added bundle keywords for pre-filtering
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
    """
    Extracts storage size in GB from title.
    Examples: "iPhone 12 mini 128GB" → 128
    """
    if not title:
        return None
    match = re.search(r'(\d+)\s*GB', title, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_year(title: str) -> Optional[int]:
    """
    Extracts year from title.
    Examples: "VW Golf 2015" → 2015
    """
    if not title:
        return None
    match = re.search(r'\b(19|20)\d{2}\b', title)
    if match:
        year = int(match.group(0))
        if 1990 <= year <= 2030:
            return year
    return None


def extract_size(title: str) -> Optional[str]:
    """
    Extracts size from title.
    Examples: "Grösse 42" → "42", "Size M" → "M"
    """
    if not title:
        return None
    
    # Numeric sizes
    match = re.search(r'(?:gr[öo]sse|size|gr\.?)\s*(\d+)', title, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Letter sizes
    match = re.search(r'\b(XXS|XS|S|M|L|XL|XXL|XXXL)\b', title, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None


def extract_weight_kg(title: str) -> Optional[float]:
    """
    v5.0: Extracts weight in kg from title.
    Examples: "Hantel 20kg" → 20, "10 kg Scheibe" → 10
    """
    if not title:
        return None
    
    # Match patterns like "20kg", "20 kg", "20KG"
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', title, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(',', '.'))
        except ValueError:
            pass
    return None


def extract_variant_attributes(title: str, critical_attributes: List[str]) -> Dict[str, any]:
    """
    Extracts variant attributes from title based on what's critical.
    """
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
    """
    Builds variant key from extracted attributes.
    
    Examples:
        "iPhone 12 Mini", {"storage_gb": 128} → "iPhone 12 Mini|128GB"
        "VW Golf", {"year": 2015} → "VW Golf|2015"
        "iPhone 12 Mini", {"storage_gb": None} → "iPhone 12 Mini"
    """
    if not base_product:
        return None
    
    if not variant_attrs:
        return base_product
    
    # Filter out None values
    present_attrs = {k: v for k, v in variant_attrs.items() if v is not None}
    
    if len(present_attrs) == 0:
        return base_product
    
    # Build key with present attributes
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
# ACCESSORY DETECTION
# ==============================================================================

ACCESSORY_KEYWORDS = [
    "panzerglas", "schutzglas", "displayschutz", "glas",
    "hülle", "case", "cover", "bumper", "etui", "tasche",
    "kabel", "ladekabel", "usb-c", "lightning",
    "ladegerät", "charger", "netzteil", "adapter", "ladestation",
    "halterung", "ständer", "halter", "dock",
    "folie", "schutzfolie", "schutzhülle", "skin",
    "armband", "band", "strap",
    "kopfhörer", "earbuds",  # Note: AirPods can be main product
    "ersatzakku", "powerbank",
    "stylus", "stift", "pen",
    "tastatur", "keyboard",
    "maus", "mouse",
]

MAIN_PRODUCT_KEYWORDS = [
    "iphone", "samsung", "galaxy", "pixel", "huawei", "xiaomi", "oneplus",
    "handy", "smartphone", "telefon", "mobile",
    "tablet", "ipad",
    "laptop", "notebook", "macbook", "thinkpad",
    "watch", "uhr", "smartwatch", "apple watch", "garmin",
    "auto", "car", "pkw", "fahrzeug",
    "bike", "fahrrad", "velo", "e-bike",
    "konsole", "playstation", "xbox", "nintendo", "switch",
    "kamera", "camera", "dslr", "spiegelreflex",
    "tv", "fernseher", "monitor", "bildschirm",
    "drucker", "printer",
]


def is_accessory_title(title: str) -> bool:
    """
    Detects if title is clearly an accessory (not the main product).
    """
    if not title:
        return False
    
    title_lower = title.lower()
    
    has_accessory = any(kw in title_lower for kw in ACCESSORY_KEYWORDS)
    if not has_accessory:
        return False
    
    has_main_product = any(kw in title_lower for kw in MAIN_PRODUCT_KEYWORDS)
    
    if has_accessory and not has_main_product:
        return True
    
    # Check if accessory keyword comes first
    first_words = " ".join(title_lower.split()[:3])
    if any(kw in first_words for kw in ACCESSORY_KEYWORDS):
        return True
    
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

def should_skip_listing(title: str, description: str = "") -> Tuple[bool, str]:
    """
    Combined pre-filter: checks for accessories AND defects.
    
    Returns: (should_skip, reason)
    """
    if is_accessory_title(title):
        return (True, "accessory")
    
    is_defect, severity, reason = detect_defect_keywords(title, description)
    if is_defect:
        return (True, f"defect: {reason}")
    
    return (False, "")
