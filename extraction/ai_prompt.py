"""
AI Extraction Prompts - Query-Agnostic & Zero Hallucinations
=============================================================
System and user prompts for product extraction.

CRITICAL: AI does NOT know search query, NO domain assumptions.
"""


# System prompt is IMMUTABLE - used for all AI extraction calls
SYSTEM_PROMPT = """You are a product extraction system for marketplace listings.

CRITICAL RULES (NEVER VIOLATE):

1. QUERY-AGNOSTIC
   - You do NOT know the search query
   - You do NOT know what product category is expected
   - You ONLY see: TITLE, DESCRIPTION, (optional) IMAGE
   - Extract ONLY from these sources

2. NO HALLUCINATIONS
   - Only extract what is EXPLICITLY stated
   - Brand ≠ Material (do NOT assume "Gym 80" = "Metal")
   - Weight ≠ Diameter (do NOT assume "40kg" = "50mm")
   - Premium brand ≠ Variant (do NOT assume "Garmin" = "Sapphire")
   - Price ≠ Quality (do NOT assume "expensive" = "premium variant")

3. NO IMPLICIT ASSUMPTIONS
   - If material not mentioned → specs.material = null
   - If variant unclear → model = null, confidence < 0.6
   - If bundle composition unclear → bundle_type = "unknown"
   - If quantity not explicit → quantity = 1

4. UNCERTAINTY IS VALID
   - confidence < 0.6 is a CORRECT answer
   - bundle_type = "unknown" is a CORRECT answer
   - products = [] (empty) is a CORRECT answer
   - Uncertainty is NOT a failure

5. NO DOMAIN ASSUMPTIONS
   - Do NOT assume product categories
   - Do NOT use domain-specific heuristics
   - Do NOT infer from brand knowledge
   - Treat every listing as unique

6. CONSERVATIVE BUNDLE CLASSIFICATION
   - Only "quantity" if EXPLICIT: "2x", "4x", "Lot de 2"
   - Only "multi_product" if multiple DIFFERENT products named
   - If unclear → "unknown", NOT "best guess"

7. PRICE-RELEVANT ATTRIBUTES ONLY
   - Only include if EXPLICITLY mentioned
   - Examples: "Solar", "Sapphire", "verstellbar", "Titan"
   - Do NOT include: colors, sizes, conditions, marketing words
   - Do NOT infer from brand or price

OUTPUT FORMAT:
Return structured JSON with explicit uncertainty markers.

The examples below are ILLUSTRATIVE ONLY.
Do NOT assume future listings are similar in domain, category, brand, or structure."""


def generate_extraction_prompt(title: str, description: str = None) -> str:
    """
    Generates user prompt for AI extraction.
    
    IMPORTANT: Contains NO query information!
    
    Args:
        title: Listing title
        description: Optional description (limited to 300 chars)
                    Can be string, dict, list, or None
    
    Returns:
        Complete user prompt for AI
    """
    
    # DEFENSIVE: Normalize description to string
    # Detail scraper may return dict with "full_description" field
    # or other structured data that cannot be sliced
    if description is None:
        desc_str = "No description"
    elif isinstance(description, dict):
        # Extract text field if present, otherwise stringify
        desc_str = description.get("full_description") or description.get("description") or str(description)
    elif isinstance(description, list):
        # Join list elements
        desc_str = " ".join(str(item) for item in description)
    else:
        # Assume string or convert to string
        desc_str = str(description)
    
    # Limit to 300 chars
    desc_preview = desc_str[:300] if desc_str else "No description"
    
    prompt = f"""Extract structured product information from this listing.

TITLE:
{title}

DESCRIPTION:
{desc_preview}

TASK:
Extract the following fields. Only set fields that are EXPLICITLY mentioned.

CRITICAL RULE FOR WEBSEARCH PRICING:
- product_type MUST be SINGULAR (one unit), NEVER plural
- We need to find: "What is the price of ONE unit of this product when new?"
- Ignore quantity words (2x, 4x, Set, Stück, Stk., Lot, Konvolut)
- Example: "4x 10kg Hantelscheiben" → product_type = "Hantelscheibe" (singular!)
- Example: "Kurzhanteln Set" → product_type = "Kurzhantel" (singular!)
- Example: "2 Stk. Gewichtsscheiben" → product_type = "Gewichtsscheibe" (singular!)

1. brand - Manufacturer name (null if not mentioned)
2. model - Specific model (null if unclear or not mentioned)
3. product_type - Generic category in SINGULAR form (e.g., "Smartwatch", "Akkuschrauber", "Tasche", "Hantelscheibe")
   MUST be singular - represents ONE unit for price lookup
4. quantity - How many? (default: 1, only if EXPLICIT: "2x", "4x", "Lot de 2")
5. specs - ONLY explicitly mentioned specifications
   Examples:
   - {{"weight_kg": 40}} if "40kg" in title
   - {{"screen_size_inch": 6.1}} if "6.1 Zoll" in title
   - {{"storage_gb": 64}} if "64GB" in title
   - {{"age_range": "3-5 Jahre"}} if explicitly stated
   
   FORBIDDEN:
   - {{"material": "Metall"}} if not mentioned
   - {{"diameter_mm": 50}} if not mentioned
   - {{"variant": "Pro"}} if not mentioned

6. price_relevant_attrs - ONLY if explicitly mentioned
   Examples: ["Solar", "Sapphire", "verstellbar", "Titan"]
   NOT allowed: inferred from brand, price, or category

7. bundle_type - One of: "single_product", "quantity", "weight_based", "bulk_lot", "multi_product", "unknown"
   Rules:
   - "quantity": only if explicit "2x", "3 Stück", etc.
   - "bulk_lot": large quantity (>50 pieces) like "500 Karten Konvolut"
   - "multi_product": only if multiple different products named
   - "unknown": if unclear (e.g., "Set" without details)

8. confidence - 0.0-1.0 (how certain are you?)
   < 0.6 if any critical information is missing or unclear

9. uncertainty_fields - List unclear aspects (e.g., ["material", "variant", "bundle_composition"])

10. needs_detail - true if title/description insufficient for pricing

11. final_search_name - CRITICAL for websearch pricing
    This is the ONLY string used for new-price websearch.
    Rules:
    - MUST be singular (one unit)
    - Use the most common merchant/shop terminology
    - Must NOT change the actual product
    - Must NOT broaden or narrow the product category
    - Ignore quantity words (2x, Set, Lot, Stück, Konvolut)
    Examples:
    - "4x 10kg Hantelscheiben Pro" → "Gewichtsscheibe 10kg"
    - "Kurzhanteln Set" → "Kurzhantel"
    - "Garmin Fenix 7 Sapphire" → "Garmin Fenix 7 Sapphire"
    - "Tommy Hilfiger Winterjacke Herren" → "Tommy Hilfiger Winterjacke"

12. category - High-level resale category
    One of: fitness, electronics, clothing, tools, collectibles, other
    No subcategories. No hybrids.

13. expected_resale_rate - Expected resale value relative to new price
    Range: 0.0 - 1.0
    Category-based, not listing-condition-based
    Typical ranges (guidance only):
    - fitness: 0.55 - 0.70
    - tools: 0.50 - 0.65
    - electronics: 0.35 - 0.55
    - clothing: 0.20 - 0.45
    - collectibles: 0.60 - 0.90

EXAMPLES (ILLUSTRATIVE - DO NOT ASSUME DOMAIN):

--- Example 1: Clear Single Product ---
Input: "iPhone 12 Mini 64GB"
Output:
{{
  "brand": "Apple",
  "model": "iPhone 12 Mini",
  "product_type": "Smartphone",
  "quantity": 1,
  "specs": {{"storage_gb": 64}},
  "price_relevant_attrs": [],
  "bundle_type": "single_product",
  "confidence": 0.95,
  "uncertainty_fields": [],
  "needs_detail": false,
  "extraction_notes": "Clear brand, model, and storage capacity"
}}

--- Example 2: Explicit Quantity ---
Input: "Bosch Akkuschrauber GSR 18V-28, 2 Stück"
Output:
{{
  "brand": "Bosch",
  "model": "GSR 18V-28",
  "product_type": "Akkuschrauber",
  "quantity": 2,
  "specs": {{"voltage": "18V"}},
  "price_relevant_attrs": [],
  "bundle_type": "quantity",
  "confidence": 0.90,
  "uncertainty_fields": [],
  "needs_detail": false,
  "final_search_name": "Bosch GSR 18V-28",
  "category": "tools",
  "expected_resale_rate": 0.55,
  "extraction_notes": "Explicit quantity '2 Stück', voltage mentioned"
}}

--- Example 3: Unclear Set ---
Input: "Playmobil Ritterburg Set mit Zubehör"
Output:
{{
  "brand": "Playmobil",
  "model": null,
  "product_type": "Ritterburg Set",
  "quantity": null,
  "specs": {{}},
  "price_relevant_attrs": [],
  "bundle_type": "unknown",
  "confidence": 0.30,
  "uncertainty_fields": ["bundle_composition", "included_items", "quantity"],
  "needs_detail": true,
  "extraction_notes": "'Set mit Zubehör' is vague, need detail page to understand composition"
}}

--- Example 4: Price-Relevant Attribute ---
Input: "Garmin Fenix 7 Sapphire Solar"
Output:
{{
  "brand": "Garmin",
  "model": "Fenix 7",
  "product_type": "Smartwatch",
  "quantity": 1,
  "specs": {{}},
  "price_relevant_attrs": ["Sapphire", "Solar"],
  "bundle_type": "single_product",
  "confidence": 0.95,
  "uncertainty_fields": [],
  "needs_detail": false,
  "final_search_name": "Garmin Fenix 7 Sapphire Solar",
  "category": "electronics",
  "expected_resale_rate": 0.45,
  "extraction_notes": "'Sapphire' and 'Solar' are price-relevant variants"
}}

--- Example 5: Fitness Equipment with Quantity ---
Input: "4x 10kg Hantelscheiben Pro"
Output:
{{
  "brand": null,
  "model": "Pro",
  "product_type": "Hantelscheibe",
  "quantity": 4,
  "specs": {{"weight_kg": 10}},
  "price_relevant_attrs": [],
  "bundle_type": "quantity",
  "confidence": 0.85,
  "uncertainty_fields": [],
  "needs_detail": false,
  "final_search_name": "Gewichtsscheibe 10kg",
  "category": "fitness",
  "expected_resale_rate": 0.60,
  "extraction_notes": "Explicit quantity '4x', weight '10kg' mentioned, using common merchant term 'Gewichtsscheibe'"
}}

--- Example 6: Clothing ---
Input: "Tommy Hilfiger Winterjacke Herren"
Output:
{{
  "brand": "Tommy Hilfiger",
  "model": null,
  "product_type": "Winterjacke",
  "quantity": 1,
  "specs": {{}},
  "price_relevant_attrs": [],
  "bundle_type": "single_product",
  "confidence": 0.90,
  "uncertainty_fields": [],
  "needs_detail": false,
  "final_search_name": "Tommy Hilfiger Winterjacke",
  "category": "clothing",
  "expected_resale_rate": 0.30,
  "extraction_notes": "Clear brand and product type, 'Herren' is target group not price-relevant"
}}

Return ONLY valid JSON (no explanation).
"""
    
    return prompt
