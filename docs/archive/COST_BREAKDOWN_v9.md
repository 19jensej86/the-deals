# 💰 KOSTEN-BREAKDOWN: Wo und Warum KI verwendet wird

**Datum:** 2026-01-11  
**Ziel:** Transparenz über jeden AI-Call, dessen Zweck und Kosten

---

## 📊 ÜBERSICHT: AI-VERWENDUNG IN DER PIPELINE

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SCHRITT                          │ AI?  │ KOSTEN    │ WANN?             │
├─────────────────────────────────────────────────────────────────────────┤
│ 1. Scraping                      │ ❌   │ $0.00     │ -                 │
│ 2. Title Cleanup                 │ ⚠️   │ ~$0.01    │ NUR wenn nötig    │
│ 3. Deduplication                 │ ❌   │ $0.00     │ -                 │
│ 4. Bundle Detection              │ ❌   │ $0.00     │ Regelbasiert      │
│ 5. Bundle Decomposition          │ ⚠️   │ ~$0.003   │ NUR wenn unklar   │
│ 6. Vision Analysis               │ ⚠️   │ ~$0.01    │ NUR wenn nötig    │
│ 7. Websearch (Neupreis)          │ ✅   │ ~$0.35    │ 1× pro Produkt    │
│ 8. Ricardo Search (Resale)       │ ❌   │ $0.00     │ Scraping          │
│ 9. Listing Evaluation            │ ❌   │ $0.00     │ Berechnung        │
└─────────────────────────────────────────────────────────────────────────┘

Legende:
  ✅ = Immer AI (unvermeidbar)
  ⚠️ = Nur wenn Regeln nicht ausreichen
  ❌ = Kein AI (Regeln/Scraping)
```

---

## 🔍 DETAIL: Jeder AI-Aufruf erklärt

---

### SCHRITT 2: TITLE CLEANUP

#### Wann wird AI verwendet?

```
ENTSCHEIDUNGSBAUM:

Titel erhalten
     │
     ▼
┌─────────────────────────────────┐
│ Kann Titel mit REGELN bereinigt │
│ werden?                         │
└─────────────────────────────────┘
     │
     ├── JA → Regex-basierte Bereinigung ($0.00)
     │        - Farben entfernen
     │        - Grössen entfernen
     │        - Zustand entfernen
     │
     └── NEIN → AI Title Cleanup ($0.003)
              Gründe:
              - Fremdsprache (Veste = Jacke)
              - Unklare Produktkategorie
              - Komplexe Modellbezeichnung
```

#### Wann REGELN ausreichen (kein AI):

```python
# Diese Fälle können mit Regex gelöst werden:

"Tommy Hilfiger Winterjacke Herren Grösse L"
→ Regex entfernt: "Grösse L"
→ Ergebnis: "Tommy Hilfiger Winterjacke Herren"
→ Kosten: $0.00

"Garmin Fenix 7 Sapphire Solar, Top Zustand"
→ Regex entfernt: "Top Zustand", ","
→ Ergebnis: "Garmin Fenix 7 Sapphire Solar"
→ Kosten: $0.00
```

#### Wann AI nötig ist:

```python
# Fall 1: Fremdsprache
"Veste Tommy Hilfiger"
→ Regel kann nicht erkennen: Veste = Jacke (Französisch)
→ AI nötig
→ Kosten: $0.003

# Fall 2: Unklare Kategorisierung
"44 NEU Hilfiger Lederschuhe Lederstiefel Sneaker Herrenschuh"
→ Mehrere Produkttypen genannt (Schuhe, Stiefel, Sneaker)
→ Welches ist das Hauptprodukt?
→ AI nötig
→ Kosten: $0.003

# Fall 3: Marketingtext vs. Modellname
"Garmin Fenix 7 PRO Solar EDITION"
→ Ist "EDITION" Teil des Modellnamens oder Marketing?
→ Bei Garmin: könnte beides sein
→ AI nötig (oder Produktdatenbank)
→ Kosten: $0.003
```

#### AI Prompt (wenn verwendet):

```
AUFGABE: Bereinige diesen Inseratstitel für eine Websearch.

REGELN:
✅ BEHALTEN:
- Marke (aus Query: "{query}")
- Modellname und -nummer
- Preisrelevante Features (Solar, Pro, Sapphire, etc.)
- Geschlecht (Herren/Damen/Kinder)
- Produkttyp-Unterschiede (Winterjacke ≠ Jacke)

❌ ENTFERNEN:
- Farbe
- Zustand (neu, gebraucht, etc.)
- Grösse
- Marketingtext
- "inkl.", "mit OVP", etc.

QUERY: {query}
TITEL: {title}

Antworte NUR mit dem bereinigten Titel.
```

**Kosten:** ~$0.003 (Claude Haiku, ~500 tokens)

---

### SCHRITT 4-5: BUNDLE DETECTION & DECOMPOSITION

#### Bundle Detection (IMMER regelbasiert, $0.00):

```python
BUNDLE_INDICATORS = [
    # Explizite Indikatoren
    "inkl", "inklusive", "mit", "plus", "+", "und", "&",
    "set", "bundle", "paket", "komplett", "zusammen",
    
    # Mengen-Indikatoren
    r'\d+\s*(?:stk|×|x)',  # "4 Stk", "2×", "3x"
    r'\d+\s*(?:stück|paar)',
]

def is_bundle(title: str) -> bool:
    """
    Regelbasierte Bundle-Erkennung.
    KEIN AI nötig!
    """
    title_lower = title.lower()
    
    for indicator in BUNDLE_INDICATORS:
        if indicator in title_lower:
            return True
    
    # Regex für Mengen
    if re.search(r'\d+\s*(?:stk|×|x|stück)', title_lower):
        return True
    
    return False
```

**Beispiele:**

| Titel | Bundle? | Regel |
|-------|---------|-------|
| "Garmin Fenix 7 **inkl.** Zubehör" | ✅ | "inkl" erkannt |
| "Hantelscheiben **Set** 4x 5kg" | ✅ | "Set", "4x" erkannt |
| "Tommy Hilfiger Jacke" | ❌ | Kein Indikator |
| "**Komplettes** Homegym" | ✅ | "Komplett" erkannt |

#### Bundle Decomposition - Wann AI nötig ist:

```
ENTSCHEIDUNGSBAUM:

Bundle erkannt
     │
     ▼
┌─────────────────────────────────┐
│ Sind alle Komponenten aus dem   │
│ TITEL klar erkennbar?           │
└─────────────────────────────────┘
     │
     ├── JA → Regex-Extraktion ($0.00)
     │        "Hantelscheiben 4×5kg + Ständer"
     │        → Hantelscheibe 5kg ×4
     │        → Hantelständer ×1
     │
     └── NEIN → Prüfe BESCHREIBUNG
              │
              ▼
         ┌─────────────────────────────────┐
         │ Sind Komponenten in BESCHREIBUNG│
         │ klar aufgelistet?               │
         └─────────────────────────────────┘
              │
              ├── JA → Regex-Extraktion ($0.00)
              │
              └── NEIN → AI Bundle Decomposition ($0.003)
                       ODER Vision ($0.01)
```

#### Wann REGELN ausreichen:

```python
# Klarer Titel
"Hantelscheiben, 2 Stk. à 10kg"
→ Regex: (\d+)\s*Stk.*?(\d+)\s*kg
→ Ergebnis: Hantelscheibe 10kg ×2
→ Kosten: $0.00

# Klare Beschreibung
Titel: "Komplettes Fitness-Set"
Beschreibung: "- 2× Kurzhantel 5kg
               - 4× Hantelscheibe 2.5kg
               - 1× Hantelständer"
→ Regex parsed Liste
→ Kosten: $0.00
```

#### Wann AI nötig ist:

```python
# Fall 1: Unklare Zusammensetzung
Titel: "Komplettes Homegym"
Beschreibung: "Alles was du brauchst für dein Training!"
→ KEINE konkreten Komponenten genannt
→ AI oder Vision nötig
→ Kosten: $0.003-$0.01

# Fall 2: Implizite Mengen
Titel: "100kg Bumper Plates Set"
→ 100kg ist NICHT eine einzelne Scheibe
→ Muss in realistische Scheiben aufgeteilt werden
→ AI nötig (oder Fitness-Heuristik)
→ Kosten: $0.003

# Fall 3: Smartwatch Bundle
Titel: "Garmin Fenix 6 inkl. Zubehör"
→ Was ist "Zubehör"? Armband? Ladekabel? Brustgurt?
→ AI oder Vision nötig
→ Kosten: $0.003-$0.01
```

#### AI Prompt für Bundle Decomposition:

```
AUFGABE: Zerlege dieses Bundle in Einzelprodukte.

TITEL: {title}
BESCHREIBUNG: {description}
KATEGORIE: {category}

Extrahiere ALLE enthaltenen Produkte mit:
- Produktname (normalisiert, Singular)
- Menge
- Relevante Specs (Gewicht, Grösse, etc.)

WICHTIG:
- "100kg Bumper Plates" ≠ 1× 100kg Scheibe
- Realistische Einzelprodukte auflisten
- Keine Phantasie-Produkte erfinden

Antworte als JSON:
[
  {"name": "...", "quantity": 1, "specs": {}},
  ...
]
```

**Kosten:** ~$0.003 (Claude Haiku)

---

### SCHRITT 6: VISION ANALYSIS

#### Wann wird Vision verwendet?

```
ENTSCHEIDUNGSBAUM:

Bundle erkannt, aber unklar
     │
     ▼
┌─────────────────────────────────┐
│ Hat AI Decomposition genug      │
│ Informationen geliefert?        │
└─────────────────────────────────┘
     │
     ├── JA → Fertig ($0.003 für AI)
     │
     └── NEIN → Hat das Inserat BILDER?
              │
              ├── JA → Vision Analysis ($0.01)
              │
              └── NEIN → Fallback auf Schätzung
```

#### Konkrete Fälle für Vision:

```python
# Fall 1: Titel und Beschreibung zu vage
Titel: "Fitness Equipment"
Beschreibung: "Verschiedene Gewichte und Zubehör"
Bild: [Foto zeigt: 2 Langhanteln, 8 Scheiben, 1 Rack]
→ NUR Vision kann die Komponenten erkennen
→ Kosten: $0.01

# Fall 2: Gewichte nicht im Text erkennbar
Titel: "Hantelscheiben Set"
Beschreibung: "Wie auf dem Bild"
Bild: [Foto zeigt Scheiben mit sichtbaren Gewichtsangaben]
→ Vision liest Gewichte vom Bild ab
→ Kosten: $0.01

# Fall 3: Zustand/Vollständigkeit prüfen
Titel: "Garmin Fenix 7 mit allem Zubehör"
Bild: [Foto zeigt: Uhr, 2 Armbänder, Ladekabel, Box]
→ Vision identifiziert tatsächliches Zubehör
→ Kosten: $0.01
```

#### Vision Prompt:

```
AUFGABE: Analysiere dieses Produktbild.

KONTEXT:
- Titel: {title}
- Kategorie: {category}
- Query: {query}

IDENTIFIZIERE:
1. Alle sichtbaren Produkte/Komponenten
2. Mengen (zähle!)
3. Bei Gewichten: lies Gewichtsangaben ab
4. Bei Elektronik: Modellnummer wenn sichtbar
5. Zustand (falls erkennbar)

WICHTIG:
- Nur beschreiben was SICHTBAR ist
- Keine Annahmen
- Bei Unsicherheit: "unklar" angeben

Antworte als JSON:
{
  "components": [
    {"name": "...", "quantity": 1, "specs": {}, "confidence": 0.9},
    ...
  ],
  "overall_condition": "gut/mittel/schlecht/unklar",
  "notes": "..."
}
```

**Kosten:** ~$0.01 (Claude Sonnet + Vision)

---

### SCHRITT 7: WEBSEARCH (NEUPREIS)

#### Immer AI (unvermeidbar):

```
Websearch ist IMMER ein AI-Call.
Es gibt keine regelbasierte Alternative.

ABER: Wir minimieren Kosten durch:
1. Deduplizierung (24 Listings → 18 unique Products)
2. Batching (18 Products in 1 Call statt 18 Calls)
3. Caching (gleiches Produkt nicht 2× suchen)
```

#### Websearch Prompt:

```
Finde Schweizer Neupreise (CHF) für diese {n} Produkte.

PRODUKTE:
1. {product_1}
2. {product_2}
...

SHOPS (in dieser Reihenfolge prüfen):
- Digitec.ch, Galaxus.ch (Elektronik)
- Zalando.ch, AboutYou.ch (Kleidung)
- Decathlon.ch (Fitness)

Antworte als JSON-Array:
[
  {"nr": 1, "price": 199.00, "shop": "Galaxus", "confidence": 0.9},
  {"nr": 2, "price": null, "shop": null, "confidence": 0.0},
  ...
]

Bei unbekannt: price=null, confidence=0
```

**Kosten:** ~$0.35 pro Batch (bis 30 Produkte)

---

### SCHRITT 8: RICARDO RESALE SEARCH

#### Kein AI - Nur Scraping:

```python
def search_resale_price(product: str) -> float:
    """
    Sucht Resale-Preis auf Ricardo.
    KEIN AI - nur Scraping!
    """
    # 1. Ricardo Suche nach "verkauft" Artikeln
    url = f"https://www.ricardo.ch/de/s/{product}?sold=true"
    
    # 2. Scrape Ergebnisse
    sold_listings = scrape_ricardo_results(url)
    
    # 3. Median berechnen
    prices = [l.final_price for l in sold_listings]
    return statistics.median(prices)

# Kosten: $0.00 (nur HTTP requests)
```

---

## 📈 ZUSAMMENFASSUNG: Kosten pro Szenario

### Szenario A: Einfaches Listing (kein Bundle)

```
"Tommy Hilfiger Winterjacke Herren L"

Step 2: Title Cleanup      → Regex      → $0.00
Step 4: Bundle Detection   → Regel      → $0.00
Step 7: Websearch          → AI         → $0.02 (anteilig)
Step 8: Resale Search      → Scraping   → $0.00
─────────────────────────────────────────────────
TOTAL:                                    $0.02
```

### Szenario B: Bundle mit klarem Titel

```
"Hantelscheiben Set 4×5kg + Ständer"

Step 2: Title Cleanup      → Regex      → $0.00
Step 4: Bundle Detection   → Regel      → $0.00
Step 5: Decomposition      → Regex      → $0.00
Step 7: Websearch (2 Prod) → AI         → $0.04 (anteilig)
Step 8: Resale Search      → Scraping   → $0.00
─────────────────────────────────────────────────
TOTAL:                                    $0.04
```

### Szenario C: Bundle mit unklarem Titel

```
"Komplettes Homegym inkl. allem"

Step 2: Title Cleanup      → AI         → $0.003
Step 4: Bundle Detection   → Regel      → $0.00
Step 5: Decomposition      → AI         → $0.003
Step 6: Vision (wenn nötig)→ AI         → $0.01
Step 7: Websearch (N Prod) → AI         → $0.10 (anteilig)
Step 8: Resale Search      → Scraping   → $0.00
─────────────────────────────────────────────────
TOTAL:                                    $0.12
```

### Szenario D: Fremdsprachiges Listing

```
"Veste Tommy Hilfiger pour femme"

Step 2: Title Cleanup      → AI         → $0.003
Step 4: Bundle Detection   → Regel      → $0.00
Step 7: Websearch          → AI         → $0.02 (anteilig)
Step 8: Resale Search      → Scraping   → $0.00
─────────────────────────────────────────────────
TOTAL:                                    $0.02
```

---

## 🎯 OPTIMIERUNGS-PRINZIPIEN

### 1. Regeln vor AI

```
IMMER zuerst versuchen:
1. Regex-basierte Extraktion
2. Keyword-Matching
3. Hardcoded Heuristiken (Fitness!)

NUR wenn das nicht reicht → AI
```

### 2. Batching maximieren

```
SCHLECHT: 24 einzelne Websearch Calls = 24 × $0.10 = $2.40
GUT:      1 Batch mit 24 Produkten    = 1  × $0.35 = $0.35
```

### 3. Caching nutzen

```
Produkt "Tommy Hilfiger Jeans" wurde heute schon gesucht?
→ Aus Cache laden, kein neuer AI Call
```

### 4. Vision nur als letztes Mittel

```
Vision ist 3× teurer als Text-AI.
Nur verwenden wenn:
- Titel UND Beschreibung unklar
- Bild tatsächlich Mehrwert bietet
```

---

## 💰 ERWARTETE KOSTEN PRO RUN

### 24 Listings, 3 Queries

| Schritt | Häufigkeit | Kosten |
|---------|------------|--------|
| Title Cleanup (AI) | ~3 (12%) | $0.01 |
| Bundle Decomposition (AI) | ~2 (8%) | $0.006 |
| Vision | ~1 (4%) | $0.01 |
| Websearch | 1 Batch | $0.35 |
| **TOTAL** | | **~$0.38** |

**Vergleich zu v7.x: $2.50 → $0.38 = 85% Einsparung**
