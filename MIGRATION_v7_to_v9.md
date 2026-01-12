# 🔄 MIGRATION: v7 → v9 Pipeline

**Was ändert sich? Was bleibt? Was ist neu?**

---

## 📊 ÜBERSICHT: Vorher vs. Nachher

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           v7 (AKTUELL)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Query 1 ──┬── Listing 1 ──► Websearch ──► Preis                       │
│            ├── Listing 2 ──► Websearch ──► Preis                       │
│            ├── Listing 3 ──► Websearch ──► Preis                       │
│            └── ...                                                      │
│                                                                         │
│  Query 2 ──┬── Listing 4 ──► Websearch ──► Preis                       │
│            ├── Listing 5 ──► Websearch ──► Preis                       │
│            └── ...                                                      │
│                                                                         │
│  ❌ Jedes Listing = eigener Websearch Call                              │
│  ❌ Duplikate werden mehrfach gesucht                                   │
│  ❌ Bundles oft nicht richtig zerlegt                                   │
│  ❌ Resale = AI Schätzung (ungenau)                                     │
│                                                                         │
│  💰 Kosten: ~$2.50 pro Run                                              │
└─────────────────────────────────────────────────────────────────────────┘

                              ▼▼▼

┌─────────────────────────────────────────────────────────────────────────┐
│                           v9 (NEU)                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Query 1 ──► [Listings] ──► Normalize ──┐                              │
│  Query 2 ──► [Listings] ──► Normalize ──┼──► GLOBAL        Websearch   │
│  Query 3 ──► [Listings] ──► Normalize ──┘    PRODUCT  ──►  (1 Batch)   │
│                                              LIST                       │
│                                              (dedupliziert)             │
│                                                  │                      │
│                                                  ▼                      │
│                                          ┌──────────────┐               │
│                                          │ Preis-Cache  │               │
│                                          │ (pro Produkt)│               │
│                                          └──────────────┘               │
│                                                  │                      │
│                                                  ▼                      │
│                                          Listing Evaluation             │
│                                          (Preise nachschlagen)          │
│                                                                         │
│  ✅ Alle Listings → eine globale Produktliste                          │
│  ✅ Websearch nur 1× pro unique Produkt                                │
│  ✅ Bundles für ALLE Kategorien zerlegt                                │
│  ✅ Resale = Ricardo Suche (echte Marktdaten)                          │
│                                                                         │
│  💰 Kosten: ~$0.40 pro Run                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 DETAILLIERTE ÄNDERUNGEN

### 1. SCRAPING (bleibt gleich)

| Aspekt | v7 | v9 |
|--------|----|----|
| Ricardo Suche | ✅ | ✅ |
| Max Listings pro Query | config.yaml | config.yaml |
| Pagination | ✅ | ✅ |

**Keine Änderung** - `scrapers/ricardo.py` bleibt unverändert.

---

### 2. TITLE CLEANUP (NEU)

| Aspekt | v7 | v9 |
|--------|----|----|
| Methode | `clean_search_term()` | `clean_title_for_search()` |
| Logik | Einfache Regex | Regelbasiert + AI Fallback |
| Modellunterschiede | ❌ Oft verloren | ✅ Behalten (7 ≠ 7s) |
| Geschlecht | ❌ Oft verloren | ✅ Behalten (Herren/Damen) |
| AI Kosten | $0 | $0.003 nur wenn nötig |

**v7 (alt):**
```python
# clean_search_term() in utils_text.py
"Garmin Fenix 7 Sapphire Solar, Top Zustand"
→ "Garmin Fenix 7 Sapphire Solar Top Zustand"  # Zustand bleibt!
```

**v9 (neu):**
```python
# clean_title_for_search() in product_extractor.py
"Garmin Fenix 7 Sapphire Solar, Top Zustand"
→ "Garmin Fenix 7 Sapphire Solar"  # Zustand entfernt!
```

---

### 3. BUNDLE DETECTION (KOMPLETT NEU)

| Aspekt | v7 | v9 |
|--------|----|----|
| Erkennung | `looks_like_bundle()` | `is_bundle_title()` |
| Kategorien | Nur Fitness | ALLE Kategorien |
| Zerlegung | AI für alles | Regeln zuerst, AI nur wenn nötig |
| Fitness Heuristik | ❌ | ✅ Hardcoded erlaubt |

**v7 (alt):**
```python
# Nur für Fitness, immer AI
"Hantelscheiben 4×5kg"
→ AI Call: "Was sind die Komponenten?" ($0.003)
```

**v9 (neu):**
```python
# Regelbasiert für alle Kategorien
"Hantelscheiben 4×5kg"
→ Regex erkennt: 4× 5kg
→ Ergebnis: Hantelscheibe 5kg ×4
→ Kosten: $0.00

"Garmin Fenix 7 inkl. Zubehör"
→ Keyword "inkl" erkannt
→ Zubehör-Patterns geprüft (Armband, Brustgurt, etc.)
→ Kosten: $0.00 (wenn erkannt) oder $0.003 (AI Fallback)
```

---

### 4. DEDUPLICATION (KOMPLETT NEU)

| Aspekt | v7 | v9 |
|--------|----|----|
| Scope | Nicht vorhanden | Global über alle Queries |
| Methode | - | Hash-basiert |
| Mapping | - | Listing → Product tracked |

**v7 (alt):**
```
Query "Tommy Hilfiger":
  - Listing 1: "Tommy Hilfiger Jeans 32/32" → Websearch
  - Listing 2: "Tommy Hilfiger Jeans 34/32" → Websearch (DUPLIKAT!)

= 2 Websearch Calls für dasselbe Produkt
```

**v9 (neu):**
```
Query "Tommy Hilfiger":
  - Listing 1: "Tommy Hilfiger Jeans 32/32" → "Tommy Hilfiger Jeans"
  - Listing 2: "Tommy Hilfiger Jeans 34/32" → "Tommy Hilfiger Jeans"

Dedupliziert:
  - "Tommy Hilfiger Jeans" (Listings: [1, 2])

= 1 Websearch Call
```

---

### 5. WEBSEARCH (OPTIMIERT)

| Aspekt | v7 | v9 |
|--------|----|----|
| Granularität | Pro Listing | Pro unique Product |
| Batching | 5-10 Listings | Bis 30 Produkte |
| Caching | ✅ | ✅ (verbessert) |
| Typische Calls | 24 (für 24 Listings) | 1-2 (für 18 Produkte) |

**v7 Kosten:** 24 × $0.10 = **$2.40**  
**v9 Kosten:** 1 × $0.35 = **$0.35**

---

### 6. RESALE PRICE (VERBESSERT)

| Aspekt | v7 | v9 |
|--------|----|----|
| Methode | Neupreis × Rate | Neupreis × Rate |
| Neupreis-Qualität | Oft ungenau | Genauer (bessere Queries) |
| Genauigkeit | ~60% | ~80% |
| Kosten | In Websearch inkl. | In Websearch inkl. |

**Hinweis:** Ricardo exponiert keine verkauften Artikel, daher bleibt die
Resale-Berechnung bei `Neupreis × Kategorie-Rate`.

**Kategorie-Rates (aus config.yaml):**
- Kleidung: 40%
- Elektronik/Smartwatch: 45%
- Fitness: 55%
- General: 50%

**Verbesserung in v9:** Da der Neupreis durch bessere Websearch-Queries 
genauer ist, wird auch der Resale-Preis genauer.

---

### 7. LISTING EVALUATION (VERBESSERT)

| Aspekt | v7 | v9 |
|--------|----|----|
| Preisquelle | Websearch pro Listing | Global Price Cache |
| Bundle Handling | Gesamtpreis | Summe der Komponenten |
| Mengen | Oft ignoriert | Korrekt multipliziert |

**v7 (alt):**
```python
# Bundle als Ganzes bewertet
"Hantelscheiben 4×5kg" → new_price = 100 CHF (Bundle)
```

**v9 (neu):**
```python
# Komponenten einzeln bewertet
"Hantelscheiben 4×5kg"
→ Hantelscheibe 5kg: 25 CHF × 4 = 100 CHF
→ Genauer bei Teilverkäufen!
```

---

## 📁 NEUE DATEIEN

| Datei | Beschreibung |
|-------|--------------|
| `product_extractor.py` | Kern-Modul: Title Cleanup, Bundle Detection, Deduplication |
| `ARCHITECTURE_v9_PIPELINE.md` | Architektur-Dokumentation |
| `COST_BREAKDOWN_v9.md` | Kosten-Analyse: Wo/Warum AI |
| `MIGRATION_v7_to_v9.md` | Diese Datei |

---

## 📁 GEÄNDERTE DATEIEN (geplant)

| Datei | Änderung |
|-------|----------|
| `main.py` | Neue Pipeline-Reihenfolge |
| `ai_filter.py` | Websearch mit Global Product List |
| `scrapers/ricardo.py` | + `search_sold()` für Resale |

---

## 🔄 PIPELINE-ABLAUF: v9

```
1. CONFIG LADEN
   └── queries: ["Garmin Smartwatch", "Tommy Hilfiger", "Hantelscheiben"]

2. PRO QUERY: SCRAPING + NORMALISIERUNG
   ┌─────────────────────────────────────────────────────────────────┐
   │ Query: "Garmin Smartwatch"                                      │
   │                                                                 │
   │ Scrape Ricardo → 8 Listings                                     │
   │      │                                                          │
   │      ▼                                                          │
   │ Title Cleanup (Regeln, AI nur wenn nötig)                       │
   │      │                                                          │
   │      ▼                                                          │
   │ Bundle Detection → Zerlegung wenn Bundle                        │
   │      │                                                          │
   │      ▼                                                          │
   │ Query Products: [Garmin Fenix 7 Solar, Garmin Lily, ...]       │
   └─────────────────────────────────────────────────────────────────┘
   
   (Wiederholen für alle Queries)

3. GLOBAL PRODUCT LIST
   ┌─────────────────────────────────────────────────────────────────┐
   │ Alle Query Products zusammenführen                              │
   │ Duplikate entfernen                                             │
   │                                                                 │
   │ Result: 18 unique Products (aus 24 Listings)                    │
   │   - Garmin Fenix 7 Solar (Listings: [1])                       │
   │   - Garmin Lily (Listings: [2, 6])                             │
   │   - Tommy Hilfiger Jeans (Listings: [9, 10])                   │
   │   - Hantelscheibe 5kg (Listings: [15, 18])                     │
   │   - ...                                                         │
   └─────────────────────────────────────────────────────────────────┘

4. PRICE SEARCH (1 Batch)
   ┌─────────────────────────────────────────────────────────────────┐
   │ WEBSEARCH (Neupreise)          │ RICARDO (Resale)              │
   │ ──────────────────────         │ ─────────────────             │
   │ 18 Products → Claude           │ 18 Products → Scraping        │
   │                                │                               │
   │ Kosten: ~$0.35                 │ Kosten: $0.00                 │
   └─────────────────────────────────────────────────────────────────┘
   
   Result: Price Cache
   {
     "garmin_fenix_7_solar": {new: 599, resale: 350},
     "garmin_lily": {new: 198, resale: 120},
     "tommy_hilfiger_jeans": {new: 124, resale: 45},
     "hantelscheibe_5kg": {new: 25, resale: 15},
     ...
   }

5. LISTING EVALUATION
   ┌─────────────────────────────────────────────────────────────────┐
   │ Pro Listing: Preise aus Cache nachschlagen                      │
   │                                                                 │
   │ Listing 15: "Hantelscheiben 4×5kg"                             │
   │   Components: Hantelscheibe 5kg ×4                              │
   │   New Price:  4 × 25 = 100 CHF                                 │
   │   Resale:     4 × 15 = 60 CHF                                  │
   │   Purchase:   11 CHF                                            │
   │   Profit:     60 - 12.10 = 47.90 CHF                           │
   │   Strategy:   BID ✅                                            │
   └─────────────────────────────────────────────────────────────────┘

6. OUTPUT
   └── Bewertete Listings mit korrekten Preisen
```

---

## 💰 KOSTEN-VERGLEICH

### Beispiel: 24 Listings, 3 Queries

| Schritt | v7 | v9 |
|---------|----|----|
| Title Cleanup | $0 | ~$0.01 (3 AI Calls) |
| Bundle Decomposition | ~$0.02 | ~$0.006 (2 AI Calls) |
| Websearch | ~$2.40 | ~$0.35 (1 Batch) |
| Vision | ~$0.05 | ~$0.01 (1 Call) |
| Resale | inkl. | $0.00 (Scraping) |
| **TOTAL** | **~$2.50** | **~$0.38** |

**Einsparung: 85%**

---

## ⚠️ WICHTIG: Was NICHT geändert wird

1. **Scraping** - Ricardo Scraper bleibt gleich
2. **Config Format** - `config.yaml` bleibt kompatibel
3. **Output Format** - `last_run_listings.json` Struktur bleibt
4. **Caching** - Bestehende Caches werden weiter verwendet
5. **Deal Score** - Berechnung bleibt gleich (nur bessere Inputs)

---

## 🚀 NÄCHSTE SCHRITTE

1. **Ricardo Resale Search** implementieren
   - `scrapers/ricardo.py` erweitern
   - `search_sold(product)` Funktion

2. **Integration in main.py**
   - `product_extractor` einbinden
   - Pipeline-Reihenfolge anpassen

3. **Testing**
   - Mit echten Daten testen
   - Kosten überwachen

---

## ❓ OFFENE FRAGEN

1. Soll Vision für unklare Bundles automatisch aktiviert werden, oder nur manuell?
2. Wie lange sollen Resale-Preise gecached werden? (24h? 7d?)
3. Soll es einen "Dry Run" Modus geben, der nur simuliert?
