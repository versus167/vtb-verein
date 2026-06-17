# Plan: Zählprotokoll (Kassenzählung / Stückelung)

> Status: in Umsetzung · Branch `feature/zaehlprotokoll` · Schema-Migration **v43**

## Kernidee

**Eine Zählung *ist* eine Buchung.** Jede Kassenzählung erzeugt eine „Zähl-Buchung"
in der Kasse, an die das Zählprotokoll als **PDF-Anhang** gehängt wird. Damit kommen
**Uhrzeit** (`created_at`) und **Ersteller** (`created_by`) gratis mit (ersetzt das
separate Unterschriften-PDF), die **Differenz ist sofort verbucht**, und im Kassenbuch
ist dokumentiert, dass gezählt wurde.

Auslöser (beide):
1. **Button „Kasse zählen"** auf der Kassenbuch-Detailseite → Ad-hoc-Kassensturz.
2. **Kategorie-Flag** `loest_zaehlung_aus`: Wird eine Buchung mit so markierter
   Kategorie gespeichert, fragt die App „Kasse jetzt zählen?" und öffnet den Dialog.

## Entscheidungen (mit dem User abgestimmt)

- **Differenz**: immer protokollieren **und** verbuchen. Verbucht wird unter
  - der **auslösenden Kategorie** (wenn per Kategorie-Trigger gestartet), sonst
  - der System-Kategorie **„Kassendifferenz"**.
- **0-Differenz**: trotzdem eine **0-€-Zähl-Buchung** anlegen (immer ein Träger fürs
  PDF + Zeitstempel + User; im Kassenbuch sichtbar „hier wurde gezählt, stimmte").
- **PDF**: kein separates Unterschriften-PDF, sondern Zählprotokoll-PDF **an die
  Zähl-Buchung** gehängt (Uhrzeit/Ersteller stehen über die Buchung fest).
- **Trigger**: Kategorie-Flag **+** dauerhafter Button.
- **Rechte**: keine neue Permission. Zählen = **Schreibzugriff** auf die Kasse
  (per-Kasse-ACL, `kassen.verwalten` umgeht sie) — konsistent zur Kategorie-Entscheidung.

## Datenmodell (Migration v43)

```sql
CREATE TABLE kassen_zaehlungen (
  id                     SERIAL PRIMARY KEY,
  kasse_id               INTEGER NOT NULL REFERENCES kassen(id),
  buchung_id             INTEGER REFERENCES kassenbuchungen(id),  -- Zähl-Buchung (PDF-Träger)
  ausloesende_buchung_id INTEGER REFERENCES kassenbuchungen(id),  -- Kontext bei Kategorie-Trigger
  stueckelung            JSONB NOT NULL DEFAULT '{}',             -- {"50000": 2, "200": 13, ...} Cent→Anzahl
  ist_cent               INTEGER NOT NULL,                        -- Σ Stückelung (gezählt)
  soll_cent              INTEGER NOT NULL,                        -- Buchbestand zum Zähl-Zeitpunkt (eingefroren)
  differenz_cent         INTEGER NOT NULL,                        -- ist - soll
  notiz                  TEXT,
  version/created_*/updated_*/deleted_*  -- Standard-Audit + Soft-Delete
);
-- + kassen_zaehlungen_history + Audit-Trigger (wie alle Domänentabellen)

ALTER TABLE kassen_kategorien ADD COLUMN loest_zaehlung_aus BOOLEAN NOT NULL DEFAULT false;
-- + History-Spalte + Audit-Funktionen (insert/update) um die Spalte ergänzen
```

**Soll einfrieren**: Der Buchbestand ändert sich durch spätere Buchungen; das Protokoll
muss historisch unverändert bleiben → `soll_cent` wird beim Zählen gespeichert. Da
`buchungsdatum` tagesgenau ist, gilt: Soll = aktueller Gesamt-Buchbestand der Kasse.

**Stückelung** als JSONB (EUR ist ein fester Wertesatz → keine Kindtabelle).
`EURO_STUECKELUNG_CENT = [50000,20000,10000,5000,2000,1000,500,200,100,50,20,10,5,2,1]`.

## Ablauf `erstelle_zaehlung` (Service)

1. Schreibzugriff prüfen.
2. `ist_cent` = Σ (Wert·Anzahl) aus der Stückelung (serverseitig berechnet, Eingaben validiert).
3. `soll_cent` = aktueller Buchbestand der Kasse.
4. `differenz_cent` = ist − soll. Vorzeichen → Buchungstyp:
   - differenz > 0 → **Einnahme** (Überschuss)
   - differenz < 0 → **Ausgabe** (Fehlbetrag)
   - differenz = 0 → 0-€-Buchung
   (Resultierender Bestand = Ist ≥ 0 → kein NegativerBestand möglich.)
5. Kategorie = auslösende Kategorie (falls Trigger) sonst „Kassendifferenz".
6. Zähl-Buchung anlegen (`create_buchung` mit `skip_kategorie_validierung=True`,
   da „Kassendifferenz" eine Systemkategorie ist).
7. `kassen_zaehlungen`-Zeile anlegen (verknüpft mit Buchung + ggf. auslösender Buchung).
8. Zählprotokoll-PDF rendern und via `add_anhang` an die Zähl-Buchung hängen (best-effort).

## Betroffene Dateien

**Backend**
- `vtb_verein/app/db/database.py` — Migration v42→v43, SCHEMA_VERSION=43, Fresh-Schema,
  Audit-Funktionen/Trigger/Indizes, Kategorie-Audit-Funktionen um Flag erweitern.
- `vtb_verein/app/models/kasse.py` — `KassenZaehlung`, `EURO_STUECKELUNG_CENT`,
  Flag in `KassenKategorie`.
- `vtb_verein/app/db/kassen_zaehlung_repository.py` — **neu** (create/get/list/mark_deleted).
- `vtb_verein/app/db/kassen_kategorie_repository.py` — Flag in `_COLS`/create/update.
- `vtb_verein/app/services/kassenbuch_service.py` — `erstelle_zaehlung`,
  `list_zaehlungen`, `skip_kategorie_validierung`-Param.
- `vtb_verein/app/services/kassenbuch_pdf_service.py` — `erstelle_zaehlprotokoll_pdf`.
- `vtb_verein/app/db/datastore.py` — Repo instanziieren + an Service übergeben.
- `backend/api/kassenbuch.py` — Zählungs-Endpunkte (`POST/GET /{kasse_id}/zaehlungen`),
  Flag in den Kategorie-Schemas/Antworten.

**Frontend**
- `frontend/src/pages/KassenbuchDetailPage.vue` — Button „Kasse zählen", Zähl-Dialog
  (Stückelungs-Grid mit Live-Summe/Differenz-Ampel), Trigger-Prompt nach Buchung,
  Protokoll-Liste.
- `frontend/src/pages/KassenverwaltungPage.vue` — Checkbox „Zählung anfordern" bei der
  Kategorie-Pflege.

**Tests**
- `vtb_verein/tests/test_kassen_zaehlung.py` — Differenz-Vorzeichen, Ist-Berechnung,
  Kategorie-Auswahl (Fakes, analog `test_kassen_kategorie.py`).

## Phasen

1. **Kern** — Migration, Modell/Repo/Service, API, Button + Dialog + Protokoll-Liste, PDF-Anhang.
2. **Trigger** — Kategorie-Flag + „Jetzt zählen?"-Prompt + Verbuchung unter auslösender Kategorie.
