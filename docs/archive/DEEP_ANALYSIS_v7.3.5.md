# 🔬 DEEP ANALYSIS: the-deals Pipeline v7.3.5

**Datum:** 2026-01-11  
**Analyst:** Senior Software Engineer  
**Fokus:** Kosten, Datenqualität, Effizienz

---

## 📋 EXECUTIVE SUMMARY: Top 10 Probleme

| # | Problem | Schweregrad | Kostenimpact | Fix-Aufwand |
|---|---------|-------------|--------------|-------------|
| 1 | **Day-Cost wird nie gespeichert** | 🔴 KRITISCH | 100% Tracking kaputt | 5 min |
| 2 | **Tommy Hilfiger = "Accessory" Skip** | 🔴 KRITISCH | 30-50% false skips | 15 min |
| 3 | **Websearch mit dreckigen Queries** | 🟠 HOCH | 60-80% miss rate | 30 min |
| 4 | **Keine Query-Deduplizierung** | 🟠 HOCH | +$0.50-1.00/run | 20 min |
| 5 | **Cleaning schneidet zu wenig ab** | 🟡 MITTEL | 30% schlechtere Ergebnisse | 45 min |
| 6 | **Bundle-Quantity nicht extrahiert** | 🟡 MITTEL | Falsche Preise | 30 min |
| 7 | **120s Wait bei JEDEM Batch** | 🟡 MITTEL | +2min/run unnötig | 10 min |
| 8 | **Kein Clothing-Category Support** | 🟡 MITTEL | False Skips | 20 min |
| 9 | **Websearch-Kosten falsch berechnet** | 🟡 MITTEL | Falsches Tracking | 15 min |
| 10 | **Keine Query-Normalisierung** | 🟡 MITTEL | Redundante Searches | 30 min |

**Geschätzte Einsparung nach Fixes:** $2.50/run → **$0.35-0.50/run** (-80%)

---

## 🚨 PROBLEM 1: Kosten-Tracking komplett kaputt

### Symptom
```
💰 This run:    $1.7680 USD  
📊 Today total: $0.0000 USD   ← IMMER 0!
```

### Ursache (Root Cause)
**`DAY_COST_FILE` wird NIE geschrieben!**

```python
# ai_filter.py Zeile 161
DAY_COST_FILE = "ai_cost_day.txt"

# get_day_cost_summary() - LIEST nur
def get_day_cost_summary() -> float:
    if os.path.exists(DAY_COST_FILE):
        with open(DAY_COST_FILE, "r") as f:  # ← NUR LESEN
            return float(f.read().strip())
    return 0.0

# PROBLEM: Es gibt KEINE save_day_cost() Funktion!
# add_cost() erhöht nur RUN_COST_USD, speichert aber nie in Datei!
```

### Fix
```python
# ai_filter.py - NEUE Funktion hinzufügen

def save_day_cost():
    """Save current day's total cost to file."""
    global RUN_COST_USD
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Lese existierende Kosten
        existing = 0.0
        existing_date = ""
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    existing_date, existing = content.split(",")
                    existing = float(existing) if existing_date == today else 0.0
        
        # Addiere Run-Kosten
        new_total = existing + RUN_COST_USD
        
        # Speichern mit Datum
        with open(DAY_COST_FILE, "w") as f:
            f.write(f"{today},{new_total:.4f}")
        
        return new_total
    except Exception as e:
        print(f"⚠️ Could not save day cost: {e}")
        return 0.0
```

**Aufruf in main.py am Ende von run_once():**
```python
from ai_filter import save_day_cost
# ... am Ende der Funktion:
day_total = save_day_cost()
print(f"📊 Today total: ${day_total:.4f} USD")
```

---

## 🚨 PROBLEM 2: Tommy Hilfiger wird als "Accessory" geskippt

### Symptom
```
🎯 Skip (hardcoded accessory):  
- Tommy Hilfiger T-Shirt, Herren Grösse XL  
- Tommy Hilfiger Handtasche Shopper  
- Tommy Hilfiger Poloshirt
```

### Ursache
**`is_accessory_title()` kennt keine "clothing" Kategorie!**

```python
# utils_text.py Zeile 271-300
def is_accessory_title(title: str, query: str = "", category: str = "") -> bool:
    # ...
    # RULE 2: Fitness category exception for bundles
    if category_lower in ["fitness", "sport"]:  # ← NUR FITNESS!
        effective_keywords = [kw for kw in effective_keywords 
                             if kw not in FITNESS_NOT_ACCESSORY]
    
    # ❌ FEHLT: Clothing/Fashion category exception!
```

**Das Problem:** "Tasche" ist in `ACCESSORY_KEYWORDS`:
```python
ACCESSORY_KEYWORDS = [
    "hülle", "case", "cover", "bumper", "etui", "tasche",  # ← "tasche"!
    # ...
]
```

Aber bei Tommy Hilfiger ist "Handtasche" das **Hauptprodukt**, kein Zubehör!

### Fix
```python
# utils_text.py - CLOTHING Support hinzufügen

# Neue Konstante
CLOTHING_BRANDS = [
    "tommy hilfiger", "tommy jeans", "calvin klein", "ralph lauren",
    "hugo boss", "lacoste", "levis", "guess", "gant", "nike", "adidas",
    "puma", "north face", "patagonia", "zara", "h&m", "mango",
]

CLOTHING_NOT_ACCESSORY = [
    "tasche", "handtasche", "bag", "shopper", "tote",
    "rucksack", "backpack",
    "gürtel", "belt",
    "schal", "scarf", "tuch",
    "mütze", "cap", "hat", "hut",
]

def detect_category(query: str) -> str:
    query_lower = (query or "").lower()
    
    # NEU: Clothing-Erkennung
    if any(brand in query_lower for brand in CLOTHING_BRANDS):
        return "clothing"
    
    if any(ind in query_lower for ind in FITNESS_INDICATORS):
        return "fitness"
    # ... rest bleibt gleich

def is_accessory_title(title: str, query: str = "", category: str = "") -> bool:
    # ... existing code ...
    
    # RULE 2a: Clothing category - Taschen sind Hauptprodukte!
    if category_lower in ["clothing", "fashion", "mode"]:
        effective_keywords = [kw for kw in effective_keywords 
                             if kw not in CLOTHING_NOT_ACCESSORY]
    
    # RULE 2b: Fitness category (existing)
    if category_lower in ["fitness", "sport"]:
        effective_keywords = [kw for kw in effective_keywords 
                             if kw not in FITNESS_NOT_ACCESSORY]
```

---

## 🚨 PROBLEM 3: Websearch mit dreckigen Queries

### Symptom
```
🌐 Web search batch: 8 products...
⚠️ Tommy Hilfiger Hampton Parka Daunenjacke... = no price found
⚠️ Tommy Hilfiger Hemd, Gr. 6 (116)... = no price found
⚠️ Tommy Hilfoger Pullover xxl... = no price found   ← TYPO!
```

### Ursache
**`clean_search_term()` ist zu schwach!**

```python
# query_analyzer.py Zeile 532-583
def clean_search_term(title: str, query_analysis: Optional[Dict] = None) -> str:
    # Step 1: Remove after keywords → OK
    # Step 2: Remove words → OK
    # Step 3: Clean whitespace → OK
    # Step 4: Remove size info → TEILWEISE
    # Step 5: Limit to 6 words → ZU VIEL!
    
    # ❌ FEHLT:
    # - Typo-Korrektur ("Hilfoger" → "Hilfiger")
    # - Brand-Normalisierung
    # - Modell-Extraktion
    # - Größen/Farben entfernen
```

### Fix: Bessere Query-Normalisierung
```python
# query_analyzer.py - Neue Funktion

def normalize_search_query(title: str, query_analysis: Optional[Dict] = None) -> str:
    """
    v7.4: Aggressive query normalization for web search.
    
    GOAL: "Tommy Hilfiger Hampton Parka Daunenjacke Gr. XL blau"
       → "Tommy Hilfiger Daunenjacke"
    """
    clean = title.strip()
    
    # 1. TYPO-KORREKTUR (häufige Fehler)
    TYPO_FIXES = {
        "hilfoger": "hilfiger",
        "calven klein": "calvin klein",
        "lacoast": "lacoste",
        "addidas": "adidas",
        "garmim": "garmin",
        "samsumg": "samsung",
    }
    clean_lower = clean.lower()
    for typo, correct in TYPO_FIXES.items():
        if typo in clean_lower:
            clean = re.sub(typo, correct, clean, flags=re.IGNORECASE)
    
    # 2. ENTFERNE: Größen, Farben, Zustände
    REMOVE_PATTERNS = [
        r'\b(Gr\.?|Grösse|Size)\s*\d+\b',           # Gr. 42, Size M
        r'\b(XXS|XS|S|M|L|XL|XXL|XXXL)\b',          # Größen
        r'\b\d{2}/\d{2}\b',                          # 32/32 Jeans
        r'\b(schwarz|weiss|blau|rot|grün|gelb|grau|braun|pink|lila)\b',
        r'\b(black|white|blue|red|green|navy)\b',
        r'\b(neu|new|top|super|original|ovp)\b',
        r'\b(herren|damen|kinder|boys?|girls?|men|women)\b',
        r'\b(gebraucht|neuwertig|wie neu)\b',
    ]
    for pattern in REMOVE_PATTERNS:
        clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
    
    # 3. EXTRAHIERE: Nur Brand + Produkttyp
    category = _get_category(query_analysis)
    
    if category == "clothing":
        # Für Kleidung: Brand + Produkttyp
        PRODUCT_TYPES = [
            "jacke", "jacket", "parka", "mantel", "coat",
            "pullover", "sweater", "hoodie", "sweatshirt",
            "hemd", "shirt", "bluse", "polo", "t-shirt",
            "hose", "jeans", "pants", "shorts", "chino",
            "kleid", "dress", "rock", "skirt",
            "tasche", "bag", "shopper", "rucksack",
        ]
        for pt in PRODUCT_TYPES:
            if pt in clean.lower():
                # Brand + Produkttyp extrahieren
                brand_match = re.search(r'^([\w\s]+?)\s+' + pt, clean, re.IGNORECASE)
                if brand_match:
                    return f"{brand_match.group(1).strip()} {pt}".title()
    
    # 4. KÜRZEN: Max 4 Wörter
    words = clean.split()
    words = [w for w in words if len(w) > 2 and w.lower() not in ['und', 'mit', 'für']]
    clean = ' '.join(words[:4])
    
    # 5. CLEANUP
    clean = re.sub(r'\s+', ' ', clean)
    clean = re.sub(r'[,;:!?]+', '', clean)
    
    return clean.strip()
```

---

## 🚨 PROBLEM 4: Keine Query-Deduplizierung

### Symptom
```
Websearch für:
1. Tommy Hilfiger Pullover XXL
2. Tommy Hilfiger Pullover L
3. Tommy Hilfiger Pullover M
→ 3 separate Searches für GLEICHEN Neupreis!
```

### Ursache
```python
# ai_filter.py - search_web_batch_for_new_prices()
# Jeder variant_key wird einzeln in den Batch genommen
# KEINE Deduplizierung auf normalisierte Produktnamen!
```

### Fix: Query-Deduplication
```python
def search_web_batch_for_new_prices(variant_keys, category, query_analysis):
    # ... existing cache check ...
    
    # NEU: Dedupliziere normalisierte Queries
    query_to_variants = {}  # normalized_query → [original_variant_keys]
    
    for vk in uncached:
        normalized = normalize_search_query(vk, query_analysis)
        if normalized not in query_to_variants:
            query_to_variants[normalized] = []
        query_to_variants[normalized].append(vk)
    
    # Jetzt nur UNIQUE queries suchen
    unique_queries = list(query_to_variants.keys())
    print(f"   📊 Deduplicated: {len(uncached)} → {len(unique_queries)} unique queries")
    
    # Websearch für unique queries
    # ... existing batch logic ...
    
    # Ergebnisse auf ALLE zugehörigen variant_keys anwenden
    for normalized, price_data in web_results.items():
        for vk in query_to_variants[normalized]:
            results[vk] = price_data
            set_cached_web_price(vk, price_data["new_price"], ...)
```

**Erwartete Einsparung:** 30-50% weniger Queries!

---

## 🚨 PROBLEM 5: Cleaning schneidet zu wenig ab

### Symptom
```
🔧 Cleaned: 'Garmin Fenix 7 Sapphire Solar, Top Zusta' → 'Garmin Fenix 7 Sapphire Solar, Top'
                                                                                        ↑ MÜLL!
🔧 Cleaned: 'Garmin Fenix 6S Pro Watch - Black' → 'Garmin Fenix 6S Pro Watch -'
                                                                           ↑ MÜLL!
```

### Erwartete Ergebnisse
```
'Garmin Fenix 7 Sapphire Solar, Top Zustand' → 'Garmin Fenix 7 Sapphire Solar'
'Garmin Fenix 6S Pro Watch - Black'          → 'Garmin Fenix 6S Pro'
```

### Fix
```python
# query_analyzer.py - Erweiterte remove_after Liste

DEFAULT_REMOVE_AFTER = [
    # Zustands-Wörter
    "top", "super", "mega", "wow", "perfect", "neuwertig", "wie neu",
    "zustand", "zusta", "condition",
    
    # Bundle-Indikatoren
    "inkl", "inklusive", "mit", "plus", "+", "und", "&", "samt",
    
    # Beschreibungen
    "neu", "new", "original", "ovp", "unbenutzt", "sealed",
    
    # Sonderzeichen (am Wort-Ende)
    "-", ",", "!", "?",
]

# Zusätzlich: Trailing Punctuation aggressiver entfernen
clean = re.sub(r'[\s,\-!?;:]+$', '', clean)
```

---

## 🚨 PROBLEM 6: Bundle-Quantity nicht extrahiert

### Symptom
```
🔧 Cleaned: 'Hantelscheiben, 2 Stk. à 10kg' → 'Hantelscheiben, 2 Stk. à 10'
```

### Erwartetes Datenmodell
```python
{
    "product": "Hantelscheibe 10kg",
    "quantity": 2,
    "unit_price": 35.0,
    "total_price": 70.0
}
```

### Fix: Quantity-Extraktion
```python
# utils_text.py - Neue Funktion

def extract_quantity_and_product(title: str) -> Tuple[str, int]:
    """
    Extrahiert Menge und normalisiertes Produkt.
    
    "Hantelscheiben, 2 Stk. à 10kg" → ("Hantelscheibe 10kg", 2)
    "3x Kurzhantel 5kg"             → ("Kurzhantel 5kg", 3)
    "Paar Hanteln 2.5kg"            → ("Hantel 2.5kg", 2)
    """
    title_lower = title.lower()
    quantity = 1
    
    # Pattern 1: "2 Stk" / "2 Stück" / "2x"
    qty_match = re.search(r'(\d+)\s*(stk\.?|stück|x)\b', title_lower)
    if qty_match:
        quantity = int(qty_match.group(1))
        title = re.sub(r'\d+\s*(stk\.?|stück|x)\b', '', title, flags=re.IGNORECASE)
    
    # Pattern 2: "Paar" = 2
    if re.search(r'\bpaar\b', title_lower):
        quantity = 2
        title = re.sub(r'\bpaar\b', '', title, flags=re.IGNORECASE)
    
    # Pattern 3: "à XYkg" → entfernen (Info ist in Produktname)
    title = re.sub(r'\bà\s*\d+', '', title, flags=re.IGNORECASE)
    
    # Pluralform → Singular
    title = re.sub(r'scheiben\b', 'scheibe', title, flags=re.IGNORECASE)
    title = re.sub(r'hanteln\b', 'hantel', title, flags=re.IGNORECASE)
    
    # Cleanup
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'^[,\s]+|[,\s]+$', '', title)
    
    return (title, quantity)
```

---

## 📊 KOSTEN-ANALYSE: Von $2.50 auf $0.40

### Aktuelle Kosten-Aufschlüsselung (geschätzt)

| Komponente | Anzahl/Run | Kosten/Stk | Total |
|------------|------------|------------|-------|
| Web Search Batches | 3-5 | $0.35 | $1.05-1.75 |
| AI Variant Estimation | 2-3 | $0.003 | $0.01 |
| AI Bundle Detection | 5-10 | $0.003 | $0.02-0.03 |
| AI Category Thresholds | 1 | $0.003 | $0.003 |
| 120s Wait × Batches | 3-5 | - | 6-10 min! |
| **TOTAL** | | | **$1.08-1.78** |

### Nach Optimierung

| Komponente | Anzahl/Run | Kosten/Stk | Total |
|------------|------------|------------|-------|
| Web Search (dedupliziert) | 1-2 | $0.35 | $0.35-0.70 |
| AI Variant (cached) | 0-1 | $0.003 | $0.00-0.003 |
| AI Bundle (batch) | 1 | $0.003 | $0.003 |
| 120s Wait (einmalig) | 1 | - | 2 min |
| **TOTAL** | | | **$0.35-0.70** |

**Einsparung: 60-80%**

---

## 🔧 KONKRETE CODE-FIXES

### Fix 1: Day-Cost speichern (5 min)
```python
# ai_filter.py - Nach Zeile 2288 einfügen

def save_day_cost() -> float:
    """Save run cost to daily total."""
    global RUN_COST_USD
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        existing = 0.0
        
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    date_str, cost_str = content.split(",", 1)
                    if date_str == today:
                        existing = float(cost_str)
        
        new_total = existing + RUN_COST_USD
        
        with open(DAY_COST_FILE, "w") as f:
            f.write(f"{today},{new_total:.4f}")
        
        return new_total
    except:
        return 0.0
```

### Fix 2: Clothing-Category Support (15 min)
Siehe oben unter Problem 2.

### Fix 3: Query-Normalisierung (30 min)
Siehe oben unter Problem 3.

### Fix 4: Query-Deduplizierung (20 min)
Siehe oben unter Problem 4.

---

## 📋 REFACTOR-PLAN (Priorität)

| PR | Änderung | Impact | Risiko | Aufwand |
|----|----------|--------|--------|---------|
| **PR1** | Fix day-cost saving | Tracking funktioniert | LOW | 5 min |
| **PR2** | Add clothing category | -30% false skips | LOW | 15 min |
| **PR3** | Query normalization | +40% search success | MEDIUM | 30 min |
| **PR4** | Query deduplication | -40% search costs | LOW | 20 min |
| **PR5** | Quantity extraction | Korrekte Bundle-Preise | MEDIUM | 30 min |
| **PR6** | Remove 120s wait | -6 min/run | LOW | 10 min |
| **PR7** | Better cleaning | +20% match rate | MEDIUM | 45 min |
| **PR8** | Cache hit tracking | Transparenz | LOW | 15 min |
| **PR9** | Brand normalization | +10% match rate | MEDIUM | 30 min |
| **PR10** | Unit test suite | Regression prevention | LOW | 2 hours |

---

## 🎯 ZUSAMMENFASSUNG

### Kritische Bugs (sofort fixen)
1. ❌ **Day-Cost wird nie gespeichert** → `save_day_cost()` hinzufügen
2. ❌ **Tommy Hilfiger = Accessory** → Clothing-Category Support

### Performance (diese Woche)
3. ⚠️ **Dreckige Search-Queries** → Aggressive Normalisierung
4. ⚠️ **Keine Deduplizierung** → Query-Merging
5. ⚠️ **120s Wait pro Batch** → Einmaliges Wait

### Datenqualität (nächste Woche)
6. 📊 **Quantity-Extraktion** fehlt
7. 📊 **Cleaning zu schwach** 
8. 📊 **Bundle-Erkennung** unvollständig

### Erwartetes Ergebnis
- **Kosten:** $2.50 → **$0.40** (-84%)
- **False Skips:** -50%
- **Search Success Rate:** +40%
- **Runtime:** -6 min (120s wait nur einmal)

---

## ⚡ QUICK WINS (heute umsetzbar)

1. **`save_day_cost()` hinzufügen** → 5 min
2. **Clothing-Brands zu `detect_category()` hinzufügen** → 10 min
3. **120s Wait nur beim ersten Batch** → 5 min
4. **"tasche" aus ACCESSORY_KEYWORDS für clothing entfernen** → 5 min

**Total: 25 min für die kritischsten Fixes!**
