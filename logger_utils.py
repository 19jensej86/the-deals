"""
Enhanced Logging Utilities for DealFinder Pipeline
===================================================
Provides structured, user-friendly logging with:
- Step-based workflow tracking
- AI transparency (cost visibility)
- Non-technical explanations
- Verification-aware logging
"""

from typing import Optional, Dict, Any
from datetime import datetime


# ==============================================================================
# STEP-BASED LOGGING
# ==============================================================================

class StepLogger:
    """
    Structured logger for pipeline steps.
    Ensures consistent, readable, and informative logs.
    """
    
    def __init__(self):
        self.current_step = None
        self.step_start_time = None
        self.ai_steps = []  # Track which steps used AI
        self.cost_steps = []  # Track cost-relevant operations
    
    def step_start(
        self,
        step_name: str,
        what: str,
        why: str,
        uses_ai: bool = False,
        uses_web_search: bool = False,
        uses_db: bool = False,
        uses_rules: bool = False,
    ):
        """
        Start a new pipeline step with clear explanation.
        
        Args:
            step_name: Short identifier (e.g. "SCRAPING", "AI_NORMALIZATION")
            what: What is happening (user-friendly)
            why: Why this step exists (business reason)
            uses_ai: Whether this step uses LLM (cost-relevant)
            uses_web_search: Whether web search is used
            uses_db: Whether database is accessed
            uses_rules: Whether rule-based logic is used
        """
        self.current_step = step_name
        self.step_start_time = datetime.now()
        
        print("\n" + "=" * 90)
        print(f"📍 STEP: {step_name}")
        print("=" * 90)
        print(f"\n💡 What: {what}")
        print(f"❓ Why:  {why}")
        
        # Technology used
        tech = []
        if uses_ai:
            tech.append("🤖 AI (LLM) - COST-RELEVANT")
            self.ai_steps.append(step_name)
        if uses_web_search:
            tech.append("🌐 Web Search - COST-RELEVANT")
            self.cost_steps.append(f"{step_name} (Web Search)")
        if uses_db:
            tech.append("💾 Database")
        if uses_rules:
            tech.append("📏 Rule-based (Regex/Heuristics) - NO COST")
        
        if tech:
            print(f"\n🔧 Technology: {', '.join(tech)}")
        
        # Cost warning
        if uses_ai or uses_web_search:
            print(f"\n💰 COST IMPACT: This step uses AI and causes API costs.")
        else:
            print(f"\n✅ NO COST: This step does NOT use AI.")
        
        print()  # Blank line before step content
    
    def step_decision(self, decision: str, reason: str):
        """Log a decision made during the step."""
        print(f"🔀 Decision: {decision}")
        print(f"   Reason: {reason}")
    
    def step_logic(self, logic: str):
        """Explain the logic being applied."""
        print(f"⚙️  Logic: {logic}")
    
    def step_ai_details(
        self,
        ai_purpose: str,
        input_summary: str,
        expected_output: str,
        fallback: str,
    ):
        """
        Provide detailed AI transparency.
        
        Args:
            ai_purpose: Why AI is used instead of rules
            input_summary: What data is sent to AI (high-level)
            expected_output: What we expect back
            fallback: How failures are handled
        """
        print(f"\n🤖 AI TRANSPARENCY:")
        print(f"   Purpose: {ai_purpose}")
        print(f"   Input:   {input_summary}")
        print(f"   Output:  {expected_output}")
        print(f"   Fallback: {fallback}")
    
    def step_progress(self, message: str):
        """Log progress within a step."""
        print(f"   ⏳ {message}")
    
    def step_success(self, message: str, count: Optional[int] = None):
        """Log successful operation."""
        if count is not None:
            print(f"   ✅ {message} ({count})")
        else:
            print(f"   ✅ {message}")
    
    def step_warning(self, message: str):
        """Log warning (non-critical issue)."""
        print(f"   ⚠️  {message}")
    
    def step_error(self, message: str):
        """Log error (critical issue)."""
        print(f"   ❌ {message}")
    
    def step_result(
        self,
        summary: str,
        quality_metrics: Optional[Dict[str, Any]] = None,
    ):
        """
        Log the result of the step.
        
        Args:
            summary: High-level summary of what was produced
            quality_metrics: Optional metrics (success rate, counts, etc.)
        """
        print(f"\n📊 Result: {summary}")
        
        if quality_metrics:
            for key, value in quality_metrics.items():
                print(f"   • {key}: {value}")
    
    def step_end(self, outcome: str):
        """
        End the current step.
        
        Args:
            outcome: Short summary of the outcome
        """
        if self.step_start_time:
            duration = (datetime.now() - self.step_start_time).total_seconds()
            print(f"\n⏱️  Duration: {duration:.1f}s")
        
        print(f"✓ Outcome: {outcome}")
        print("=" * 90)
        
        self.current_step = None
        self.step_start_time = None
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """Return summary of cost-relevant steps."""
        return {
            "ai_steps": self.ai_steps,
            "cost_steps": self.cost_steps,
            "total_ai_steps": len(self.ai_steps),
        }


# ==============================================================================
# CONVENIENCE FUNCTIONS
# ==============================================================================

def log_explanation(text: str):
    """
    Log a user-friendly explanation.
    Use simple language to explain complex logic.
    """
    print(f"\n💬 Explanation:")
    # Wrap text at 80 chars
    words = text.split()
    line = "   "
    for word in words:
        if len(line) + len(word) + 1 > 80:
            print(line)
            line = "   " + word
        else:
            line += " " + word if line != "   " else word
    if line.strip():
        print(line)


def log_verification(
    claim: str,
    verified: bool,
    evidence: Optional[str] = None,
):
    """
    Log verification of a claim.
    Never claim success without verification.
    
    Args:
        claim: What is being claimed (e.g. "Detail page scraped")
        verified: Whether the claim is verified
        evidence: Optional evidence (e.g. "location field populated")
    """
    if verified:
        print(f"✓ VERIFIED: {claim}")
        if evidence:
            print(f"   Evidence: {evidence}")
    else:
        print(f"✗ NOT VERIFIED: {claim}")
        if evidence:
            print(f"   Issue: {evidence}")


def log_cost_summary(
    ai_calls: int,
    web_searches: int,
    total_cost_usd: float,
    breakdown: Optional[Dict[str, float]] = None,
):
    """
    Log final cost summary at end of job.
    
    Args:
        ai_calls: Total number of AI API calls
        web_searches: Total number of web searches
        total_cost_usd: Total cost in USD
        breakdown: Optional cost breakdown by step
    """
    print("\n" + "=" * 90)
    print("💰 COST SUMMARY")
    print("=" * 90)
    
    print(f"\n📊 API Usage:")
    print(f"   • AI Calls:      {ai_calls}")
    print(f"   • Web Searches:  {web_searches}")
    print(f"   • Total Cost:    ${total_cost_usd:.4f} USD")
    
    if breakdown:
        print(f"\n📈 Cost Breakdown:")
        for step, cost in breakdown.items():
            print(f"   • {step}: ${cost:.4f}")
    
    print(f"\n✅ Steps that used AI (cost-relevant):")
    print(f"   • Query Analysis")
    print(f"   • Title Normalization")
    print(f"   • Web Price Search")
    print(f"   • Deal Evaluation")
    
    print(f"\n✅ Steps that did NOT use AI (free):")
    print(f"   • Scraping (Playwright)")
    print(f"   • Regex-based filtering")
    print(f"   • Database operations")
    print(f"   • Detail page scraping")
    
    print("=" * 90)


# ==============================================================================
# GLOBAL LOGGER INSTANCE
# ==============================================================================

_logger = StepLogger()


def get_logger() -> StepLogger:
    """Get the global step logger instance."""
    return _logger
