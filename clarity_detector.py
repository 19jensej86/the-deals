"""
Clarity Detector v1.0 - Intelligente Erkennung unklarer Inserate

Fluss:
1. Title Clarity Check: Ist der Titel spezifisch genug?
   - GUT: "Garmin Forerunner 255", "Gorilla Sport Langhantelbank"
   - SCHLECHT: "Sachen für Krafttraining", "iPhone cool"

2. Falls unklar → Detail-Scraping für Beschreibung
   - GUT: Spezifische Produktdetails in Beschreibung
   - SCHLECHT: "Ich verkaufe diese Sachen"

3. Falls immer noch unklar → Vision Analyse der Bilder
"""

import re
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ==============================================================================
# KONFIGURATION
# ==============================================================================

# Mindestlänge für einen "guten" Titel (Wörter)
MIN_TITLE_WORDS = 2

# Mindestlänge für eine "gute" Beschreibung (Zeichen)
MIN_DESCRIPTION_LENGTH = 50

# Vage Titel-Patterns die auf unklare Inserate hindeuten
VAGUE_TITLE_PATTERNS = [
    r'^(sachen|zeug|dinge|stuff)\s',           # "Sachen für..."
    r'\s(sachen|zeug|dinge)$',                 # "...Sachen"
    r'^(diverses|verschiedenes|allerlei)\b',   # "Diverses..."
    r'\b(cool|super|toll|mega|geil)\s*$',      # Nur Marketing-Wörter am Ende
    r'^[a-z]+\s+(cool|super|toll)$',           # "iPhone cool"
    r'^(zu verkaufen|verkaufe|biete)\s*$',     # Nur "Zu verkaufen"
    r'^\w+\s*$',                               # Einzelnes Wort
    r'^(set|paket|bundle|sammlung)\s*$',       # Nur "Set" ohne Details
]

# Patterns die auf GUTE, spezifische Titel hindeuten
SPECIFIC_TITLE_PATTERNS = [
    # Modellnummern
    r'\b\d{2,4}[a-z]?\b',                      # 255, 7s, 965
    r'\b(pro|plus|ultra|lite|mini|max)\b',    # Produktvarianten
    r'\b(gen\s*\d|generation\s*\d)\b',        # Generation
    # Marken mit Modell
    r'\b(garmin|apple|samsung|polar|suunto|coros)\s+\w+',
    r'\b(nike|adidas|mammut|salomon|the north face)\s+\w+',
    # Fitness-spezifisch
    r'\b\d+\s*(kg|lb|lbs)\b',                  # Gewichtsangabe
    r'\b(olympia|olympic|standard)\s*(hantel|scheibe|stange)',
    r'\b(langhantel|kurzhantel|kettlebell|hantelscheibe)',
]

# Vage Beschreibungs-Patterns
VAGUE_DESCRIPTION_PATTERNS = [
    r'^(ich )?verkaufe?\s+(diese[rsmn]?|das|die|den)\s+(sachen?|zeug|artikel)',
    r'^\s*(zu verkaufen|verkaufe|biete)\s*\.?\s*$',
    r'^(siehe|schau|guck)\s+(bild|foto|bilder|fotos)',
    r'^\s*-+\s*$',                             # Nur Striche
    r'^\s*\.+\s*$',                            # Nur Punkte
]

# Keywords die auf spezifische Produktinfos in der Beschreibung hindeuten
SPECIFIC_DESCRIPTION_KEYWORDS = [
    # Produktdetails
    r'\b(modell|model|typ|type|version)\s*[:=]?\s*\w+',
    r'\b(marke|brand|hersteller)\s*[:=]?\s*\w+',
    # Spezifikationen
    r'\b\d+\s*(kg|g|lb|mm|cm|m|zoll|inch)\b',
    # Aufzählungen
    r'\b(\d+x|\d+\s*stk|\d+\s*stück)\b',
    r'\b(besteht aus|enthält|inklusive|dabei|dazu)\b',
    # Zustandsbeschreibung mit Details
    r'\b(neupreis|originalpreis|np|vp)\s*[:=]?\s*(chf|sfr|fr\.?)?\s*\d+',
]


# ==============================================================================
# DATENKLASSEN
# ==============================================================================

@dataclass
class ClarityResult:
    """Ergebnis der Clarity-Analyse"""
    is_clear: bool                    # Inserat ist klar genug
    title_clarity: str                # "clear", "vague", "unknown"
    description_clarity: str          # "clear", "vague", "missing", "not_checked"
    needs_detail_scrape: bool         # Detail-Seite sollte gescraped werden
    needs_vision: bool                # Vision-Analyse notwendig
    confidence: float                 # 0-1, wie sicher sind wir
    reasons: List[str]                # Begründungen
    extracted_info: Dict[str, Any]    # Bereits extrahierte Infos
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_clear": self.is_clear,
            "title_clarity": self.title_clarity,
            "description_clarity": self.description_clarity,
            "needs_detail_scrape": self.needs_detail_scrape,
            "needs_vision": self.needs_vision,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "extracted_info": self.extracted_info,
        }


# ==============================================================================
# TITLE CLARITY CHECK
# ==============================================================================

def check_title_clarity(title: str) -> Tuple[str, float, List[str]]:
    """
    Prüft ob ein Titel spezifisch genug ist.
    
    Returns:
        Tuple[clarity_status, confidence, reasons]
        - clarity_status: "clear", "vague", "unknown"
        - confidence: 0-1
        - reasons: Liste von Begründungen
    """
    if not title or not title.strip():
        return "vague", 1.0, ["Titel ist leer"]
    
    title_lower = title.lower().strip()
    title_words = title_lower.split()
    reasons = []
    
    # 1. Zu kurzer Titel
    if len(title_words) < MIN_TITLE_WORDS:
        reasons.append(f"Titel zu kurz ({len(title_words)} Wörter)")
        return "vague", 0.9, reasons
    
    # 2. Check für vage Patterns
    for pattern in VAGUE_TITLE_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            reasons.append(f"Vager Titel-Pattern erkannt: '{pattern}'")
            return "vague", 0.85, reasons
    
    # 3. Check für spezifische Patterns (positiv)
    specificity_score = 0
    for pattern in SPECIFIC_TITLE_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            specificity_score += 1
    
    if specificity_score >= 2:
        reasons.append(f"Spezifische Patterns erkannt: {specificity_score}")
        return "clear", 0.9, reasons
    
    if specificity_score == 1:
        reasons.append("Ein spezifisches Pattern erkannt")
        return "clear", 0.7, reasons
    
    # 4. Fallback: Wortanzahl und Länge
    if len(title_words) >= 4 and len(title) >= 20:
        reasons.append("Titel ausreichend lang und detailliert")
        return "clear", 0.6, reasons
    
    # 5. Unsicher - braucht mehr Infos
    reasons.append("Titel-Klarheit unsicher, Detail-Check empfohlen")
    return "unknown", 0.5, reasons


# ==============================================================================
# DESCRIPTION CLARITY CHECK
# ==============================================================================

def check_description_clarity(
    description: str,
    title: str = ""
) -> Tuple[str, float, List[str], Dict[str, Any]]:
    """
    Prüft ob eine Beschreibung spezifisch genug ist.
    
    Returns:
        Tuple[clarity_status, confidence, reasons, extracted_info]
    """
    extracted_info = {}
    
    if not description or not description.strip():
        return "missing", 1.0, ["Keine Beschreibung vorhanden"], extracted_info
    
    desc_lower = description.lower().strip()
    reasons = []
    
    # 1. Zu kurze Beschreibung
    if len(description) < MIN_DESCRIPTION_LENGTH:
        reasons.append(f"Beschreibung zu kurz ({len(description)} Zeichen)")
        return "vague", 0.85, reasons, extracted_info
    
    # 2. Check für vage Patterns
    for pattern in VAGUE_DESCRIPTION_PATTERNS:
        if re.search(pattern, desc_lower, re.IGNORECASE):
            reasons.append(f"Vage Beschreibung erkannt")
            return "vague", 0.8, reasons, extracted_info
    
    # 3. Check für spezifische Keywords
    specificity_score = 0
    for pattern in SPECIFIC_DESCRIPTION_KEYWORDS:
        match = re.search(pattern, desc_lower, re.IGNORECASE)
        if match:
            specificity_score += 1
            # Extrahiere gefundene Infos
            if "kg" in match.group() or "lb" in match.group():
                extracted_info["weight_mentioned"] = True
            if "modell" in pattern or "model" in pattern:
                extracted_info["model_mentioned"] = True
    
    if specificity_score >= 3:
        reasons.append(f"Sehr spezifische Beschreibung ({specificity_score} Keywords)")
        return "clear", 0.95, reasons, extracted_info
    
    if specificity_score >= 1:
        reasons.append(f"Einige spezifische Details ({specificity_score} Keywords)")
        return "clear", 0.75, reasons, extracted_info
    
    # 4. Längere Beschreibungen sind oft informativer
    if len(description) >= 200:
        reasons.append("Lange Beschreibung, wahrscheinlich informativ")
        return "clear", 0.65, reasons, extracted_info
    
    # 5. Unsicher
    reasons.append("Beschreibungs-Klarheit unsicher")
    return "unknown", 0.5, reasons, extracted_info


# ==============================================================================
# MAIN CLARITY ANALYSIS
# ==============================================================================

def analyze_listing_clarity(
    title: str,
    description: str = None,
    category: str = None,
    price: float = None,
) -> ClarityResult:
    """
    Analysiert die Klarheit eines Inserats.
    
    Args:
        title: Inserat-Titel
        description: Beschreibung (optional, wenn schon vorhanden)
        category: Kategorie (optional)
        price: Preis (optional)
    
    Returns:
        ClarityResult mit Empfehlungen
    """
    all_reasons = []
    extracted_info = {}
    
    # Step 1: Title Clarity
    title_clarity, title_conf, title_reasons = check_title_clarity(title)
    all_reasons.extend([f"[Title] {r}" for r in title_reasons])
    
    # Wenn Titel klar ist, sind wir fertig
    if title_clarity == "clear" and title_conf >= 0.8:
        return ClarityResult(
            is_clear=True,
            title_clarity=title_clarity,
            description_clarity="not_checked",
            needs_detail_scrape=False,
            needs_vision=False,
            confidence=title_conf,
            reasons=all_reasons,
            extracted_info=extracted_info,
        )
    
    # Step 2: Description Clarity (wenn vorhanden)
    if description:
        desc_clarity, desc_conf, desc_reasons, desc_extracted = check_description_clarity(
            description, title
        )
        all_reasons.extend([f"[Desc] {r}" for r in desc_reasons])
        extracted_info.update(desc_extracted)
        
        if desc_clarity == "clear":
            return ClarityResult(
                is_clear=True,
                title_clarity=title_clarity,
                description_clarity=desc_clarity,
                needs_detail_scrape=False,
                needs_vision=False,
                confidence=max(title_conf, desc_conf),
                reasons=all_reasons,
                extracted_info=extracted_info,
            )
        
        # Beschreibung auch unklar -> Vision nötig
        if desc_clarity in ["vague", "unknown"]:
            all_reasons.append("[Action] Beschreibung unklar → Vision empfohlen")
            return ClarityResult(
                is_clear=False,
                title_clarity=title_clarity,
                description_clarity=desc_clarity,
                needs_detail_scrape=False,  # Haben schon Description
                needs_vision=True,
                confidence=min(title_conf, desc_conf),
                reasons=all_reasons,
                extracted_info=extracted_info,
            )
    
    # Keine Description -> Detail-Scraping empfohlen
    all_reasons.append("[Action] Titel unklar, keine Beschreibung → Detail-Scraping empfohlen")
    return ClarityResult(
        is_clear=False,
        title_clarity=title_clarity,
        description_clarity="missing",
        needs_detail_scrape=True,
        needs_vision=False,
        confidence=title_conf,
        reasons=all_reasons,
        extracted_info=extracted_info,
    )


# ==============================================================================
# BATCH PROCESSING
# ==============================================================================

def filter_unclear_listings(
    listings: List[Dict[str, Any]],
    max_unclear: int = 20,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Filtert Listings in klare und unklare.
    
    Args:
        listings: Liste von Listing-Dicts mit 'title', optional 'description'
        max_unclear: Maximale Anzahl unklarer Listings zum Verarbeiten
    
    Returns:
        Tuple[clear_listings, unclear_listings]
    """
    clear = []
    unclear = []
    
    for listing in listings:
        title = listing.get("title", "")
        description = listing.get("description", "")
        
        result = analyze_listing_clarity(title, description)
        
        # Speichere Analyse-Ergebnis im Listing
        listing["_clarity_result"] = result.to_dict()
        
        if result.is_clear:
            clear.append(listing)
        else:
            unclear.append(listing)
    
    # Limitiere unklare Listings
    if len(unclear) > max_unclear:
        logger.info(f"Limiting unclear listings from {len(unclear)} to {max_unclear}")
        unclear = unclear[:max_unclear]
    
    logger.info(f"Clarity filter: {len(clear)} clear, {len(unclear)} unclear")
    
    return clear, unclear


# ==============================================================================
# VISION PROMPT GENERATOR
# ==============================================================================

def generate_vision_prompt(
    title: str,
    description: str = "",
    category: str = "",
) -> str:
    """
    Generiert einen dynamischen Vision-Prompt basierend auf dem Kontext.
    
    Der Prompt fordert die KI auf, fehlende Informationen aus dem Bild zu extrahieren.
    """
    context_parts = []
    
    if title:
        context_parts.append(f"Titel: {title}")
    if description:
        context_parts.append(f"Beschreibung: {description[:200]}...")
    if category:
        context_parts.append(f"Kategorie: {category}")
    
    context = "\n".join(context_parts) if context_parts else "Keine Kontextinformationen"
    
    prompt = f"""Du analysierst ein Produktbild von einem Online-Inserat um fehlende Informationen zu identifizieren.

BEKANNTE INFORMATIONEN:
{context}

DEINE AUFGABE:
Die vorhandenen Informationen sind zu vage um das Produkt zu identifizieren und bewerten.
Analysiere das Bild und extrahiere folgende fehlende Details:

1. **Produktidentifikation**
   - Um was für ein Produkt handelt es sich genau?
   - Marke/Hersteller (falls erkennbar)
   - Modell/Modellnummer (falls erkennbar)
   - Produktvariante (Pro, Plus, Lite, etc.)

2. **Spezifikationen**
   - Material (Metall, Kunststoff, Gummi, etc.)
   - Gewicht/Grösse (falls relevant und erkennbar)
   - Farbe (nur wenn preisrelevant)

3. **Zustand**
   - Erscheint das Produkt neu, neuwertig oder gebraucht?
   - Sichtbare Gebrauchsspuren oder Schäden?

4. **Bundle/Set** (falls mehrere Artikel sichtbar)
   - Welche einzelnen Produkte sind im Bild?
   - Geschätzte Anzahl (z.B. "2x Hantelscheiben 5kg")

ANTWORTFORMAT (JSON):
{{
    "product_type": "z.B. Hantelscheiben, Smartwatch, etc.",
    "brand": "erkannte Marke oder null",
    "model": "erkanntes Modell oder null",
    "specifications": {{
        "weight_kg": null,
        "material": null,
        "size": null
    }},
    "condition": "neu/neuwertig/gebraucht/unklar",
    "is_bundle": true/false,
    "bundle_items": ["Item 1", "Item 2"],
    "confidence": 0.0-1.0,
    "notes": "zusätzliche Beobachtungen"
}}

Antworte NUR mit dem JSON-Objekt, ohne zusätzlichen Text."""

    return prompt


# ==============================================================================
# VISION RESULT → NEW TITLES
# ==============================================================================

def build_title_from_vision(vision_result: Dict[str, Any]) -> str:
    """
    Builds a clean, searchable product title from vision analysis results.
    
    Example:
        vision_result = {"brand": "Apple", "model": "iPhone 12 Mini", "product_type": "Smartphone"}
        → "Apple iPhone 12 Mini"
        
        vision_result = {"brand": None, "model": None, "product_type": "Hantelscheiben", 
                         "specifications": {"weight_kg": 5, "material": "Gusseisen"}}
        → "Hantelscheiben Gusseisen 5kg"
    """
    if not vision_result or not vision_result.get("success"):
        return None
    
    parts = []
    
    # Brand first (if present)
    brand = vision_result.get("brand")
    if brand and brand.lower() not in ["unknown", "unbekannt", "null", "none"]:
        parts.append(brand)
    
    # Model (usually most specific)
    model = vision_result.get("model")
    if model and model.lower() not in ["unknown", "unbekannt", "null", "none"]:
        parts.append(model)
    
    # If no brand/model, use product_type
    if not parts:
        product_type = vision_result.get("product_type")
        if product_type:
            parts.append(product_type)
    
    # Add key specifications
    specs = vision_result.get("specifications", {})
    if specs:
        # Weight (important for fitness equipment)
        weight = specs.get("weight_kg")
        if weight:
            parts.append(f"{weight}kg")
        
        # Material
        material = specs.get("material")
        if material and material.lower() not in ["unknown", "unbekannt", "null", "none"]:
            parts.append(material)
        
        # Size
        size = specs.get("size") or specs.get("grösse")
        if size and size.lower() not in ["unknown", "unbekannt", "null", "none"]:
            parts.append(size)
    
    if not parts:
        return None
    
    return " ".join(parts)


def build_bundle_titles_from_vision(vision_result: Dict[str, Any]) -> List[str]:
    """
    Extracts individual product titles from a bundle detected by vision.
    
    Example:
        vision_result = {
            "is_bundle": True,
            "bundle_items": [
                "Hantelscheibe Gusseisen 5kg",
                "Langhantelstange Olympia",
                "Gorilla Langhantelbank"
            ]
        }
        → ["Hantelscheibe Gusseisen 5kg", "Langhantelstange Olympia", "Gorilla Langhantelbank"]
    """
    if not vision_result or not vision_result.get("success"):
        return []
    
    if not vision_result.get("is_bundle"):
        return []
    
    bundle_items = vision_result.get("bundle_items", [])
    
    # Filter out empty/invalid items
    valid_items = [
        item.strip() for item in bundle_items 
        if item and isinstance(item, str) and len(item.strip()) > 2
    ]
    
    return valid_items


def apply_vision_to_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies vision results to a listing, creating new title(s) for web search.
    
    Updates the listing with:
    - _vision_title: New improved title (for single product)
    - _vision_bundle_titles: List of titles (for bundles)
    - _use_vision_title: True if vision improved the title
    
    Returns:
        The updated listing
    """
    vision_result = listing.get("_vision_result")
    if not vision_result or not vision_result.get("success"):
        return listing
    
    original_title = listing.get("title", "")
    
    # Check if it's a bundle
    if vision_result.get("is_bundle"):
        bundle_titles = build_bundle_titles_from_vision(vision_result)
        if bundle_titles:
            listing["_vision_bundle_titles"] = bundle_titles
            listing["_is_bundle"] = True
            listing["_use_vision_title"] = True
            print(f"   📦 Bundle detected: '{original_title[:30]}' → {len(bundle_titles)} items:")
            for bt in bundle_titles[:3]:
                print(f"      • {bt}")
            if len(bundle_titles) > 3:
                print(f"      ... +{len(bundle_titles) - 3} more")
    else:
        # Single product - build improved title
        new_title = build_title_from_vision(vision_result)
        if new_title and new_title.lower() != original_title.lower():
            listing["_vision_title"] = new_title
            listing["_use_vision_title"] = True
            print(f"   🔍 Vision improved: '{original_title[:30]}' → '{new_title}'")
    
    return listing


def process_vision_results(listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Processes all listings with vision results and applies improved titles.
    
    Call this after batch_analyze_with_vision() to convert vision results
    into usable titles for web search.
    """
    improved_count = 0
    bundle_count = 0
    
    for listing in listings:
        if listing.get("_vision_result"):
            apply_vision_to_listing(listing)
            if listing.get("_use_vision_title"):
                if listing.get("_vision_bundle_titles"):
                    bundle_count += 1
                else:
                    improved_count += 1
    
    if improved_count or bundle_count:
        print(f"\n✅ Vision title improvements: {improved_count} einzeln, {bundle_count} bundles")
    
    return listings


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    # Test cases
    test_cases = [
        # Klare Titel
        ("Garmin Forerunner 255", None),
        ("Gorilla Sport Langhantelbank super Zustand", None),
        ("Apple Watch Series 9 45mm GPS", None),
        ("2x 5kg Hantelscheiben Gusseisen", None),
        
        # Unklare Titel
        ("Sachen für Krafttraining", None),
        ("iPhone cool", None),
        ("Diverses", None),
        ("Set", None),
        ("Sportzeug", None),
        
        # Unklarer Titel, klare Beschreibung
        ("Sachen für Krafttraining", 
         "Ich verkaufe mein Krafttraining-Set: 2x 5kg Hantelscheiben, "
         "eine Curlstange und eine Olympiastange mit zwei 20kg Bumperplates."),
        
        # Unklarer Titel, unklare Beschreibung
        ("iPhone cool", "Coole iPhone zu verkaufen."),
    ]
    
    print("=" * 60)
    print("CLARITY DETECTOR TEST")
    print("=" * 60)
    
    for title, desc in test_cases:
        result = analyze_listing_clarity(title, desc)
        
        print(f"\n📝 Title: '{title}'")
        if desc:
            print(f"   Desc: '{desc[:50]}...'")
        print(f"   ✅ Clear: {result.is_clear}")
        print(f"   📊 Title: {result.title_clarity}, Desc: {result.description_clarity}")
        print(f"   🔍 Need Detail: {result.needs_detail_scrape}, Vision: {result.needs_vision}")
        print(f"   📈 Confidence: {result.confidence:.2f}")
        for reason in result.reasons:
            print(f"      - {reason}")
