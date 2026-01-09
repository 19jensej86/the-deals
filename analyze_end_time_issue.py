"""
Quick analysis script to check which listings have missing end_time incorrectly.
"""
import json

with open("last_run_listings.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 80)
print("ANALYZING end_time ISSUES")
print("=" * 80)

buy_now_only = []
auctions_with_end_time = []
auctions_missing_end_time = []

for listing in data:
    current_price = listing.get("current_price_ricardo")
    buy_now = listing.get("buy_now_price")
    end_time = listing.get("end_time")
    hours = listing.get("hours_remaining")
    
    # Buy-Now-Only (no auction)
    if current_price is None and buy_now is not None:
        buy_now_only.append({
            "id": listing["id"],
            "title": listing["title"][:50],
            "end_time": end_time,
            "hours": hours
        })
    # Auction (with or without buy_now option)
    elif current_price is not None:
        if end_time:
            auctions_with_end_time.append({
                "id": listing["id"],
                "title": listing["title"][:50],
                "end_time": end_time,
                "hours": hours
            })
        else:
            auctions_missing_end_time.append({
                "id": listing["id"],
                "title": listing["title"][:50],
                "current_price": current_price,
                "bids": listing.get("bids_count"),
                "hours": hours
            })

print(f"\n📊 SUMMARY:")
print(f"Buy-Now-Only listings: {len(buy_now_only)}")
print(f"Auctions WITH end_time: {len(auctions_with_end_time)}")
print(f"Auctions MISSING end_time: {len(auctions_missing_end_time)} ⚠️")

print(f"\n✅ Buy-Now-Only (end_time=NULL is OK):")
for item in buy_now_only[:5]:
    print(f"  ID {item['id']}: {item['title']} (hours={item['hours']})")

if auctions_with_end_time:
    print(f"\n✅ Auctions WITH end_time:")
    for item in auctions_with_end_time[:5]:
        print(f"  ID {item['id']}: {item['title']} (end_time={item['end_time']}, hours={item['hours']})")

if auctions_missing_end_time:
    print(f"\n❌ Auctions MISSING end_time (THIS IS THE BUG!):")
    for item in auctions_missing_end_time:
        print(f"  ID {item['id']}: {item['title']}")
        print(f"    current_price={item['current_price']}, bids={item['bids']}, hours={item['hours']}")

print(f"\n" + "=" * 80)
print(f"CONCLUSION:")
if auctions_missing_end_time:
    print(f"❌ {len(auctions_missing_end_time)} auctions are missing end_time!")
    print(f"   These should have end_time extracted by the scraper.")
else:
    print(f"✅ All auctions have end_time. Only Buy-Now-Only listings have NULL.")
print("=" * 80)
