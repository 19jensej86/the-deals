# 🏗️ REFACTORING PLAN v9: Methodische Umsetzung

**Autor:** AI Senior Architect  
**Datum:** 2026-01-11  
**Prinzip:** Keine Überraschungen, schrittweise Validierung, Rückwärtskompatibilität

---

## 📋 AKTUELLE ARCHITEKTUR (v7.x)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ MAIN.PY FLOW                                                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. load_config()                                                       │
│  2. analyze_queries() → query_analyses{}                               │
│                                                                         │
│  3. FOR EACH query IN queries:                                          │
│     │                                                                   │
│     ├─ 4. search_ricardo(query) → all_listings[]                       │
│     │                                                                   │
│     ├─ 5. PRE-FILTERS (accessory, defect, exclude)                     │
│     │                                                                   │
│     ├─ 6. cluster_variants_from_titles(all_titles)                     │
│     │      └─► variant_key = EXACT TITLE (!)                           │
│     │                                                                   │
│     ├─ 7. calculate_all_market_resale_prices()                         │
│     │      └─► Sucht andere Listings mit GLEICHEM variant_key          │
│     │                                                                   │
│     ├─ 8. fetch_variant_info_batch(variant_keys)                       │
│     │      ├─► Check cache                                              │
│     │      ├─► search_web_batch_for_new_prices()                       │
│     │      │    └─► clean_search_term() für bessere Queries            │
│     │      └─► AI fallback                                              │
│     │                                                                   │
│     ├─ 9. FOR EACH listing:                                             │
│     │      └─► evaluate_listing_with_ai()                              │
│     │                                                                   │
│     └─ 10. upsert_listing() → DB                                       │
│                                                                         │
│  11. save_day_cost()                                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Aktuelle Schwachstellen

| Problem | Auswirkung | Wo im Code |
|---------|------------|------------|
| variant_key = exact title | Keine Gruppierung, viele Websearches | `cluster_variants_from_titles()` |
| clean_search_term() zu einfach | Suboptimale Websearch-Queries | `query_analyzer.py` |
| Market resale findet wenig Matches | Oft Fallback auf AI Estimate | `calculate_market_resale_from_listings()` |
| Websearch pro Query | Duplikate über Queries nicht erkannt | `main.py` Loop |

---

## 🎯 ZIEL-ARCHITEKTUR (v9)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ MAIN.PY FLOW (v9)                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  PHASE 1: DATEN SAMMELN                                                 │
│  ═══════════════════════                                                │
│  1. load_config()                                                       │
│  2. analyze_queries() → query_analyses{}                               │
│                                                                         │
│  3. all_listings_by_query = {}                                          │
│     FOR EACH query IN queries:                                          │
│     │                                                                   │
│     ├─ search_ricardo(query) → listings[]                              │
│     ├─ PRE-FILTERS (accessory, defect, exclude)                        │
│     └─ all_listings_by_query[query] = listings                         │
│                                                                         │
│  PHASE 2: PRODUKT-EXTRAKTION (NEU!)                                     │
│  ═══════════════════════════════════                                    │
│  4. all_listing_products = []                                           │
│     FOR EACH query, listings IN all_listings_by_query:                  │
│     │                                                                   │
│     ├─ process_query_listings(query, listings, category)               │
│     │    ├─ clean_title_for_search() für jeden Titel                   │
│     │    ├─ is_bundle_title() → decompose wenn Bundle                  │
│     │    └─ → ListingProducts[] (listing_id → products[])              │
│     │                                                                   │
│     └─ all_listing_products.extend(results)                            │
│                                                                         │
│  5. global_products = build_global_product_list(all_listing_products)   │
│     └─► Dedupliziert! 24 Listings → 18 unique Products                 │
│                                                                         │
│  PHASE 3: PREISSUCHE (OPTIMIERT!)                                       │
│  ═════════════════════════════════                                      │
│  6. product_prices = {}                                                 │
│     │                                                                   │
│     ├─ 6a. MARKET RESALE (Priorität 1)                                 │
│     │      calculate_market_resale_for_products(global_products,        │
│     │                                           all_listings_by_query)  │
│     │      └─► Sucht konkurrierende Listings für jedes Produkt         │
│     │                                                                   │
│     ├─ 6b. WEB SEARCH (Priorität 2)                                    │
│     │      products_needing_newprice = [p for p if no market data]     │
│     │      search_web_batch_for_new_prices(products_needing_newprice)  │
│     │      └─► EIN Batch für alle! (nicht pro Query)                   │
│     │                                                                   │
│     └─ 6c. AI FALLBACK (Priorität 3)                                   │
│            Für Produkte ohne Web-Ergebnis                               │
│                                                                         │
│  PHASE 4: BEWERTUNG                                                     │
│  ══════════════════                                                     │
│  7. FOR EACH query, listings IN all_listings_by_query:                  │
│        FOR EACH listing IN listings:                                    │
│        │                                                                │
│        ├─ listing_products = get_products_for_listing(listing_id)      │
│        ├─ total_new = sum(p.new_price * p.quantity)                    │
│        ├─ total_resale = sum(p.resale_price * p.quantity)              │
│        ├─ evaluate_listing(listing, total_new, total_resale)           │
│        └─ upsert_listing() → DB                                        │
│                                                                         │
│  8. save_day_cost()                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 ÄNDERUNGEN IM DETAIL

### ÄNDERUNG 1: Neues Modul `product_extractor.py` (bereits erstellt)

**Status:** ✅ Bereits implementiert

**Funktionen:**
- `clean_title_for_search(title, query, category)` - Bessere Titel-Bereinigung
- `is_bundle_title(title)` - Regelbasierte Bundle-Erkennung
- `decompose_bundle_universal(...)` - Bundle-Zerlegung für alle Kategorien
- `process_query_listings(...)` - Hauptfunktion pro Query
- `build_global_product_list(...)` - Globale Deduplication

**Risiko:** NIEDRIG - Neues Modul, beeinflusst bestehenden Code nicht.

---

### ÄNDERUNG 2: `main.py` - Zwei-Phasen-Verarbeitung

**Aktuell:**
```python
for query in queries:
    listings = search_ricardo(query)
    # ... filter ...
    cluster_result = cluster_variants_from_titles(titles)
    market_prices = calculate_all_market_resale_prices(listings, ...)
    variant_info = fetch_variant_info_batch(variant_keys, ...)
    for listing in listings:
        evaluate_listing_with_ai(...)
```

**Neu:**
```python
# PHASE 1: Sammeln
all_listings_by_query = {}
for query in queries:
    listings = search_ricardo(query)
    # ... filter ...
    all_listings_by_query[query] = listings

# PHASE 2: Produkt-Extraktion
from product_extractor import process_query_listings, build_global_product_list

all_listing_products = []
for query, listings in all_listings_by_query.items():
    category = detect_category(query)
    listing_products = process_query_listings(query, listings, category)
    all_listing_products.extend(listing_products)

global_products = build_global_product_list(all_listing_products)

# PHASE 3: Preissuche (EINMAL für alle!)
product_prices = fetch_prices_for_products(global_products, all_listings_by_query)

# PHASE 4: Bewertung
for query, listings in all_listings_by_query.items():
    for listing in listings:
        # Preise aus product_prices nachschlagen
        evaluate_listing(listing, product_prices, ...)
```

**Risiko:** MITTEL - Strukturänderung, aber Logik bleibt.

---

### ÄNDERUNG 3: Market Resale mit normalisierten Produkten

**Aktuell:** Sucht nach variant_key = exact title  
**Neu:** Sucht nach product_key = normalisierter Produktname

```python
# ALT
def calculate_market_resale_from_listings(variant_key, listings, ...):
    for listing in listings:
        if listing.get("variant_key") != variant_key:  # EXACT MATCH
            continue
        # ...

# NEU
def calculate_market_resale_for_product(product_key, all_listings, product_mapping):
    """
    Findet alle Listings die dieses Produkt enthalten.
    
    product_mapping = {listing_id: [product_keys]}
    """
    matching_listings = []
    for listing in all_listings:
        listing_id = listing.get("listing_id")
        if product_key in product_mapping.get(listing_id, []):
            matching_listings.append(listing)
    
    # Gleiche Logik wie vorher, aber mit mehr Matches!
    return calculate_market_resale_from_listings(product_key, matching_listings, ...)
```

**Risiko:** NIEDRIG - Bestehende Funktion wird wiederverwendet.

---

### ÄNDERUNG 4: Websearch mit Global Product List

**Aktuell:** `fetch_variant_info_batch(variant_keys)` pro Query  
**Neu:** `fetch_prices_for_products(global_products)` EINMAL

```python
def fetch_prices_for_products(
    global_products: Dict[str, Product],
    all_listings_by_query: Dict[str, List[Dict]],
) -> Dict[str, Dict[str, Any]]:
    """
    Holt Preise für alle Produkte.
    
    Priorität:
    1. Market-Based (Ricardo Konkurrenz)
    2. Web Search (Digitec, Galaxus, etc.)
    3. AI Fallback
    """
    product_prices = {}
    
    # 1. Market-Based für alle Produkte
    all_listings = [l for listings in all_listings_by_query.values() for l in listings]
    for product_key, product in global_products.items():
        market_data = calculate_market_resale_for_product(
            product_key, all_listings, product.source_listings
        )
        if market_data:
            product_prices[product_key] = market_data
    
    # 2. Web Search für Produkte ohne Market-Data
    need_websearch = [
        product.display_name 
        for pk, product in global_products.items() 
        if pk not in product_prices
    ]
    
    if need_websearch:
        web_results = search_web_batch_for_new_prices(need_websearch, ...)
        # ... merge results ...
    
    return product_prices
```

**Risiko:** MITTEL - Neue Funktion, aber nutzt bestehende Logik.

---

## 📊 RISIKOANALYSE

### Niedrig-Risiko Änderungen
1. ✅ `product_extractor.py` hinzufügen (bereits done)
2. ⬜ Import in `main.py` hinzufügen
3. ⬜ Listings in Dict sammeln (statt direkt verarbeiten)

### Mittel-Risiko Änderungen
4. ⬜ Produkt-Extraktion nach Scraping
5. ⬜ Global Product List aufbauen
6. ⬜ Preissuche umstrukturieren

### Hoch-Risiko Änderungen
7. ⬜ Market Resale mit neuen Product Keys
8. ⬜ Listing Evaluation mit aggregierten Preisen

---

## 🛡️ SICHERHEITSMASSNAHMEN

### 1. Feature Flag
```python
# config.yaml
pipeline:
  use_v9_product_extraction: true  # Kann ausgeschaltet werden!
```

### 2. Fallback auf alte Logik
```python
if cfg.pipeline.use_v9_product_extraction:
    # Neue Logik
    global_products = build_global_product_list(...)
else:
    # Alte Logik (v7)
    cluster_result = cluster_variants_from_titles(...)
```

### 3. Validierung vor Speicherung
```python
# Sanity Check: Neue Preise müssen plausibel sein
if new_price < 1 or new_price > 50000:
    print(f"⚠️ Unrealistic price {new_price} for {product_key}")
    # Fallback auf alte Methode
```

### 4. Logging für Debugging
```python
print(f"📊 v9 Product Extraction:")
print(f"   Raw Listings: {total_listings}")
print(f"   Unique Products: {len(global_products)}")
print(f"   Deduplication Rate: {(1 - len(global_products)/total_listings)*100:.0f}%")
```

---

## 📋 IMPLEMENTIERUNGS-REIHENFOLGE

### Phase 1: Vorbereitung (JETZT)
1. ✅ `product_extractor.py` erstellt
2. ✅ Dokumentation erstellt
3. ⬜ Feature Flag in config.yaml hinzufügen
4. ⬜ Test-Funktion für product_extractor

### Phase 2: Integration (HEUTE)
5. ⬜ Import product_extractor in main.py
6. ⬜ Listings sammeln (Phase 1 der neuen Pipeline)
7. ⬜ Produkt-Extraktion aufrufen (Phase 2)
8. ⬜ Logging hinzufügen

### Phase 3: Preissuche (DANACH)
9. ⬜ `fetch_prices_for_products()` implementieren
10. ⬜ Market Resale mit neuen Product Keys
11. ⬜ Websearch mit Global List

### Phase 4: Evaluation (FINAL)
12. ⬜ Listing Evaluation anpassen
13. ⬜ Vollständiger Test
14. ⬜ Alte Logik als Fallback behalten

---

## ✅ CHECKLISTE VOR JEDEM SCHRITT

- [ ] Verstehe ich was der Code AKTUELL macht?
- [ ] Verstehe ich was der Code DANACH machen soll?
- [ ] Habe ich alle Abhängigkeiten identifiziert?
- [ ] Gibt es einen Fallback wenn etwas schief geht?
- [ ] Kann ich die Änderung isoliert testen?
- [ ] Ist die Änderung rückgängig machbar?

---

## 🎯 ERFOLGSMETRIKEN

| Metrik | v7 (aktuell) | v9 (Ziel) | Messung |
|--------|--------------|-----------|---------|
| Websearch Calls | ~24 | ~1-2 | Console Log |
| Kosten pro Run | ~$2.50 | <$0.50 | ai_cost_day.txt |
| Market Matches | ~20% | ~60% | "market_based" in DB |
| Bundle Detection | AI-only | Regex+AI | Console Log |

---

## 🚀 LOS GEHT'S

Der nächste Schritt ist:
1. Feature Flag in config.yaml hinzufügen
2. Dann die schrittweise Integration beginnen
