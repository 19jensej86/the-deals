"""
Query Normalizer v8.0 - Markenagnostisches Normalisierungssystem

GRUNDPRINZIP:
1. User-Query definiert das HAUPTPRODUKT (Marke, Produkttyp, Zielgruppe)
2. Inserate sind noisy Repräsentationen dieses Hauptprodukts
3. Aufgabe: Ableiten, wie der Neupreis korrekt abgefragt werden muss

REGELN:
- Marke kommt vom User-Query, NICHT aus Code-Listen
- Preisirrelevante Attribute entfernen (Farbe, Zustand, Grösse)
- Produkttyp im Singular
- Bundles zerlegen
- Fitness ist Sonderfall (hardcoded erlaubt)
"""

import re
from typing import Dict, List, Any, Optional, Tuple


# ==============================================================================
# PRODUKTTYP-KATEGORIEN (markenagnostisch!)
# ==============================================================================

PRODUCT_TYPE_CATEGORIES = {
    "fitness": [
        "hantel", "scheibe", "gewicht", "langhantel", "kurzhantel",
        "kettlebell", "rack", "bank", "stange", "bumper", "plate",
        "hantelscheibe", "gewichtsscheibe", "olympia", "kraftstation",
    ],
    "electronics": [
        "smartphone", "handy", "tablet", "laptop", "notebook", "watch",
        "smartwatch", "kopfhörer", "headphones", "tv", "fernseher",
        "kamera", "camera", "konsole", "playstation", "xbox", "switch",
        "iphone", "ipad", "macbook", "airpods", "pixel", "galaxy",
    ],
    "clothing": [
        "jacke", "jacket", "parka", "mantel", "coat", "blazer", "weste",
        "pullover", "sweater", "hoodie", "sweatshirt", "cardigan",
        "hemd", "shirt", "bluse", "polo", "t-shirt", "top",
        "hose", "jeans", "pants", "shorts", "chino", "jogger",
        "kleid", "dress", "rock", "skirt",
        "tasche", "handtasche", "bag", "shopper", "rucksack", "backpack",
        "schuhe", "shoes", "sneaker", "stiefel", "boots", "sandalen",
        "gürtel", "belt", "schal", "scarf", "mütze", "cap", "hat",
    ],
}

TARGET_GROUPS = ["herren", "damen", "kinder", "boys", "girls", "men", "women", "unisex"]


# ==============================================================================
# PREISIRRELEVANTE ATTRIBUTE
# ==============================================================================

COLORS = [
    "schwarz", "weiss", "blau", "rot", "grün", "gelb", "grau",
    "braun", "pink", "lila", "orange", "beige", "navy", "bordeaux",
    "black", "white", "blue", "red", "green", "grey", "brown",
    "anthrazit", "türkis", "gold", "silber", "rose", "mint",
]

CONDITIONS = [
    "neu", "neuwertig", "wie neu", "top", "super", "gut", "sehr gut",
    "gebraucht", "defekt", "beschädigt", "original", "ovp", "unbenutzt",
    "new", "used", "mint", "excellent", "good", "ungetragen",
    "einwandfrei", "perfekt", "makellos", "kaum getragen",
]

SIZE_PATTERNS = [
    r'\b(xxs|xs|s|m|l|xl|xxl|xxxl)\b',
    r'\b\d{2}/\d{2}\b',           # 32/32 für Jeans
    r'\bgr\.?\s*\d+\b',           # Gr. 42
    r'\bgrösse\s*\d+\b',
    r'\bsize\s*\d+\b',
    r'\b\d{2,3}\s*(cm)?\b',       # 176 cm
]


# ==============================================================================
# PLURAL → SINGULAR REGELN
# ==============================================================================

PLURAL_TO_SINGULAR = [
    (r'scheiben\b', 'scheibe'),
    (r'hanteln\b', 'hantel'),
    (r'jacken\b', 'jacke'),
    (r'hosen\b', 'hose'),
    (r'taschen\b', 'tasche'),
    (r'schuhen\b', 'schuh'),
    (r'hemden\b', 'hemd'),
    (r'kleider\b', 'kleid'),
    (r'mäntel\b', 'mantel'),
    (r'pullover\b', 'pullover'),  # bleibt gleich
    (r'jeans\b', 'jeans'),        # bleibt gleich
    (r'plates\b', 'plate'),
    (r'shoes\b', 'shoe'),
    (r'bags\b', 'bag'),
]


# ==============================================================================
# BUNDLE-INDIKATOREN
# ==============================================================================

BUNDLE_INDICATORS = [
    "inkl", "inklusive", "mit", "plus", "+", "und", "&", "samt",
    "set", "bundle", "paket", "komplett", "zusammen", "konvolut",
]


# ==============================================================================
# MODUL 1: QUERY ANALYZER
# ==============================================================================

def analyze_user_query(query: str) -> Dict[str, Any]:
    """
    Analysiert den User-Query und extrahiert Kernattribute.
    
    KEINE Markenlisten! Marke = Wörter VOR dem Produkttyp.
    
    Args:
        query: User-Suchbegriff (z.B. "Tommy Hilfiger Pullover")
    
    Returns:
        {
            "brand": Optional[str],       # z.B. "Tommy Hilfiger"
            "product_type": str,          # z.B. "pullover"
            "target_group": Optional[str], # "Herren" / "Damen" / "Kinder"
            "category": str,              # "fitness" / "electronics" / "clothing" / "general"
            "raw_query": str,
        }
    
    Beispiele:
        "Tommy Hilfiger Pullover" → brand="Tommy Hilfiger", product_type="pullover", category="clothing"
        "Hantelscheiben 50mm"     → brand=None, product_type="hantelscheibe", category="fitness"
        "Nike Sneaker Herren"     → brand="Nike", product_type="sneaker", target_group="Herren"
    """
    if not query:
        return {
            "brand": None,
            "product_type": "",
            "target_group": None,
            "category": "general",
            "raw_query": "",
        }
    
    query_lower = query.lower().strip()
    words = query_lower.split()
    
    # 1. Finde Produkttyp und Kategorie
    product_type = None
    product_type_pos = len(words)
    category = "general"
    
    for cat, types in PRODUCT_TYPE_CATEGORIES.items():
        for pt in types:
            if pt in query_lower:
                # Finde Wort-Position
                try:
                    pos = query_lower.find(pt)
                    word_pos = len(query_lower[:pos].split())
                except:
                    word_pos = len(words)
                
                if word_pos < product_type_pos:
                    product_type = pt
                    product_type_pos = word_pos
                    category = cat
    
    # 2. Alles VOR Produkttyp = potentielle Marke
    brand = None
    if product_type_pos > 0:
        brand_words = words[:product_type_pos]
        # Filtere Target Groups aus Brand
        brand_words = [w for w in brand_words if w.lower() not in TARGET_GROUPS]
        if brand_words:
            brand = " ".join(brand_words).title()
    
    # 3. Finde Target Group
    target_group = None
    for tg in TARGET_GROUPS:
        if tg in query_lower:
            target_group = tg.title()
            break
    
    # 4. Falls kein Produkttyp gefunden, Query = Produkttyp
    if not product_type:
        # Entferne Target Group, Rest = Produkttyp
        remaining = [w for w in words if w.lower() not in TARGET_GROUPS]
        product_type = " ".join(remaining) if remaining else query
    
    # 5. Normalisiere Produkttyp zu Singular
    product_type = normalize_to_singular(product_type)
    
    return {
        "brand": brand,
        "product_type": product_type,
        "target_group": target_group,
        "category": category,
        "raw_query": query,
    }


# ==============================================================================
# MODUL 2: ATTRIBUTE EXTRACTOR
# ==============================================================================

def extract_listing_attributes(
    title: str,
    query_analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extrahiert und klassifiziert Attribute aus Inserat-Titel.
    Entfernt preisirrelevante Attribute (Farbe, Zustand, Grösse).
    
    Args:
        title: Inserat-Titel
        query_analysis: Output von analyze_user_query()
    
    Returns:
        {
            "cleaned_title": str,      # Titel ohne irrelevante Attribute
            "quantity": int,           # Erkannte Menge (default 1)
            "specs": Dict,             # Category-spezifische Specs (Fitness)
            "removed": List[str],      # Was entfernt wurde
            "product_type": str,       # Extrahierter Produkttyp
        }
    """
    if not title:
        return {
            "cleaned_title": "",
            "quantity": 1,
            "specs": {},
            "removed": [],
            "product_type": "",
        }
    
    cleaned = title
    removed = []
    category = query_analysis.get("category", "general")
    
    # 1. Entferne Farben
    for color in COLORS:
        pattern = rf'\b{re.escape(color)}\b'
        if re.search(pattern, cleaned, re.IGNORECASE):
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            removed.append(f"color:{color}")
    
    # 2. Entferne Zustandsbeschreibungen
    for cond in CONDITIONS:
        pattern = rf'\b{re.escape(cond)}\b'
        if re.search(pattern, cleaned, re.IGNORECASE):
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            removed.append(f"condition:{cond}")
    
    # 3. Entferne Grössen
    for size_pattern in SIZE_PATTERNS:
        matches = re.findall(size_pattern, cleaned, re.IGNORECASE)
        if matches:
            cleaned = re.sub(size_pattern, '', cleaned, flags=re.IGNORECASE)
            removed.append(f"size:{matches}")
    
    # 4. Extrahiere Quantity
    quantity = 1
    qty_patterns = [
        (r'(\d+)\s*(?:stk\.?|stück|x)\b', 1),
        (r'(\d+)\s*×', 1),
        (r'\bpaar\b', 2),
        (r'\bset\s+(?:von\s+)?(\d+)', 1),
    ]
    for pattern, group_idx in qty_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            if isinstance(group_idx, int) and group_idx > 0:
                try:
                    quantity = int(match.group(group_idx))
                except:
                    quantity = 2 if 'paar' in pattern else 1
            else:
                quantity = group_idx
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            break
    
    # 5. Extrahiere category-spezifische Specs (nur Fitness!)
    specs = {}
    if category == "fitness":
        # Gewicht
        weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', cleaned, re.IGNORECASE)
        if weight_match:
            specs["weight_kg"] = float(weight_match.group(1).replace(',', '.'))
        
        # Durchmesser
        diameter_match = re.search(r'(\d+)\s*mm', cleaned, re.IGNORECASE)
        if diameter_match:
            specs["diameter_mm"] = int(diameter_match.group(1))
        
        # Material
        if re.search(r'gusseisen|cast\s*iron', cleaned, re.IGNORECASE):
            specs["material"] = "gusseisen"
        elif re.search(r'gummi|rubber|bumper', cleaned, re.IGNORECASE):
            specs["material"] = "gummi"
    
    # 6. Cleanup
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', cleaned)
    cleaned = re.sub(r'\s*[,\-]\s*$', '', cleaned)
    
    # 7. Extrahiere Produkttyp aus gereinigtem Titel
    product_type = extract_product_type(cleaned, query_analysis)
    
    return {
        "cleaned_title": cleaned,
        "quantity": quantity,
        "specs": specs,
        "removed": removed,
        "product_type": product_type,
    }


def extract_product_type(title: str, query_analysis: Dict[str, Any]) -> str:
    """Extrahiert den Produkttyp aus einem Titel."""
    title_lower = title.lower()
    category = query_analysis.get("category", "general")
    
    # Suche nach bekannten Produkttypen
    if category in PRODUCT_TYPE_CATEGORIES:
        for pt in PRODUCT_TYPE_CATEGORIES[category]:
            if pt in title_lower:
                return normalize_to_singular(pt)
    
    # Fallback: Verwende Query-Produkttyp
    return query_analysis.get("product_type", "")


# ==============================================================================
# MODUL 3: BUNDLE DETECTOR
# ==============================================================================

def detect_bundle(
    title: str,
    description: str = "",
    query_analysis: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Erkennt ob Inserat ein Bundle ist.
    
    Returns:
        {
            "is_bundle": bool,
            "components": List[Dict],  # Wenn erkannt
            "needs_vision": bool,      # Wenn unklar
            "confidence": float,
        }
    """
    title_lower = title.lower()
    desc_lower = (description or "").lower()
    combined = f"{title_lower} {desc_lower}"
    
    # Check für Bundle-Indikatoren
    has_indicator = any(ind in combined for ind in BUNDLE_INDICATORS)
    
    # Check für multiple Mengenangaben
    quantities = re.findall(r'\d+\s*(?:stk|x|×)', combined)
    has_multiple_qty = len(quantities) > 1
    
    # Check für Aufzählungen
    has_list = bool(re.search(r'(?:\d+\.\s|\-\s|•|\n\s*\-)', combined))
    
    is_bundle = has_indicator or has_multiple_qty or has_list
    needs_vision = is_bundle and not has_list  # Wenn Bundle aber keine klare Liste
    
    components = []
    if is_bundle and has_list:
        # Versuche Komponenten zu extrahieren
        lines = re.split(r'[\n•]|\s*\-\s*', combined)
        for line in lines:
            line = line.strip()
            if len(line) > 3 and not line.startswith(('http', 'www')):
                components.append({
                    "raw": line,
                    "quantity": 1,
                    "parsed": False,
                })
    
    return {
        "is_bundle": is_bundle,
        "components": components,
        "needs_vision": needs_vision,
        "confidence": 0.9 if has_list else 0.6 if has_indicator else 0.3,
    }


# ==============================================================================
# MODUL 4: WEBSEARCH QUERY BUILDER
# ==============================================================================

def build_websearch_query(
    query_analysis: Dict[str, Any],
    listing_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Baut Websearch-Query(s) aus Query-Analyse und Listing-Daten.
    
    REGEL: Marke kommt aus User-Query, NICHT aus Inserat!
    
    Args:
        query_analysis: Output von analyze_user_query()
        listing_data: Output von extract_listing_attributes()
    
    Returns:
        Liste von Search-Queries mit Quantity:
        [
            {"query": "Tommy Hilfiger Pullover", "quantity": 1},
            {"query": "Hantelscheibe 10kg 50mm", "quantity": 2},
        ]
    """
    queries = []
    
    # Basis-Infos aus User-Query
    brand = query_analysis.get("brand", "")
    target_group = query_analysis.get("target_group", "")
    category = query_analysis.get("category", "general")
    
    # Produkttyp aus Listing (oder Fallback auf Query)
    product_type = listing_data.get("product_type") or query_analysis.get("product_type", "")
    product_type = normalize_to_singular(product_type)
    
    # Query zusammenbauen
    parts = []
    
    # 1. Marke (aus User-Query!)
    if brand:
        parts.append(brand)
    
    # 2. Produkttyp
    if product_type:
        parts.append(product_type)
    
    # 3. Target Group (nur bei Clothing, da preisrelevant)
    if target_group and category == "clothing":
        parts.append(target_group)
    
    # 4. Fitness-Specs (Gewicht, Durchmesser)
    if category == "fitness":
        specs = listing_data.get("specs", {})
        if specs.get("weight_kg"):
            parts.append(f"{specs['weight_kg']}kg")
        if specs.get("diameter_mm"):
            parts.append(f"{specs['diameter_mm']}mm")
        if specs.get("material"):
            parts.append(specs["material"])
    
    query = " ".join(parts)
    quantity = listing_data.get("quantity", 1)
    
    queries.append({
        "query": query,
        "quantity": quantity,
    })
    
    return queries


# ==============================================================================
# HILFSFUNKTIONEN
# ==============================================================================

def normalize_to_singular(text: str) -> str:
    """Konvertiert Plural zu Singular."""
    if not text:
        return text
    
    text_lower = text.lower()
    
    for pattern, replacement in PLURAL_TO_SINGULAR:
        if re.search(pattern, text_lower):
            return re.sub(pattern, replacement, text_lower)
    
    return text_lower


def build_clean_websearch_query(
    user_query: str,
    listing_title: str,
    listing_description: str = "",
) -> Dict[str, Any]:
    """
    Hauptfunktion: Baut saubere Websearch-Query aus User-Query und Listing.
    
    Args:
        user_query: Was der User gesucht hat
        listing_title: Titel des Inserats
        listing_description: Beschreibung des Inserats
    
    Returns:
        {
            "queries": List[{"query": str, "quantity": int}],
            "is_bundle": bool,
            "needs_vision": bool,
            "query_analysis": Dict,
            "listing_data": Dict,
        }
    
    Beispiel:
        user_query: "Tommy Hilfiger"
        listing_title: "Tommy Hilfiger Pullover neuwertig grün Gr. S"
        
        → queries: [{"query": "Tommy Hilfiger Pullover", "quantity": 1}]
    """
    # 1. Analysiere User-Query
    query_analysis = analyze_user_query(user_query)
    
    # 2. Extrahiere Listing-Attribute
    listing_data = extract_listing_attributes(listing_title, query_analysis)
    
    # 3. Check für Bundle
    bundle_info = detect_bundle(listing_title, listing_description, query_analysis)
    
    # 4. Baue Websearch-Query(s)
    if bundle_info["is_bundle"] and bundle_info["components"]:
        # Pro Komponente eine Query
        queries = []
        for comp in bundle_info["components"]:
            comp_data = extract_listing_attributes(comp["raw"], query_analysis)
            comp_queries = build_websearch_query(query_analysis, comp_data)
            queries.extend(comp_queries)
    else:
        queries = build_websearch_query(query_analysis, listing_data)
    
    return {
        "queries": queries,
        "is_bundle": bundle_info["is_bundle"],
        "needs_vision": bundle_info["needs_vision"],
        "query_analysis": query_analysis,
        "listing_data": listing_data,
    }


# ==============================================================================
# TEST / DEMO
# ==============================================================================

if __name__ == "__main__":
    # Beispiel 1: Kleidung
    result = build_clean_websearch_query(
        user_query="Tommy Hilfiger",
        listing_title="Top Tommy Hilfiger Winterjacke Herren XL guter Zustand grün",
    )
    print("=== Kleidung ===")
    print(f"Query: {result['queries']}")
    print(f"Analysis: {result['query_analysis']}")
    print()
    
    # Beispiel 2: Fitness
    result = build_clean_websearch_query(
        user_query="Hantelscheiben 50mm",
        listing_title="Hantelscheiben Set 4x 10kg Gusseisen 50mm",
    )
    print("=== Fitness ===")
    print(f"Query: {result['queries']}")
    print(f"Specs: {result['listing_data'].get('specs')}")
    print()
    
    # Beispiel 3: Elektronik
    result = build_clean_websearch_query(
        user_query="Garmin Fenix 7",
        listing_title="Garmin Fenix 7 Sapphire Solar neuwertig mit OVP",
    )
    print("=== Elektronik ===")
    print(f"Query: {result['queries']}")
    print(f"Removed: {result['listing_data'].get('removed')}")
