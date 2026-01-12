# 🏗️ ARCHITEKTUR v9.0: 10-Step Pipeline

**Datum:** 2026-01-11  
**Status:** Design-Dokument  
**Ziel:** Robustes System für strukturierte Produktextraktion und Preisberechnung

---

## 📐 PIPELINE-ÜBERSICHT

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        QUERY SEQUENCE                                    │
│  [Garmin Smartwatch] → [Tommy Hilfiger] → [Hantelscheiben]              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 1: SCRAPING (pro Query)                                            │
│ ────────────────────────────                                            │
│ Ricardo durchsuchen → Rohe Inserate sammeln                             │
│                                                                         │
│ Output: List[RawListing]                                                │
│   - listing_id, title, price, image_url, etc.                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 2: AI TITLE CLEANUP (pro Listing)                                  │
│ ──────────────────────────────────────                                  │
│ Nur preisrelevante Infos behalten                                       │
│                                                                         │
│ Regeln:                                                                 │
│   ✅ Modellunterschiede behalten (7 ≠ 7s ≠ 7 Sapphire)                 │
│   ✅ Solar, Pro, Sapphire = preisrelevant                              │
│   ✅ Herren/Damen/Kinder behalten                                      │
│   ❌ Farbe entfernen                                                    │
│   ❌ Zustand entfernen                                                  │
│   ❌ Grösse entfernen                                                   │
│   ❌ Marketingtext entfernen                                            │
│                                                                         │
│ Beispiel:                                                               │
│   "Garmin Fenix 7 Sapphire Solar, Top Zustand" → "Garmin Fenix 7 Sapphire Solar"│
│   "Tommy Hilfiger Winterjacke Herren L" → "Tommy Hilfiger Winterjacke Herren"   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 3: DEDUPLICATION (pro Query)                                       │
│ ─────────────────────────────────                                       │
│ Identische normalisierte Produkte → nur 1× behalten                     │
│                                                                         │
│ Beispiel:                                                               │
│   2× "Garmin Lily" → 1× "Garmin Lily"                                  │
│                                                                         │
│ WICHTIG: Mapping behalten! (welche Listings → welches Produkt)          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 4-6: WEITERE QUERIES VERARBEITEN                                   │
│ ─────────────────────────────────────                                   │
│ Schritte 1-3 für jede Query wiederholen                                 │
│                                                                         │
│ Garmin Smartwatch → [7 unique products]                                 │
│ Tommy Hilfiger    → [6 unique products]                                 │
│ Hantelscheiben    → [N products + bundles]                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 7: FITNESS BUNDLE DECOMPOSITION (Sonderfall)                       │
│ ─────────────────────────────────────────────────                       │
│ Fitness-Bundles → Einzelprodukte aufteilen                              │
│                                                                         │
│ Regeln (hardcoded erlaubt):                                             │
│   1. Bundles IMMER in Einzelprodukte                                    │
│   2. Produkte IMMER im Singular                                         │
│   3. Menge separat erfassen                                             │
│   4. Gewicht/Durchmesser behalten                                       │
│                                                                         │
│ Beispiel:                                                               │
│   "Hantelscheiben, 2 Stk. à 10kg" → Hantelscheibe 10kg ×2              │
│   "Kettler 2×2.5kg"               → Kettler Hantelscheibe 2.5kg ×2     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 7b: UNCLEAR BUNDLES → DETAIL + VISION                              │
│ ──────────────────────────────────────────                              │
│ Wenn Titel unklar (z.B. "Komplettes Homegym"):                          │
│   1. Detailseite öffnen                                                 │
│   2. Beschreibung analysieren                                           │
│   3. Falls nötig: Bilder mit Vision                                     │
│                                                                         │
│ Beispiel:                                                               │
│   "100kg Bumper Plates" ≠ 1× 100kg Scheibe                             │
│   → 2×20kg + 2×15kg + 2×10kg + 2×5kg = 100kg                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 8: GLOBAL PRODUCT LIST (DEDUPLIZIERT)                              │
│ ──────────────────────────────────────────                              │
│ Alle Produkte aus ALLEN Queries zusammenführen                          │
│ → Finale Liste für Websearch                                            │
│                                                                         │
│ Beispiel (23 unique products):                                          │
│   - Garmin Fenix 7 Solar                                                │
│   - Garmin Fenix 7s                                                     │
│   - Tommy Hilfiger Jacke Damen                                          │
│   - Hantelscheibe 10kg                                                  │
│   - Bumper Plate 20kg                                                   │
│   ...                                                                   │
│                                                                         │
│ ZIEL: Websearch NUR 1× pro Produkt!                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│ WEBSEARCH: NEUPREISE          │   │ RICARDO SEARCH: RESALE        │
│ ─────────────────────         │   │ ──────────────────────        │
│ Pro unique product:           │   │ Pro unique product:           │
│ → Digitec, Galaxus, etc.      │   │ → Ricardo "verkaufte"         │
│ → Neupreis in CHF             │   │ → Median/Durchschnitt         │
│                               │   │                               │
│ Output: new_prices{}          │   │ Output: resale_prices{}       │
└───────────────────────────────┘   └───────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 10: LISTING EVALUATION                                             │
│ ───────────────────────────                                             │
│ Pro INSERAT (nicht pro Produkt!):                                       │
│   1. Alle Komponenten auflisten                                         │
│   2. Preise nachschlagen (aus global cache)                             │
│   3. Mengen multiplizieren                                              │
│   4. Summe Neupreis                                                     │
│   5. Summe Resale-Preis                                                 │
│   6. Deal-Score berechnen                                               │
│                                                                         │
│ Beispiel:                                                               │
│   Inserat: "Hantelscheiben 4×10kg + Ständer"                           │
│   → Hantelscheibe 10kg ×4 = 4 × 35 CHF = 140 CHF                       │
│   → Hantelständer ×1 = 60 CHF                                          │
│   → Total Neupreis: 200 CHF                                            │
│   → Total Resale: 110 CHF                                              │
│   → Deal-Score: ...                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 DATENFLUSS

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ RawListing   │     │ CleanedTitle │     │ Product      │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ listing_id   │────▶│ listing_id   │────▶│ product_key  │
│ title        │     │ clean_title  │     │ quantity     │
│ price        │     │ query        │     │ new_price    │
│ image_url    │     │ category     │     │ resale_price │
│ ...          │     │              │     │ listings[]   │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
                                                 ▼
                                          ┌──────────────┐
                                          │ Evaluation   │
                                          ├──────────────┤
                                          │ listing_id   │
                                          │ products[]   │
                                          │ total_new    │
                                          │ total_resale │
                                          │ profit       │
                                          │ deal_score   │
                                          └──────────────┘
```

---

## 📊 DATENSTRUKTUREN

```python
@dataclass
class RawListing:
    """Step 1: Rohes Inserat von Ricardo"""
    listing_id: str
    title: str
    current_price: float
    buy_now_price: Optional[float]
    image_url: str
    url: str
    bids_count: int
    end_time: datetime
    query: str  # Welcher User-Query


@dataclass
class CleanedListing:
    """Step 2: Bereinigtes Inserat"""
    listing_id: str
    original_title: str
    clean_title: str
    query: str
    category: str  # smartwatch, clothing, fitness


@dataclass
class Product:
    """Step 3-8: Normalisiertes Produkt"""
    product_key: str        # Unique identifier
    display_name: str       # Für Websearch
    category: str
    quantity: int           # Default 1
    specs: Dict[str, Any]   # weight_kg, diameter_mm, etc.
    source_listings: List[str]  # listing_ids die dieses Produkt haben


@dataclass
class ProductPrice:
    """Step 9: Preise für ein Produkt"""
    product_key: str
    new_price: float
    new_price_source: str   # web_galaxus, web_digitec, etc.
    resale_price: float
    resale_sample_size: int
    resale_source: str      # ricardo_search


@dataclass
class ListingEvaluation:
    """Step 10: Finale Bewertung pro Inserat"""
    listing_id: str
    components: List[Dict]  # [{product_key, quantity, new_price, resale_price}]
    total_new_price: float
    total_resale_price: float
    purchase_price: float
    expected_profit: float
    deal_score: float
    strategy: str           # bid, buy_now, watch, skip
```

---

## 🔧 STEP 2: AI TITLE CLEANUP

### Prompt-Template

```
Du bist ein Produktnormalisierungs-Experte.

AUFGABE:
Bereinige den folgenden Inseratstitel so, dass NUR preisrelevante Informationen bleiben.

REGELN:
✅ BEHALTEN:
- Marke (kommt vom Query: "{query}")
- Modellunterschiede (7 ≠ 7s ≠ 7 Sapphire)
- Preisrelevante Features (Solar, Pro, Sapphire, etc.)
- Geschlecht bei Kleidung (Herren/Damen/Kinder)
- Produkttyp-Unterschiede (Winterjacke ≠ Jacke)

❌ ENTFERNEN:
- Farbe (schwarz, blau, olive, etc.)
- Zustand (neu, neuwertig, top, etc.)
- Grösse (S, M, L, XL, 32/32, Gr. 42)
- Marketingtext (THFLEX, Original, etc.)
- Zusätze (inkl. OVP, mit Box, etc.)

QUERY: {query}
TITEL: {title}

Antworte NUR mit dem bereinigten Titel, nichts anderes.
```

### Beispiel-Transformationen

| Original | Clean |
|----------|-------|
| Garmin Fenix 7 Sapphire Solar, Top Zustand | Garmin Fenix 7 Sapphire Solar |
| Garmin Fenix 7s (recertified) | Garmin Fenix 7s |
| Tommy Hilfiger Winterjacke Herren Grösse L | Tommy Hilfiger Winterjacke Herren |
| Dame Jacke TOMMY HILFIGER THFLEX | Tommy Hilfiger Jacke Damen |
| Tommy Hilfiger Strickpullover, Size XL | Tommy Hilfiger Pullover |

---

## 🔧 STEP 7: FITNESS DECOMPOSITION (Hardcoded)

```python
def decompose_fitness_listing(title: str, description: str = "") -> List[Product]:
    """
    Fitness-Sonderbehandlung: Bundles in Einzelprodukte aufteilen.
    
    Hardcoded Regeln erlaubt!
    """
    products = []
    combined = f"{title} {description}".lower()
    
    # Pattern 1: "2 Stk. à 10kg" oder "4×5kg"
    qty_weight = re.findall(r'(\d+)\s*(?:stk\.?|×|x)\s*(?:à|a)?\s*(\d+(?:[.,]\d+)?)\s*kg', combined)
    for qty, weight in qty_weight:
        products.append(Product(
            product_key=f"hantelscheibe_{weight}kg",
            display_name=f"Hantelscheibe {weight}kg",
            category="fitness",
            quantity=int(qty),
            specs={"weight_kg": float(weight)},
        ))
    
    # Pattern 2: "Langhantelbank"
    if "langhantelbank" in combined:
        brand = extract_brand(combined)  # z.B. "Gorilla Sports"
        products.append(Product(
            product_key="langhantelbank",
            display_name=f"{brand} Langhantelbank" if brand else "Langhantelbank",
            category="fitness",
            quantity=1,
        ))
    
    # Pattern 3: "Bumper Plates 100kg" → aufteilen!
    if "bumper" in combined and "100kg" in combined:
        # Typische 100kg Set Zusammensetzung
        products.extend([
            Product("bumper_plate_20kg", "Bumper Plate 20kg", "fitness", 2, {"weight_kg": 20}),
            Product("bumper_plate_15kg", "Bumper Plate 15kg", "fitness", 2, {"weight_kg": 15}),
            Product("bumper_plate_10kg", "Bumper Plate 10kg", "fitness", 2, {"weight_kg": 10}),
            Product("bumper_plate_5kg", "Bumper Plate 5kg", "fitness", 2, {"weight_kg": 5}),
        ])
    
    return products
```

---

## 🔧 STEP 8: GLOBAL PRODUCT LIST

```python
def build_global_product_list(
    all_query_products: Dict[str, List[Product]]
) -> Dict[str, Product]:
    """
    Alle Produkte aus allen Queries zusammenführen.
    Duplikate entfernen.
    
    Returns:
        Dict[product_key, Product] - Unique products for websearch
    """
    global_products = {}
    
    for query, products in all_query_products.items():
        for product in products:
            key = product.product_key
            
            if key in global_products:
                # Merge: Listings zusammenführen
                global_products[key].source_listings.extend(product.source_listings)
            else:
                global_products[key] = product
    
    return global_products
```

---

## 🔧 STEP 9: RESALE PRICE SEARCH

```python
def search_resale_prices(products: List[Product]) -> Dict[str, float]:
    """
    Suche Resale-Preise auf Ricardo für verkaufte Artikel.
    
    Für jedes Produkt:
    1. Ricardo-Suche mit product.display_name
    2. Filter: nur "verkauft" / abgeschlossene Auktionen
    3. Median berechnen
    """
    resale_prices = {}
    
    for product in products:
        # Ricardo-Suche
        sold_listings = ricardo_search_sold(product.display_name)
        
        if sold_listings:
            prices = [l.final_price for l in sold_listings]
            resale_prices[product.product_key] = statistics.median(prices)
        else:
            # Fallback: Schätzung basierend auf Neupreis
            resale_prices[product.product_key] = None
    
    return resale_prices
```

---

## 💰 KOSTENABSCHÄTZUNG

### Aktuell (v7.x)
| Schritt | Kosten | Häufigkeit |
|---------|--------|------------|
| Web Search pro Listing | $0.10-0.35 | ~24 Listings |
| AI Cleanup | $0.003 | pro Listing |
| Bundle Detection | $0.003 | pro Bundle |
| **Total** | **$2.50-8.50** | |

### Nach v9.0
| Schritt | Kosten | Häufigkeit |
|---------|--------|------------|
| AI Cleanup (Batch) | $0.01 | pro Query (nicht pro Listing!) |
| Web Search | $0.35 | 1× pro unique Product (~23) |
| Resale Search | $0.00 | Ricardo scraping |
| Vision (nur unclear) | $0.01 | ~5% der Bundles |
| **Total** | **$0.40-0.70** | |

**Einsparung: 85%+**

---

## 📋 IMPLEMENTIERUNGSREIHENFOLGE

### Phase 1: Core Pipeline (DIESE WOCHE)
1. ✅ Architektur-Dokument
2. ⬜ `product_extractor.py` - Step 2 AI Cleanup
3. ⬜ `product_deduplicator.py` - Step 3 & 8
4. ⬜ `fitness_decomposer.py` - Step 7

### Phase 2: Price Search (NÄCHSTE WOCHE)
5. ⬜ Websearch mit Global Product List
6. ⬜ Ricardo Resale Search (Step 9)
7. ⬜ Price Cache Integration

### Phase 3: Evaluation (DANACH)
8. ⬜ Listing Evaluation Refactor (Step 10)
9. ⬜ Integration in main.py
10. ⬜ Testing & Validation

---

## ❗ DESIGN-PRINZIPIEN

| ✅ ERLAUBT | ❌ VERBOTEN |
|-----------|-------------|
| Fitness Hardcoding | Markenlisten (ausser Fitness) |
| Regelbasierte Extraktion | AI pro Inserat wenn Regeln reichen |
| Query-driven Brand | Mischpreise über Marken |
| Batch AI Calls | Einzelne AI Calls pro Listing |
| Global Deduplication | Redundante Websearches |

---

## 📝 ZUSAMMENFASSUNG

Das v9.0 System:

1. **Ist query-sequenziell** - Queries nacheinander, nicht parallel
2. **Normalisiert intelligent** - Modellunterschiede behalten, Noise entfernen
3. **Dedupliziert global** - Websearch nur 1× pro unique Product
4. **Berechnet Resale korrekt** - Ricardo-Suche für verkaufte Artikel
5. **Bewertet pro Inserat** - Aggregiert Preise für Bundle-Komponenten

**Kernprinzip:** Aus chaotischen Inseraten → strukturierte Produkte → realistische Marktpreise
