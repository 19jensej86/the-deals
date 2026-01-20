# 🎯 DESIGN: Query-Driven Normalization System v8.0

**Datum:** 2026-01-11  
**Prinzip:** Markenagnostisch, Query-Driven, Regelbasiert

---

## 📐 ARCHITEKTUR-ÜBERSICHT

```
User Query ──────────────────────────────────────────────────────────┐
     │                                                                │
     ▼                                                                │
┌─────────────────────────────────────────────────────────────────┐   │
│  1. QUERY ANALYZER                                               │   │
│  ────────────────                                                │   │
│  Extrahiert aus User-Query:                                      │   │
│  • brand (falls vorhanden)                                       │   │
│  • product_type                                                  │   │
│  • target_group (Herren/Damen/Kinder)                           │   │
│  • category (fitness/electronics/clothing/general)               │   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. LISTING PROCESSOR (pro Inserat)                              │
│  ──────────────────────────────                                  │
│  Input: Titel + Description + (optional) Image                   │
│                                                                  │
│  2a. ATTRIBUTE EXTRACTOR                                         │
│      • Farbe, Grösse, Zustand → ENTFERNEN                       │
│      • Menge/Quantity → EXTRAHIEREN                             │
│      • Gewicht/Specs → BEHALTEN (category-abhängig)             │
│                                                                  │
│  2b. BUNDLE DETECTOR                                             │
│      • Ist es ein Bundle?                                        │
│      • Falls ja → Komponenten auflisten                         │
│      • Falls unklar → Vision verwenden                          │
│                                                                  │
│  2c. SINGULAR NORMALIZER                                         │
│      • Plural → Singular                                         │
│      • "Hantelscheiben" → "Hantelscheibe"                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. WEBSEARCH QUERY BUILDER                                      │
│  ──────────────────────────────                                  │
│  Kombiniert:                                                     │
│  • Brand (aus User-Query, NICHT aus Inserat)                    │
│  • Normalisierter Produkttyp                                     │
│  • Target Group (falls preisrelevant)                           │
│  • Specs (falls category = fitness)                             │
│                                                                  │
│  Output: Saubere Websearch-Query                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. PRICE AGGREGATOR                                             │
│  ───────────────────                                             │
│  • Neupreis pro Komponente                                       │
│  • × Quantity                                                    │
│  • = Gesamt-Neupreis                                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 MODUL 1: QUERY ANALYZER

### Funktionalität

```python
def analyze_user_query(query: str) -> Dict[str, Any]:
    """
    Analysiert den User-Query und extrahiert Kernattribute.
    
    KEINE Markenlisten! Marke = erstes Wort/Phrase vor Produkttyp.
    
    Returns:
        {
            "brand": Optional[str],       # z.B. "Tommy Hilfiger"
            "product_type": str,          # z.B. "Pullover"
            "target_group": Optional[str], # "Herren" / "Damen" / "Kinder"
            "category": str,              # "fitness" / "electronics" / "clothing" / "general"
            "raw_query": str,
        }
    """
```

### Regelwerk (markenagnostisch)

```python
# Produkttypen die Kategorien definieren (NICHT Marken!)
PRODUCT_TYPE_CATEGORIES = {
    "fitness": [
        "hantel", "scheibe", "gewicht", "langhantel", "kurzhantel",
        "kettlebell", "rack", "bank", "stange", "bumper", "plate",
    ],
    "electronics": [
        "smartphone", "handy", "tablet", "laptop", "notebook", "watch",
        "smartwatch", "kopfhörer", "headphones", "tv", "fernseher",
        "kamera", "camera", "konsole", "playstation", "xbox", "switch",
    ],
    "clothing": [
        "jacke", "jacket", "pullover", "sweater", "hoodie", "hemd",
        "shirt", "hose", "jeans", "kleid", "dress", "rock", "mantel",
        "coat", "tasche", "bag", "schuhe", "shoes", "sneaker",
    ],
}

TARGET_GROUPS = ["herren", "damen", "kinder", "boys", "girls", "men", "women"]

def analyze_user_query(query: str) -> Dict[str, Any]:
    query_lower = query.lower().strip()
    words = query_lower.split()
    
    # 1. Finde Produkttyp
    product_type = None
    product_type_pos = len(words)
    category = "general"
    
    for cat, types in PRODUCT_TYPE_CATEGORIES.items():
        for pt in types:
            if pt in query_lower:
                pos = query_lower.find(pt)
                word_pos = len(query_lower[:pos].split())
                if word_pos < product_type_pos:
                    product_type = pt
                    product_type_pos = word_pos
                    category = cat
                break
    
    # 2. Alles VOR Produkttyp = Marke
    brand = None
    if product_type_pos > 0:
        brand_words = words[:product_type_pos]
        # Filtere Target Groups aus Brand
        brand_words = [w for w in brand_words if w not in TARGET_GROUPS]
        if brand_words:
            brand = " ".join(brand_words).title()
    
    # 3. Finde Target Group
    target_group = None
    for tg in TARGET_GROUPS:
        if tg in query_lower:
            target_group = tg.title()
            break
    
    # 4. Falls kein Produkttyp gefunden, Query = Produkttyp
    if not product_type:
        # Entferne Target Group, Rest = Produkttyp
        remaining = [w for w in words if w not in TARGET_GROUPS]
        product_type = " ".join(remaining) if remaining else query
    
    return {
        "brand": brand,
        "product_type": product_type,
        "target_group": target_group,
        "category": category,
        "raw_query": query,
    }
```

### Beispiele

| User Query | Brand | Product Type | Target Group | Category |
|------------|-------|--------------|--------------|----------|
| "Tommy Hilfiger Pullover" | Tommy Hilfiger | pullover | - | clothing |
| "Garmin Fenix 7" | Garmin | fenix 7 | - | electronics |
| "Hantelscheiben 50mm" | - | hantelscheibe | - | fitness |
| "Nike Sneaker Herren" | Nike | sneaker | Herren | clothing |
| "iPhone 14 Pro" | - | iphone 14 pro | - | electronics |

---

## 🔧 MODUL 2: LISTING PROCESSOR

### 2a. Attribute Extractor

```python
# Preisirrelevante Attribute (IMMER entfernen)
PRICE_IRRELEVANT = {
    "colors": [
        "schwarz", "weiss", "blau", "rot", "grün", "gelb", "grau",
        "braun", "pink", "lila", "orange", "beige", "navy", "bordeaux",
        "black", "white", "blue", "red", "green", "grey", "brown",
    ],
    "conditions": [
        "neu", "neuwertig", "wie neu", "top", "super", "gut", "sehr gut",
        "gebraucht", "defekt", "beschädigt", "original", "ovp", "unbenutzt",
        "new", "used", "mint", "excellent", "good",
    ],
    "sizes": [
        "xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl",
        r"\d{2}/\d{2}",  # 32/32 für Jeans
        r"gr\.?\s*\d+",  # Gr. 42
        r"grösse\s*\d+",
        r"size\s*\d+",
    ],
}

def extract_attributes(title: str, query_analysis: Dict) -> Dict[str, Any]:
    """
    Extrahiert und klassifiziert Attribute aus Inserat-Titel.
    
    Returns:
        {
            "cleaned_title": str,      # Titel ohne irrelevante Attribute
            "quantity": int,           # Erkannte Menge (default 1)
            "specs": Dict,             # Category-spezifische Specs
            "removed": List[str],      # Was entfernt wurde
        }
    """
    title_lower = title.lower()
    removed = []
    
    # 1. Entferne Farben
    for color in PRICE_IRRELEVANT["colors"]:
        if re.search(rf'\b{color}\b', title_lower):
            title = re.sub(rf'\b{color}\b', '', title, flags=re.IGNORECASE)
            removed.append(f"color:{color}")
    
    # 2. Entferne Zustandsbeschreibungen
    for cond in PRICE_IRRELEVANT["conditions"]:
        if re.search(rf'\b{cond}\b', title_lower):
            title = re.sub(rf'\b{cond}\b', '', title, flags=re.IGNORECASE)
            removed.append(f"condition:{cond}")
    
    # 3. Entferne Grössen
    for size_pattern in PRICE_IRRELEVANT["sizes"]:
        if re.search(size_pattern, title_lower):
            title = re.sub(size_pattern, '', title, flags=re.IGNORECASE)
            removed.append(f"size:{size_pattern}")
    
    # 4. Extrahiere Quantity
    quantity = 1
    qty_patterns = [
        (r'(\d+)\s*(?:stk\.?|stück|x)\b', 1),
        (r'(\d+)\s*×', 1),
        (r'\bpaar\b', 2),
        (r'\bset\s+(?:von\s+)?(\d+)', 1),
    ]
    for pattern, group_or_val in qty_patterns:
        match = re.search(pattern, title_lower)
        if match:
            if isinstance(group_or_val, int) and group_or_val > 0:
                try:
                    quantity = int(match.group(group_or_val))
                except:
                    quantity = group_or_val
            else:
                quantity = group_or_val
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
            break
    
    # 5. Extrahiere category-spezifische Specs
    specs = {}
    if query_analysis.get("category") == "fitness":
        # Gewicht
        weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', title_lower)
        if weight_match:
            specs["weight_kg"] = float(weight_match.group(1).replace(',', '.'))
        
        # Durchmesser
        diameter_match = re.search(r'(\d+)\s*mm', title_lower)
        if diameter_match:
            specs["diameter_mm"] = int(diameter_match.group(1))
        
        # Material
        if "gusseisen" in title_lower or "cast iron" in title_lower:
            specs["material"] = "gusseisen"
        elif "gummi" in title_lower or "rubber" in title_lower:
            specs["material"] = "gummi"
    
    # 6. Cleanup
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', title)
    
    return {
        "cleaned_title": title,
        "quantity": quantity,
        "specs": specs,
        "removed": removed,
    }
```

### 2b. Bundle Detector

```python
BUNDLE_INDICATORS = [
    "inkl", "inklusive", "mit", "plus", "+", "und", "&", "samt",
    "set", "bundle", "paket", "komplett", "zusammen",
]

def detect_bundle(title: str, description: str, query_analysis: Dict) -> Dict[str, Any]:
    """
    Erkennt ob Inserat ein Bundle ist.
    
    Returns:
        {
            "is_bundle": bool,
            "components": List[Dict],  # Wenn erkannt
            "needs_vision": bool,      # Wenn unklar
            "confidence": float,
        }
    """
    title_lower = title.lower()
    desc_lower = (description or "").lower()
    combined = f"{title_lower} {desc_lower}"
    
    # Check für Bundle-Indikatoren
    has_indicator = any(ind in combined for ind in BUNDLE_INDICATORS)
    
    # Check für multiple Mengenangaben
    quantities = re.findall(r'\d+\s*(?:stk|x|×)', combined)
    has_multiple_qty = len(quantities) > 1
    
    # Check für Aufzählungen
    has_list = bool(re.search(r'(?:\d+\.\s|\-\s|•)', combined))
    
    is_bundle = has_indicator or has_multiple_qty or has_list
    needs_vision = is_bundle and not has_list  # Wenn Bundle aber keine klare Liste
    
    components = []
    if is_bundle and has_list:
        # Versuche Komponenten zu extrahieren
        lines = re.split(r'[\n•\-]', combined)
        for line in lines:
            line = line.strip()
            if len(line) > 3:
                components.append({
                    "raw": line,
                    "quantity": 1,
                    "parsed": False,
                })
    
    return {
        "is_bundle": is_bundle,
        "components": components,
        "needs_vision": needs_vision,
        "confidence": 0.9 if has_list else 0.6 if has_indicator else 0.3,
    }
```

### 2c. Singular Normalizer

```python
# Deutsche Plural → Singular Regeln
PLURAL_RULES = [
    # -en Endung
    (r'scheiben$', 'scheibe'),
    (r'hanteln$', 'hantel'),
    (r'jacken$', 'jacke'),
    (r'hosen$', 'hose'),
    (r'taschen$', 'tasche'),
    (r'schuhen$', 'schuh'),
    
    # -e Endung
    (r'pullover$', 'pullover'),  # bleibt gleich
    
    # -s Endung (Englisch)
    (r'plates$', 'plate'),
    (r'shoes$', 'shoe'),
    (r'bags$', 'bag'),
    
    # Spezialfälle
    (r'jeans$', 'jeans'),  # bleibt gleich
]

def normalize_singular(text: str) -> str:
    """Konvertiert Plural zu Singular."""
    text_lower = text.lower()
    
    for pattern, replacement in PLURAL_RULES:
        if re.search(pattern, text_lower):
            return re.sub(pattern, replacement, text_lower)
    
    return text
```

---

## 🔧 MODUL 3: WEBSEARCH QUERY BUILDER

```python
def build_websearch_query(
    query_analysis: Dict,
    listing_data: Dict,
) -> List[Dict[str, Any]]:
    """
    Baut Websearch-Query(s) aus Query-Analyse und Listing-Daten.
    
    Args:
        query_analysis: Output von analyze_user_query()
        listing_data: Output von Listing Processor
    
    Returns:
        Liste von Search-Queries mit Quantity:
        [
            {"query": "Tommy Hilfiger Pullover", "quantity": 1},
            {"query": "Hantelscheibe 10kg 50mm", "quantity": 2},
        ]
    """
    queries = []
    
    # Basis-Query aus User-Query
    brand = query_analysis.get("brand", "")
    target_group = query_analysis.get("target_group", "")
    category = query_analysis.get("category", "general")
    
    # Ist es ein Bundle?
    if listing_data.get("is_bundle") and listing_data.get("components"):
        # Pro Komponente eine Query
        for comp in listing_data["components"]:
            comp_query = build_component_query(
                component=comp,
                brand=brand,
                category=category,
            )
            queries.append(comp_query)
    else:
        # Einzelprodukt
        product_type = normalize_singular(listing_data.get("product_type", ""))
        
        # Query zusammenbauen
        parts = []
        if brand:
            parts.append(brand)
        if product_type:
            parts.append(product_type)
        if target_group and category == "clothing":
            parts.append(target_group)
        
        # Fitness: Specs hinzufügen
        if category == "fitness":
            specs = listing_data.get("specs", {})
            if specs.get("weight_kg"):
                parts.append(f"{specs['weight_kg']}kg")
            if specs.get("diameter_mm"):
                parts.append(f"{specs['diameter_mm']}mm")
        
        query = " ".join(parts)
        quantity = listing_data.get("quantity", 1)
        
        queries.append({
            "query": query,
            "quantity": quantity,
        })
    
    return queries


def build_component_query(component: Dict, brand: str, category: str) -> Dict:
    """Baut Query für eine Bundle-Komponente."""
    raw = component.get("raw", "")
    quantity = component.get("quantity", 1)
    
    # Extrahiere Produkttyp aus Komponente
    # (Marke kommt vom User-Query, nicht aus Komponente!)
    
    # Vereinfachte Extraktion
    cleaned = extract_attributes(raw, {"category": category})
    product_type = normalize_singular(cleaned["cleaned_title"])
    
    parts = []
    if brand:
        parts.append(brand)
    parts.append(product_type)
    
    if category == "fitness" and cleaned.get("specs"):
        specs = cleaned["specs"]
        if specs.get("weight_kg"):
            parts.append(f"{specs['weight_kg']}kg")
    
    return {
        "query": " ".join(parts),
        "quantity": quantity * cleaned.get("quantity", 1),
    }
```

---

## 📋 BEISPIELE

### Beispiel 1: Kleidung

```
User Query: "Tommy Hilfiger"
Inserat:    "Top Tommy Hilfiger Winterjacke Herren XL guter Zustand grün"

→ Query Analysis:
  brand: "Tommy Hilfiger"
  product_type: None (kein Produkttyp im Query)
  category: "general"

→ Attribute Extraction:
  removed: ["color:grün", "condition:top", "condition:guter zustand", "size:xl"]
  cleaned_title: "Tommy Hilfiger Winterjacke Herren"
  quantity: 1

→ Websearch Query:
  "Tommy Hilfiger Winterjacke Herren"
  quantity: 1
```

### Beispiel 2: Elektronik

```
User Query: "Garmin Fenix 7"
Inserat:    "Garmin Fenix 7 Sapphire Solar neuwertig mit OVP"

→ Query Analysis:
  brand: "Garmin"
  product_type: "fenix 7"
  category: "electronics"

→ Attribute Extraction:
  removed: ["condition:neuwertig", "condition:ovp"]
  cleaned_title: "Garmin Fenix 7 Sapphire Solar"
  quantity: 1

→ Websearch Query:
  "Garmin Fenix 7 Sapphire Solar"
  quantity: 1
```

### Beispiel 3: Fitness Bundle

```
User Query: "Hantelscheiben 50mm"
Inserat:    "Hantelscheiben Set 4x 10kg + 4x 5kg Gusseisen 50mm inkl. Ständer"

→ Query Analysis:
  brand: None
  product_type: "hantelscheibe"
  category: "fitness"

→ Bundle Detection:
  is_bundle: True
  components:
    - "4x 10kg Hantelscheibe Gusseisen 50mm"
    - "4x 5kg Hantelscheibe Gusseisen 50mm"
    - "1x Hantelständer"

→ Websearch Queries:
  1. "Hantelscheibe 10kg 50mm Gusseisen" × 4
  2. "Hantelscheibe 5kg 50mm Gusseisen" × 4
  3. "Hantelständer" × 1

→ Preis-Aggregation:
  Neupreis 10kg: 35 CHF × 4 = 140 CHF
  Neupreis 5kg:  20 CHF × 4 =  80 CHF
  Neupreis Ständer:         =  60 CHF
  ─────────────────────────────────────
  Gesamt-Neupreis:          = 280 CHF
```

### Beispiel 4: Fitness mit Vision

```
User Query: "Hantelscheiben"
Inserat:    "Hantelscheiben Set komplett" (Titel unklar)
Bild:       [Foto zeigt diverse Scheiben]

→ Bundle Detection:
  is_bundle: True
  needs_vision: True

→ Vision Analysis:
  "Ich sehe:
   - 2× große schwarze Scheiben (geschätzt 20kg)
   - 4× mittlere Scheiben (geschätzt 10kg)
   - 4× kleine Scheiben (geschätzt 5kg)
   - Durchmesser erscheint 50mm (Olympic)
   - Material: Gusseisen"

→ Websearch Queries:
  1. "Hantelscheibe 20kg 50mm" × 2
  2. "Hantelscheibe 10kg 50mm" × 4
  3. "Hantelscheibe 5kg 50mm" × 4
```

---

## 💰 KOSTENABSCHÄTZUNG

### Aktuell (v7.3.x)
| Schritt | Kosten | Häufigkeit |
|---------|--------|------------|
| Web Search pro Query | $0.35 | ~5-10 pro Run |
| AI Bundle Detection | $0.003 | pro Listing |
| Vision Analysis | $0.01 | 20% der Bundles |
| **Total pro Run** | **$1.75-3.50** | |

### Nach v8.0
| Schritt | Kosten | Häufigkeit |
|---------|--------|------------|
| Query Normalization | $0.00 | Regelbasiert |
| Attribute Extraction | $0.00 | Regelbasiert |
| Bundle Detection | $0.00 | Regelbasiert |
| Vision (nur wenn nötig) | $0.01 | ~5% der Listings |
| Web Search (dedupliziert) | $0.35 | ~1-2 pro Run |
| **Total pro Run** | **$0.35-0.70** | |

**Einsparung: 80%**

---

## 🔄 MIGRATION VON v7.3 → v8.0

### Phase 1: Aufräumen (SOFORT)
1. ❌ `CLOTHING_BRANDS` Liste entfernen
2. ❌ `CLOTHING_NOT_ACCESSORY` entfernen
3. ✅ `analyze_user_query()` implementieren

### Phase 2: Attribute Extraction (DIESE WOCHE)
1. ✅ `extract_attributes()` implementieren
2. ✅ `PRICE_IRRELEVANT` Listen definieren
3. ✅ `normalize_singular()` implementieren

### Phase 3: Bundle Detection (NÄCHSTE WOCHE)
1. ✅ `detect_bundle()` implementieren
2. ✅ Vision-Integration für unklare Bundles
3. ✅ Komponenten-Parsing

### Phase 4: Query Builder (DANACH)
1. ✅ `build_websearch_query()` implementieren
2. ✅ Query-Deduplizierung
3. ✅ Preis-Aggregation

---

## ❗ DESIGN-PRINZIPIEN (NICHT VERLETZEN)

| ✅ ERLAUBT | ❌ VERBOTEN |
|-----------|-------------|
| Produkttyp-Listen | Marken-Listen |
| Regelbasierte Extraktion | AI pro Inserat (wenn Regeln reichen) |
| Fitness-Heuristiken (hardcoded) | Marken-spezifische Sonderfälle |
| Query-driven Brand Detection | Marken im Code hinzufügen |
| Generische Attribut-Entfernung | Per-Kategorie Sonderlogik |

---

## 📝 ZUSAMMENFASSUNG

Das neue System:

1. **Ist markenagnostisch** - Marke kommt aus User-Query, nicht aus Code
2. **Ist regelbasiert** - Keine AI wo Regeln reichen
3. **Ist kosteneffizient** - 80% Kostenreduktion
4. **Ist generisch** - Funktioniert für alle Produktkategorien
5. **Erlaubt Fitness-Hardcoding** - Gewichte, Durchmesser, Material

Der Schlüssel ist: **User-Query = Wahrheitsquelle für Marke und Produkttyp**
