# 🌊 Windsurf Workflow Guide für DealFinder

## 📚 Für Anfänger: Wie arbeite ich mit Windsurf + Cascade?

### **Was ist Windsurf?**
Windsurf ist eine AI-native IDE (wie VS Code, aber mit eingebauter AI). Cascade ist der AI-Assistent, der dir beim Coden hilft.

---

## 🚀 Grundlegender Workflow

### **1. Projekt öffnen**
```
File → Open Folder → c:\AI-Projekt\the-deals
```

### **2. Terminal öffnen**
```
View → Terminal (oder Ctrl + `)
```

### **3. Virtual Environment aktivieren**
```powershell
.venv\Scripts\activate
```

### **4. Applikation starten**
```powershell
python main.py
```

---

## 🤖 Mit Cascade arbeiten

### **Chat-Befehle**

#### **Code analysieren:**
```
"Kannst du main.py analysieren und mir sagen, was Zeile 250-280 macht?"
"Warum wird is_accessory_title() mit query und category aufgerufen?"
```

#### **Code ändern:**
```
"Ändere max_listings_per_query in config.yaml auf 10"
"Füge einen neuen Filter für 'gebraucht' hinzu"
"Refactor die is_accessory_title() Funktion für bessere Lesbarkeit"
```

#### **Debugging:**
```
"Warum bekomme ich diesen Error: [Error einfügen]"
"Analysiere die letzten 100 Zeilen vom Terminal Output"
"Prüfe ob die Datenbank-Verbindung funktioniert"
```

#### **Neue Features:**
```
"Implementiere einen Email-Versand für Top-Deals"
"Erstelle einen Telegram-Bot für Benachrichtigungen"
"Füge Support für tutti.ch hinzu (zusätzlich zu Ricardo)"
```

### **Wichtige Cascade-Features**

#### **@-Mentions:**
- `@main.py` - Referenziert eine Datei
- `@config.yaml:50-60` - Referenziert spezifische Zeilen
- `@conversation` - Referenziert frühere Chat-Nachrichten

#### **Beispiel:**
```
"Schau dir @main.py:250-280 an und erkläre mir die Filter-Logik"
```

---

## 📊 Datenbank analysieren

### **Option 1: SQL-Queries direkt**
```powershell
# PostgreSQL Client starten
psql -U dealuser -d dealfinder

# Queries ausführen
SELECT * FROM listings WHERE expected_profit > 100 ORDER BY deal_score DESC;
```

### **Option 2: Mit Cascade**
```
"Erstelle eine SQL-Query die alle Deals mit Score > 7 zeigt"
"Analysiere die listings Tabelle und finde unrealistische Werte"
```

### **Option 3: Vorgefertigte Queries**
Ich habe dir `analyze_results.sql` erstellt mit 15 nützlichen Queries:

```powershell
# Alle Queries ausführen:
psql -U dealuser -d dealfinder -f analyze_results.sql
```

---

## 🔍 Logs analysieren

### **Während die App läuft:**

1. **Terminal Output beobachten:**
   - Filter-Statistiken: Wie viele wurden gefiltert?
   - AI-Kosten: Wie viel wurde ausgegeben?
   - Fehler: Gibt es Probleme?

2. **Mit Cascade analysieren:**
```
"Analysiere den Terminal Output und sage mir:
- Wie viele Listings wurden gescraped?
- Wie effektiv war der Pre-Filter?
- Gab es Fehler oder Warnungen?"
```

### **Nach dem Run:**

1. **ai_cost_day.txt prüfen:**
```powershell
cat ai_cost_day.txt
```

2. **Datenbank prüfen:**
```sql
-- Schneller Überblick
SELECT COUNT(*), AVG(expected_profit), MAX(deal_score) FROM listings;
```

---

## 🛠️ Typische Entwicklungs-Tasks

### **1. Neuen Filter hinzufügen**

**Sag zu Cascade:**
```
"Füge einen Filter für 'Replica' Produkte hinzu in utils_text.py.
Sollte ähnlich wie der Defekt-Filter funktionieren."
```

Cascade wird:
1. `utils_text.py` öffnen
2. Neue Keywords definieren
3. Filter-Funktion erstellen
4. In `main.py` integrieren

### **2. Neue Produktkategorie**

**Sag zu Cascade:**
```
"Ich möchte 'Lego' als neue Kategorie hinzufügen.
Brauche spezielle Logik für Set-Nummern und Vollständigkeit."
```

### **3. Bug fixen**

**Sag zu Cascade:**
```
"Ich sehe in der DB dass resale_price_est manchmal NULL ist.
Finde heraus warum und fixe es."
```

### **4. Performance optimieren**

**Sag zu Cascade:**
```
"Die Applikation ist langsam bei 50+ Listings.
Analysiere wo Bottlenecks sind und optimiere."
```

---

## 📈 Projekt weiterentwickeln

### **Ideen für Features:**

#### **🔔 Benachrichtigungen**
```
"Implementiere Telegram-Bot der mich benachrichtigt wenn:
- Deal Score > 8
- Expected Profit > 200 CHF
- Auction endet in < 2 Stunden"
```

#### **📊 Dashboard**
```
"Erstelle ein Web-Dashboard mit Flask das zeigt:
- Aktuelle Top-Deals
- Profit-Statistiken
- Filter-Effizienz
- AI-Kosten Timeline"
```

#### **🤖 Auto-Bidding**
```
"Implementiere automatisches Bieten für Deals mit Score > 8
Mit Sicherheits-Limits und Benachrichtigungen"
```

#### **📱 Mobile App**
```
"Erstelle eine React Native App zum Durchsehen der Deals"
```

#### **🌐 Mehr Plattformen**
```
"Füge Support für tutti.ch und anibis.ch hinzu"
```

---

## 🎯 Best Practices

### **DO:**
✅ Kleine, iterative Änderungen
✅ Nach jeder Änderung testen
✅ Cascade fragen wenn unsicher
✅ Code kommentieren (Cascade macht das automatisch)
✅ Git commits nach Features

### **DON'T:**
❌ Große Refactorings ohne Backup
❌ Direkt in Production-DB testen
❌ API-Keys im Code (immer .env!)
❌ Caching deaktivieren (kostet Geld!)

---

## 🐛 Debugging-Workflow

### **Problem: Applikation crashed**

1. **Error-Message kopieren**
2. **Zu Cascade:**
```
"Ich bekomme diesen Error:
[Error hier einfügen]

Was ist das Problem und wie fixe ich es?"
```

### **Problem: Unrealistische Werte in DB**

1. **SQL Query:**
```sql
SELECT * FROM listings WHERE expected_profit > 1000;
```

2. **Zu Cascade:**
```
"Diese Listings haben unrealistische Profits.
Analysiere die Daten und finde den Bug in der Profit-Berechnung."
```

### **Problem: Filter zu aggressiv**

1. **Logs checken:**
```
📊 Pipeline Statistics:
🎯 Hardcoded accessory filter: 45
🤖 AI accessory filter: 12
```

2. **Zu Cascade:**
```
"Der hardcoded Filter filtert zu viel (45 von 60 Listings).
Kannst du die ACCESSORY_KEYWORDS Liste überprüfen und anpassen?"
```

---

## 💾 Git Workflow mit Windsurf

### **Änderungen committen:**

1. **Source Control öffnen** (Ctrl + Shift + G)
2. **Änderungen reviewen**
3. **Commit Message schreiben**
4. **Commit & Push**

### **Oder mit Cascade:**
```
"Erstelle einen Git commit mit Message:
'feat: Add query-aware accessory filtering (v7.2)'"
```

---

## 🎓 Lern-Ressourcen

### **Cascade lernen:**
- Einfach Fragen stellen!
- Cascade erklärt Code, Konzepte, Best Practices
- "Erkläre mir wie X funktioniert" ist immer OK

### **Python lernen:**
```
"Erkläre mir was List Comprehensions sind"
"Wie funktionieren Decorators in Python?"
"Was ist der Unterschied zwischen @dataclass und class?"
```

### **SQL lernen:**
```
"Erkläre mir diese Query: [Query einfügen]"
"Wie kann ich JOINs besser verstehen?"
```

---

## 🚀 Nächste Schritte

### **Für dich als Anfänger:**

1. **Experimentiere mit Config:**
   - Ändere `max_listings_per_query` auf 5
   - Teste verschiedene Queries
   - Schau wie sich Filter-Stats ändern

2. **Lerne SQL:**
   - Führe die Queries in `analyze_results.sql` aus
   - Verstehe was sie machen
   - Modifiziere sie für deine Needs

3. **Erweitere Features:**
   - Starte klein (z.B. neuer Filter)
   - Lass Cascade helfen
   - Teste gründlich

4. **Verstehe den Code:**
   - Frage Cascade über Funktionen die du nicht verstehst
   - Lese die Kommentare
   - Experimentiere mit Änderungen

---

## 💬 Beispiel-Konversationen

### **Anfänger:**
```
User: "Was macht die Funktion is_accessory_title()?"
Cascade: [Erklärt die Funktion im Detail]

User: "Kannst du ein Beispiel zeigen?"
Cascade: [Zeigt Code-Beispiele]

User: "Wie teste ich das?"
Cascade: [Erstellt Test-Code]
```

### **Fortgeschritten:**
```
User: "Refactor is_accessory_title() zu mehreren kleineren Funktionen"
Cascade: [Refactored Code mit Tests]

User: "Füge Type Hints hinzu"
Cascade: [Fügt Type Hints hinzu]

User: "Schreibe Unit Tests"
Cascade: [Erstellt pytest Tests]
```

---

## 🎯 Dein Ziel

**Von Anfänger zu Profi:**
1. ✅ Verstehe wie die Pipeline funktioniert
2. ✅ Kann Config anpassen
3. ✅ Kann SQL-Queries schreiben
4. ✅ Kann kleine Features hinzufügen
5. ✅ Kann Bugs fixen
6. ✅ Kann neue Plattformen integrieren
7. ✅ Kann eigene AI-Features bauen

**Cascade ist dein Pair-Programming Partner - nutze ihn! 🤖**

---

**Viel Erfolg! 🚀**
