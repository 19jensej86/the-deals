"""
Run Logger - Run-Level Statistics & Cost Tracking
==================================================
Aggregates statistics and costs for entire pipeline run.

CRITICAL: Transparent reporting for non-technical users.
"""

from typing import Dict, Any
from logging_utils.listing_logger import ListingProcessingLog


class RunLogger:
    """Logging for entire run."""
    
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.listing_logs: Dict[str, ListingProcessingLog] = {}
        self.run_stats = {
            "total_listings": 0,
            "ready_for_pricing": 0,
            "needed_detail": 0,
            "needed_vision": 0,
            "skipped": 0,
            "total_ai_calls": 0,
            "total_websearches": 0,
            "total_cost_usd": 0.0
        }
    
    def get_listing_log(self, listing_id: str) -> ListingProcessingLog:
        """Get or create listing log."""
        if listing_id not in self.listing_logs:
            self.listing_logs[listing_id] = ListingProcessingLog(listing_id)
        return self.listing_logs[listing_id]
    
    def increment_stat(self, stat_name: str, amount: int = 1):
        """Increment a run statistic."""
        if stat_name in self.run_stats:
            self.run_stats[stat_name] += amount
    
    def log_ai_call(self, purpose: str, model: str, cost_usd: float):
        """Log an AI call at run level."""
        self.run_stats["total_ai_calls"] += 1
        self.run_stats["total_cost_usd"] += cost_usd
    
    def finalize_run(self) -> Dict[str, Any]:
        """Calculate final statistics."""
        for log in self.listing_logs.values():
            summary = log.summary()
            
            # Type-safe handling: ai_calls can be int (count) or list (detailed calls)
            ai_calls = summary["ai_calls"]
            if isinstance(ai_calls, int):
                self.run_stats["total_ai_calls"] += ai_calls
            elif isinstance(ai_calls, list):
                self.run_stats["total_ai_calls"] += len(ai_calls)
            else:
                # Defensive: log unexpected type but continue
                print(f"⚠️ Warning: Unexpected ai_calls type: {type(ai_calls)}")
            
            self.run_stats["total_cost_usd"] += summary["costs"]["total"]
        
        return self.run_stats
    
    def print_cost_breakdown(self):
        """Print cost breakdown for non-technical users."""
        print("\n" + "="*60)
        print(f"COST BREAKDOWN - Run {self.run_id}")
        print("="*60)
        
        total_ai = sum(log.costs["ai_extraction"] for log in self.listing_logs.values())
        total_websearch = sum(log.costs["websearch"] for log in self.listing_logs.values())
        total_detail = sum(log.costs["detail_scraping"] for log in self.listing_logs.values())
        total_vision = sum(log.costs["vision"] for log in self.listing_logs.values())
        
        print(f"AI Extraction:    ${total_ai:.4f}")
        print(f"Websearch:        ${total_websearch:.4f}")
        print(f"Detail Scraping:  ${total_detail:.4f}")
        print(f"Vision:           ${total_vision:.4f}")
        print("-" * 60)
        print(f"TOTAL:            ${self.run_stats['total_cost_usd']:.4f}")
        print("="*60)
        
        print(f"\n📊 STATISTICS")
        print(f"Total Listings:        {self.run_stats['total_listings']}")
        print(f"Ready for Pricing:     {self.run_stats['ready_for_pricing']}")
        print(f"Needed Detail:         {self.run_stats['needed_detail']}")
        print(f"Needed Vision:         {self.run_stats['needed_vision']}")
        print(f"Skipped (too unclear): {self.run_stats['skipped']}")
        print(f"\n🤖 AI USAGE")
        print(f"AI Calls:              {self.run_stats['total_ai_calls']}")
        print(f"Websearches:           {self.run_stats['total_websearches']}")
        
        # Calculate rates
        if self.run_stats['total_listings'] > 0:
            skip_rate = (self.run_stats['skipped'] / self.run_stats['total_listings']) * 100
            detail_rate = (self.run_stats['needed_detail'] / self.run_stats['total_listings']) * 100
            vision_rate = (self.run_stats['needed_vision'] / self.run_stats['total_listings']) * 100
            
            print(f"\n📈 RATES")
            print(f"Skip Rate:             {skip_rate:.1f}%")
            print(f"Detail Scraping Rate:  {detail_rate:.1f}%")
            print(f"Vision Rate:           {vision_rate:.1f}%")
