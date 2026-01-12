"""
Batch Bundle Detection - v7.3.4
================================
Optimizes bundle detection by processing multiple listings in ONE AI call.

Cost savings: 96%!
- Before: 24 listings × $0.003 = $0.072
- After:  1 batch call × $0.003 = $0.003
"""

import json
import re
from typing import List, Dict, Any, Optional
from ai_filter import call_ai, add_cost, COST_CLAUDE_HAIKU


def detect_bundles_batch(
    listings: List[Dict[str, Any]],
    query: str,
) -> Dict[int, Dict[str, Any]]:
    """
    Detect bundles for multiple listings in ONE AI call.
    
    Args:
        listings: List of dicts with 'title', 'description', 'index'
        query: Search query for context
    
    Returns:
        Dict mapping listing index to bundle detection result:
        {
            0: {"is_bundle": True, "components": [...], "confidence": 0.9},
            1: {"is_bundle": False, "components": [], "confidence": 0.0},
            ...
        }
    """
    if not listings:
        return {}
    
    # Build compact prompt with all listings
    listings_text = []
    for i, listing in enumerate(listings):
        title = listing.get("title", "")
        desc = listing.get("description", "")[:200]  # Limit description length
        listings_text.append(f"{i+1}. TITEL: {title}\n   DESC: {desc or 'Keine'}")
    
    prompt = f"""Analysiere diese {len(listings)} Ricardo-Inserate auf Bundle/Set.
SUCHBEGRIFF: {query}

INSERATE:
{chr(10).join(listings_text)}

Für JEDES Inserat: Ist es ein Bundle/Set mit mehreren Artikeln?
Wenn JA, liste die Komponenten mit Anzahl auf.

Antworte NUR als JSON-Array:
[
  {{"nr": 1, "is_bundle": true, "components": [{{"name": "Artikel 1", "quantity": 2}}, {{"name": "Artikel 2", "quantity": 1}}], "confidence": 0.9}},
  {{"nr": 2, "is_bundle": false, "components": [], "confidence": 0.0}},
  ...
]"""

    try:
        raw = call_ai(prompt, max_tokens=1500)
        if not raw:
            print("   ⚠️ No response from batch bundle detection")
            return {}
        
        # Track cost (ONE call for all listings!)
        add_cost(COST_CLAUDE_HAIKU)
        
        # Parse JSON array
        json_match = re.search(r'\[[\s\S]*\]', raw)
        if not json_match:
            print("   ⚠️ No JSON array in batch bundle response")
            return {}
        
        parsed = json.loads(json_match.group(0))
        
        # Map results by listing index
        results = {}
        for item in parsed:
            nr = item.get("nr", 0) - 1  # Convert to 0-indexed
            if 0 <= nr < len(listings):
                results[nr] = {
                    "is_bundle": item.get("is_bundle", False),
                    "components": item.get("components", []),
                    "confidence": item.get("confidence", 0.0),
                }
        
        return results
        
    except Exception as e:
        print(f"   ⚠️ Batch bundle detection failed: {e}")
        return {}
