# Codebase Audit & Cleanup - 2026-01-20

## 🎯 Ziel
Identifiziere Dead Code, ungenutzte Dateien und weitere Optimierungsmöglichkeiten.

---

## 📊 GEFUNDENE PROBLEME

### **1. DEAD CODE - Ungenutzte Dateien**

#### **A) `db_pg.py` - VERALTET**
- **Status:** ❌ Nicht mehr verwendet
- **Ersetzt durch:** `db_pg_v2.py`
- **Verwendung:** Keine Imports gefunden
- **Aktion:** ✅ **LÖSCHEN**

#### **B) `market_prices.py` - UNGENUTZT**
- **Status:** ❌ Nicht mehr verwendet
- **Verwendung:** Keine Imports gefunden
- **Funktion:** Vermutlich alte Preis-Logik
- **Aktion:** ✅ **LÖSCHEN**

#### **C) `logger_utils.py` - VERALTET**
- **Status:** ❌ Ersetzt durch `logging_utils/`
- **Verwendung:** Nur in `main.py` (2 Imports)
- **Ersetzt durch:** `logging_utils/run_logger.py`
- **Aktion:** ⚠️ **MIGRIEREN dann LÖSCHEN**

#### **D) `utils_logging.py` - REDUNDANT**
- **Status:** ⚠️ Nur 1 Import in `ai_filter.py`
- **Funktion:** Logging-Utilities
- **Problem:** Überschneidung mit `logging_utils/`
- **Aktion:** ⚠️ **KONSOLIDIEREN**

---

### **2. VERALTETE DOKUMENTATION**

#### **Zu viele MD-Dateien im Root:**
```
ARCHITECTURE_v9_PIPELINE.md
CLEANUP_ANALYSIS.md
DB_SCHEMA_V11.md
FIXES_APPLIED_SUMMARY.md
HARDENING_COMPLETE.md
MIGRATION_HARDENING_REPORT.md
TEST_RUN_READY.md
TYPE_SAFETY_FIX_COMPLETE.md
WINDSURF_WORKFLOW.md
```

**Problem:** Unübersichtlich, viele veraltete Infos

**Aktion:** ✅ **ARCHIVIEREN** in `docs/archive/`

**Behalten im Root:**
- `README.md` - Hauptdokumentation
- `HAIKU_4.5_MIGRATION.md` - Aktuell
- `OPTIMIZATION_SUMMARY_2026-01-20.md` - Aktuell
- `SCHEMA_V2.2_RATIONALE.md` - Aktuell

---

### **3. VERALTETE SCHEMA-DATEIEN**

```
schema_v2.sql - VERALTET
schema_v2.1_FINAL.sql - VERALTET
schema_v2.2.1_PATCH.sql - VERALTET
schema_v2.2.2_PATCH.sql - VERALTET
```

**Aktuell:** `schema_v2.2_FINAL.sql`

**Aktion:** ✅ **ARCHIVIEREN** alte Schemas

---

### **4. LEERE DATEIEN**

```
analyze_results.sql - 0 bytes
validate_data.sql - 0 bytes
```

**Aktion:** ✅ **LÖSCHEN**

---

### **5. UNGENUTZTE PIPELINE-FUNKTION**

#### **`process_listing()` in `pipeline_runner.py`**
- **Status:** ⚠️ Definiert aber nicht verwendet
- **Grund:** `process_batch()` nutzt jetzt Batch-Extraktion
- **Problem:** `process_listing()` nutzt noch alte `extract_product_with_ai()`
- **Aktion:** ⚠️ **ENTFERNEN oder AKTUALISIEREN**

---

## 🔍 WEITERE OPTIMIERUNGEN GEFUNDEN

### **OPTIMIERUNG #1: Query Analysis Caching**

**Aktuell:**
```python
# query_analyzer.py
# Cache-File: query_analysis_cache.json
# Cache-Dauer: 30 Tage
```

**Problem:** Cache wird nicht genutzt wenn Queries leicht variieren
```
"Apple Watch Ultra Armband original" → Cache Miss
"Apple Watch Ultra Armband" → Cache Miss (unterschiedlich!)
```

**Lösung:** Normalisiere Queries vor Cache-Lookup
```python
def normalize_query(query: str) -> str:
    # Entferne Füllwörter
    query = query.lower()
    query = re.sub(r'\b(original|neu|gebraucht|wie neu)\b', '', query)
    query = re.sub(r'\s+', ' ', query).strip()
    return query
```

**Ersparnis:** Mehr Cache-Hits = weniger AI-Calls

---

### **OPTIMIERUNG #2: Web Price Cache Konsolidierung**

**Aktuell:**
```python
# ai_filter.py
# Cache-File: web_price_cache.json
# Cache-Dauer: 60 Tage
```

**Problem:** Variant-Keys sind zu spezifisch
```
"Apple AirPods Pro 2. Generation" → Cache
"Apple AirPods Pro 2nd Gen" → Cache Miss (unterschiedlich!)
```

**Lösung:** Normalisiere Produkt-Namen vor Cache
```python
def normalize_product_name(name: str) -> str:
    # "2. Generation" → "2nd Gen" → "Gen 2"
    name = re.sub(r'2\.\s*Generation', '2nd Gen', name)
    name = re.sub(r'2nd\s*Gen', 'Gen 2', name)
    return name.lower().strip()
```

**Ersparnis:** Mehr Cache-Hits = weniger Websearch-Calls ($0.35 pro Call!)

---

### **OPTIMIERUNG #3: Bundle Detection Caching**

**Aktuell:**
```python
# ai_filter.py - detect_bundle_with_ai()
# KEIN CACHE!
```

**Problem:** Gleiche Titel werden mehrfach analysiert
```
"Olympic Gewichtsset 100kg" → AI-Call ($0.012)
"Olympic Gewichtsset 100kg" → AI-Call ($0.012) (wieder!)
```

**Lösung:** Cache Bundle-Detection Ergebnisse
```python
_bundle_cache = {}  # title → bundle_result

def detect_bundle_with_ai(title: str):
    if title in _bundle_cache:
        return _bundle_cache[title]
    
    result = _call_ai(...)
    _bundle_cache[title] = result
    return result
```

**Ersparnis:** ~50% weniger Bundle-Detection Calls

---

### **OPTIMIERUNG #4: Batch-Größe erhöhen**

**Aktuell:**
```python
# ai_filter.py
batch_size = int(40 * 0.8) = 32 Produkte
```

**Problem:** Zu konservativ! Claude Sonnet kann mehr verarbeiten.

**Analyse:**
```
MAX_RESPONSE_TOKENS = 8000
ESTIMATED_TOKENS_PER_PRODUCT = 200
Theoretisch: 8000 / 200 = 40 Produkte
Aktuell: 40 * 0.8 = 32 Produkte (80% Safety Margin)
```

**Lösung:** Erhöhe auf 90% Safety Margin
```python
batch_size = int(40 * 0.9) = 36 Produkte
```

**Ersparnis:**
```
100 Produkte:
- Alt: 100 / 32 = 4 Batches → $1.40
- Neu: 100 / 36 = 3 Batches → $1.05
- Ersparnis: $0.35 (25%)
```

---

### **OPTIMIERUNG #5: Shop-Auswahl Caching**

**Aktuell:**
```python
# ai_filter.py - Zeile 728-760
# Shop-Auswahl wird JEDES MAL neu gemacht
```

**Problem:** Gleiche Kategorie = gleiche Shops, aber AI wird jedes Mal gefragt

**Lösung:** Cache Shop-Auswahl pro Kategorie
```python
_shop_cache = {}  # category → shops

def get_relevant_shops(category: str):
    if category in _shop_cache:
        return _shop_cache[category]
    
    shops = _call_ai(shop_prompt)
    _shop_cache[category] = shops
    return shops
```

**Ersparnis:** Websearch-Calls werden kürzer (weniger Tokens im Prompt)

---

## 📋 CLEANUP-AKTIONEN

### **SOFORT LÖSCHEN (Safe):**
1. ✅ `db_pg.py` - Ersetzt durch `db_pg_v2.py`
2. ✅ `market_prices.py` - Nicht verwendet
3. ✅ `analyze_results.sql` - Leer
4. ✅ `validate_data.sql` - Leer

### **ARCHIVIEREN:**
1. ✅ Alte MD-Dateien → `docs/archive/`
2. ✅ Alte Schema-Dateien → `docs/archive/schemas/`

### **MIGRIEREN DANN LÖSCHEN:**
1. ⚠️ `logger_utils.py` → Migriere zu `logging_utils/`
2. ⚠️ `utils_logging.py` → Konsolidiere mit `logging_utils/`

### **CODE-FIXES:**
1. ⚠️ `pipeline_runner.py` - Entferne oder aktualisiere `process_listing()`
2. ⚠️ `extraction/ai_extractor.py` - Markiere als deprecated (wird durch Batch ersetzt)

---

## 💰 GESCHÄTZTE EINSPARUNGEN DURCH OPTIMIERUNGEN

| Optimierung | Ersparnis pro Run | Wahrscheinlichkeit |
|-------------|-------------------|-------------------|
| Query Normalisierung | ~$0.024 | 50% Cache-Hits |
| Web Price Cache | ~$0.175 | 50% Cache-Hits |
| Bundle Caching | ~$0.012 | 50% Cache-Hits |
| Batch-Größe 36 | ~$0.088 | 25% weniger Batches |
| Shop Caching | ~$0.010 | Token-Reduktion |
| **TOTAL** | **~$0.309** | **Pro Run** |

**Über 10 Runs:** ~$3.09 gespart!

---

## 🚀 EMPFOHLENE REIHENFOLGE

### **Phase 1: Cleanup (Safe, kein Code-Change)**
1. ✅ Lösche ungenutzte Dateien
2. ✅ Archiviere alte Dokumentation
3. ✅ Archiviere alte Schemas

### **Phase 2: Optimierungen (Low-Risk)**
1. ✅ Query Normalisierung
2. ✅ Bundle Detection Caching
3. ✅ Shop-Auswahl Caching

### **Phase 3: Optimierungen (Medium-Risk)**
1. ⚠️ Web Price Cache Normalisierung
2. ⚠️ Batch-Größe erhöhen (36 statt 32)

### **Phase 4: Code-Refactoring**
1. ⚠️ Migriere `logger_utils.py`
2. ⚠️ Konsolidiere `utils_logging.py`
3. ⚠️ Entferne `process_listing()` oder aktualisiere

---

## 📊 ZUSAMMENFASSUNG

### **Dead Code gefunden:**
- 4 Dateien zum Löschen
- 2 Dateien zum Migrieren
- ~15 MD-Dateien zum Archivieren
- 4 Schema-Dateien zum Archivieren

### **Optimierungen gefunden:**
- 5 Caching-Optimierungen
- 1 Batch-Größen-Optimierung
- Geschätzte Ersparnis: ~$0.31 pro Run

### **Nächste Schritte:**
1. User-Bestätigung für Cleanup
2. User-Bestätigung für Optimierungen
3. Implementierung in Phasen

---

**Audit abgeschlossen: 2026-01-20**
**Gefunden: 4 Dead Files, 5 Optimierungen, ~$0.31 Ersparnis/Run**
