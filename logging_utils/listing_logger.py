"""
Listing Logger - Per-Listing Cost & Step Tracking
==================================================
Detailed logging for individual listing processing.

CRITICAL: Transparent cost tracking for all AI/websearch calls.
"""

from datetime import datetime
from typing import Dict, List, Any


class ListingProcessingLog:
    """Detailed logging for one listing."""
    
    def __init__(self, listing_id: str):
        self.listing_id = listing_id
        self.steps: List[Dict[str, Any]] = []
        self.ai_calls: List[Dict[str, Any]] = []
        self.costs = {
            "ai_extraction": 0.0,
            "websearch": 0.0,
            "detail_scraping": 0.0,
            "vision": 0.0,
            "total": 0.0
        }
    
    def log_step(self, step_name: str, **kwargs):
        """Log a pipeline step."""
        self.steps.append({
            "step": step_name,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        })
    
    def log_ai_call(self, purpose: str, model: str, cost_usd: float):
        """Log an AI call with cost."""
        self.ai_calls.append({
            "purpose": purpose,
            "model": model,
            "cost_usd": cost_usd,
            "timestamp": datetime.now().isoformat()
        })
        self.costs["ai_extraction"] += cost_usd
        self.costs["total"] += cost_usd
    
    def log_websearch(self, query: str, success: bool, cost_usd: float = 0.0):
        """Log a websearch call."""
        self.log_step("websearch", query=query, success=success)
        self.costs["websearch"] += cost_usd
        self.costs["total"] += cost_usd
    
    def log_escalation(self, from_phase: str, to_phase: str, reason: str):
        """Log an escalation between phases."""
        self.log_step("escalation",
                     from_phase=from_phase,
                     to_phase=to_phase,
                     reason=reason)
    
    def log_skip(self, reason: str):
        """Log a skip decision."""
        self.log_step("skip", reason=reason)
    
    def summary(self) -> Dict[str, Any]:
        """Generate summary of processing."""
        return {
            "listing_id": self.listing_id,
            "total_steps": len(self.steps),
            "ai_calls": len(self.ai_calls),
            "costs": self.costs,
            "steps": self.steps
        }
    
    def print_summary(self):
        """Print human-readable summary."""
        print(f"\n{'='*60}")
        print(f"Listing: {self.listing_id}")
        print(f"{'='*60}")
        print(f"Steps: {len(self.steps)}")
        print(f"AI Calls: {len(self.ai_calls)}")
        print(f"Total Cost: ${self.costs['total']:.4f}")
        print(f"  - AI Extraction: ${self.costs['ai_extraction']:.4f}")
        print(f"  - Websearch: ${self.costs['websearch']:.4f}")
        print(f"  - Detail Scraping: ${self.costs['detail_scraping']:.4f}")
        print(f"  - Vision: ${self.costs['vision']:.4f}")
        
        if self.steps:
            print(f"\nSteps:")
            for step in self.steps:
                print(f"  - {step['step']}: {step.get('reason', 'N/A')}")
