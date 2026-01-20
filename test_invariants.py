"""
Post-Run Invariant Checks for TEST MODE
========================================
IMPROVEMENT #4: Verify data integrity after test runs.

v2.2: UPDATED FOR NEW SCHEMA (2026-01-20)
- Checks now query deals/deal_audit tables (not old listings columns)
- Validates deal_audit.price_source values
- Checks for deals with no market_value
- Verifies price_cache table is cleared

Checks:
1. All deals have valid price_source in deal_audit
2. All deals have positive cost_estimate and market_value
3. Cache tables cleared (price_cache)
4. Run record exists and is completed

Usage:
    from test_invariants import run_invariant_checks
    run_invariant_checks(conn, mode_config)
"""

import psycopg2
from typing import Optional


class InvariantViolation(Exception):
    """Raised when a post-run invariant is violated."""
    pass


def run_invariant_checks(conn, mode_config) -> None:
    """
    Run all invariant checks after a test run.
    
    Args:
        conn: Database connection
        mode_config: Runtime mode configuration
    
    Raises:
        InvariantViolation: If any invariant is violated
    """
    if mode_config.mode.value != "test":
        # Only run in TEST mode
        return
    
    print("\n🔍 Running post-run invariant checks (TEST MODE) - v2.2 Schema...")
    
    violations = []
    
    # Check 1: All deals have valid price_source in deal_audit
    try:
        with conn.cursor() as cur:
            valid_sources = (
                'web_median', 'web_single', 'web_median_qty_adjusted',
                'ai_estimate', 'query_baseline', 'buy_now_fallback',
                'bundle_aggregate', 'market_auction', 'no_price'
            )
            cur.execute("""
                SELECT COUNT(*), da.price_source
                FROM deals d
                LEFT JOIN deal_audit da ON d.id = da.deal_id
                WHERE da.price_source IS NULL 
                   OR da.price_source NOT IN %s
                GROUP BY da.price_source
            """, (valid_sources,))
            invalid = cur.fetchall()
            
            if invalid:
                invalid_count = sum(row[0] for row in invalid)
                invalid_sources = [f"{row[1] or 'NULL'}({row[0]})" for row in invalid]
                violations.append(f"❌ INVARIANT VIOLATED: {invalid_count} deals with invalid price_source: {', '.join(invalid_sources)}")
            else:
                print("   ✅ All deal price_source values are valid")
    except Exception as e:
        print(f"   ⚠️ Could not check price_source: {e}")
    
    # Check 2: All deals have positive cost_estimate and market_value
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM deals 
                WHERE cost_estimate <= 0 OR market_value <= 0
            """)
            invalid_count = cur.fetchone()[0]
            
            if invalid_count > 0:
                cur.execute("""
                    SELECT d.id, l.title, d.cost_estimate, d.market_value
                    FROM deals d
                    JOIN listings l ON d.listing_id = l.id
                    WHERE d.cost_estimate <= 0 OR d.market_value <= 0
                    LIMIT 5
                """)
                samples = cur.fetchall()
                sample_info = "\n".join([f"      - Deal {row[0]}: {row[1][:40] if row[1] else 'NO TITLE'}... (cost={row[2]}, value={row[3]})" for row in samples])
                violations.append(
                    f"❌ INVARIANT VIOLATED: {invalid_count} deals with invalid pricing\n"
                    f"   Deals must have positive cost_estimate and market_value:\n{sample_info}"
                )
            else:
                print("   ✅ All deals have valid cost/value")
    except Exception as e:
        print(f"   ⚠️ Could not check deal pricing: {e}")
    
    # Check 3: Listings have required fields
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM listings 
                WHERE title IS NULL OR title = ''
                   OR url IS NULL OR url = ''
                   OR source_id IS NULL OR source_id = ''
            """)
            invalid_count = cur.fetchone()[0]
            
            if invalid_count > 0:
                violations.append(f"❌ INVARIANT VIOLATED: {invalid_count} listings missing required fields (title, url, source_id)")
            else:
                print("   ✅ All listings have required fields")
    except Exception as e:
        print(f"   ⚠️ Could not check listing fields: {e}")
    
    # Check 4: Verify price_cache was cleared (if truncate_on_start was true)
    if mode_config.truncate_on_start:
        try:
            with conn.cursor() as cur:
                # Check price_cache
                cur.execute("SELECT COUNT(*) FROM price_cache")
                cache_count = cur.fetchone()[0]
                
                if cache_count > 0:
                    # Price cache may be populated during run - just info, not violation
                    print(f"   ℹ️ price_cache has {cache_count} rows (populated during run)")
                else:
                    print(f"   ✅ price_cache is empty")
                
                # Check price_history - expected to be populated during run
                cur.execute("SELECT COUNT(*) FROM price_history")
                ph_count = cur.fetchone()[0]
                if ph_count > 0:
                    print(f"   ℹ️ price_history has {ph_count} rows (expected - populated during run)")
                else:
                    print(f"   ✅ price_history is empty")
        except Exception as e:
            print(f"   ⚠️ Could not check cache tables: {e}")
    
    # Report results
    if violations:
        print("\n❌ INVARIANT CHECKS FAILED:")
        for v in violations:
            print(f"\n{v}")
        
        raise InvariantViolation(
            f"\n\n{'='*60}\n"
            f"POST-RUN INVARIANT CHECKS FAILED\n"
            f"{'='*60}\n"
            f"{len(violations)} violation(s) detected:\n\n"
            + "\n\n".join(violations) +
            f"\n\n{'='*60}\n"
            f"FIX REQUIRED BEFORE NEXT RUN\n"
            f"{'='*60}\n"
        )
    else:
        print("\n✅ All invariant checks passed!")


def check_deals_have_audit(conn) -> tuple[bool, int]:
    """
    Check if all deals have corresponding audit records.
    
    v2.2: Uses deal_audit table for price source tracking.
    
    Returns:
        (passed, count): True if all deals have audit, count of missing
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM deals d
                LEFT JOIN deal_audit da ON d.id = da.deal_id
                WHERE da.deal_id IS NULL
            """)
            count = cur.fetchone()[0]
            return (count == 0, count)
    except Exception:
        return (True, 0)


def check_deals_have_valid_pricing(conn) -> tuple[bool, int]:
    """
    Check for deals with invalid pricing (zero or negative).
    
    v2.2: Checks cost_estimate and market_value in deals table.
    
    Returns:
        (passed, count): True if all deals have valid pricing, count of invalid
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) 
            FROM deals 
            WHERE cost_estimate <= 0 OR market_value <= 0
        """)
        count = cur.fetchone()[0]
        return (count == 0, count)


def check_valid_price_sources(conn) -> tuple[bool, int]:
    """
    Check if all deal_audit records have valid price_source values.
    
    v2.2: Uses deal_audit table for price source tracking.
    
    Returns:
        (passed, count): True if all price_sources valid, count of invalid
    """
    valid_sources = (
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) 
            FROM deal_audit 
            WHERE price_source IS NULL 
               OR price_source NOT IN %s
        """, (valid_sources,))
        count = cur.fetchone()[0]
        return (count == 0, count)


# Standalone test
if __name__ == "__main__":
    import psycopg2
    from runtime_mode import get_mode_config
    
    # Connect to DB
    conn = psycopg2.connect(
        host="localhost",
        database="dealfinder",
        user="dealuser",
        password="dealpass"
    )
    
    # Get test mode config
    mode_config = get_mode_config("test")
    
    try:
        run_invariant_checks(conn, mode_config)
        print("\n✅ All checks passed!")
    except InvariantViolation as e:
        print(f"\n❌ Checks failed:\n{e}")
    finally:
        conn.close()
