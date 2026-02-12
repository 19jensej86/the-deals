"""
Extraction Package - AI-Based Product Extraction
=================================================
Query-agnostic product extraction with zero hallucinations.
"""

from extraction.ai_prompt import SYSTEM_PROMPT, generate_extraction_prompt
from extraction.ai_extractor import extract_product_with_ai
from extraction.bundle_classifier import classify_bundle
from extraction.bundle_extractor import extract_bundle_components, generate_component_identity_key

__all__ = [
    'SYSTEM_PROMPT',
    'generate_extraction_prompt',
    'extract_product_with_ai',
    'classify_bundle',
    'extract_bundle_components',
    'generate_component_identity_key',
]
