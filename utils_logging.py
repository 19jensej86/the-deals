"""
Logging Utilities - v7.3.5
===========================
Optimized logging with levels and statistics tracking.
"""

import os
import gzip
import shutil
from datetime import datetime
from typing import Dict, Any

# Log levels
LOG_LEVEL_SILENT = 0
LOG_LEVEL_ERROR = 1
LOG_LEVEL_INFO = 2
LOG_LEVEL_DEBUG = 3

# Global log level (can be set from config)
CURRENT_LOG_LEVEL = LOG_LEVEL_INFO


def set_log_level(level: int):
    """Set global log level."""
    global CURRENT_LOG_LEVEL
    CURRENT_LOG_LEVEL = level


def log_error(msg: str):
    """Always printed (critical errors)."""
    print(f"❌ {msg}")


def log_info(msg: str):
    """Printed at INFO level and above."""
    if CURRENT_LOG_LEVEL >= LOG_LEVEL_INFO:
        print(msg)


def log_debug(msg: str):
    """Only printed at DEBUG level."""
    if CURRENT_LOG_LEVEL >= LOG_LEVEL_DEBUG:
        print(f"   🔍 {msg}")


def archive_old_logs(log_file: str = "last_run.log", keep_last: int = 10):
    """
    Archive old log files with compression.
    
    Args:
        log_file: Current log file path
        keep_last: Number of archived logs to keep
    """
    if not os.path.exists(log_file):
        return
    
    # Create archive filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"logs/run_{timestamp}.log.gz"
    
    # Create logs directory if needed
    os.makedirs("logs", exist_ok=True)
    
    # Compress and archive
    with open(log_file, 'rb') as f_in:
        with gzip.open(archive_name, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    log_debug(f"Archived log to {archive_name}")
    
    # Clean up old archives (keep only last N)
    log_files = sorted([f for f in os.listdir("logs") if f.endswith(".log.gz")])
    if len(log_files) > keep_last:
        for old_file in log_files[:-keep_last]:
            os.remove(os.path.join("logs", old_file))
            log_debug(f"Deleted old log: {old_file}")


class CacheStats:
    """Track cache hit/miss statistics."""
    
    def __init__(self):
        self.web_price_hits = 0
        self.web_price_misses = 0
        self.variant_hits = 0
        self.variant_misses = 0
        self.query_analysis_hits = 0
        self.query_analysis_misses = 0
        self.total_cost_saved = 0.0
    
    def record_web_price_hit(self):
        self.web_price_hits += 1
        self.total_cost_saved += 0.35  # Cost of one web search
    
    def record_web_price_miss(self):
        self.web_price_misses += 1
    
    def record_variant_hit(self):
        self.variant_hits += 1
    
    def record_variant_miss(self):
        self.variant_misses += 1
    
    def record_query_analysis_hit(self):
        self.query_analysis_hits += 1
        self.total_cost_saved += 0.003  # Cost of one Haiku call
    
    def record_query_analysis_miss(self):
        self.query_analysis_misses += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get cache statistics summary."""
        total_hits = self.web_price_hits + self.variant_hits + self.query_analysis_hits
        total_misses = self.web_price_misses + self.variant_misses + self.query_analysis_misses
        total_requests = total_hits + total_misses
        
        hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "web_price_hits": self.web_price_hits,
            "web_price_misses": self.web_price_misses,
            "variant_hits": self.variant_hits,
            "variant_misses": self.variant_misses,
            "query_analysis_hits": self.query_analysis_hits,
            "query_analysis_misses": self.query_analysis_misses,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_rate": hit_rate,
            "cost_saved_usd": self.total_cost_saved,
        }
    
    def print_summary(self):
        """Print formatted cache statistics."""
        stats = self.get_summary()
        
        print("\n" + "="*60)
        print("📊 CACHE STATISTICS")
        print("="*60)
        
        if stats["total_hits"] + stats["total_misses"] == 0:
            print("   No cache operations recorded")
            return
        
        print(f"   Web Price Cache:    {stats['web_price_hits']:3d} hits, {stats['web_price_misses']:3d} misses")
        print(f"   Variant Cache:      {stats['variant_hits']:3d} hits, {stats['variant_misses']:3d} misses")
        print(f"   Query Analysis:     {stats['query_analysis_hits']:3d} hits, {stats['query_analysis_misses']:3d} misses")
        print(f"   " + "-"*56)
        print(f"   Total:              {stats['total_hits']:3d} hits, {stats['total_misses']:3d} misses")
        print(f"   Hit Rate:           {stats['hit_rate']:.1f}%")
        print(f"   💰 Cost Saved:      ${stats['cost_saved_usd']:.4f} USD")
        print("="*60 + "\n")


# Global cache stats instance
_cache_stats = CacheStats()


def get_cache_stats() -> CacheStats:
    """Get global cache statistics instance."""
    return _cache_stats


def reset_cache_stats():
    """Reset cache statistics for new run."""
    global _cache_stats
    _cache_stats = CacheStats()
