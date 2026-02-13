"""
Strategy determination and deal scoring module.
Extracted from ai_filter.py v8.0
"""

from typing import Tuple, Optional

# Import constants from parent - will be set by ai_filter.py
MIN_PROFIT_THRESHOLD = 10.0  # Default, overridden by ai_filter


def set_min_profit_threshold(value: float):
    """Allow ai_filter to set the threshold."""
    global MIN_PROFIT_THRESHOLD
    MIN_PROFIT_THRESHOLD = value


def determine_strategy(
    expected_profit: float, 
    is_auction: bool, 
    has_buy_now: bool, 
    bids_count: int = 0, 
    hours_remaining: float = None, 
    is_bundle: bool = False
) -> Tuple[str, str]:
    """
    Determine trading strategy based on profit and auction status.
    
    Returns:
        Tuple of (strategy, reason)
        Strategies: 'skip', 'buy_now', 'bid_now', 'bid', 'watch'
    """
    profit = expected_profit or 0
    hours = hours_remaining if hours_remaining is not None else 999
    bids = bids_count or 0
    
    if profit < MIN_PROFIT_THRESHOLD:
        return ("skip", f"Profit {profit:.0f} CHF below minimum ({MIN_PROFIT_THRESHOLD:.0f})")
    if has_buy_now and profit >= 80:
        return ("buy_now", f"🔥 Buy now! Profit {profit:.0f} CHF")
    if has_buy_now and profit >= 40:
        return ("buy_now", f"Buy recommended, profit {profit:.0f} CHF")
    if is_auction:
        if bids >= 15:
            return ("watch", f"⚠️ Highly contested ({bids} bids)")
        if hours < 2 and profit >= 40:
            return ("bid_now", f"🔥 Ending soon! Max {profit:.0f} CHF profit possible")
        if hours < 6 and profit >= 30:
            return ("bid", f"Bid recommended, ends in {hours:.0f}h")
        if hours < 24 and profit >= 40:
            return ("bid", f"Bid today, profit {profit:.0f} CHF")
        if profit >= 60:
            return ("watch", f"Watch, good profit ({profit:.0f} CHF)")
        return ("watch", f"Watch, {hours:.0f}h remaining")
    if profit >= 30:
        return ("watch", f"Inquire, profit {profit:.0f} CHF")
    return ("watch", f"Watch, profit {profit:.0f} CHF")


def calculate_deal_score(
    expected_profit: float, 
    purchase_price: float, 
    resale_price: Optional[float], 
    bids_count: Optional[int] = None, 
    hours_remaining: Optional[float] = None, 
    is_auction: bool = True, 
    has_variant_key: bool = True, 
    market_based_resale: bool = False, 
    is_bundle: bool = False
) -> float:
    """
    v6.8: Calculate deal score with reformed scoring.
    
    Score ranges from 0.0 to 10.0.
    Higher = better deal.
    """
    score = 5.0
    profit = expected_profit or 0
    
    # Variant classification bonus/penalty
    if not has_variant_key:
        score -= 0.5
    
    if market_based_resale:
        score += 1.0
    if is_bundle:
        score += 0.3
    
    # Margin-based scoring
    if resale_price and resale_price > 0 and purchase_price > 0:
        margin = (profit / purchase_price) * 100
        if margin > 100: score += 3.5
        elif margin > 50: score += 3.0
        elif margin > 30: score += 2.0
        elif margin > 15: score += 1.0
        elif margin > 0: score += 0.5
        elif margin > -10: score -= 0.5
        elif margin > -25: score -= 1.5
        else: score -= 2.5
    
    # Absolute profit bonus
    if profit > 500:
        score += 3.0
    elif profit > 200:
        score += 2.0
    elif profit > 100:
        score += 1.5
    elif profit > 50:
        score += 1.0
    
    # Auction timing
    if is_auction:
        hours = hours_remaining if hours_remaining is not None else 999
        bids = bids_count or 0
        
        if hours > 48: score -= 1.5
        elif hours > 24: score -= 1.0
        elif hours > 12: score -= 0.5
        elif hours < 2: score += 0.5
        
        # High bids = BONUS (not penalty!)
        if bids >= 20:
            score += 0.5
        elif bids >= 10:
            score += 0.3
    
    # Clamp score to 0-10 range
    return max(0.0, min(10.0, score))
