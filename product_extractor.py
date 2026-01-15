"""
Product Extractor v9.0 - Kernmodul für strukturierte Produktextraktion

STEPS:
- Step 2: AI Title Cleanup (nur preisrelevantes behalten)
- Step 3: Deduplication nach Normalisierung
- Step 7: Fitness Bundle Decomposition
- Step 8: Global Product List Builder

WICHTIG:
- Modellunterschiede behalten (7 ≠ 7s ≠ 7 Sapphire)
- Fitness darf hardcoded sein
- Keine Markenlisten (ausser Fitness)
"""

import re
import json
import hashlib
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ==============================================================================
# DATENSTRUKTUREN
# ==============================================================================

@dataclass
class Product:
    """Normalisiertes Produkt für Websearch"""
    product_key: str           # Unique identifier (hash of display_name)
    display_name: str          # Für Websearch
    category: str              # smartwatch, clothing, fitness
    quantity: int = 1          # Default 1, bei Bundles > 1
    specs: Dict[str, Any] = field(default_factory=dict)
    source_listings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ListingProducts:
    """Mapping: Inserat → Produkte"""
    listing_id: str
    original_title: str
    products: List[Product]    # Ein Inserat kann mehrere Produkte haben (Bundle)
    is_bundle: bool = False


# ==============================================================================
# KATEGORIEN UND REGELN
# ==============================================================================

# Preisrelevante Features die behalten werden müssen
PRICE_RELEVANT_FEATURES = {
    "smartwatch": ["solar", "sapphire", "pro", "plus", "ultra", "titanium"],
    "clothing": ["herren", "damen", "kinder", "winter", "sommer", "daune"],
    "fitness": [],  # Wird separat behandelt
}

# Preisirrelevante Attribute die entfernt werden
# WICHTIG: Reihenfolge matters! Grössere Patterns zuerst.
REMOVE_PATTERNS = [
    # Zustand (ganze Phrasen zuerst!)
    r'\b(top|super|sehr guter?|guter?)\s+zustand\b',  # "Top Zustand" komplett
    r'\bwie neu\b',
    r'\b(neu|neuwertig|gebraucht|defekt)\b',
    r'\b(original|ovp|unbenutzt|ungetragen|einwandfrei|perfekt|makellos)\b',
    r'\b(recertified|refurbished|b-ware)\b',
    # Farben - EXPLIZIT zusammengesetzte Farben ZUERST!
    r'\b(dunkelblau|hellblau|dunkelgrau|hellgrau|dunkelbraun|hellbraun|dunkelgrün|hellgrün|dunkelrot|hellrot)\b',
    r'\b(schwarz|weiss|blau|rot|grün|gelb|grau|braun|pink|lila|orange|violett|türkis)\b',
    r'\b(beige|navy|bordeaux|olive|anthrazit|gold|silber|rose|mint|creme|ivory|taupe|khaki)\b',
    r'\b(black|white|blue|red|green|grey|gray|brown|pink|purple|orange|cream|midnight)\b',
    # Grössen - WICHTIG: Pipe + Grösse Pattern muss funktionieren!
    r'\|\s*Grösse\s*[A-Z0-9]*',                  # "| Grösse M" oder "| Grösse" (case sensitive für Anfang)
    r'\|\s*grösse\s*\w*',                        # "| grösse" lowercase
    r',?\s*[Gg]r\.?\s*(xxs|xs|s|m|l|xl|xxl|xxxl|\d+)\b',  # ", Gr. M" oder "Gr.42"
    r'\bsize\s*(xxs|xs|s|m|l|xl|xxl|xxxl|\d+)\b',
    r'\b(xxs|xs|xl|xxl|xxxl)\b',                 # Nur eindeutige Grössen (S/M/L zu häufig in Namen)
    r'\b\d{2}/\d{2}\b',                          # 32/32
    r'\b\(\d{2,3}\)\b',                          # (116)
    # Mengenangaben für Singular-Suche - MUSS Gewicht behalten!
    r',?\s*\d+\s*[Ss]tk\.?\s*[àax@]\s*',        # ", 2 Stk. à" -> entfernen (Komma optional)
    # Marketing
    r'\bthflex\b',
    r'\binkl\.?\s*(ovp|box|zubehör)\b',
    r'\bmit\s+(ovp|box)\b',
]

# Fitness-spezifische Produkttypen
FITNESS_PRODUCT_TYPES = [
    "hantelscheibe", "hantelscheiben", "gewichtsscheibe",
    "langhantel", "kurzhantel", "hantel",
    "kettlebell", "bumper plate", "bumper plates",
    "hantelbank", "langhantelbank", "schrägbank",
    "hantelständer", "rack", "power rack",
    "olympiastange", "langhantelstange", "sz-stange",
]


# ==============================================================================
# STEP 2: AI TITLE CLEANUP
# ==============================================================================

def clean_title_for_search(
    title: str,
    query: str,
    category: str,
) -> str:
    """
    Bereinigt Inseratstitel für Websearch.
    
    REGELN:
    ✅ Modellunterschiede behalten (7 ≠ 7s ≠ 7 Sapphire)
    ✅ Preisrelevante Features behalten (Solar, Pro, etc.)
    ✅ Geschlecht bei Kleidung behalten
    ❌ Farbe, Zustand, Grösse entfernen
    
    Args:
        title: Original-Titel vom Inserat
        query: User-Query (für Marke)
        category: Produktkategorie
    
    Returns:
        Bereinigter Titel für Websearch
    """
    if not title:
        return ""
    
    cleaned = title.strip()
    
    # 1. Entferne preisirrelevante Attribute
    for pattern in REMOVE_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # 2. Post-cleanup Normalisierung (WICHTIG: nach Pattern-Entfernung!)
    # Entferne orphaned punctuation und Whitespace-Artefakte
    cleaned = re.sub(r'\s+', ' ', cleaned)                    # Mehrfach-Spaces
    cleaned = re.sub(r'\s*[–—-]\s*$', '', cleaned)            # Trailing dashes (inkl. em/en dash)
    cleaned = re.sub(r'^\s*[–—-]\s*', '', cleaned)            # Leading dashes
    cleaned = re.sub(r'\s*[–—-]\s*[–—-]\s*', ' ', cleaned)    # Double dashes
    cleaned = re.sub(r'\s+[–—-]\s*$', '', cleaned)            # " - " am Ende
    cleaned = re.sub(r',\s*,', ',', cleaned)                  # Doppel-Kommas
    cleaned = re.sub(r'\s*,\s*$', '', cleaned)                # Trailing comma
    cleaned = re.sub(r'^\s*,\s*', '', cleaned)                # Leading comma
    cleaned = re.sub(r'\(\s*\)', '', cleaned)                 # Leere Klammern
    cleaned = re.sub(r'\|\s*$', '', cleaned)                  # Trailing pipe
    cleaned = re.sub(r'^\s*\|', '', cleaned)                  # Leading pipe
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()            # Final cleanup
    
    # 2b. Plural → Singular für bessere Web-Suche
    cleaned = re.sub(r'\bhantelscheiben\b', 'Hantelscheibe', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bgewichtsscheiben\b', 'Gewichtsscheibe', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bkurzhanteln\b', 'Kurzhantel', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bgewichte\b', 'Gewicht', cleaned, flags=re.IGNORECASE)
    
    # 3. Stelle sicher dass Marke vom Query erhalten bleibt
    brand = extract_brand_from_query(query)
    if brand and brand.lower() not in cleaned.lower():
        cleaned = f"{brand} {cleaned}"
    
    # 4. Normalisiere Marke (lowercase → proper case)
    cleaned = normalize_brand_case(cleaned, brand)
    
    # 5. Extrahiere Geschlecht falls in Titel aber nicht im cleaned
    gender = extract_gender(title)
    if gender and category == "clothing" and gender.lower() not in cleaned.lower():
        cleaned = f"{cleaned} {gender}"
    
    return cleaned.strip()


def extract_brand_from_query(query: str) -> Optional[str]:
    """
    Extrahiert Marke aus User-Query.
    
    Marke = alles VOR dem ersten Produkttyp-Wort.
    """
    if not query:
        return None
    
    query_lower = query.lower()
    
    # Bekannte Produkttyp-Wörter
    product_type_words = [
        "smartwatch", "watch", "uhr",
        "jacke", "jacket", "pullover", "sweater", "hemd", "shirt",
        "hose", "jeans", "kleid", "rock", "tasche", "schuhe",
        "hantelscheiben", "hantel", "scheibe", "gewicht",
    ]
    
    # Finde erstes Produkttyp-Wort
    first_product_pos = len(query)
    for pt in product_type_words:
        pos = query_lower.find(pt)
        if pos != -1 and pos < first_product_pos:
            first_product_pos = pos
    
    if first_product_pos > 0:
        brand = query[:first_product_pos].strip()
        return brand.title() if brand else None
    
    # Kein Produkttyp gefunden - Query könnte nur Marke sein
    # z.B. "Tommy Hilfiger" ohne Produkttyp
    return query.title()


def extract_gender(title: str) -> Optional[str]:
    """
    Extrahiert Geschlecht aus Titel.
    
    WICHTIG: Damen vor Herren prüfen, weil "men" in "Damen" vorkommt!
    Verwendet Word-Boundaries für präzise Matches.
    """
    title_lower = title.lower()
    
    # Damen/Frauen ZUERST prüfen (weil "men" in "damen" vorkommt!)
    if re.search(r'\b(damen|women|frauen|femme)\b', title_lower):
        return "Damen"
    # "dame" ohne boundary weil "damenjacke" etc.
    if "dame" in title_lower:
        return "Damen"
    
    # Herren/Männer
    if re.search(r'\b(herren|männer|homme)\b', title_lower):
        return "Herren"
    # "men" nur als ganzes Wort (nicht in "damen", "women" etc.)
    if re.search(r'\bmen\b', title_lower):
        return "Herren"
    
    # Kinder
    if re.search(r'\b(kinder|kids|jungen|mädchen|boys|girls|jungs)\b', title_lower):
        return "Kinder"
    
    return None


def normalize_brand_case(text: str, brand: Optional[str]) -> str:
    """Normalisiert Marken-Schreibweise."""
    if not brand:
        return text
    
    # Ersetze verschiedene Schreibweisen durch korrekte
    brand_lower = brand.lower()
    
    # Pattern: beliebige Schreibweise → korrekte
    pattern = rf'\b{re.escape(brand_lower)}\b'
    result = re.sub(pattern, brand.title(), text, flags=re.IGNORECASE)
    
    return result


# ==============================================================================
# STEP 3: DEDUPLICATION
# ==============================================================================

def deduplicate_products(products: List[Product]) -> List[Product]:
    """
    Entfernt Duplikate basierend auf product_key.
    Merged source_listings, aber NICHT quantity!
    
    WICHTIG: Quantity wird NICHT addiert, weil:
    - Jedes Listing behält seine eigene Quantity
    - Dedup ist nur für Web Search (unique Produkte finden)
    - Quantity-Addition würde Original-Objekte in-place modifizieren!
    """
    unique: Dict[str, Product] = {}
    
    for product in products:
        key = product.product_key
        
        if key in unique:
            # Merge: Nur Listings zusammenführen, NICHT quantity!
            existing = unique[key]
            for listing_id in product.source_listings:
                if listing_id not in existing.source_listings:
                    existing.source_listings.append(listing_id)
            # REMOVED: quantity addition - this was a bug!
            # Each listing keeps its own quantity
        else:
            unique[key] = product
    
    return list(unique.values())


def generate_product_key(display_name: str) -> str:
    """Generiert unique key für ein Produkt."""
    normalized = display_name.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


# ==============================================================================
# STEP 7: FITNESS BUNDLE DECOMPOSITION
# ==============================================================================

def decompose_fitness_bundle(
    title: str,
    description: str = "",
    listing_id: str = "",
) -> List[Product]:
    """
    Fitness-Sonderbehandlung: Bundles in Einzelprodukte aufteilen.
    
    HARDCODED REGELN (erlaubt für Fitness!):
    1. Bundles IMMER in Einzelprodukte
    2. Produkte IMMER im Singular
    3. Menge separat erfassen
    4. Gewicht/Durchmesser behalten
    """
    products = []
    combined = f"{title} {description}".lower()
    
    # =========================================================================
    # Pattern 1: Hantelscheiben mit Menge und Gewicht
    # "2 Stk. à 10kg", "4×5kg", "2x 2.5kg", "Zwei 5kg"
    # =========================================================================
    
    # Numerische Mengen
    qty_patterns = [
        r'(\d+)\s*(?:stk\.?|stück|×|x)\s*(?:à|a)?\s*(\d+(?:[.,]\d+)?)\s*kg',
        r'(\d+)\s*(?:×|x)\s*(\d+(?:[.,]\d+)?)\s*kg',
        r'(\d+)\s*hantelscheiben?\s*(?:à|a)?\s*(\d+(?:[.,]\d+)?)\s*kg',
    ]
    
    for pattern in qty_patterns:
        matches = re.findall(pattern, combined)
        for qty, weight in matches:
            weight_float = float(weight.replace(',', '.'))
            product = Product(
                product_key=f"hantelscheibe_{weight_float}kg",
                display_name=f"Hantelscheibe {weight_float}kg",
                category="fitness",
                quantity=int(qty),
                specs={"weight_kg": weight_float},
                source_listings=[listing_id] if listing_id else [],
            )
            products.append(product)
    
    # Wort-Mengen (Zwei, Drei, Vier)
    word_qty_map = {"zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6}
    for word, qty in word_qty_map.items():
        pattern = rf'{word}\s*(?:\d+\s*mm\s*)?hantelscheiben?\s*(\d+(?:[.,]\d+)?)\s*kg'
        matches = re.findall(pattern, combined)
        for weight in matches:
            weight_float = float(weight.replace(',', '.'))
            product = Product(
                product_key=f"hantelscheibe_{weight_float}kg",
                display_name=f"Hantelscheibe {weight_float}kg",
                category="fitness",
                quantity=qty,
                specs={"weight_kg": weight_float},
                source_listings=[listing_id] if listing_id else [],
            )
            products.append(product)
    
    # =========================================================================
    # Pattern 2: Einzelne Hantelscheiben ohne explizite Menge
    # "Hantelscheiben 10kg" → ×1
    # =========================================================================
    if not products:  # Nur wenn noch keine gefunden
        single_pattern = r'hantelscheiben?\s*(\d+(?:[.,]\d+)?)\s*kg'
        matches = re.findall(single_pattern, combined)
        for weight in matches:
            weight_float = float(weight.replace(',', '.'))
            product = Product(
                product_key=f"hantelscheibe_{weight_float}kg",
                display_name=f"Hantelscheibe {weight_float}kg",
                category="fitness",
                quantity=1,
                specs={"weight_kg": weight_float},
                source_listings=[listing_id] if listing_id else [],
            )
            products.append(product)
    
    # =========================================================================
    # Pattern 3: Bumper Plates
    # "100kg Bumper Plates" → aufteilen in realistische Konfiguration
    # =========================================================================
    if "bumper" in combined:
        # Suche nach Gesamtgewicht
        total_match = re.search(r'(\d+)\s*kg\s*bumper', combined)
        if total_match:
            total_kg = int(total_match.group(1))
            products.extend(_decompose_bumper_set(total_kg, listing_id))
        else:
            # Einzelne Bumper Plates mit Gewicht
            bumper_pattern = r'bumper\s*plates?\s*(\d+(?:[.,]\d+)?)\s*kg'
            matches = re.findall(bumper_pattern, combined)
            for weight in matches:
                weight_float = float(weight.replace(',', '.'))
                product = Product(
                    product_key=f"bumper_plate_{weight_float}kg",
                    display_name=f"Bumper Plate {weight_float}kg",
                    category="fitness",
                    quantity=2,  # Default: Paar
                    specs={"weight_kg": weight_float},
                    source_listings=[listing_id] if listing_id else [],
                )
                products.append(product)
    
    # =========================================================================
    # Pattern 4: Andere Fitness-Geräte
    # =========================================================================
    
    if "langhantelbank" in combined or "hantelbank" in combined:
        brand = _extract_fitness_brand(combined)
        name = f"{brand} Langhantelbank" if brand else "Langhantelbank"
        products.append(Product(
            product_key="langhantelbank",
            display_name=name,
            category="fitness",
            quantity=1,
            source_listings=[listing_id] if listing_id else [],
        ))
    
    if "kurzhantel" in combined and "scheibe" not in combined:
        products.append(Product(
            product_key="kurzhantel",
            display_name="Kurzhantel",
            category="fitness",
            quantity=2 if "paar" in combined or "set" in combined else 1,
            source_listings=[listing_id] if listing_id else [],
        ))
    
    if "olympiastange" in combined or "langhantelstange" in combined:
        products.append(Product(
            product_key="olympiastange",
            display_name="Olympiastange",
            category="fitness",
            quantity=1,
            source_listings=[listing_id] if listing_id else [],
        ))
    
    if "kettlebell" in combined:
        # Versuche Gewicht zu extrahieren
        kb_weight = re.search(r'kettlebell\s*(\d+)\s*kg', combined)
        if kb_weight:
            weight = int(kb_weight.group(1))
            products.append(Product(
                product_key=f"kettlebell_{weight}kg",
                display_name=f"Kettlebell {weight}kg",
                category="fitness",
                quantity=1,
                specs={"weight_kg": weight},
                source_listings=[listing_id] if listing_id else [],
            ))
        else:
            products.append(Product(
                product_key="kettlebell",
                display_name="Kettlebell",
                category="fitness",
                quantity=1,
                source_listings=[listing_id] if listing_id else [],
            ))
    
    if "hantelständer" in combined or "rack" in combined:
        products.append(Product(
            product_key="hantelstaender",
            display_name="Hantelständer",
            category="fitness",
            quantity=1,
            source_listings=[listing_id] if listing_id else [],
        ))
    
    return deduplicate_products(products)


def _decompose_bumper_set(total_kg: int, listing_id: str) -> List[Product]:
    """
    Zerlegt ein Bumper Plate Set in realistische Einzelscheiben.
    
    Typische Konfigurationen:
    - 100kg = 2×20 + 2×15 + 2×10 + 2×5
    - 50kg = 2×10 + 2×10 + 2×5
    """
    products = []
    
    if total_kg >= 100:
        # Standard 100kg Set
        config = [(20, 2), (15, 2), (10, 2), (5, 2)]
    elif total_kg >= 50:
        config = [(15, 2), (10, 2), (5, 2)]
    elif total_kg >= 25:
        config = [(10, 2), (2.5, 2)]
    else:
        config = [(5, 2)]
    
    for weight, qty in config:
        products.append(Product(
            product_key=f"bumper_plate_{weight}kg",
            display_name=f"Bumper Plate {weight}kg",
            category="fitness",
            quantity=qty,
            specs={"weight_kg": weight},
            source_listings=[listing_id] if listing_id else [],
        ))
    
    return products


def _extract_fitness_brand(text: str) -> Optional[str]:
    """Extrahiert Fitness-Marke aus Text."""
    fitness_brands = [
        "gorilla sports", "capital sports", "hop-sport",
        "kettler", "hammer", "technogym", "rogue", "eleiko",
    ]
    
    text_lower = text.lower()
    for brand in fitness_brands:
        if brand in text_lower:
            return brand.title()
    
    return None


# ==============================================================================
# STEP 8: GLOBAL PRODUCT LIST BUILDER
# ==============================================================================

def build_global_product_list(
    all_listings_products: List[ListingProducts],
) -> Dict[str, Product]:
    """
    Baut globale, deduplizierte Produktliste aus allen Queries.
    
    Args:
        all_listings_products: Liste von ListingProducts aus allen Queries
    
    Returns:
        Dict[product_key, Product] - Unique products für Websearch
    """
    all_products: List[Product] = []
    
    for listing_data in all_listings_products:
        all_products.extend(listing_data.products)
    
    # Dedupliziere
    unique_products = deduplicate_products(all_products)
    
    # Als Dict zurückgeben
    return {p.product_key: p for p in unique_products}


# ==============================================================================
# UNIVERSAL BUNDLE DETECTION (alle Kategorien!)
# ==============================================================================

BUNDLE_INDICATORS = [
    "inkl", "inklusive", "mit", "plus", "+", "und", "&", "samt",
    "set", "bundle", "paket", "komplett", "zusammen", "konvolut",
]

# Patterns that look like bundles but are NOT bundles
BUNDLE_EXCLUSIONS = [
    r"inkl\.?\s*garantie",      # "inkl. Garantie" = warranty, not bundle
    r"mit\s*garantie",          # "mit Garantie"
    r"inkl\.?\s*rechnung",      # "inkl. Rechnung" = invoice
    r"inkl\.?\s*versand",       # "inkl. Versand" = shipping
    r"inkl\.?\s*ovp",           # "inkl. OVP" = original packaging
    r"inkl\.?\s*box",           # "inkl. Box" = box
    r"inkl\.?\s*etui",          # "inkl. Etui" = case
    r"inkl\.?\s*karton",        # "inkl. Karton" = cardboard box
    r"mit\s*ovp",               # "mit OVP"
    r"mit\s*box",               # "mit Box"
    r"komplett\s*mit\s*ovp",    # "komplett mit OVP" = complete with box
]

def is_bundle_title(title: str) -> bool:
    """
    Erkennt ob Titel ein Bundle ist.
    Funktioniert für ALLE Kategorien!
    KEIN AI nötig - rein regelbasiert.
    
    WICHTIG: Bundle = mehrere VERSCHIEDENE Produkte
    NICHT Bundle = Menge eines Produkts (z.B. "2 Stk. à 2.5kg")
    """
    title_lower = title.lower()
    
    # Check für Exclusions ZUERST
    for exclusion in BUNDLE_EXCLUSIONS:
        if re.search(exclusion, title_lower):
            cleaned = re.sub(exclusion, '', title_lower)
            has_other_indicator = False
            for indicator in BUNDLE_INDICATORS:
                if indicator in cleaned:
                    has_other_indicator = True
                    break
            if not has_other_indicator:
                return False
    
    # v9.0 FIX: "2 Stk. à 2.5kg" = KEIN Bundle, sondern Quantity!
    # Pattern: Zahl + Stk + à/x + Gewicht = Menge eines Produkts
    if re.search(r'\d+\s*stk\.?\s*[àax@]\s*\d+', title_lower):
        return False  # Quantity, not bundle
    
    # Check für echte Bundle-Indikatoren (mehrere verschiedene Produkte)
    for indicator in BUNDLE_INDICATORS:
        if indicator in title_lower:
            return True
    
    # Mengenangaben NUR als Bundle wenn mehrere verschiedene Gewichte/Produkte
    # "2x 15kg, 2x 10kg" = Bundle (verschiedene Gewichte)
    # "2x 10kg" = KEIN Bundle (nur Quantity)
    quantity_matches = re.findall(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', title_lower)
    if len(quantity_matches) >= 2:
        # Mehrere verschiedene Gewichte = Bundle
        weights = set(m[1] for m in quantity_matches)
        if len(weights) >= 2:
            return True
    
    # "mit" Verbindungen = echtes Bundle
    if re.search(r'\bmit\s+\w+', title_lower) and not re.search(r'mit\s+(ovp|box|garantie|rechnung)', title_lower):
        return True
    
    return False


def decompose_bundle_universal(
    title: str,
    description: str,
    listing_id: str,
    category: str,
    query: str,
) -> Tuple[List[Product], bool]:
    """
    Universelle Bundle-Zerlegung für ALLE Kategorien.
    
    Entscheidungsbaum:
    1. Ist es überhaupt ein Bundle? → is_bundle_title()
    2. Kann Titel mit REGELN zerlegt werden? → Regex
    3. Kann Beschreibung mit REGELN zerlegt werden? → Regex
    4. Sonst: markiere als "needs_ai" für späteren AI-Call
    
    Returns:
        (products, needs_ai)
    """
    if not is_bundle_title(title):
        return [], False
    
    products = []
    combined = f"{title} {description}".lower()
    
    # =========================================================================
    # KATEGORIE: FITNESS (spezielle Heuristiken erlaubt)
    # =========================================================================
    if category == "fitness":
        products = decompose_fitness_bundle(title, description, listing_id)
        if products:
            return products, False
    
    # =========================================================================
    # KATEGORIE: SMARTWATCH / ELEKTRONIK
    # =========================================================================
    if category in ["smartwatch", "electronics"]:
        # Pattern: "Garmin Fenix 7 inkl. Zubehör/Armband/Brustgurt"
        main_product_match = re.search(
            r'(garmin|apple|samsung|fitbit|polar)\s+[\w\s]+\d*',
            combined
        )
        
        if main_product_match:
            main_product = main_product_match.group(0).strip().title()
            products.append(Product(
                product_key=generate_product_key(main_product),
                display_name=main_product,
                category=category,
                quantity=1,
                source_listings=[listing_id],
            ))
        
        # Zubehör erkennen
        accessories = []
        if "armband" in combined or "band" in combined:
            accessories.append("Armband")
        if "brustgurt" in combined or "herzfrequenz" in combined:
            accessories.append("Brustgurt")
        if "ladekabel" in combined or "charger" in combined:
            accessories.append("Ladekabel")
        if "hülle" in combined or "case" in combined:
            accessories.append("Schutzhülle")
        
        for acc in accessories:
            # Menge erkennen (z.B. "zwei Armbänder")
            qty = 1
            qty_match = re.search(rf'(\d+|zwei|drei)\s*{acc.lower()}', combined)
            if qty_match:
                qty_str = qty_match.group(1)
                qty = {"zwei": 2, "drei": 3}.get(qty_str, int(qty_str) if qty_str.isdigit() else 1)
            
            brand = extract_brand_from_query(query) or ""
            products.append(Product(
                product_key=generate_product_key(f"{brand} {acc}".strip()),
                display_name=f"{brand} {acc}".strip(),
                category=category,
                quantity=qty,
                source_listings=[listing_id],
            ))
        
        if products:
            return products, False
    
    # =========================================================================
    # KATEGORIE: CLOTHING (selten Bundles, aber möglich)
    # =========================================================================
    if category == "clothing":
        # Pattern: "Tommy Hilfiger Set: Hemd + Krawatte"
        # Meist keine komplexen Bundles bei Kleidung
        
        # Check ob explizite Auflistung in Beschreibung
        if description:
            lines = re.split(r'[\n•\-]', description)
            for line in lines:
                line = line.strip()
                if len(line) > 5:
                    brand = extract_brand_from_query(query) or ""
                    clean = clean_title_for_search(line, query, category)
                    if clean and len(clean) > 3:
                        products.append(Product(
                            product_key=generate_product_key(clean),
                            display_name=clean,
                            category=category,
                            quantity=1,
                            source_listings=[listing_id],
                        ))
        
        if products:
            return products, False
    
    # =========================================================================
    # FALLBACK: Bundle erkannt, aber kann nicht zerlegt werden
    # → Markiere für AI-Call
    # =========================================================================
    return [], True  # needs_ai = True


# ==============================================================================
# HAUPTFUNKTION: Process Query
# ==============================================================================

# v9.2: Global flag for AI-based title normalization
USE_AI_TITLE_NORMALIZATION = True


def process_query_listings(
    query: str,
    listings: List[Dict[str, Any]],
    category: str,
    use_ai_normalization: bool = None,
) -> List[ListingProducts]:
    """
    Verarbeitet alle Listings einer Query.
    
    v9.2: NEUE AI-basierte Titel-Normalisierung!
    - Ersetzt Regex-basiertes Cleanup
    - Bessere Bundle-Erkennung
    - Mehrsprachig (DE/FR/EN)
    - Edge-Cases werden korrekt behandelt
    
    Steps:
    0. Vision-erkannte Bundles/Titel übernehmen (wenn vorhanden)
    1. AI Title Normalization (NEU in v9.2!)
    2. Fallback: Regex-basierte Verarbeitung
    
    Args:
        query: User-Query (z.B. "Tommy Hilfiger")
        listings: Liste von Rohdaten-Inseraten
        category: Kategorie (smartwatch, clothing, fitness)
        use_ai_normalization: Override für AI-Normalisierung (default: USE_AI_TITLE_NORMALIZATION)
    
    Returns:
        Liste von ListingProducts (Mapping Inserat → Produkte)
    """
    results: List[ListingProducts] = []
    
    # v9.2: Determine if we should use AI normalization
    use_ai = use_ai_normalization if use_ai_normalization is not None else USE_AI_TITLE_NORMALIZATION
    
    # v9.2: AI-based title normalization (batch processing)
    if use_ai and listings:
        try:
            from ai_filter import normalize_titles_with_ai
            
            # Check if AI normalization was already done globally (passed via _ai_normalized)
            has_precomputed = any(l.get("_ai_normalized") is not None for l in listings)
            
            if has_precomputed:
                # Use pre-computed AI normalization from global batch
                print(f"\n✅ Using pre-computed AI normalization (global batch)")
                
                # Process pre-computed results
                for listing in listings:
                    listing_id = listing.get("listing_id", "")
                    title = listing.get("title", "")
                    
                    # Check for vision-detected bundle titles first
                    vision_bundle_titles = listing.get("_vision_bundle_titles")
                    if vision_bundle_titles and isinstance(vision_bundle_titles, list):
                        products = []
                        for vt in vision_bundle_titles:
                            if vt and isinstance(vt, str) and len(vt.strip()) > 2:
                                products.append(Product(
                                    product_key=generate_product_key(vt.strip()),
                                    display_name=vt.strip(),
                                    category=category,
                                    quantity=1,
                                    source_listings=[listing_id],
                                ))
                        if products:
                            results.append(ListingProducts(
                                listing_id=listing_id,
                                original_title=title,
                                products=products,
                                is_bundle=True,
                            ))
                            continue
                    
                    # Use pre-computed AI products
                    ai_products = listing.get("_ai_normalized", [])
                    
                    if ai_products:
                        products = []
                        is_bundle = len(ai_products) > 1 or any(p.get("quantity", 1) > 1 for p in ai_products)
                        
                        for ap in ai_products:
                            name = ap.get("name", title)
                            qty = ap.get("quantity", 1)
                            
                            # v9.2: POST-AI CLEANUP (Safety net for AI failures)
                            # Remove size/color/condition if AI missed them
                            name = re.sub(r'\b(Gr\.?|Grösse|taille|size)\s*[A-Z0-9]*\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\b\d+mm\b', '', name, flags=re.IGNORECASE)  # "43mm"
                            name = re.sub(r'\b(neu|neuwertig|gebraucht|top zustand|garantieaustausch)\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\b(schwarz|weiss|blau|rot|grün|black|white|blue|red)\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\bI\s+Smartwatch\b', '', name, flags=re.IGNORECASE)  # "Forerunner 970 I Smartwatch"
                            name = re.sub(r'\s+', ' ', name).strip()
                            name = re.sub(r',\s*$', '', name).strip()
                            
                            # Validation: Name must not be empty
                            if not name or len(name) < 3:
                                print(f"   ⚠️ Empty name after cleanup for '{title[:40]}' - using fallback")
                                name = clean_title_for_search(title, query, category)
                            
                            # Generate consistent product_key
                            weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', name.lower())
                            if weight_match and category == "fitness":
                                weight = float(weight_match.group(1).replace(',', '.'))
                                product_key = f"hantelscheibe_{weight}kg"
                            else:
                                product_key = generate_product_key(name)
                            
                            products.append(Product(
                                product_key=product_key,
                                display_name=name,
                                category=category,
                                quantity=qty,
                                source_listings=[listing_id],
                            ))
                        
                        results.append(ListingProducts(
                            listing_id=listing_id,
                            original_title=title,
                            products=products,
                            is_bundle=is_bundle,
                        ))
                        
                        # Log the normalization
                        if products:
                            print(f"   ✅ '{title[:50]}' → {[p.display_name for p in products]}")
                    else:
                        # Fallback: use regex-based cleanup
                        clean_title = clean_title_for_search(title, query, category)
                        products = [Product(
                            product_key=generate_product_key(clean_title),
                            display_name=clean_title,
                            category=category,
                            quantity=1,
                            source_listings=[listing_id],
                        )]
                        results.append(ListingProducts(
                            listing_id=listing_id,
                            original_title=title,
                            products=products,
                            is_bundle=False,
                        ))
                
                return results
            
            # Otherwise: do AI normalization now (per-query batch)
            # Collect all titles for batch AI processing
            titles = [l.get("title", "") for l in listings if l.get("title")]
            
            if titles:
                print(f"\n🤖 v9.2: AI Title Normalization für {len(titles)} Titel...")
                ai_normalized = normalize_titles_with_ai(titles, query, batch_size=15)
                
                # Process AI-normalized results
                for listing in listings:
                    listing_id = listing.get("listing_id", "")
                    title = listing.get("title", "")
                    
                    # Check for vision-detected bundle titles first
                    vision_bundle_titles = listing.get("_vision_bundle_titles")
                    if vision_bundle_titles and isinstance(vision_bundle_titles, list):
                        products = []
                        for vt in vision_bundle_titles:
                            if vt and isinstance(vt, str) and len(vt.strip()) > 2:
                                products.append(Product(
                                    product_key=generate_product_key(vt.strip()),
                                    display_name=vt.strip(),
                                    category=category,
                                    quantity=1,
                                    source_listings=[listing_id],
                                ))
                        if products:
                            results.append(ListingProducts(
                                listing_id=listing_id,
                                original_title=title,
                                products=products,
                                is_bundle=True,
                            ))
                            continue
                    
                    # Use AI-normalized products
                    ai_products = ai_normalized.get(title, [])
                    
                    if ai_products:
                        products = []
                        is_bundle = len(ai_products) > 1 or any(p.get("quantity", 1) > 1 for p in ai_products)
                        
                        for ap in ai_products:
                            name = ap.get("name", title)
                            qty = ap.get("quantity", 1)
                            
                            # v9.2: POST-AI CLEANUP (Safety net - same as pre-computed path)
                            name = re.sub(r'\b(Gr\.?|Grösse|taille|size)\s*[A-Z0-9]*\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\b\d+mm\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\b(neu|neuwertig|gebraucht|top zustand|garantieaustausch)\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\b(schwarz|weiss|blau|rot|grün|black|white|blue|red)\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\bI\s+Smartwatch\b', '', name, flags=re.IGNORECASE)
                            name = re.sub(r'\s+', ' ', name).strip()
                            name = re.sub(r',\s*$', '', name).strip()
                            
                            # v9.2: VALIDATION - Name must not be empty
                            if not name or len(name) < 3:
                                print(f"   ⚠️ Empty name after cleanup for '{title[:40]}' - using fallback")
                                name = clean_title_for_search(title, query, category)
                            
                            # Generate consistent product_key based on normalized name
                            # For fitness: use weight-based key if weight present
                            weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', name.lower())
                            if weight_match and category == "fitness":
                                weight = float(weight_match.group(1).replace(',', '.'))
                                product_key = f"hantelscheibe_{weight}kg"
                            else:
                                product_key = generate_product_key(name)
                            
                            products.append(Product(
                                product_key=product_key,
                                display_name=name,
                                category=category,
                                quantity=qty,
                                source_listings=[listing_id],
                            ))
                        
                        results.append(ListingProducts(
                            listing_id=listing_id,
                            original_title=title,
                            products=products,
                            is_bundle=is_bundle,
                        ))
                        
                        # Log the normalization
                        if products:
                            print(f"   ✅ '{title[:50]}' → {[p.display_name for p in products]}")
                    else:
                        # Fallback: use regex-based cleanup
                        clean_title = clean_title_for_search(title, query, category)
                        products = [Product(
                            product_key=generate_product_key(clean_title),
                            display_name=clean_title,
                            category=category,
                            quantity=1,
                            source_listings=[listing_id],
                        )]
                        results.append(ListingProducts(
                            listing_id=listing_id,
                            original_title=title,
                            products=products,
                            is_bundle=False,
                        ))
                
                return results
                
        except ImportError as e:
            print(f"   ⚠️ AI normalization not available: {e}")
        except Exception as e:
            print(f"   ⚠️ AI normalization failed: {e} - using regex fallback")
    
    # Fallback: Original regex-based processing
    for listing in listings:
        listing_id = listing.get("listing_id", "")
        title = listing.get("title", "")
        description = listing.get("description", "")
        
        # Step 0: Check for vision-detected bundle titles
        # e.g. "Krafttraining Set" → ["Hantelscheibe 5kg", "Langhantelstange", "Bank"]
        vision_bundle_titles = listing.get("_vision_bundle_titles")
        if vision_bundle_titles and isinstance(vision_bundle_titles, list):
            products = []
            for vt in vision_bundle_titles:
                if vt and isinstance(vt, str) and len(vt.strip()) > 2:
                    clean_vt = clean_title_for_search(vt.strip(), query, category)
                    products.append(Product(
                        product_key=generate_product_key(clean_vt),
                        display_name=clean_vt,
                        category=category,
                        quantity=1,
                        source_listings=[listing_id],
                    ))
            
            if products:
                results.append(ListingProducts(
                    listing_id=listing_id,
                    original_title=title,
                    products=products,
                    is_bundle=True,
                ))
                continue
        
        # Step 1: Bundle Detection (ALLE Kategorien!)
        if is_bundle_title(title):
            products, needs_ai = decompose_bundle_universal(
                title, description, listing_id, category, query
            )
            
            if products:
                # Erfolgreich mit Regeln zerlegt
                results.append(ListingProducts(
                    listing_id=listing_id,
                    original_title=title,
                    products=products,
                    is_bundle=True,
                ))
                continue
            
            if needs_ai:
                # Bundle erkannt, aber AI nötig für Zerlegung
                # Markiere für späteren AI-Call
                results.append(ListingProducts(
                    listing_id=listing_id,
                    original_title=title,
                    products=[],  # Wird später von AI gefüllt
                    is_bundle=True,
                ))
                continue
        
        # Step 2: Kein Bundle - normales Title Cleanup
        clean_title = clean_title_for_search(title, query, category)
        
        products = [Product(
            product_key=generate_product_key(clean_title),
            display_name=clean_title,
            category=category,
            quantity=1,
            source_listings=[listing_id],
        )]
        
        results.append(ListingProducts(
            listing_id=listing_id,
            original_title=title,
            products=products,
            is_bundle=False,
        ))
    
    return results


# ==============================================================================
# HILFSFUNKTIONEN
# ==============================================================================

def detect_category_from_query(query: str) -> str:
    """Erkennt Kategorie aus Query."""
    query_lower = query.lower()
    
    # Fitness
    if any(kw in query_lower for kw in ["hantel", "scheibe", "gewicht", "bumper", "kettlebell"]):
        return "fitness"
    
    # Smartwatch
    if any(kw in query_lower for kw in ["garmin", "smartwatch", "fitbit", "polar", "apple watch"]):
        return "smartwatch"
    
    # Clothing (wenn Produkttyp erkannt wird)
    clothing_types = ["jacke", "pullover", "hemd", "hose", "jeans", "kleid", "tasche", "schuhe"]
    if any(kw in query_lower for kw in clothing_types):
        return "clothing"
    
    # Default: Wenn nur Marke, prüfe ob bekannte Mode-Suche
    # (Tommy Hilfiger ohne Produkttyp = clothing)
    return "general"


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    # Test 1: Smartwatch
    print("=== TEST: Garmin Smartwatch ===")
    listings = [
        {"listing_id": "1", "title": "Garmin Fenix 7 Sapphire Solar, Top Zustand"},
        {"listing_id": "2", "title": "Garmin Fenix 7s (recertified)"},
        {"listing_id": "3", "title": "Garmin Lily"},
    ]
    
    results = process_query_listings("Garmin Smartwatch", listings, "smartwatch")
    for r in results:
        print(f"  {r.original_title}")
        print(f"  → {[p.display_name for p in r.products]}")
        print()
    
    # Test 2: Clothing
    print("=== TEST: Tommy Hilfiger ===")
    listings = [
        {"listing_id": "4", "title": "Tommy Hilfiger Winterjacke Herren Grösse L"},
        {"listing_id": "5", "title": "Tommy Hilfiger Strickpullover, Size XL"},
        {"listing_id": "6", "title": "Dame Jacke TOMMY HILFIGER THFLEX"},
    ]
    
    results = process_query_listings("Tommy Hilfiger", listings, "clothing")
    for r in results:
        print(f"  {r.original_title}")
        print(f"  → {[p.display_name for p in r.products]}")
        print()
    
    # Test 3: Fitness Bundle
    print("=== TEST: Hantelscheiben ===")
    listings = [
        {"listing_id": "7", "title": "Hantelscheiben, 2 Stk. à 10kg"},
        {"listing_id": "8", "title": "Zwei 50 mm Hantelscheiben 5 kg"},
        {"listing_id": "9", "title": "Langhantelbank mit Kurzhantel-Set"},
    ]
    
    results = process_query_listings("Hantelscheiben", listings, "fitness")
    for r in results:
        print(f"  {r.original_title}")
        for p in r.products:
            print(f"    → {p.display_name} ×{p.quantity}")
        print()
    
    # Test 4: Global Product List
    print("=== TEST: Global Product List ===")
    all_results = []
    all_results.extend(process_query_listings("Garmin", [
        {"listing_id": "1", "title": "Garmin Fenix 7 Solar"},
        {"listing_id": "2", "title": "Garmin Lily"},
    ], "smartwatch"))
    all_results.extend(process_query_listings("Hantelscheiben", [
        {"listing_id": "3", "title": "4x10kg Hantelscheiben"},
        {"listing_id": "4", "title": "Hantelscheibe 10kg"},  # Duplikat!
    ], "fitness"))
    
    global_products = build_global_product_list(all_results)
    print(f"  Unique Products: {len(global_products)}")
    for key, product in global_products.items():
        print(f"    - {product.display_name} (sources: {product.source_listings})")
