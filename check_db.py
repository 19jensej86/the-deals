"""Quick DB check script to verify data quality after run."""
import psycopg2

conn = psycopg2.connect(
    dbname='dealfinder',
    user='dealuser',
    password='dealpass',
    host='localhost'
)
cur = conn.cursor()

print("=" * 60)
print("DATABASE CHECK - Run e27ee4bf")
print("=" * 60)

# Check deals
cur.execute("""
    SELECT 
        COUNT(*) as total,
        COUNT(*) FILTER (WHERE profit_chf > 10) as profitable,
        COUNT(*) FILTER (WHERE profit_chf > 50) as very_profitable,
        ROUND(AVG(profit_chf)::numeric, 2) as avg_profit,
        ROUND(MAX(profit_chf)::numeric, 2) as max_profit
    FROM deals;
""")
total, profitable, very_profitable, avg_profit, max_profit = cur.fetchone()
print(f"\n📊 DEALS:")
print(f"   Total:            {total}")
print(f"   Profitable (>10): {profitable}")
print(f"   Very Good (>50):  {very_profitable}")
print(f"   Avg Profit:       {avg_profit} CHF")
print(f"   Max Profit:       {max_profit} CHF")

# Check bundles
cur.execute("SELECT COUNT(*) FROM bundles;")
bundle_count = cur.fetchone()[0]
print(f"\n📦 BUNDLES:")
print(f"   Total:            {bundle_count}")

# Check products
cur.execute("""
    SELECT 
        COUNT(*) as total,
        COUNT(DISTINCT brand) as brands,
        COUNT(DISTINCT model) as models
    FROM products;
""")
prod_total, brands, models = cur.fetchone()
print(f"\n🏷️ PRODUCTS:")
print(f"   Total:            {prod_total}")
print(f"   Unique Brands:    {brands}")
print(f"   Unique Models:    {models}")

# Top 5 deals
print(f"\n🔥 TOP 5 DEALS:")
cur.execute("""
    SELECT 
        title,
        profit_chf,
        deal_score,
        price_source
    FROM deals
    ORDER BY profit_chf DESC
    LIMIT 5;
""")
for i, (title, profit, score, source) in enumerate(cur.fetchall(), 1):
    print(f"   {i}. {title[:50]}...")
    print(f"      Profit: {profit:.2f} CHF | Score: {score}/10 | Source: {source}")

# Check price sources
print(f"\n💰 PRICE SOURCES:")
cur.execute("""
    SELECT 
        price_source,
        COUNT(*) as count
    FROM deals
    GROUP BY price_source
    ORDER BY count DESC;
""")
for source, count in cur.fetchall():
    print(f"   {source}: {count}")

# Check data quality issues
print(f"\n⚠️ DATA QUALITY:")
cur.execute("SELECT COUNT(*) FROM deals WHERE new_price_chf IS NULL;")
null_prices = cur.fetchone()[0]
print(f"   Missing new_price: {null_prices}")

cur.execute("SELECT COUNT(*) FROM deals WHERE resale_price_chf IS NULL;")
null_resale = cur.fetchone()[0]
print(f"   Missing resale:    {null_resale}")

cur.execute("SELECT COUNT(*) FROM deals WHERE profit_chf < 0;")
negative = cur.fetchone()[0]
print(f"   Negative profit:   {negative}")

print("\n" + "=" * 60)

conn.close()
