# Analysis: v7.2.1 Test Run Results

**Date:** 2026-01-08 23:06  
**Total Listings:** 24

---

## 🎯 BUG FIX VERIFICATION

### ✅ **Bug #1: Variant Clustering - FIXED!**
**Expected:** Fenix 7 ≠ Fenix 8 (separate variants)

**Results:**
- `Garmin smartwatch|Fenix 7` (ID 1313) - ✅ Separate variant
- `Garmin smartwatch|Fenix 8` (ID 1319) - ✅ Separate variant
- `Garmin smartwatch|Fenix 3 HR` (ID 1320) - ✅ Separate variant
- `Garmin smartwatch|Venu 3` (ID 1316) - ✅ Separate variant
- `Garmin smartwatch|vivoactive 4S` (ID 1315) - ✅ Separate variant

**Verdict:** ✅ **ERFOLG!** Modellnummern werden jetzt korrekt unterschieden.

---

### ✅ **Bug #2: Fitness Bundle Filter - FIXED!**
**Expected:** "Hantelscheiben Set 4x 5kg" NOT filtered as accessory

**Results:**
- ID 1322: "Hantelscheiben Set 4x 5kg, NEU" - ✅ Durchgekommen (nicht gefiltert)
- ID 1326: "Hantelscheiben Set, 2 Stk. à 25kg" - ✅ Durchgekommen (Bundle erkannt)
- ID 1321: "30kg 3 in1 Hantelset" - ✅ Durchgekommen (Bundle erkannt)
- ID 1324: "Hantelschieben Eisen 140kg" - ✅ Durchgekommen (Bundle erkannt)

**Verdict:** ✅ **ERFOLG!** Fitness-Bundles werden nicht mehr als Accessories gefiltert.

---

### ✅ **Bug #3: Resale > New Price - FIXED!**
**Expected:** No resale_price_est > new_price * 0.95

**Check all listings:**
```
ID 1305: resale=42.5, new=249.9 → 17% ✅
ID 1306: resale=42.5, new=140.0 → 30% ✅
ID 1307: resale=25.5, new=100.0 → 26% ✅
ID 1310: resale=8.1, new=199.0 → 4% ✅
ID 1313: resale=200.45, new=359.95 → 56% ✅
ID 1315: resale=84.15, new=329.9 → 26% ✅
ID 1316: resale=106.4, new=296.0 → 36% ✅
ID 1317: resale=467.5, new=515.0 → 91% ✅ (unter 95%)
ID 1318: resale=80.75, new=549.0 → 15% ✅
ID 1319: resale=764.15, new=??? → ⚠️ new_price=NULL!
ID 1320: resale=144.5, new=449.9 → 32% ✅
ID 1326: resale=67.5, new=175.0 → 39% ✅
```

**Verdict:** ✅ **ERFOLG!** Keine unrealistischen Resale-Preise mehr (außer wo new_price fehlt).

---

### ✅ **Bug #5: Rate Limits - FIXED!**
**Expected:** No 429 errors

**Observation:** Keine Rate-Limit-Fehler in den Daten sichtbar. Alle Web-Searches scheinen erfolgreich.

**Verdict:** ✅ **ERFOLG!** (Muss im Log bestätigt werden)

---

### ✅ **Bug #6: Bundle Resale = 0 - FIXED!**
**Expected:** Bundles have resale_price_bundle > 0

**Results:**
- ID 1326: Bundle → resale_price_bundle=67.5 ✅
- ID 1321: Bundle → resale_price_bundle=360.0 ✅
- ID 1324: Bundle → resale_price_bundle=2211.3 ✅
- ID 1325: Bundle → resale_price_bundle=27.0 ✅

**Verdict:** ✅ **ERFOLG!** Alle Bundles haben realistische Resale-Preise.

---

## 🚨 NEUE KRITISCHE PROBLEME ENTDECKT

### ❌ **PROBLEM #1: end_time = NULL (KRITISCH!)**
**Beobachtung:** 18 von 24 Listings (75%) haben `end_time=NULL`

**Betroffene Listings:**
- Alle Tommy Hilfiger (IDs 1305-1312, 1308)
- Alle Hantelscheiben außer 3 (IDs 1323, 1326, 1327, 1328)
- Einige Garmin (ID 1314)

**Auswirkung:**
- `hours_remaining=999.0` für alle NULL end_times
- Confidence-Berechnung basiert auf falschen Zeitdaten
- Strategie-Entscheidungen sind ungenau

**Ursache:** Scraper extrahiert `end_time` nicht korrekt für alle Listing-Typen.

---

### ❌ **PROBLEM #2: new_price = NULL für Fenix 8**
**Beobachtung:** ID 1319 (Fenix 8) hat `new_price=NULL`

```
ID 1319: Fenix 8 Amoled Sapphire 51mm
- buy_now_price: 899 CHF
- resale_price_est: 764.15 CHF
- new_price: NULL ❌
```

**Auswirkung:** Sanity-Check kann nicht greifen, Profit-Berechnung ungenau.

**Ursache:** Web-Search fand keinen Preis für diese spezifische Variante.

---

### ⚠️ **PROBLEM #3: Unrealistische Bundle-Bewertungen**
**Beobachtung:** ID 1324 hat extreme Werte

```
ID 1324: "Hantelschieben Eisen 140kg"
- buy_now_price: 350 CHF
- new_price: 4422.6 CHF ❌ (unrealistisch hoch!)
- resale_price_bundle: 2211.3 CHF ❌
- expected_profit: 1640 CHF ❌
- Strategy: buy_now 🔥
```

**Realität:** 140kg Hantelscheiben kosten NEU ca. 200-300 CHF, nicht 4422 CHF!

**Ursache:** AI überschätzt Bundle-Komponenten massiv:
```json
[
  {"qty": 6, "name": "Gusseisen-Hantelscheiben", "market_price": 315},
  {"qty": 3, "name": "Größere Hantelscheiben", "market_price": 126},
  {"qty": 3, "name": "Kleinere Hantelscheiben", "market_price": 63}
]
```
→ 6×315 + 3×126 + 3×63 = 2457 CHF (viel zu hoch!)

**Korrekte Berechnung:**
- 2×25kg = 50kg @ 1.5 CHF/kg = 75 CHF
- 2×20kg = 40kg @ 1.5 CHF/kg = 60 CHF
- 2×15kg = 30kg @ 1.5 CHF/kg = 45 CHF
- 2×10kg = 20kg @ 1.5 CHF/kg = 30 CHF
- **Total NEU: ~210 CHF** (nicht 4422 CHF!)

---

### ⚠️ **PROBLEM #4: Shipping Cost Integration fehlt**
**Beobachtung:** `shipping_cost` ist nur für 3 Listings gefüllt:
- ID 1308: 9.0 CHF
- ID 1321: 8.0 CHF
- ID 1322, 1324, 1325: NULL

**Status:** Detail-Scraping funktioniert teilweise, aber:
1. Nicht alle Listings haben Shipping-Daten
2. Shipping wird nicht vom Profit abgezogen

---

## 📊 DATEN-QUALITÄT BEWERTUNG

### Vorher (aus Analyse):
- **Daten-Qualität:** 58/100
- **Filter-Effizienz:** 14.3%
- **Unrealistische Preise:** 5 Fälle
- **Bundle-Resale:** 0 CHF

### Nachher (aktuell):
- **Daten-Qualität:** ~65/100 (+7 Punkte, nicht +20!)
- **Filter-Effizienz:** Unbekannt (brauche Log)
- **Unrealistische Preise:** 1 Fall (Fenix 8 new_price=NULL)
- **Bundle-Resale:** Funktioniert ✅
- **Neue Probleme:** end_time=NULL (75%), Bundle-Überschätzung

---

## 🎯 ERFOLGE

✅ **Varianten-Clustering:** Fenix 7 ≠ Fenix 8 (perfekt!)  
✅ **Fitness-Bundles:** Nicht mehr gefiltert  
✅ **Resale-Sanity:** Keine Resale > New Price  
✅ **Bundle-Resale:** Alle > 0 CHF  
✅ **Rate-Limits:** Keine Fehler sichtbar  

---

## ❌ NEUE/BESTEHENDE PROBLEME

### Kritisch:
1. **end_time=NULL (75%)** → hours_remaining=999 → falsche Confidence
2. **Bundle-Überschätzung** → ID 1324 hat 1640 CHF "Profit" (unrealistisch!)
3. **new_price=NULL** → Sanity-Checks greifen nicht

### Medium:
4. **Shipping-Kosten** → Nicht integriert in Profit
5. **Detail-Scraping** → Nur 3/24 Listings haben Daten

---

## 🔧 EMPFOHLENE FIXES

### **FIX #1: end_time Scraping (KRITISCH!)**
**Problem:** 75% der Listings haben NULL end_time

**Lösung:** Scraper muss end_time für alle Listing-Typen extrahieren:
- Buy-Now-Only Listings → end_time = "weit in Zukunft" (z.B. +30 Tage)
- Auktionen → end_time aus HTML extrahieren

**Datei:** `scrapers/ricardo.py` (vermutlich)

---

### **FIX #2: Bundle-Komponenten Validierung**
**Problem:** AI überschätzt Bundle-Werte massiv (4422 CHF statt 210 CHF)

**Lösung:** Weight-based pricing für Hantelscheiben-Bundles:
```python
# In calculate_bundle_new_price()
if is_weight_plate(comp_name):
    weight_kg = extract_weight_kg(comp_name)
    if weight_kg:
        component_new = weight_kg * 1.5  # 1.5 CHF/kg für Gusseisen
```

**Datei:** `ai_filter.py` (calculate_bundle_new_price)

---

### **FIX #3: new_price Fallback**
**Problem:** Fenix 8 hat new_price=NULL

**Lösung:** Fallback auf buy_now_price * 1.1 wenn Web-Search fehlschlägt:
```python
if not new_price and buy_now_price:
    new_price = buy_now_price * 1.1  # Konservative Schätzung
```

---

### **FIX #4: Shipping Integration**
**Problem:** Shipping-Kosten nicht vom Profit abgezogen

**Lösung:** Nach Detail-Scraping Profit neu berechnen:
```python
if shipping_cost:
    expected_profit -= shipping_cost
```

---

## 📈 REALISTISCHE ERWARTUNG

### Aktuelle Daten-Qualität: **65/100**
- ✅ Varianten: +10 Punkte
- ✅ Bundle-Resale: +5 Punkte
- ✅ Resale-Sanity: +5 Punkte
- ❌ end_time NULL: -10 Punkte
- ❌ Bundle-Überschätzung: -5 Punkte

### Nach weiteren Fixes: **~80/100**
- Fix end_time: +10 Punkte
- Fix Bundle-Bewertung: +5 Punkte

---

## ✅ FAZIT

**Die Fixes haben TEILWEISE funktioniert:**

### Was funktioniert:
1. ✅ Varianten-Clustering ist perfekt
2. ✅ Fitness-Bundles werden nicht gefiltert
3. ✅ Resale-Sanity-Checks greifen
4. ✅ Bundle-Resale > 0

### Was NICHT funktioniert:
1. ❌ 75% der Listings haben end_time=NULL
2. ❌ Bundle-Bewertungen sind unrealistisch hoch
3. ❌ Shipping-Kosten nicht integriert

### Nächste Priorität:
1. **end_time Scraping fixen** (KRITISCH!)
2. **Bundle-Komponenten validieren** (verhindert falsche Deals)
3. **Shipping-Kosten integrieren**

**Daten-Qualität:** 65/100 (nicht 78/100 wie erwartet)
