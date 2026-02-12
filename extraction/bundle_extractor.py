"""
Bundle Extractor - Query-Agnostic Component Extraction
=======================================================
Extracts structured components from bundle listings.

CRITICAL DESIGN PRINCIPLES:
1. Query-agnostic: Works for ANY product category
2. German-first: Ricardo listings are in German
3. Category-aware: Uses specialized logic for known categories (fitness, electronics, etc.)
4. Conservative: Only extracts what's explicitly stated
"""

import re
import json
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from models.bundle_component import BundleComponent, BundleExtractionResult


# =============================================================================
# GERMAN PRODUCT TYPE MAPPINGS
# =============================================================================

# Maps German terms to normalized product types for identity_key generation
GERMAN_PRODUCT_TYPES = {
    # === FITNESS: Weights ===
    "hantelscheibe": "hantelscheibe",
    "hantelscheiben": "hantelscheibe",
    "gewichtsscheibe": "hantelscheibe",
    "gewichtsscheiben": "hantelscheibe",
    "scheibe": "hantelscheibe",
    "scheiben": "hantelscheibe",
    "weight plate": "hantelscheibe",
    "weight plates": "hantelscheibe",
    "bumper plate": "hantelscheibe_bumper",
    "bumper plates": "hantelscheibe_bumper",
    "gusseisenplatte": "hantelscheibe_gusseisen",
    
    # === FITNESS: Barbells ===
    "langhantel": "langhantel",
    "langhantelstange": "langhantel",
    "olympiastange": "langhantel_olympic",
    "hantelstange": "langhantel",
    "barbell": "langhantel",
    "olympic bar": "langhantel_olympic",
    "sz-stange": "sz_stange",
    "curlstange": "sz_stange",
    
    # === FITNESS: Dumbbells ===
    "kurzhantel": "kurzhantel",
    "kurzhanteln": "kurzhantel",
    "dumbbell": "kurzhantel",
    "dumbbells": "kurzhantel",
    "gymnastikhantel": "kurzhantel",
    
    # === FITNESS: Racks & Benches ===
    "squat rack": "squat_rack",
    "kniebeugenständer": "squat_rack",
    "hantelständer": "hantelstaender",
    "hantelablage": "hantelstaender",
    "power rack": "power_rack",
    "hantelbank": "hantelbank",
    "trainingsbank": "hantelbank",
    "flachbank": "hantelbank_flach",
    "schrägbank": "hantelbank_schraeg",
    
    # === FITNESS: Other ===
    "bodenmatte": "bodenmatte",
    "bodenschutzmatte": "bodenmatte",
    "gymnastikmatte": "bodenmatte",
    "floor mat": "bodenmatte",
    "kettlebell": "kettlebell",
    "kugelhantel": "kettlebell",
    "widerstandsband": "widerstandsband",
    "resistance band": "widerstandsband",
    
    # === ELECTRONICS ===
    "smartphone": "smartphone",
    "handy": "smartphone",
    "tablet": "tablet",
    "ipad": "tablet_ipad",
    "laptop": "laptop",
    "notebook": "laptop",
    "ladegerät": "ladegeraet",
    "charger": "ladegeraet",
    "kopfhörer": "kopfhoerer",
    "headphones": "kopfhoerer",
    "earbuds": "kopfhoerer_inear",
    "smartwatch": "smartwatch",
    "uhr": "uhr",
    
    # === GENERAL ===
    "kabel": "kabel",
    "cable": "kabel",
    "tasche": "tasche",
    "case": "case",
    "hülle": "huelle",
    "cover": "huelle",
    "adapter": "adapter",
    "ständer": "staender",
    "halterung": "halterung",
}

# Material mappings for identity_key suffix
MATERIAL_MAPPINGS = {
    # Fitness weights
    "bumper": "bumper",
    "gummi": "bumper",
    "rubber": "bumper",
    "gusseisen": "gusseisen",
    "cast iron": "gusseisen",
    "eisen": "gusseisen",
    "calibrated": "calibrated",
    "competition": "calibrated",
    "wettkampf": "calibrated",
    "urethane": "urethane",
    "chrome": "chrome",
    "chrom": "chrome",
    "vinyl": "vinyl",
    "neopren": "neopren",
}


# =============================================================================
# AI PROMPTS - GERMAN-AWARE
# =============================================================================

BUNDLE_EXTRACTION_PROMPT_GENERAL = """Analysiere dieses Ricardo-Inserat und extrahiere alle enthaltenen Produkte.

TITEL: {title}
BESCHREIBUNG: {description}

AUFGABE:
1. Ist dies ein Bundle/Set mit MEHREREN VERSCHIEDENEN Produkten?
2. Falls ja: Liste JEDES einzelne Produkt mit Menge und Spezifikationen

WICHTIG:
- Nur EXPLIZIT genannte Produkte extrahieren
- Mengen nur wenn klar angegeben (z.B. "4x", "2 Stück")
- Bei Gewichten: Gewicht pro Stück angeben (z.B. "5kg" nicht "20kg total")
- Deutsche Produktnamen verwenden

Antwort NUR als JSON:
{{
  "is_bundle": true/false,
  "components": [
    {{
      "name": "Produktname auf Deutsch",
      "product_type": "hantelscheibe|langhantel|kurzhantel|etc",
      "quantity": 1,
      "specs": {{
        "weight_kg": null,
        "material": null,
        "size": null,
        "brand": null
      }}
    }}
  ],
  "confidence": 0.0-1.0,
  "total_weight_kg": null
}}

Beispiel für "Squat Rack + Langhantel + 4x5kg + 2x10kg + 2x15kg Hantelscheiben":
{{
  "is_bundle": true,
  "components": [
    {{"name": "Squat Rack", "product_type": "squat_rack", "quantity": 1, "specs": {{}}}},
    {{"name": "Langhantelstange", "product_type": "langhantel", "quantity": 1, "specs": {{}}}},
    {{"name": "Hantelscheibe 5kg", "product_type": "hantelscheibe", "quantity": 4, "specs": {{"weight_kg": 5}}}},
    {{"name": "Hantelscheibe 10kg", "product_type": "hantelscheibe", "quantity": 2, "specs": {{"weight_kg": 10}}}},
    {{"name": "Hantelscheibe 15kg", "product_type": "hantelscheibe", "quantity": 2, "specs": {{"weight_kg": 15}}}}
  ],
  "confidence": 0.9,
  "total_weight_kg": 70
}}"""


BUNDLE_EXTRACTION_PROMPT_FITNESS = """Analysiere dieses Fitness-Equipment-Inserat und extrahiere alle Komponenten.

TITEL: {title}
BESCHREIBUNG: {description}

AUFGABE - FOKUS FITNESS:
1. Identifiziere ALLE Fitness-Geräte und Gewichte
2. Bei Gewichten: JEDE Gewichtsklasse separat auflisten
3. Material erkennen: Bumper (Gummi), Gusseisen, Calibrated (Wettkampf)

WICHTIGE FITNESS-DETAILS:
- Hantelscheiben: Gewicht pro Stück, Material, Olympisch (50mm) oder Standard (30mm)
- Langhanteln: Länge, Olympisch oder Standard, Belastbarkeit
- Kurzhanteln: Gewicht, verstellbar oder fix
- Racks: Typ (Squat Rack, Power Rack, Half Rack)

Antwort NUR als JSON:
{{
  "is_bundle": true/false,
  "components": [
    {{
      "name": "Produktname auf Deutsch",
      "product_type": "hantelscheibe|langhantel|kurzhantel|squat_rack|hantelbank|bodenmatte|kettlebell",
      "quantity": 1,
      "specs": {{
        "weight_kg": null,
        "material": "bumper|gusseisen|calibrated|chrome|vinyl",
        "diameter_mm": null,
        "length_cm": null,
        "brand": null
      }}
    }}
  ],
  "confidence": 0.0-1.0,
  "total_weight_kg": null
}}

MATERIAL-ERKENNUNG:
- "Bumper", "Gummi", "Hi-Temp", "können fallen gelassen werden" → bumper
- "Gusseisen", "Eisen", "Cast Iron" → gusseisen  
- "Calibrated", "Wettkampf", "Competition", "IWF" → calibrated
- "Olympia", "50mm Loch" → olympisch (höherer Wert)

Beispiel für "70kg Bumper Plates Set + Olympiastange":
{{
  "is_bundle": true,
  "components": [
    {{"name": "Olympia Langhantelstange", "product_type": "langhantel", "quantity": 1, "specs": {{"diameter_mm": 50, "material": "chrome"}}}},
    {{"name": "Bumper Plate 5kg", "product_type": "hantelscheibe", "quantity": 4, "specs": {{"weight_kg": 5, "material": "bumper", "diameter_mm": 50}}}},
    {{"name": "Bumper Plate 10kg", "product_type": "hantelscheibe", "quantity": 2, "specs": {{"weight_kg": 10, "material": "bumper", "diameter_mm": 50}}}},
    {{"name": "Bumper Plate 15kg", "product_type": "hantelscheibe", "quantity": 2, "specs": {{"weight_kg": 15, "material": "bumper", "diameter_mm": 50}}}}
  ],
  "confidence": 0.95,
  "total_weight_kg": 70
}}"""


BUNDLE_VISION_PROMPT_GENERAL = """Analysiere dieses Bild eines Produkt-Bundles.

Für jedes sichtbare Produkt identifiziere:
1. Produkttyp
2. Ungefähre Anzahl
3. Marke (falls sichtbar)
4. Material/Qualität (falls erkennbar)

Antwort als JSON:
{{
  "components": [
    {{"type": "produkttyp", "quantity": 1, "brand": null, "material": null}}
  ],
  "confidence": 0.0-1.0
}}"""


BUNDLE_VISION_PROMPT_FITNESS = """Analysiere dieses Bild von Fitness-Equipment.

FOKUS auf:
1. Hantelscheiben: Typ erkennen!
   - Bumper Plates (Gummi-ummantelt, können fallen gelassen werden) = HOHER WERT
   - Gusseisen (grau/schwarz, Metall) = MITTLERER WERT
   - Calibrated/Competition (farbcodiert nach IWF) = SEHR HOHER WERT
   
2. Langhantel: Olympisch (dick, 50mm) oder Standard (dünn, 30mm)?

3. Sonstige Geräte: Rack, Bank, Matten

Für jedes sichtbare Teil:
{{
  "components": [
    {{
      "type": "hantelscheibe|langhantel|kurzhantel|squat_rack|hantelbank|bodenmatte",
      "quantity": 1,
      "material": "bumper|gusseisen|calibrated|standard",
      "weight_kg": null,
      "brand": null
    }}
  ],
  "confidence": 0.0-1.0
}}

WICHTIG: Bumper Plates sind DEUTLICH mehr wert als Gusseisen!"""


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def extract_bundle_components(
    title: str,
    description: str,
    category: Optional[str] = None,
    image_url: Optional[str] = None,
    use_vision: bool = False,
    call_ai_func=None,
    v10_products: Optional[List] = None,
) -> BundleExtractionResult:
    """
    Extract structured components from a bundle listing.
    
    COST OPTIMIZATION: Uses multiple strategies to minimize AI calls:
    1. Regex extraction (free)
    2. Reuse v10 pipeline products if available (no extra cost)
    3. AI extraction only if needed
    
    Args:
        title: Listing title
        description: Listing description
        category: Product category (e.g., "fitness", "electronics")
        image_url: Optional image URL for vision analysis
        use_vision: Whether to use vision API
        call_ai_func: Function to call AI (injected for testability)
        v10_products: Pre-extracted products from v10 pipeline (avoids duplicate AI call)
    
    Returns:
        BundleExtractionResult with extracted components
    """
    result = BundleExtractionResult()
    
    # Step 1: Try regex-based extraction first (fast, no AI cost)
    regex_result = _extract_with_regex(title, description, category)
    if regex_result.is_bundle and regex_result.confidence >= 0.8:
        print(f"      ✅ Regex extraction successful (confidence: {regex_result.confidence:.2f})")
        return regex_result
    
    # Step 2: Try to use v10 pipeline products (no extra AI cost)
    if v10_products and len(v10_products) >= 2:
        v10_result = _convert_v10_products_to_components(v10_products, category)
        if v10_result.is_bundle and v10_result.confidence >= 0.7:
            print(f"      ✅ Using v10 products (no extra AI cost)")
            return v10_result
    
    # Step 2: Use AI extraction
    if call_ai_func is None:
        # Import here to avoid circular imports
        try:
            from ai_filter import call_ai
            call_ai_func = call_ai
        except ImportError:
            return result
    
    # Choose prompt based on category
    is_fitness = _is_fitness_category(category, title, description)
    
    if is_fitness:
        prompt = BUNDLE_EXTRACTION_PROMPT_FITNESS.format(
            title=title,
            description=description[:1000] if description else "Keine Beschreibung"
        )
    else:
        prompt = BUNDLE_EXTRACTION_PROMPT_GENERAL.format(
            title=title,
            description=description[:1000] if description else "Keine Beschreibung"
        )
    
    try:
        raw_response = call_ai_func(prompt, max_tokens=1000)
        if raw_response:
            result = _parse_ai_response(raw_response, category)
            result.extraction_method = "ai_text"
            result.category = "fitness" if is_fitness else category
    except Exception as e:
        print(f"      ⚠️ Bundle extraction failed: {e}")
    
    # Step 3: Vision refinement (optional, for high-value bundles)
    if use_vision and image_url and result.is_bundle:
        vision_result = _refine_with_vision(
            image_url, 
            result, 
            is_fitness,
            call_ai_func
        )
        if vision_result:
            result = vision_result
            result.extraction_method = "ai_vision"
    
    # Step 4: Generate identity keys for each component
    for component in result.components:
        component.identity_key = generate_component_identity_key(component)
        component.category = result.category
    
    return result


def _is_fitness_category(
    category: Optional[str], 
    title: str, 
    description: str
) -> bool:
    """Detect if listing is fitness-related."""
    if category and category.lower() in ["fitness", "sport", "krafttraining", "gewichte"]:
        return True
    
    text = f"{title} {description}".lower()
    fitness_keywords = [
        "hantel", "gewicht", "langhantel", "kurzhantel", "scheibe",
        "squat", "rack", "bank", "fitness", "training", "gym",
        "bumper", "olympia", "kraftsport", "bodybuilding",
        "kettlebell", "kugelhantel", "crossfit"
    ]
    
    return sum(1 for kw in fitness_keywords if kw in text) >= 2


def _extract_with_regex(
    title: str, 
    description: str,
    category: Optional[str]
) -> BundleExtractionResult:
    """
    Fast regex-based extraction for common patterns.
    
    Patterns:
    - "4x 5kg" → 4 pieces of 5kg
    - "2× 10kg + 2× 15kg" → 2 pieces of 10kg + 2 pieces of 15kg
    """
    result = BundleExtractionResult()
    text = f"{title} {description}".lower()
    
    # Pattern: Nx Ykg (e.g., "4x 5kg", "2× 10kg")
    weight_pattern = r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg'
    matches = re.findall(weight_pattern, text)
    
    if len(matches) >= 2:
        # Multiple weight groups = likely bundle
        result.is_bundle = True
        total_weight = 0.0
        
        for qty_str, weight_str in matches:
            qty = int(qty_str)
            weight = float(weight_str.replace(',', '.'))
            total_weight += qty * weight
            
            component = BundleComponent(
                product_type="hantelscheibe",
                display_name=f"Hantelscheibe {weight}kg",
                quantity=qty,
                specs={"weight_kg": weight},
                confidence=0.85,
            )
            result.components.append(component)
        
        result.total_weight_kg = total_weight
        result.confidence = 0.80
        result.extraction_method = "regex"
        result.category = "fitness"
    
    return result


def _convert_v10_products_to_components(
    v10_products: List,
    category: Optional[str]
) -> BundleExtractionResult:
    """
    Convert v10 pipeline extracted products to BundleComponents.
    
    This avoids making a duplicate AI call when v10 already extracted
    product info.
    
    Args:
        v10_products: List of ProductSpec objects from v10 pipeline
        category: Product category
    
    Returns:
        BundleExtractionResult with components
    """
    result = BundleExtractionResult()
    
    if not v10_products or len(v10_products) < 2:
        return result
    
    result.is_bundle = True
    result.extraction_method = "v10_reuse"
    result.category = category
    
    total_weight = 0.0
    confidences = []
    
    for product in v10_products:
        # Extract info from ProductSpec
        product_type = getattr(product, 'product_type', 'unknown')
        brand = getattr(product, 'brand', None)
        model = getattr(product, 'model', None)
        specs = getattr(product, 'specs', {}) or {}
        confidence = getattr(product, 'confidence', 0.5)
        
        # Normalize product type
        normalized_type = GERMAN_PRODUCT_TYPES.get(
            product_type.lower() if product_type else 'unknown',
            product_type.lower() if product_type else 'unknown'
        )
        
        # Build display name
        display_parts = []
        if brand:
            display_parts.append(brand)
        if model:
            display_parts.append(model)
        elif product_type:
            display_parts.append(product_type)
        display_name = " ".join(display_parts) or "Unknown"
        
        # Extract weight if present
        weight_kg = specs.get('weight_kg')
        if weight_kg:
            total_weight += float(weight_kg)
        
        component = BundleComponent(
            product_type=normalized_type,
            display_name=display_name,
            quantity=1,  # v10 already handles quantity separately
            specs=specs,
            confidence=confidence,
        )
        result.components.append(component)
        confidences.append(confidence)
    
    # Overall confidence is average of component confidences
    result.confidence = sum(confidences) / len(confidences) if confidences else 0.0
    result.total_weight_kg = total_weight if total_weight > 0 else None
    
    return result


def _parse_ai_response(
    raw_response: str,
    category: Optional[str]
) -> BundleExtractionResult:
    """Parse AI response into BundleExtractionResult."""
    result = BundleExtractionResult()
    
    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', raw_response)
    if not json_match:
        return result
    
    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return result
    
    result.is_bundle = data.get("is_bundle", False)
    result.confidence = data.get("confidence", 0.0)
    result.total_weight_kg = data.get("total_weight_kg")
    result.category = category
    
    components_data = data.get("components", [])
    for comp_data in components_data:
        if not isinstance(comp_data, dict):
            continue
        
        # Normalize product type
        raw_type = comp_data.get("product_type", comp_data.get("type", "unknown"))
        normalized_type = GERMAN_PRODUCT_TYPES.get(raw_type.lower(), raw_type.lower())
        
        # Extract specs
        specs = comp_data.get("specs", {})
        if not specs:
            # Try to extract from top-level fields
            if comp_data.get("weight_kg"):
                specs["weight_kg"] = comp_data["weight_kg"]
            if comp_data.get("material"):
                specs["material"] = comp_data["material"]
        
        component = BundleComponent(
            product_type=normalized_type,
            display_name=comp_data.get("name", comp_data.get("display_name", "Unknown")),
            quantity=comp_data.get("quantity", 1),
            specs=specs,
            confidence=result.confidence,
        )
        result.components.append(component)
    
    # Validate: Need at least 2 components for a bundle
    if len(result.components) < 2:
        result.is_bundle = False
        result.confidence = 0.0
    
    return result


def _refine_with_vision(
    image_url: str,
    current_result: BundleExtractionResult,
    is_fitness: bool,
    call_ai_func
) -> Optional[BundleExtractionResult]:
    """
    Refine extraction using vision API.
    
    Primary use: Identify material quality (bumper vs gusseisen for weights).
    """
    if is_fitness:
        prompt = BUNDLE_VISION_PROMPT_FITNESS
    else:
        prompt = BUNDLE_VISION_PROMPT_GENERAL
    
    try:
        # Call vision API with image
        raw_response = call_ai_func(
            prompt,
            max_tokens=800,
            image_url=image_url,
        )
        
        if not raw_response:
            return None
        
        # Parse vision response
        json_match = re.search(r'\{[\s\S]*\}', raw_response)
        if not json_match:
            return None
        
        data = json.loads(json_match.group(0))
        vision_components = data.get("components", [])
        vision_confidence = data.get("confidence", 0.0)
        
        # Only use vision result if it's confident
        if vision_confidence < 0.6 or not vision_components:
            return None
        
        # Merge vision info with text extraction
        # Vision is better at material detection
        for i, comp in enumerate(current_result.components):
            if i < len(vision_components):
                vision_comp = vision_components[i]
                # Update material if vision detected it
                if vision_comp.get("material") and not comp.specs.get("material"):
                    comp.specs["material"] = vision_comp["material"]
                # Update brand if vision detected it
                if vision_comp.get("brand") and not comp.specs.get("brand"):
                    comp.specs["brand"] = vision_comp["brand"]
        
        # Update confidence to reflect vision enhancement
        current_result.confidence = max(current_result.confidence, vision_confidence)
        print(f"      👁️ Vision enhanced extraction (confidence: {vision_confidence:.2f})")
        
        return current_result
        
    except json.JSONDecodeError:
        print(f"      ⚠️ Vision response not valid JSON")
        return None
    except Exception as e:
        print(f"      ⚠️ Vision refinement failed: {e}")
        return None


def generate_component_identity_key(component: BundleComponent) -> str:
    """
    Generate canonical identity key for market aggregation.
    
    Format: {product_type}_{material}_{weight}kg
    Examples:
    - hantelscheibe_bumper_5kg
    - langhantel_olympic
    - squat_rack
    """
    parts = [component.product_type]
    
    # Add material if known
    material = component.specs.get("material")
    if material:
        normalized_material = MATERIAL_MAPPINGS.get(material.lower(), material.lower())
        parts.append(normalized_material)
    
    # Add weight for weight-based products
    weight_kg = component.specs.get("weight_kg")
    if weight_kg and component.product_type in ["hantelscheibe", "kurzhantel", "kettlebell"]:
        # Normalize weight (5.0 → 5, 2.5 → 2_5)
        if weight_kg == int(weight_kg):
            parts.append(f"{int(weight_kg)}kg")
        else:
            parts.append(f"{str(weight_kg).replace('.', '_')}kg")
    
    # Add diameter for plates if relevant
    diameter = component.specs.get("diameter_mm")
    if diameter and diameter in [50, 51]:
        parts.append("olympic")
    elif diameter and diameter in [30, 31]:
        parts.append("standard")
    
    return "_".join(parts)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def validate_bundle_components(
    components: List[BundleComponent]
) -> Tuple[List[BundleComponent], List[str]]:
    """
    Validate extracted components and filter invalid ones.
    
    Returns:
        (valid_components, warnings)
    """
    valid = []
    warnings = []
    
    for comp in components:
        # Check: Weight plates must have weight
        if comp.product_type == "hantelscheibe":
            weight = comp.specs.get("weight_kg")
            if not weight or weight <= 0:
                warnings.append(f"Hantelscheibe ohne Gewicht übersprungen: {comp.display_name}")
                continue
        
        # Check: Quantity must be positive
        if comp.quantity <= 0:
            warnings.append(f"Ungültige Menge für {comp.display_name}: {comp.quantity}")
            continue
        
        valid.append(comp)
    
    return valid, warnings


def estimate_component_count(title: str, description: str) -> int:
    """
    Quick estimate of component count without full extraction.
    
    Used to decide if bundle detection is worth the AI cost.
    """
    text = f"{title} {description}".lower()
    
    # Count quantity patterns
    qty_patterns = re.findall(r'\d+\s*[x×]', text)
    plus_count = text.count('+') + text.count(' und ') + text.count(' mit ')
    
    return len(qty_patterns) + plus_count + 1
