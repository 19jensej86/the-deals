"""
DealFinder Run Analyzer - v7.2
================================
Analyzes last_run.log and last_run_listings.json to provide:
- Data quality assessment
- Realism checks
- Performance metrics
- Improvement suggestions

Usage:
    python analyze_run.py
"""

import json
import re
from typing import Dict, List, Any, Tuple
from datetime import datetime


def load_log(filename: str = "last_run.log") -> str:
    """Load log file."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {filename}")
        print("   Run the pipeline first to generate the log file.")
        return ""
    except Exception as e:
        print(f"❌ Error reading log: {e}")
        return ""


def load_listings(filename: str = "last_run_listings.json") -> Dict[str, Any]:
    """Load listings JSON file."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {filename}")
        print("   Run the pipeline first to generate the listings file.")
        return {'listings': []}
    except Exception as e:
        print(f"❌ Error reading listings: {e}")
        return {'listings': []}


def analyze_log(log_text: str) -> Dict[str, Any]:
    """Extract key metrics from log."""
    analysis = {
        'filter_stats': {},
        'ai_costs': {},
        'errors': [],
        'warnings': [],
        'queries_processed': 0,
        'total_listings': 0
    }
    
    # Filter statistics (v7.2)
    stats_match = re.search(
        r'📊 Total scraped:\s+(\d+).*?'
        r'🎯 Hardcoded accessory filter:\s+(\d+).*?'
        r'🤖 AI accessory filter:\s+(\d+).*?'
        r'🔧 Defect filter:\s+(\d+).*?'
        r'⚪ Exclude terms filter:\s+(\d+).*?'
        r'🧠 Sent to AI evaluation:\s+(\d+)',
        log_text,
        re.DOTALL
    )
    
    if stats_match:
        total = int(stats_match.group(1))
        hardcoded = int(stats_match.group(2))
        ai_acc = int(stats_match.group(3))
        defect = int(stats_match.group(4))
        exclude = int(stats_match.group(5))
        sent_ai = int(stats_match.group(6))
        
        total_filtered = hardcoded + ai_acc + defect + exclude
        efficiency = (total_filtered / total * 100) if total > 0 else 0
        
        analysis['filter_stats'] = {
            'total_scraped': total,
            'hardcoded_accessory': hardcoded,
            'ai_accessory': ai_acc,
            'defect': defect,
            'exclude_terms': exclude,
            'sent_to_ai': sent_ai,
            'total_filtered': total_filtered,
            'efficiency_pct': efficiency
        }
    
    # AI costs
    run_cost_match = re.search(r'💰 This run:\s+\$?([\d.]+)', log_text)
    day_cost_match = re.search(r'📊 Today total:\s+\$?([\d.]+)', log_text)
    
    if run_cost_match:
        analysis['ai_costs']['run_cost'] = float(run_cost_match.group(1))
    if day_cost_match:
        analysis['ai_costs']['day_total'] = float(day_cost_match.group(1))
    
    # Errors and warnings
    analysis['errors'] = re.findall(r'❌.*?(?:\n|$)', log_text)
    analysis['warnings'] = re.findall(r'⚠️.*?(?:\n|$)', log_text)
    
    # Query count
    analysis['queries_processed'] = len(re.findall(r'=== Search:', log_text))
    
    return analysis


def analyze_listings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze listings data quality."""
    listings = data.get('listings', [])
    
    if not listings:
        return {'error': 'No listings found'}
    
    analysis = {
        'total': len(listings),
        'with_profit': 0,
        'high_score': 0,
        'market_based': 0,
        'missing_new_price': 0,
        'unrealistic_resale': [],
        'unrealistic_profit': [],
        'suspicious_deals': [],
        'top_deals': [],
        'price_sources': {},
        'strategies': {},
        'avg_profit': 0,
        'avg_score': 0,
        'data_quality_score': 0
    }
    
    total_profit = 0
    total_score = 0
    
    for listing in listings:
        profit = listing.get('expected_profit') or 0
        score = listing.get('deal_score') or 0
        new_price = listing.get('new_price')
        resale = listing.get('resale_price_est')
        
        # Count metrics
        if profit > 0:
            analysis['with_profit'] += 1
            total_profit += profit
        
        if score >= 7:
            analysis['high_score'] += 1
        
        if listing.get('market_based_resale'):
            analysis['market_based'] += 1
        
        if not new_price:
            analysis['missing_new_price'] += 1
        
        total_score += score
        
        # Price source distribution
        source = listing.get('price_source', 'unknown')
        analysis['price_sources'][source] = analysis['price_sources'].get(source, 0) + 1
        
        # Strategy distribution
        strategy = listing.get('recommended_strategy', 'unknown')
        analysis['strategies'][strategy] = analysis['strategies'].get(strategy, 0) + 1
        
        # Realism checks
        if new_price and resale:
            if resale > new_price * 1.3:
                analysis['unrealistic_resale'].append({
                    'title': listing.get('title', '')[:60],
                    'new_price': new_price,
                    'resale': resale,
                    'ratio': resale / new_price
                })
            
            if profit > new_price * 0.6:
                analysis['unrealistic_profit'].append({
                    'title': listing.get('title', '')[:60],
                    'new_price': new_price,
                    'profit': profit,
                    'ratio': profit / new_price
                })
        
        # Suspicious high deals
        if profit > 200 and score > 8:
            analysis['suspicious_deals'].append({
                'title': listing.get('title', '')[:60],
                'profit': profit,
                'score': score,
                'new_price': new_price,
                'resale': resale,
                'market_based': listing.get('market_based_resale', False)
            })
    
    # Top 10 deals
    sorted_listings = sorted(listings, key=lambda x: x.get('expected_profit') or 0, reverse=True)
    analysis['top_deals'] = [
        {
            'title': l.get('title', '')[:60],
            'profit': l.get('expected_profit'),
            'score': l.get('deal_score'),
            'current': l.get('current_price_ricardo'),
            'buy_now': l.get('buy_now_price'),
            'new_price': l.get('new_price'),
            'resale': l.get('resale_price_est'),
            'strategy': l.get('recommended_strategy'),
            'market_based': l.get('market_based_resale', False)
        }
        for l in sorted_listings[:10]
    ]
    
    # Averages
    if analysis['with_profit'] > 0:
        analysis['avg_profit'] = total_profit / analysis['with_profit']
    if analysis['total'] > 0:
        analysis['avg_score'] = total_score / analysis['total']
    
    # Data quality score (0-100)
    quality_score = 100
    
    # Deduct for missing data
    if analysis['missing_new_price'] > 0:
        missing_pct = (analysis['missing_new_price'] / analysis['total']) * 100
        quality_score -= min(missing_pct, 30)  # Max -30 points
    
    # Deduct for unrealistic data
    unrealistic_count = len(analysis['unrealistic_resale']) + len(analysis['unrealistic_profit'])
    if unrealistic_count > 0:
        unrealistic_pct = (unrealistic_count / analysis['total']) * 100
        quality_score -= min(unrealistic_pct * 2, 40)  # Max -40 points
    
    analysis['data_quality_score'] = max(0, quality_score)
    
    return analysis


def print_report(log_analysis: Dict[str, Any], listings_analysis: Dict[str, Any]):
    """Print comprehensive analysis report."""
    print("\n" + "=" * 90)
    print("📊 DEALFINDER RUN ANALYSIS - v7.2")
    print("=" * 90)
    
    # Filter Statistics
    if log_analysis.get('filter_stats'):
        stats = log_analysis['filter_stats']
        print("\n🎯 FILTER PERFORMANCE (v7.2)")
        print("-" * 90)
        print(f"Total scraped:              {stats['total_scraped']}")
        print(f"🎯 Hardcoded accessory:     {stats['hardcoded_accessory']}")
        print(f"🤖 AI accessory:            {stats['ai_accessory']}")
        print(f"🔧 Defect:                  {stats['defect']}")
        print(f"⚪ Exclude terms:           {stats['exclude_terms']}")
        print(f"🧠 Sent to AI:              {stats['sent_to_ai']}")
        print(f"\n💰 Filter efficiency:       {stats['efficiency_pct']:.1f}% filtered")
        
        if stats['efficiency_pct'] > 60:
            print("   ✅ EXCELLENT - Saves significant AI costs!")
        elif stats['efficiency_pct'] > 40:
            print("   ⚠️ OK - Could be improved")
        else:
            print("   ❌ LOW - Consider adding more filters")
    
    # AI Costs
    if log_analysis.get('ai_costs'):
        costs = log_analysis['ai_costs']
        print("\n💵 AI COSTS")
        print("-" * 90)
        print(f"This run:    ${costs.get('run_cost', 0):.4f} USD")
        print(f"Today total: ${costs.get('day_total', 0):.4f} USD")
        
        if costs.get('run_cost', 0) < 0.30:
            print("   ✅ Very cost-efficient!")
        elif costs.get('run_cost', 0) < 0.60:
            print("   ⚠️ Moderate costs")
        else:
            print("   ❌ High costs - check filter efficiency")
    
    # Listings Overview
    if 'error' not in listings_analysis:
        print("\n📦 LISTINGS OVERVIEW")
        print("-" * 90)
        print(f"Total listings:             {listings_analysis['total']}")
        print(f"With profit:                {listings_analysis['with_profit']}")
        print(f"High score (≥7):            {listings_analysis['high_score']}")
        print(f"Market-based pricing:       {listings_analysis['market_based']}")
        print(f"Missing new_price:          {listings_analysis['missing_new_price']}")
        print(f"\nAverage profit:             {listings_analysis['avg_profit']:.2f} CHF")
        print(f"Average deal score:         {listings_analysis['avg_score']:.2f}")
    
    # Data Quality
    if 'data_quality_score' in listings_analysis:
        print("\n🏆 DATA QUALITY SCORE")
        print("-" * 90)
        score = listings_analysis['data_quality_score']
        print(f"Overall quality: {score:.1f}/100")
        
        if score >= 80:
            print("✅ EXCELLENT - Data is realistic and complete")
        elif score >= 60:
            print("⚠️ GOOD - Minor issues, mostly usable")
        elif score >= 40:
            print("⚠️ FAIR - Some data quality issues")
        else:
            print("❌ POOR - Significant data quality problems")
    
    # Top Deals
    if listings_analysis.get('top_deals'):
        print("\n🔥 TOP 10 DEALS")
        print("-" * 90)
        for i, deal in enumerate(listings_analysis['top_deals'][:10], 1):
            market_icon = "📈" if deal['market_based'] else "🤖"
            print(f"\n{i}. {deal['title']}")
            print(f"   Profit: {deal['profit']:.0f} CHF | Score: {deal['score']:.1f} | {market_icon} {deal['strategy']}")
            print(f"   Current: {deal['current'] or 'N/A'} | Buy-now: {deal['buy_now'] or 'N/A'}")
            print(f"   New: {deal['new_price']:.0f} → Resale: {deal['resale']:.0f}")
    
    # Unrealistic Data
    if listings_analysis.get('unrealistic_resale'):
        print("\n⚠️ UNREALISTIC RESALE PRICES (Resale > 130% of new)")
        print("-" * 90)
        for item in listings_analysis['unrealistic_resale'][:5]:
            print(f"• {item['title']}")
            print(f"  New: {item['new_price']:.0f} → Resale: {item['resale']:.0f} ({item['ratio']*100:.0f}%)")
    
    if listings_analysis.get('unrealistic_profit'):
        print("\n⚠️ UNREALISTIC PROFITS (Profit > 60% of new price)")
        print("-" * 90)
        for item in listings_analysis['unrealistic_profit'][:5]:
            print(f"• {item['title']}")
            print(f"  New: {item['new_price']:.0f} → Profit: {item['profit']:.0f} ({item['ratio']*100:.0f}%)")
    
    # Suspicious Deals
    if listings_analysis.get('suspicious_deals'):
        print("\n🔍 SUSPICIOUS HIGH-PROFIT DEALS (Manual Review Recommended)")
        print("-" * 90)
        for deal in listings_analysis['suspicious_deals'][:5]:
            market_text = "Market data" if deal['market_based'] else "AI estimate"
            print(f"• {deal['title']}")
            print(f"  Profit: {deal['profit']:.0f} CHF | Score: {deal['score']:.1f} | {market_text}")
    
    # Errors & Warnings
    if log_analysis.get('errors'):
        print("\n❌ ERRORS DETECTED")
        print("-" * 90)
        for error in log_analysis['errors'][:5]:
            print(f"  {error.strip()}")
    
    if log_analysis.get('warnings'):
        print("\n⚠️ WARNINGS")
        print("-" * 90)
        for warning in log_analysis['warnings'][:5]:
            print(f"  {warning.strip()}")
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("-" * 90)
    
    recommendations = []
    
    # Filter efficiency
    if log_analysis.get('filter_stats', {}).get('efficiency_pct', 0) < 50:
        recommendations.append("• Improve filter efficiency - add more accessory/defect keywords")
    
    # Missing data
    if listings_analysis.get('missing_new_price', 0) > listings_analysis.get('total', 1) * 0.2:
        recommendations.append("• >20% missing new_price - improve web search or add fallback sources")
    
    # Unrealistic data
    if len(listings_analysis.get('unrealistic_resale', [])) > 3:
        recommendations.append("• Multiple unrealistic resale prices - review AI prompts or market data")
    
    # Low market data usage
    market_pct = (listings_analysis.get('market_based', 0) / listings_analysis.get('total', 1)) * 100
    if market_pct < 30:
        recommendations.append(f"• Only {market_pct:.0f}% using market data - need more auction data")
    
    # AI costs
    if log_analysis.get('ai_costs', {}).get('run_cost', 0) > 0.50:
        recommendations.append("• High AI costs - increase filter efficiency or reduce listings per query")
    
    # Suspicious deals
    if len(listings_analysis.get('suspicious_deals', [])) > 5:
        recommendations.append("• Many suspicious high-profit deals - verify data quality manually")
    
    if recommendations:
        for rec in recommendations:
            print(rec)
    else:
        print("✅ No major issues detected - system is working well!")
    
    print("\n" + "=" * 90)


def main():
    """Main entry point."""
    print("🔍 Loading run data...")
    
    log_text = load_log("last_run.log")
    listings_data = load_listings("last_run_listings.json")
    
    if not log_text or not listings_data.get('listings'):
        print("\n❌ Cannot analyze - missing data files")
        print("   Run the pipeline first: python main.py")
        return
    
    print("📊 Analyzing log...")
    log_analysis = analyze_log(log_text)
    
    print("📊 Analyzing listings...")
    listings_analysis = analyze_listings(listings_data)
    
    print_report(log_analysis, listings_analysis)


if __name__ == "__main__":
    main()
