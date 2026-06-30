'''
PostgreSQL database connection and schema management.
Rewritten 2026-05-18: sqlite3 → psycopg3, single consolidated schema (v15).
'''

import logging
import os
import bcrypt
from contextlib import contextmanager

logger = logging.getLogger(__name__)

import psycopg
from psycopg.rows import dict_row

SCHEMA_VERSION = 60


# ---------------------------------------------------------------------------
# Audit-Trigger-Funktionen, die zwischen Frischaufbau (_create_trigger_functions)
# und der Migration v45→v46 geteilt werden, damit beide Pfade garantiert die
# gleiche Spaltenmenge schreiben (Fibu-Export-Spalten + Konten-Stammdaten).
# ---------------------------------------------------------------------------

_FN_FIBU_EXPORTE_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_fibu_exporte_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO fibu_exporte_history (
            id, version, exportiert_am, exportiert_von, dateiname, format,
            anzahl_positionen, summe_cent, storno_von_export_id,
            created_at, created_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.exportiert_am, NEW.exportiert_von, NEW.dateiname, NEW.format,
            NEW.anzahl_positionen, NEW.summe_cent, NEW.storno_von_export_id,
            NEW.created_at, NEW.created_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

# Un-Export nimmt einen Lauf zurück (Soft-Delete des Headers) → UPDATE muss in die History.
_FN_FIBU_EXPORTE_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_fibu_exporte_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO fibu_exporte_history (
                id, version, exportiert_am, exportiert_von, dateiname, format,
                anzahl_positionen, summe_cent, storno_von_export_id,
                created_at, created_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.exportiert_am, NEW.exportiert_von, NEW.dateiname, NEW.format,
                NEW.anzahl_positionen, NEW.summe_cent, NEW.storno_von_export_id,
                NEW.created_at, NEW.created_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

_FN_ABTEILUNG_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_abteilung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO abteilung_history (
            id, version, name, kuerzel, beschreibung, kostenstelle,
            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung, NEW.kostenstelle,
            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

_FN_ABTEILUNG_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_abteilung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO abteilung_history (
                id, version, name, kuerzel, beschreibung, kostenstelle,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung, NEW.kostenstelle,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

_FN_BEITRAGSREGEL_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO beitragsregel_history (
            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
            zahler_typ,
            bedingung_funktionen, bedingung_funktion_abteilung_id, bedingung_abteilung_ids,
            ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
            bedingung_alter_min, bedingung_alter_max, gegenkonto, steuerschluessel,
            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
            NEW.zahler_typ,
            NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id, NEW.bedingung_abteilung_ids,
            NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
            NEW.bedingung_alter_min, NEW.bedingung_alter_max, NEW.gegenkonto, NEW.steuerschluessel,
            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

_FN_BEITRAGSREGEL_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO beitragsregel_history (
                id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                zahler_typ,
                bedingung_funktionen, bedingung_funktion_abteilung_id, bedingung_abteilung_ids,
                ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
                bedingung_alter_min, bedingung_alter_max, gegenkonto, steuerschluessel,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                NEW.zahler_typ,
                NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id, NEW.bedingung_abteilung_ids,
                NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
                NEW.bedingung_alter_min, NEW.bedingung_alter_max, NEW.gegenkonto, NEW.steuerschluessel,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

_FN_GEBUEHR_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO gebuehr_history (
            id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
            zahler_typ, bedingung_alter_min, bedingung_alter_max,
            gegenkonto, steuerschluessel, kostenstelle, kostentraeger,
            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
            NEW.zahler_typ, NEW.bedingung_alter_min, NEW.bedingung_alter_max,
            NEW.gegenkonto, NEW.steuerschluessel, NEW.kostenstelle, NEW.kostentraeger,
            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

_FN_GEBUEHR_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO gebuehr_history (
                id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                zahler_typ, bedingung_alter_min, bedingung_alter_max,
                gegenkonto, steuerschluessel, kostenstelle, kostentraeger,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                NEW.zahler_typ, NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                NEW.gegenkonto, NEW.steuerschluessel, NEW.kostenstelle, NEW.kostentraeger,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

_FN_BEITRAG_SOLLSTELLUNG_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO beitrag_sollstellung_history (
            id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
            faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
            exportiert_in_export_id, storno_exportiert_in_export_id,
            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
            NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
            NEW.exportiert_in_export_id, NEW.storno_exportiert_in_export_id,
            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

_FN_BEITRAG_SOLLSTELLUNG_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO beitrag_sollstellung_history (
                id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                exportiert_in_export_id, storno_exportiert_in_export_id,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                NEW.exportiert_in_export_id, NEW.storno_exportiert_in_export_id,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

_FN_GEBUEHR_FORDERUNG_AUDIT_INSERT = """
    CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO gebuehr_forderung_history (
            id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
            exportiert_in_export_id, storno_exportiert_in_export_id,
            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
        ) VALUES (
            NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
            NEW.exportiert_in_export_id, NEW.storno_exportiert_in_export_id,
            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
        );
        RETURN NEW;
    END; $$;
"""

_FN_GEBUEHR_FORDERUNG_AUDIT_UPDATE = """
    CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO gebuehr_forderung_history (
                id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                exportiert_in_export_id, storno_exportiert_in_export_id,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                NEW.exportiert_in_export_id, NEW.storno_exportiert_in_export_id,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""

# ---------------------------------------------------------------------------
# Mitglied-Audit-Trigger (inkl. Trainerlizenz/Qualifikation ab Schema v54),
# geteilt zwischen Frischaufbau (_create_trigger_functions) und Migration v53→v54.
# ---------------------------------------------------------------------------

_MITGLIED_COLS = (
    "id, version, mitgliedsnummer, vorname, nachname, geburtsdatum, "
    "strasse, plz, ort, land, eintrittsdatum, austrittsdatum, status, "
    "zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis, "
    "geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum, "
    "user_id, trainerlizenz_nr, qualifikation, trainerlizenz_gueltig_bis, "
    "trainerlizenz_gueltig_von, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_MITGLIED_VALS = ", ".join("NEW." + c.strip() for c in _MITGLIED_COLS.split(","))

_FN_MITGLIED_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO mitglied_history ({_MITGLIED_COLS}) VALUES ({_MITGLIED_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_MITGLIED_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO mitglied_history ({_MITGLIED_COLS}) VALUES ({_MITGLIED_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

# ---------------------------------------------------------------------------
# Übungsleiter-Stundenerfassung (Schema v53): Audit-Trigger-Funktionen, geteilt
# zwischen Frischaufbau (_create_trigger_functions) und Migration v52→v53.
# ---------------------------------------------------------------------------

_UL_ABRECHNUNG_COLS = (
    "id, version, mitglied_id, abteilung_id, zeitraum_von, zeitraum_bis, status, "
    "lizenz_klassifikation, foerder_klassifikation, verguetung_pro_stunde, "
    "trainerlizenz_nr, qualifikation, "
    "eingereicht_am, eingereicht_von, bestaetigt_am, bestaetigt_von, abgelehnt_grund, "
    "exportiert_in_export_id, storno_exportiert_in_export_id, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_UL_ABRECHNUNG_VALS = ", ".join("NEW." + c.strip() for c in _UL_ABRECHNUNG_COLS.split(","))

_FN_UL_ABRECHNUNG_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_ul_abrechnung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO ul_abrechnung_history ({_UL_ABRECHNUNG_COLS}) VALUES ({_UL_ABRECHNUNG_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_UL_ABRECHNUNG_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_ul_abrechnung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO ul_abrechnung_history ({_UL_ABRECHNUNG_COLS}) VALUES ({_UL_ABRECHNUNG_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

_UL_STUNDE_COLS = (
    "id, version, abrechnung_id, datum, stunden, wochentag, angebot, bemerkung, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_UL_STUNDE_VALS = ", ".join("NEW." + c.strip() for c in _UL_STUNDE_COLS.split(","))

_FN_UL_STUNDE_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_ul_stunde_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO ul_stunde_history ({_UL_STUNDE_COLS}) VALUES ({_UL_STUNDE_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_UL_STUNDE_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_ul_stunde_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO ul_stunde_history ({_UL_STUNDE_COLS}) VALUES ({_UL_STUNDE_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

_UL_SATZ_COLS = (
    "id, version, mitglied_id, abteilung_id, lizenz_klassifikation, satz, gueltig_ab, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_UL_SATZ_VALS = ", ".join("NEW." + c.strip() for c in _UL_SATZ_COLS.split(","))

_FN_UL_SATZ_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_ul_satz_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO ul_satz_history ({_UL_SATZ_COLS}) VALUES ({_UL_SATZ_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_UL_SATZ_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_ul_satz_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO ul_satz_history ({_UL_SATZ_COLS}) VALUES ({_UL_SATZ_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

# DDL der drei ÜL-Tabellen (+ History), geteilt zwischen Frischaufbau und Migration.
_DDL_UL_TABLES = """
    CREATE TABLE IF NOT EXISTS ul_abrechnung (
      id                              SERIAL PRIMARY KEY,
      mitglied_id                     INTEGER NOT NULL REFERENCES mitglied(id),
      abteilung_id                    INTEGER NOT NULL REFERENCES abteilung(id),
      zeitraum_von                    TEXT NOT NULL,
      zeitraum_bis                    TEXT NOT NULL,
      status                          TEXT NOT NULL DEFAULT 'entwurf',
      lizenz_klassifikation           TEXT NOT NULL DEFAULT 'ohne_lizenz',
      foerder_klassifikation          TEXT,
      verguetung_pro_stunde           REAL,
      trainerlizenz_nr                TEXT,   -- Snapshot beim Einreichen (Beleg)
      qualifikation                   TEXT,   -- Snapshot beim Einreichen (Beleg)
      eingereicht_am                  TEXT,
      eingereicht_von                 TEXT,
      bestaetigt_am                   TEXT,
      bestaetigt_von                  TEXT,
      abgelehnt_grund                 TEXT,
      exportiert_in_export_id         INTEGER,
      storno_exportiert_in_export_id  INTEGER,
      version                         INTEGER NOT NULL DEFAULT 1,
      created_at                      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by                      TEXT,
      updated_at                      TEXT,
      updated_by                      TEXT,
      deleted_at                      TEXT,
      deleted_by                      TEXT
    );
    CREATE TABLE IF NOT EXISTS ul_abrechnung_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      mitglied_id INTEGER, abteilung_id INTEGER, zeitraum_von TEXT, zeitraum_bis TEXT,
      status TEXT, lizenz_klassifikation TEXT, foerder_klassifikation TEXT,
      verguetung_pro_stunde REAL, trainerlizenz_nr TEXT, qualifikation TEXT,
      eingereicht_am TEXT, eingereicht_von TEXT, bestaetigt_am TEXT, bestaetigt_von TEXT,
      abgelehnt_grund TEXT, exportiert_in_export_id INTEGER, storno_exportiert_in_export_id INTEGER,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
    CREATE TABLE IF NOT EXISTS ul_stunde (
      id            SERIAL PRIMARY KEY,
      abrechnung_id INTEGER NOT NULL REFERENCES ul_abrechnung(id),
      datum         TEXT NOT NULL,
      stunden       REAL NOT NULL,
      wochentag     INTEGER,
      angebot       TEXT,
      bemerkung     TEXT,
      version       INTEGER NOT NULL DEFAULT 1,
      created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by    TEXT,
      updated_at    TEXT,
      updated_by    TEXT,
      deleted_at    TEXT,
      deleted_by    TEXT
    );
    CREATE TABLE IF NOT EXISTS ul_stunde_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      abrechnung_id INTEGER, datum TEXT, stunden REAL, wochentag INTEGER,
      angebot TEXT, bemerkung TEXT,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
    CREATE TABLE IF NOT EXISTS ul_satz (
      id                    SERIAL PRIMARY KEY,
      mitglied_id           INTEGER REFERENCES mitglied(id),
      abteilung_id          INTEGER REFERENCES abteilung(id),
      lizenz_klassifikation TEXT NOT NULL DEFAULT 'ohne_lizenz',
      satz                  REAL NOT NULL,
      gueltig_ab            TEXT,
      version               INTEGER NOT NULL DEFAULT 1,
      created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by            TEXT,
      updated_at            TEXT,
      updated_by            TEXT,
      deleted_at            TEXT,
      deleted_by            TEXT
    );
    CREATE TABLE IF NOT EXISTS ul_satz_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      mitglied_id INTEGER, abteilung_id INTEGER, lizenz_klassifikation TEXT,
      satz REAL, gueltig_ab TEXT,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
"""

# Indizes der ÜL-Tabellen, geteilt zwischen Frischaufbau und Migration.
_UL_INDEXES = (
    ("idx_ul_abrechnung_mitglied_id",   "ul_abrechnung(mitglied_id)"),
    ("idx_ul_abrechnung_abteilung_id",  "ul_abrechnung(abteilung_id)"),
    ("idx_ul_abrechnung_status",        "ul_abrechnung(status)"),
    ("idx_ul_abrechnung_sperre",        "ul_abrechnung(mitglied_id, abteilung_id, zeitraum_bis)"),
    ("idx_ul_abrechnung_export_id",     "ul_abrechnung(exportiert_in_export_id)"),
    ("idx_ul_abrechnung_deleted_at",    "ul_abrechnung(deleted_at)"),
    ("idx_ul_abrechnung_history_id",    "ul_abrechnung_history(id)"),
    ("idx_ul_stunde_abrechnung_id",     "ul_stunde(abrechnung_id)"),
    ("idx_ul_stunde_deleted_at",        "ul_stunde(deleted_at)"),
    ("idx_ul_stunde_history_id",        "ul_stunde_history(id)"),
    ("idx_ul_satz_lookup",              "ul_satz(lizenz_klassifikation, mitglied_id, abteilung_id)"),
    ("idx_ul_satz_deleted_at",          "ul_satz(deleted_at)"),
    ("idx_ul_satz_history_id",          "ul_satz_history(id)"),
)

# ÜL-Trigger (Tabelle ↔ Funktion), geteilt zwischen Frischaufbau und Migration.
_UL_TRIGGERS = (
    ('trig_ul_abrechnung_audit_insert', 'INSERT', 'ul_abrechnung', 'fn_ul_abrechnung_audit_insert'),
    ('trig_ul_abrechnung_audit_update', 'UPDATE', 'ul_abrechnung', 'fn_ul_abrechnung_audit_update'),
    ('trig_ul_stunde_audit_insert',     'INSERT', 'ul_stunde',     'fn_ul_stunde_audit_insert'),
    ('trig_ul_stunde_audit_update',     'UPDATE', 'ul_stunde',     'fn_ul_stunde_audit_update'),
    ('trig_ul_satz_audit_insert',       'INSERT', 'ul_satz',       'fn_ul_satz_audit_insert'),
    ('trig_ul_satz_audit_update',       'UPDATE', 'ul_satz',       'fn_ul_satz_audit_update'),
)

# Standard-Berechtigungen je Funktion für die ÜL-Stundenerfassung (Seed/Migration).
_UL_FUNKTION_PERMISSIONS = (
    ('uebungsleiter',    'ulstunden.erfassen'),
    ('abteilungsleiter', 'ulstunden.bestaetigen'),
)


# ============================================================================
# Zutrittskontrolle / Schließsystem (TT-Lock), Schema v57
# ----------------------------------------------------------------------------
# DDL/Trigger/Index-Definitionen, geteilt zwischen Frischaufbau (_create_*) und
# Migration v56→v57, damit beide Pfade identische Schemata erzeugen.
# Die App ist Orchestrierungsschicht über der TTLock-Cloud (Quelle der Wahrheit):
#  * ttlock_konto      – Single-Row-Laufzeitstatus (Tokens/Sync), kein History/Soft-Delete.
#  * tuer_schloss      – gespiegeltes Schloss-Inventar (+History, Soft-Delete).
#  * schluessel_chip   – physischer Chip ↔ Mitglied/Standort (+History, Soft-Delete).
#  * tuer_berechtigung – Chip an Schloss = eine TTLock-IC-Card (+History, Soft-Delete).
#  * tuer_zutritt_log  – append-only Zutrittslog (kein History-Mirror, dedupe über recordId).
# ============================================================================
_TUER_SCHLOSS_COLS = (
    "id, version, ttlock_lock_id, name, standort, abteilung_id, ttlock_gateway_id, "
    "gateway_online, lock_mac, akku_prozent, akku_stand_at, aktiv, notiz, "
    "letzter_log_serverdate, letztes_event_at, letztes_event_type, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_TUER_SCHLOSS_VALS = ", ".join("NEW." + c.strip() for c in _TUER_SCHLOSS_COLS.split(","))

_FN_TUER_SCHLOSS_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_schloss_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO tuer_schloss_history ({_TUER_SCHLOSS_COLS}) VALUES ({_TUER_SCHLOSS_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_TUER_SCHLOSS_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_schloss_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO tuer_schloss_history ({_TUER_SCHLOSS_COLS}) VALUES ({_TUER_SCHLOSS_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

_SCHLUESSEL_CHIP_COLS = (
    "id, version, kartennummer, bezeichnung, mitglied_id, aufbewahrungsort, status, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_SCHLUESSEL_CHIP_VALS = ", ".join("NEW." + c.strip() for c in _SCHLUESSEL_CHIP_COLS.split(","))

_FN_SCHLUESSEL_CHIP_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_schluessel_chip_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO schluessel_chip_history ({_SCHLUESSEL_CHIP_COLS}) VALUES ({_SCHLUESSEL_CHIP_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_SCHLUESSEL_CHIP_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_schluessel_chip_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO schluessel_chip_history ({_SCHLUESSEL_CHIP_COLS}) VALUES ({_SCHLUESSEL_CHIP_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

_TUER_BERECHTIGUNG_COLS = (
    "id, version, chip_id, schloss_id, ttlock_card_id, gueltig_von, gueltig_bis, "
    "sync_status, sync_fehler, erteilt_von, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_TUER_BERECHTIGUNG_VALS = ", ".join("NEW." + c.strip() for c in _TUER_BERECHTIGUNG_COLS.split(","))

_FN_TUER_BERECHTIGUNG_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_berechtigung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO tuer_berechtigung_history ({_TUER_BERECHTIGUNG_COLS}) VALUES ({_TUER_BERECHTIGUNG_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_TUER_BERECHTIGUNG_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_berechtigung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO tuer_berechtigung_history ({_TUER_BERECHTIGUNG_COLS}) VALUES ({_TUER_BERECHTIGUNG_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

# DDL aller Zutritts-Tabellen (+History), geteilt zwischen Frischaufbau und Migration.
_DDL_ZUTRITT_TABLES = """
    CREATE TABLE IF NOT EXISTS ttlock_konto (
      id               SERIAL PRIMARY KEY,
      endpoint         TEXT NOT NULL DEFAULT 'https://euapi.ttlock.com',
      ttlock_uid       BIGINT,
      access_token     TEXT,
      refresh_token    TEXT,
      token_expires_at TEXT,
      letzter_sync_at  TEXT,
      version          INTEGER NOT NULL DEFAULT 1,
      created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by       TEXT,
      updated_at       TEXT,
      updated_by       TEXT
    );
    CREATE TABLE IF NOT EXISTS tuer_schloss (
      id                     SERIAL PRIMARY KEY,
      ttlock_lock_id         BIGINT NOT NULL,
      name                   TEXT NOT NULL,
      standort               TEXT,
      abteilung_id           INTEGER REFERENCES abteilung(id),
      ttlock_gateway_id      BIGINT,
      gateway_online         BOOLEAN,
      lock_mac               TEXT,
      akku_prozent           INTEGER,
      akku_stand_at          TEXT,
      aktiv                  BOOLEAN NOT NULL DEFAULT TRUE,
      notiz                  TEXT,
      letzter_log_serverdate BIGINT,
      letztes_event_at       TEXT,
      letztes_event_type     INTEGER,
      version                INTEGER NOT NULL DEFAULT 1,
      created_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by             TEXT,
      updated_at             TEXT,
      updated_by             TEXT,
      deleted_at             TEXT,
      deleted_by             TEXT
    );
    CREATE TABLE IF NOT EXISTS tuer_schloss_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      ttlock_lock_id BIGINT, name TEXT, standort TEXT, abteilung_id INTEGER,
      ttlock_gateway_id BIGINT, gateway_online BOOLEAN, lock_mac TEXT,
      akku_prozent INTEGER, akku_stand_at TEXT, aktiv BOOLEAN, notiz TEXT,
      letzter_log_serverdate BIGINT, letztes_event_at TEXT, letztes_event_type INTEGER,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
    CREATE TABLE IF NOT EXISTS schluessel_chip (
      id               SERIAL PRIMARY KEY,
      kartennummer     TEXT NOT NULL,
      bezeichnung      TEXT,
      mitglied_id      INTEGER REFERENCES mitglied(id),
      aufbewahrungsort TEXT,
      status           TEXT NOT NULL DEFAULT 'aktiv',
      version          INTEGER NOT NULL DEFAULT 1,
      created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by       TEXT,
      updated_at       TEXT,
      updated_by       TEXT,
      deleted_at       TEXT,
      deleted_by       TEXT
    );
    CREATE TABLE IF NOT EXISTS schluessel_chip_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      kartennummer TEXT, bezeichnung TEXT, mitglied_id INTEGER, aufbewahrungsort TEXT,
      status TEXT,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
    CREATE TABLE IF NOT EXISTS tuer_berechtigung (
      id             SERIAL PRIMARY KEY,
      chip_id        INTEGER NOT NULL REFERENCES schluessel_chip(id),
      schloss_id     INTEGER NOT NULL REFERENCES tuer_schloss(id),
      ttlock_card_id BIGINT,
      gueltig_von    TEXT,
      gueltig_bis    TEXT,
      sync_status    TEXT NOT NULL DEFAULT 'pending',
      sync_fehler    TEXT,
      erteilt_von    INTEGER REFERENCES users(id),
      version        INTEGER NOT NULL DEFAULT 1,
      created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by     TEXT,
      updated_at     TEXT,
      updated_by     TEXT,
      deleted_at     TEXT,
      deleted_by     TEXT
    );
    CREATE TABLE IF NOT EXISTS tuer_berechtigung_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      chip_id INTEGER, schloss_id INTEGER, ttlock_card_id BIGINT,
      gueltig_von TEXT, gueltig_bis TEXT, sync_status TEXT, sync_fehler TEXT,
      erteilt_von INTEGER,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
    CREATE TABLE IF NOT EXISTS tuer_zutritt_log (
      id                    SERIAL PRIMARY KEY,
      ttlock_record_id      BIGINT NOT NULL UNIQUE,
      schloss_id            INTEGER NOT NULL REFERENCES tuer_schloss(id),
      record_type           INTEGER,
      record_type_from_lock INTEGER,
      methode               TEXT,
      erfolg                BOOLEAN,
      credential            TEXT,
      key_name              TEXT,
      ttlock_username       TEXT,
      chip_id               INTEGER REFERENCES schluessel_chip(id),
      mitglied_id           INTEGER REFERENCES mitglied(id),
      lock_date             TEXT,
      server_date           BIGINT,
      raw                   JSONB,
      created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

# Einfache Indizes (CREATE INDEX-Loop), geteilt zwischen Frischaufbau und Migration.
_ZUTRITT_INDEXES = (
    ("idx_tuer_schloss_abteilung_id",     "tuer_schloss(abteilung_id)"),
    ("idx_tuer_schloss_deleted_at",       "tuer_schloss(deleted_at)"),
    ("idx_tuer_schloss_history_id",       "tuer_schloss_history(id)"),
    ("idx_schluessel_chip_mitglied_id",   "schluessel_chip(mitglied_id)"),
    ("idx_schluessel_chip_deleted_at",    "schluessel_chip(deleted_at)"),
    ("idx_schluessel_chip_history_id",    "schluessel_chip_history(id)"),
    ("idx_tuer_berechtigung_chip_id",     "tuer_berechtigung(chip_id)"),
    ("idx_tuer_berechtigung_schloss_id",  "tuer_berechtigung(schloss_id)"),
    ("idx_tuer_berechtigung_deleted_at",  "tuer_berechtigung(deleted_at)"),
    ("idx_tuer_berechtigung_history_id",  "tuer_berechtigung_history(id)"),
    ("idx_tuer_zutritt_log_schloss_id",   "tuer_zutritt_log(schloss_id)"),
    ("idx_tuer_zutritt_log_chip_id",      "tuer_zutritt_log(chip_id)"),
    ("idx_tuer_zutritt_log_mitglied_id",  "tuer_zutritt_log(mitglied_id)"),
    ("idx_tuer_zutritt_log_lock_date",    "tuer_zutritt_log(lock_date)"),
    ("idx_tuer_zutritt_log_server_date",  "tuer_zutritt_log(schloss_id, server_date)"),
)

# Partielle Unique-Indizes (Soft-Delete-tauglich), explizit ausgeführt.
_ZUTRITT_UNIQUE_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_tuer_schloss_lock_active "
    "ON tuer_schloss (ttlock_lock_id) WHERE deleted_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_schluessel_chip_kartennummer_active "
    "ON schluessel_chip (kartennummer) WHERE deleted_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_tuer_berechtigung_chip_schloss_active "
    "ON tuer_berechtigung (chip_id, schloss_id) WHERE deleted_at IS NULL",
)

# Audit-Trigger (Tabelle ↔ Funktion), geteilt zwischen Frischaufbau und Migration.
_ZUTRITT_TRIGGERS = (
    ('trig_tuer_schloss_audit_insert',      'INSERT', 'tuer_schloss',      'fn_tuer_schloss_audit_insert'),
    ('trig_tuer_schloss_audit_update',      'UPDATE', 'tuer_schloss',      'fn_tuer_schloss_audit_update'),
    ('trig_schluessel_chip_audit_insert',   'INSERT', 'schluessel_chip',   'fn_schluessel_chip_audit_insert'),
    ('trig_schluessel_chip_audit_update',   'UPDATE', 'schluessel_chip',   'fn_schluessel_chip_audit_update'),
    ('trig_tuer_berechtigung_audit_insert', 'INSERT', 'tuer_berechtigung', 'fn_tuer_berechtigung_audit_insert'),
    ('trig_tuer_berechtigung_audit_update', 'UPDATE', 'tuer_berechtigung', 'fn_tuer_berechtigung_audit_update'),
)

# Neue Permission-Keys (Seed Admin + Migration für Bestands-Admins).
_ZUTRITT_PERMISSIONS = (
    'schliessanlage.read',
    'schliessanlage.verwalten',
    'schliessanlage.protokoll',
)

# ----------------------------------------------------------------------------
# Kurzzeitige App-Betätigungs-Berechtigung (Schema v58): einem User befristet das
# Öffnen genau eines Schlosses per App erlauben – ohne Chip. Getrennt von
# tuer_berechtigung (Chip↔Schloss/IC-Card), da es hier keinen Chip gibt.
# ----------------------------------------------------------------------------
_TUER_APP_BERECHTIGUNG_COLS = (
    "id, version, user_id, schloss_id, gueltig_von, gueltig_bis, grund, erteilt_von, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_TUER_APP_BERECHTIGUNG_VALS = ", ".join(
    "NEW." + c.strip() for c in _TUER_APP_BERECHTIGUNG_COLS.split(","))

_FN_TUER_APP_BERECHTIGUNG_AUDIT_INSERT = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_app_berechtigung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO tuer_app_berechtigung_history ({_TUER_APP_BERECHTIGUNG_COLS}) VALUES ({_TUER_APP_BERECHTIGUNG_VALS});
        RETURN NEW;
    END; $$;
"""
_FN_TUER_APP_BERECHTIGUNG_AUDIT_UPDATE = f"""
    CREATE OR REPLACE FUNCTION fn_tuer_app_berechtigung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO tuer_app_berechtigung_history ({_TUER_APP_BERECHTIGUNG_COLS}) VALUES ({_TUER_APP_BERECHTIGUNG_VALS});
        END IF;
        RETURN NEW;
    END; $$;
"""

_DDL_TUER_APP_BERECHTIGUNG = """
    CREATE TABLE IF NOT EXISTS tuer_app_berechtigung (
      id          SERIAL PRIMARY KEY,
      user_id     INTEGER NOT NULL REFERENCES users(id),
      schloss_id  INTEGER NOT NULL REFERENCES tuer_schloss(id),
      gueltig_von TEXT,
      gueltig_bis TEXT,
      grund       TEXT,
      erteilt_von INTEGER REFERENCES users(id),
      version     INTEGER NOT NULL DEFAULT 1,
      created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      created_by  TEXT,
      updated_at  TEXT,
      updated_by  TEXT,
      deleted_at  TEXT,
      deleted_by  TEXT
    );
    CREATE TABLE IF NOT EXISTS tuer_app_berechtigung_history (
      id INTEGER NOT NULL, version INTEGER NOT NULL,
      user_id INTEGER, schloss_id INTEGER, gueltig_von TEXT, gueltig_bis TEXT,
      grund TEXT, erteilt_von INTEGER,
      created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
      deleted_at TEXT, deleted_by TEXT,
      PRIMARY KEY (id, version)
    );
"""

_TUER_APP_BERECHTIGUNG_INDEXES = (
    ("idx_tuer_app_berechtigung_user_id",    "tuer_app_berechtigung(user_id)"),
    ("idx_tuer_app_berechtigung_schloss_id", "tuer_app_berechtigung(schloss_id)"),
    ("idx_tuer_app_berechtigung_deleted_at", "tuer_app_berechtigung(deleted_at)"),
    ("idx_tuer_app_berechtigung_history_id", "tuer_app_berechtigung_history(id)"),
)

_TUER_APP_BERECHTIGUNG_TRIGGERS = (
    ('trig_tuer_app_berechtigung_audit_insert', 'INSERT', 'tuer_app_berechtigung', 'fn_tuer_app_berechtigung_audit_insert'),
    ('trig_tuer_app_berechtigung_audit_update', 'UPDATE', 'tuer_app_berechtigung', 'fn_tuer_app_berechtigung_audit_update'),
)

# ----------------------------------------------------------------------------
# Read-only Credential-Mirror je Schloss (Schema v59): Fingerprints, Passcodes,
# App-/eKeys und IC-Karten 1:1 aus der TTLock-Cloud spiegeln, damit auch
# Credential-Typen sichtbar werden, die NICHT über unsere App liefen (Fingerprints/
# Funk-Keys = bisheriger blinder Fleck). Reiner Mirror – kein History/Audit/Soft-Delete;
# pro Schloss+Typ wird die Cloud-Liste autoritativ ersetzt. Indizes sind in der DDL
# eingebettet (self-contained), da die Tabelle keine geteilten Index-/Trigger-Tupel nutzt.
# ----------------------------------------------------------------------------
_DDL_TUER_CREDENTIAL = """
    CREATE TABLE IF NOT EXISTS tuer_credential (
      id                   SERIAL PRIMARY KEY,
      schloss_id           INTEGER NOT NULL REFERENCES tuer_schloss(id),
      typ                  TEXT NOT NULL,
      ttlock_credential_id BIGINT,
      name                 TEXT,
      detail               TEXT,
      gueltig_von          TEXT,
      gueltig_bis          TEXT,
      gesehen_am           TEXT,
      raw                  JSONB,
      created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_tuer_credential_schloss_id
      ON tuer_credential(schloss_id);
    CREATE UNIQUE INDEX IF NOT EXISTS uix_tuer_credential_schloss_typ_credid
      ON tuer_credential(schloss_id, typ, ttlock_credential_id);
"""


class Database:
    """Manages PostgreSQL connection and schema."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        self.conn = psycopg.connect(database_url, row_factory=dict_row)
        self._init_schema()

    @contextmanager
    def cursor(self):
        """Context manager for cursor with automatic commit/rollback."""
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def close(self):
        self.conn.close()

    # -----------------------------------
    # Schema-Initialisierung
    # -----------------------------------

    def _init_schema(self):
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id         INTEGER PRIMARY KEY CHECK (id = 1),
                    version    INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            logger.info("Frische Datenbank – Schema v%d wird erstellt …", SCHEMA_VERSION)
            self._create_schema()
            logger.info("Schema v%d erfolgreich angelegt.", SCHEMA_VERSION)
        elif row['version'] < SCHEMA_VERSION:
            logger.info("Schema-Version in DB: v%d – Code erwartet v%d. Starte Migrationen …",
                        row['version'], SCHEMA_VERSION)
            self._run_migrations(row['version'])
            logger.info("Alle Migrationen abgeschlossen. Schema jetzt v%d.", SCHEMA_VERSION)
        elif row['version'] > SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema-Version {row['version']} ist neuer als der Code (v{SCHEMA_VERSION}). "
                f"Bitte Code aktualisieren."
            )
        else:
            logger.info("Datenbank bereit. Schema v%d.", SCHEMA_VERSION)

    def _run_migrations(self, current_version: int) -> None:
        """Führt alle ausstehenden Migrationen sequenziell aus.
        Jede Migration läuft in einer eigenen Transaktion und aktualisiert
        schema_version als letzten Schritt — bei Fehler vollständiger Rollback."""
        migration_map = {
            16: self._migrate_v15_to_v16,
            17: self._migrate_v16_to_v17,
            18: self._migrate_v17_to_v18,
            19: self._migrate_v18_to_v19,
            20: self._migrate_v19_to_v20,
            21: self._migrate_v20_to_v21,
            22: self._migrate_v21_to_v22,
            23: self._migrate_v22_to_v23,
            24: self._migrate_v23_to_v24,
            25: self._migrate_v24_to_v25,
            26: self._migrate_v25_to_v26,
            27: self._migrate_v26_to_v27,
            28: self._migrate_v27_to_v28,
            29: self._migrate_v28_to_v29,
            30: self._migrate_v29_to_v30,
            31: self._migrate_v30_to_v31,
            32: self._migrate_v31_to_v32,
            33: self._migrate_v32_to_v33,
            34: self._migrate_v33_to_v34,
            35: self._migrate_v34_to_v35,
            36: self._migrate_v35_to_v36,
            37: self._migrate_v36_to_v37,
            38: self._migrate_v37_to_v38,
            39: self._migrate_v38_to_v39,
            40: self._migrate_v39_to_v40,
            41: self._migrate_v40_to_v41,
            42: self._migrate_v41_to_v42,
            43: self._migrate_v42_to_v43,
            44: self._migrate_v43_to_v44,
            45: self._migrate_v44_to_v45,
            46: self._migrate_v45_to_v46,
            47: self._migrate_v46_to_v47,
            48: self._migrate_v47_to_v48,
            49: self._migrate_v48_to_v49,
            50: self._migrate_v49_to_v50,
            51: self._migrate_v50_to_v51,
            52: self._migrate_v51_to_v52,
            53: self._migrate_v52_to_v53,
            54: self._migrate_v53_to_v54,
            55: self._migrate_v54_to_v55,
            56: self._migrate_v55_to_v56,
            57: self._migrate_v56_to_v57,
            58: self._migrate_v57_to_v58,
            59: self._migrate_v58_to_v59,
            60: self._migrate_v59_to_v60,
        }
        for target in range(current_version + 1, SCHEMA_VERSION + 1):
            fn = migration_map.get(target)
            if fn is None:
                raise RuntimeError(
                    f"Keine Migrationsfunktion für v{target} vorhanden. "
                    f"Bitte Code aktualisieren."
                )
            logger.info("Schema-Migration v%d → v%d wird ausgeführt …", target - 1, target)
            fn()
            logger.info("Schema-Migration v%d abgeschlossen.", target)

    def _migrate_v15_to_v16(self) -> None:
        """Partielle Unique-Indizes auf users.email/username (statt harter UNIQUE-Constraints),
        damit soft-gelöschte Accounts die E-Mail nicht dauerhaft blockieren."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key")
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_email_active
                ON users (email) WHERE deleted_at IS NULL
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_username_active
                ON users (username) WHERE deleted_at IS NULL
            """)
            cur.execute("UPDATE schema_version SET version = 16 WHERE id = 1")

    def _migrate_v16_to_v17(self) -> None:
        """mitglied.user_id → users.id (optional, 1:1) + Rolle 'mitglied' im CHECK-Constraint."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
            cur.execute("""
                ALTER TABLE users ADD CONSTRAINT users_role_check
                CHECK(role IN ('admin', 'user', 'readonly', 'special', 'mitglied'))
            """)
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_user_id
                ON mitglied (user_id) WHERE user_id IS NOT NULL
            """)
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS user_id INTEGER")
            cur.execute("UPDATE schema_version SET version = 17 WHERE id = 1")

    def _migrate_v17_to_v18(self) -> None:
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel RENAME COLUMN betrag TO betrag_pro_monat")
            cur.execute("ALTER TABLE beitragsregel RENAME COLUMN periode TO einzug_turnus")
            cur.execute("ALTER TABLE beitragsregel_history RENAME COLUMN betrag TO betrag_pro_monat")
            cur.execute("ALTER TABLE beitragsregel_history RENAME COLUMN periode TO einzug_turnus")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS zahler_typ TEXT NOT NULL DEFAULT 'mitglied'")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS zahler_kasse_id INTEGER REFERENCES kassen(id)")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_abteilung_status TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS zahler_typ TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS zahler_kasse_id INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_abteilung_status TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS faelligkeitsdatum TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'offen'")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS bezahlt_am TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS kassenbuchung_id INTEGER REFERENCES kassenbuchungen(id)")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS faelligkeitsdatum TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS status TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS bezahlt_am TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS kassenbuchung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_insert
                AFTER INSERT ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_update
                AFTER UPDATE ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_update();
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitrag_sollstellung_history (
                        id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                        faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                        NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitrag_sollstellung_history (
                            id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                            faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                            NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_insert
                AFTER INSERT ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_update
                AFTER UPDATE ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 18 WHERE id = 1")

    def _migrate_v18_to_v19(self) -> None:
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_funktion (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  abteilung_id   INTEGER REFERENCES abteilung(id),
                  funktion       TEXT NOT NULL,
                  von            TEXT,
                  bis            TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_funktion_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,
                  mitglied_id    INTEGER,
                  abteilung_id   INTEGER,
                  funktion       TEXT,
                  von            TEXT,
                  bis            TEXT,
                  created_at     TEXT,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_funktion_history (
                        id, version, mitglied_id, abteilung_id, funktion, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_funktion_history (
                            id, version, mitglied_id, abteilung_id, funktion, von, bis,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_insert
                AFTER INSERT ON mitglied_funktion
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_update
                AFTER UPDATE ON mitglied_funktion
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_update();
            """)
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER REFERENCES abteilung(id)")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 19 WHERE id = 1")

    def _migrate_v19_to_v20(self) -> None:
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion (
                  id            SERIAL PRIMARY KEY,
                  key           TEXT NOT NULL,
                  name          TEXT NOT NULL,
                  beschreibung  TEXT,
                  version       INTEGER NOT NULL DEFAULT 1,
                  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  created_by    TEXT,
                  updated_at    TIMESTAMP,
                  updated_by    TEXT,
                  deleted_at    TIMESTAMP,
                  deleted_by    TEXT
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_funktion_key_active
                ON funktion (key)
                WHERE deleted_at IS NULL
            """)
            for key, name in [
                ('schiedsrichter',   'Schiedsrichter'),
                ('uebungsleiter',    'Übungsleiter'),
                ('abteilungsleiter', 'Abteilungsleiter'),
            ]:
                cur.execute("""
                    INSERT INTO funktion (key, name, created_by)
                    SELECT %s, %s, 'system'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM funktion WHERE key = %s AND deleted_at IS NULL
                    )
                """, (key, name, key))
            cur.execute("UPDATE schema_version SET version = 20 WHERE id = 1")

    def _migrate_v20_to_v21(self) -> None:
        """Benennt Permissions von mitglieder.*/users.* auf personen.* um."""
        mapping = [
            ('mitglieder.read',   'personen.read'),
            ('mitglieder.write',  'personen.write'),
            ('mitglieder.delete', 'personen.delete'),
            ('users.manage',      'personen.permissions'),
            ('users.read',        'personen.read'),
        ]
        with self.cursor() as cur:
            for old, new in mapping:
                # Neue Permission anlegen wo sie noch nicht existiert
                cur.execute("""
                    INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                    SELECT user_id, %s, created_by, created_by
                    FROM user_permissions
                    WHERE permission = %s
                      AND deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM user_permissions up2
                          WHERE up2.user_id = user_permissions.user_id
                            AND up2.permission = %s
                            AND up2.deleted_at IS NULL
                      )
                """, (new, old, new))
                # Alte Permission soft-deleten
                cur.execute("""
                    UPDATE user_permissions
                    SET deleted_at = CURRENT_TIMESTAMP, deleted_by = 'migration_v21'
                    WHERE permission = %s AND deleted_at IS NULL
                """, (old,))
            # users.manage-User bekommen auch personen.read/write/delete
            for perm in ('personen.read', 'personen.write', 'personen.delete'):
                cur.execute("""
                    INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                    SELECT DISTINCT user_id, %s, 'migration_v21', 'migration_v21'
                    FROM user_permissions
                    WHERE permission = 'personen.permissions'
                      AND deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM user_permissions up2
                          WHERE up2.user_id = user_permissions.user_id
                            AND up2.permission = %s
                            AND up2.deleted_at IS NULL
                      )
                """, (perm, perm))
            cur.execute("UPDATE schema_version SET version = 21 WHERE id = 1")

    def _migrate_v21_to_v22(self) -> None:
        """Fügt bedingung_funktion_abteilung_id zu beitragsregel hinzu."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_funktion_abteilung_id INTEGER REFERENCES abteilung(id)")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_funktion_abteilung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, bedingung_funktion_abteilung_id,
                        ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, bedingung_funktion_abteilung_id,
                            ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.bedingung_funktion_abteilung_id,
                            NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 22 WHERE id = 1")

    def _migrate_v22_to_v23(self) -> None:
        """Fügt funktion_history + Audit-Trigger für die funktion-Tabelle hinzu."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion_history (
                  id           INTEGER NOT NULL,
                  version      INTEGER NOT NULL,
                  key          TEXT,
                  name         TEXT,
                  beschreibung TEXT,
                  created_at   TIMESTAMP,
                  created_by   TEXT,
                  updated_at   TIMESTAMP,
                  updated_by   TEXT,
                  deleted_at   TIMESTAMP,
                  deleted_by   TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO funktion_history (
                        id, version, key, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO funktion_history (
                            id, version, key, name, beschreibung,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                            NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_audit_insert
                AFTER INSERT ON funktion
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_audit_update
                AFTER UPDATE ON funktion
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 23 WHERE id = 1")

    def _migrate_v23_to_v24(self) -> None:
        """Mehrere Kontaktdaten je Mitglied: neue Tabelle mitglied_kontakt (voll
        normalisiert). Bestehende mitglied.email/telefon werden als primäre Kontakte
        übernommen, danach werden die Spalten entfernt. mitglied_history behält seine
        email/telefon-Spalten als eingefrorene Historie."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_kontakt (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  typ            TEXT NOT NULL,
                  wert           TEXT NOT NULL,
                  label          TEXT,
                  ist_primaer    BOOLEAN NOT NULL DEFAULT FALSE,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_kontakt_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,
                  mitglied_id    INTEGER,
                  typ            TEXT,
                  wert           TEXT,
                  label          TEXT,
                  ist_primaer    BOOLEAN,
                  created_at     TEXT,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_kontakt_history (
                        id, version, mitglied_id, typ, wert, label, ist_primaer,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_kontakt_history (
                            id, version, mitglied_id, typ, wert, label, ist_primaer,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_kontakt_audit_insert
                AFTER INSERT ON mitglied_kontakt
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_kontakt_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_kontakt_audit_update
                AFTER UPDATE ON mitglied_kontakt
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_kontakt_audit_update();
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_mitglied_id ON mitglied_kontakt(mitglied_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_deleted_at  ON mitglied_kontakt(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_history_id  ON mitglied_kontakt_history(id)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_kontakt_primaer ON mitglied_kontakt (mitglied_id, typ) WHERE ist_primaer AND deleted_at IS NULL")

            # Bestandsdaten übernehmen: vorhandene email/telefon als primäre Kontakte
            cur.execute("""
                INSERT INTO mitglied_kontakt (mitglied_id, typ, wert, ist_primaer, created_by)
                SELECT id, 'email', email, TRUE, 'migration'
                FROM mitglied WHERE email IS NOT NULL AND email <> ''
            """)
            cur.execute("""
                INSERT INTO mitglied_kontakt (mitglied_id, typ, wert, ist_primaer, created_by)
                SELECT id, 'telefon', telefon, TRUE, 'migration'
                FROM mitglied WHERE telefon IS NOT NULL AND telefon <> ''
            """)

            # mitglied-Audit-Funktionen ohne email/telefon neu definieren …
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_history (
                            id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                            strasse, plz, ort, land,
                            eintrittsdatum, austrittsdatum, status,
                            zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                            user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                            NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                            NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                            NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                            NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            # … und erst danach die Spalten entfernen (Funktion referenziert sie nicht mehr)
            cur.execute("ALTER TABLE mitglied DROP COLUMN IF EXISTS email")
            cur.execute("ALTER TABLE mitglied DROP COLUMN IF EXISTS telefon")

            cur.execute("UPDATE schema_version SET version = 24 WHERE id = 1")

    def _migrate_v24_to_v25(self) -> None:
        """Funktions-Zeitraum verpflichtend: mitglied_funktion.von wird NOT NULL.
        Bestehende NULL/leere Werte werden auf das Anlagedatum (created_at) gesetzt."""
        with self.cursor() as cur:
            cur.execute("""
                UPDATE mitglied_funktion
                SET von = COALESCE(NULLIF(von, ''), LEFT(created_at, 10), CURRENT_DATE::text)
                WHERE von IS NULL OR von = ''
            """)
            cur.execute("ALTER TABLE mitglied_funktion ALTER COLUMN von SET NOT NULL")
            cur.execute("UPDATE schema_version SET version = 25 WHERE id = 1")

    def _migrate_v25_to_v26(self) -> None:
        """Altersabhängige Beitragsregeln: bedingung_alter_min/max an beitragsregel."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_alter_min INTEGER")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_alter_max INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_alter_min INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_alter_max INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 26 WHERE id = 1")

    def _migrate_v26_to_v27(self) -> None:
        """Mannschaften/Teams: mannschaft + mitglied_mannschaft (mit Rolle/Zeitraum)."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mannschaft (
                  id             SERIAL PRIMARY KEY,
                  abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
                  name           TEXT NOT NULL,
                  saison         TEXT,
                  beschreibung   TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mannschaft_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  abteilung_id INTEGER, name TEXT, saison TEXT, beschreibung TEXT,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_mannschaft (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  mannschaft_id  INTEGER NOT NULL REFERENCES mannschaft(id),
                  rolle          TEXT NOT NULL,
                  von            TEXT NOT NULL,
                  bis            TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_mannschaft_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  mitglied_id INTEGER, mannschaft_id INTEGER, rolle TEXT, von TEXT, bis TEXT,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            for sql in (
                """CREATE OR REPLACE FUNCTION fn_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO mannschaft_history (id, version, abteilung_id, name, saison, beschreibung,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO mannschaft_history (id, version, abteilung_id, name, saison, beschreibung,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO mitglied_mannschaft_history (id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO mitglied_mannschaft_history (id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                "CREATE OR REPLACE TRIGGER trig_mannschaft_audit_insert AFTER INSERT ON mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mannschaft_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_mannschaft_audit_update AFTER UPDATE ON mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mannschaft_audit_update()",
                "CREATE OR REPLACE TRIGGER trig_mitglied_mannschaft_audit_insert AFTER INSERT ON mitglied_mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mitglied_mannschaft_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_mitglied_mannschaft_audit_update AFTER UPDATE ON mitglied_mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mitglied_mannschaft_audit_update()",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_abteilung_id ON mannschaft(abteilung_id)",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_deleted_at ON mannschaft(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_history_id ON mannschaft_history(id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_mitglied_id ON mitglied_mannschaft(mitglied_id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_mannschaft_id ON mitglied_mannschaft(mannschaft_id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_deleted_at ON mitglied_mannschaft(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_history_id ON mitglied_mannschaft_history(id)",
            ):
                cur.execute(sql)
            cur.execute("UPDATE schema_version SET version = 27 WHERE id = 1")

    def _migrate_v27_to_v28(self) -> None:
        """Aufnahme-/Einmalgebühren: gebuehr (Katalog mit Gültigkeit) + gebuehr_forderung
        (einmalige Forderung je Mitglied, einziehbar wie Beiträge)."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr (
                  id              SERIAL PRIMARY KEY,
                  name            TEXT NOT NULL,
                  abteilung_id    INTEGER REFERENCES abteilung(id),
                  betrag          REAL NOT NULL,
                  anlass          TEXT NOT NULL DEFAULT 'aufnahme',
                  gueltig_ab      TEXT NOT NULL,
                  gueltig_bis     TEXT,
                  zahler_typ      TEXT NOT NULL DEFAULT 'mitglied',
                  zahler_kasse_id INTEGER REFERENCES kassen(id),
                  version         INTEGER NOT NULL DEFAULT 1,
                  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by      TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at      TEXT, deleted_by TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  name TEXT, abteilung_id INTEGER, betrag REAL, anlass TEXT,
                  gueltig_ab TEXT, gueltig_bis TEXT, zahler_typ TEXT, zahler_kasse_id INTEGER,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_forderung (
                  id                SERIAL PRIMARY KEY,
                  mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
                  gebuehr_id        INTEGER NOT NULL REFERENCES gebuehr(id),
                  datum             TEXT NOT NULL,
                  betrag_soll       REAL NOT NULL,
                  status            TEXT NOT NULL DEFAULT 'offen',
                  bezahlt_am        TEXT,
                  kassenbuchung_id  INTEGER REFERENCES kassenbuchungen(id),
                  version           INTEGER NOT NULL DEFAULT 1,
                  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by        TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at        TEXT, deleted_by TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_forderung_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  mitglied_id INTEGER, gebuehr_id INTEGER, datum TEXT, betrag_soll REAL,
                  status TEXT, bezahlt_am TEXT, kassenbuchung_id INTEGER,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            for sql in (
                """CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO gebuehr_history (id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                       zahler_typ, zahler_kasse_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                       NEW.zahler_typ, NEW.zahler_kasse_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO gebuehr_history (id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                       zahler_typ, zahler_kasse_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                       NEW.zahler_typ, NEW.zahler_kasse_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO gebuehr_forderung_history (id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO gebuehr_forderung_history (id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_audit_insert AFTER INSERT ON gebuehr FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_audit_update AFTER UPDATE ON gebuehr FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_audit_update()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_forderung_audit_insert AFTER INSERT ON gebuehr_forderung FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_forderung_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_forderung_audit_update AFTER UPDATE ON gebuehr_forderung FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_forderung_audit_update()",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_abteilung_id ON gebuehr(abteilung_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_deleted_at ON gebuehr(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_history_id ON gebuehr_history(id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_mitglied_id ON gebuehr_forderung(mitglied_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_gebuehr_id ON gebuehr_forderung(gebuehr_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_status ON gebuehr_forderung(status)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_deleted_at ON gebuehr_forderung(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_history_id ON gebuehr_forderung_history(id)",
            ):
                cur.execute(sql)
            cur.execute("UPDATE schema_version SET version = 28 WHERE id = 1")

    def _migrate_v28_to_v29(self) -> None:
        """Import-Zusatzfelder am Mitglied: Geschlecht, Bemerkungen, SEPA-Mandatsreferenz
        (+ -datum). Für die Übernahme aus dem SPG-Verein-Export."""
        with self.cursor() as cur:
            for col in ('geschlecht', 'bemerkungen', 'sepa_mandatsref', 'sepa_mandatsdatum'):
                cur.execute(f"ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS {col} TEXT")
                cur.execute(f"ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS {col} TEXT")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                        user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                        NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_history (
                            id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                            strasse, plz, ort, land,
                            eintrittsdatum, austrittsdatum, status,
                            zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                            geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                            user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                            NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                            NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                            NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                            NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                            NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 29 WHERE id = 1")

    def _migrate_v29_to_v30(self) -> None:
        """Entfernt die 'Kasse für Umbuchung' (zahler_kasse_id) aus beitragsregel und
        gebuehr (inkl. *_history). Beiträge/Gebühren werden nie auf Kassen gebucht;
        zahler_typ='abteilung' bleibt als reine Zahler-Zuordnung erhalten."""
        with self.cursor() as cur:
            # Audit-Trigger-Funktionen ohne zahler_kasse_id neu schreiben (sonst brechen
            # sie beim nächsten INSERT/UPDATE, weil NEW.zahler_kasse_id wegfällt).
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO gebuehr_history (
                        id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                        zahler_typ,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                        NEW.zahler_typ,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO gebuehr_history (
                            id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                            zahler_typ,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                            NEW.zahler_typ,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            # Spalte überall entfernen (FK auf kassen wird mit gedroppt)
            for tbl in ('beitragsregel', 'beitragsregel_history', 'gebuehr', 'gebuehr_history'):
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS zahler_kasse_id")
            cur.execute("UPDATE schema_version SET version = 30 WHERE id = 1")

    def _migrate_v30_to_v31(self) -> None:
        """Matrix-ID/Telegram-ID-Unique-Indizes schließen soft-gelöschte User aus.
        Bisher blockierte ein gelöschter Account die Matrix-/Telegram-ID dauerhaft,
        sodass sie kein anderer (lebender) Benutzer mehr verwenden konnte –
        analog zu uix_users_email_active/uix_users_username_active."""
        with self.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS uix_users_matrix_id")
            cur.execute("DROP INDEX IF EXISTS uix_users_telegram_id")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_matrix_id
                ON users (matrix_id) WHERE matrix_id IS NOT NULL AND deleted_at IS NULL
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_telegram_id
                ON users (telegram_id) WHERE telegram_id IS NOT NULL AND deleted_at IS NULL
            """)
            cur.execute("UPDATE schema_version SET version = 31 WHERE id = 1")

    def _migrate_v31_to_v32(self) -> None:
        """Fehlende Audit-Trigger auf beitragsregel und beitrag_sollstellung nachziehen.
        Beide Tabellen entstanden in der v17→v18-Migration; DBs, die diese Migration
        durchliefen, bevor die Trigger-Erzeugung dort ergänzt wurde, haben zwar die
        fn_*_audit_*-Funktionen, aber keine angebrachten Trigger – es wurde also keine
        *_history geschrieben. Frischaufbauten sind nicht betroffen (siehe _create_triggers).
        CREATE OR REPLACE TRIGGER ist idempotent: auf bereits korrekten DBs ein No-Op."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_insert
                AFTER INSERT ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_update
                AFTER UPDATE ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_update();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_insert
                AFTER INSERT ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_update
                AFTER UPDATE ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 32 WHERE id = 1")

    def _migrate_v32_to_v33(self) -> None:
        """Ein-/Ausschluss von Funktionen je Beitragsregel von Einzelwert auf
        Mehrfachauswahl umstellen: bedingung_funktion/ausnahme_funktion (TEXT) →
        bedingung_funktionen/ausnahme_funktionen (TEXT[]). Bestehende Einzelwerte
        werden in einelementige Arrays migriert, danach die Altspalten entfernt.
        Die Abteilungs-Qualifizierer (…_abteilung_id) bleiben unverändert."""
        with self.cursor() as cur:
            # 1) Neue Array-Spalten anlegen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS bedingung_funktionen TEXT[]")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS ausnahme_funktionen TEXT[]")

            # 2) Backfill: vorhandene Einzelwerte in einelementige Arrays überführen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(
                    f"UPDATE {tbl} SET bedingung_funktionen = ARRAY[bedingung_funktion] "
                    f"WHERE bedingung_funktion IS NOT NULL AND bedingung_funktion <> ''"
                )
                cur.execute(
                    f"UPDATE {tbl} SET ausnahme_funktionen = ARRAY[ausnahme_funktion] "
                    f"WHERE ausnahme_funktion IS NOT NULL AND ausnahme_funktion <> ''"
                )

            # 3) Audit-Trigger-Funktionen auf die neuen Spalten umstellen (vor dem Drop,
            #    damit die Funktionskörper keine entfallenden Spalten mehr referenzieren)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktionen, bedingung_funktion_abteilung_id,
                        ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktionen, bedingung_funktion_abteilung_id,
                            ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                            NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            # 4) Altspalten entfernen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS bedingung_funktion")
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS ausnahme_funktion")

            cur.execute("UPDATE schema_version SET version = 33 WHERE id = 1")

    def _migrate_v33_to_v34(self) -> None:
        """Echtes Aktivitäts-Feld users.last_seen einführen.

        Bisher diente last_login doppelt: als Login-Zeitpunkt UND (durch den Bump
        bei jedem GET /me) als "zuletzt aktiv". Das war mehrdeutig. Ab jetzt:
        - last_login = echter Login (Passwort/Magic-Link)
        - last_seen  = letzter authentifizierter Request (im Auth-Dependency gebumpt)
        Bestandswerte werden mit last_login vorbelegt, damit "Zuletzt aktiv" nicht leer ist."""
        with self.cursor() as cur:
            for tbl in ('users', 'users_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS last_seen TEXT")
                cur.execute(f"UPDATE {tbl} SET last_seen = last_login WHERE last_seen IS NULL")

            # Audit-Trigger-Funktionen auf last_seen erweitern
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_users_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login, last_seen,
                        telegram_id, matrix_id, preferred_contact,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.last_seen, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_users_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO users_history (
                            id, version, username, email, password_hash, role, active, last_login, last_seen,
                            telegram_id, matrix_id, preferred_contact,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                            NEW.active, NEW.last_login, NEW.last_seen, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            cur.execute("UPDATE schema_version SET version = 34 WHERE id = 1")

    def _migrate_v34_to_v35(self) -> None:
        """Funktionsbasierte Berechtigungen – Stufe A (siehe BERECHTIGUNGEN.md).

        1. Neue Tabelle funktion_permission: Berechtigungsmatrix pro Katalog-Funktion.
           Referenz über funktion_id (nicht key): FK auf den partiellen Unique-Index
           uix_funktion_key_active ist nicht möglich, und Key-Reuse nach Soft-Delete
           darf alte Rechte nicht wiederbeleben.
        2. user_permissions wird zum Tri-State-Override: effect 'grant'|'deny'.
           Bestandszeilen werden durch DEFAULT 'grant' automatisch zu individuellen
           Grants – kein Datenumbau nötig, niemand verliert Rechte.
        3. abteilung_id als Scope-Reserve (Stufe A immer NULL).
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion_permission (
                  id           SERIAL PRIMARY KEY,
                  funktion_id  INTEGER NOT NULL REFERENCES funktion(id),
                  permission   TEXT NOT NULL,
                  version      INTEGER NOT NULL DEFAULT 1,
                  created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by   TEXT NOT NULL,
                  updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_by   TEXT NOT NULL,
                  deleted_at   TEXT,
                  deleted_by   TEXT,
                  UNIQUE (funktion_id, permission)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion_permission_history (
                  id           INTEGER NOT NULL,
                  version      INTEGER NOT NULL,
                  funktion_id  INTEGER NOT NULL,
                  permission   TEXT NOT NULL,
                  created_at   TEXT NOT NULL,
                  created_by   TEXT NOT NULL,
                  updated_at   TEXT NOT NULL,
                  updated_by   TEXT NOT NULL,
                  deleted_at   TEXT,
                  deleted_by   TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_permission_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO funktion_permission_history (
                        id, version, funktion_id, permission,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.funktion_id, NEW.permission,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_permission_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO funktion_permission_history (
                            id, version, funktion_id, permission,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.funktion_id, NEW.permission,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_permission_audit_insert
                AFTER INSERT ON funktion_permission
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_permission_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_permission_audit_update
                AFTER UPDATE ON funktion_permission
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_permission_audit_update();
            """)

            # user_permissions → Tri-State-Override (+ Scope-Reserve)
            cur.execute("""
                ALTER TABLE user_permissions
                ADD COLUMN IF NOT EXISTS effect TEXT NOT NULL DEFAULT 'grant'
                CHECK (effect IN ('grant', 'deny'))
            """)
            cur.execute("""
                ALTER TABLE user_permissions
                ADD COLUMN IF NOT EXISTS abteilung_id INTEGER REFERENCES abteilung(id)
            """)
            cur.execute("ALTER TABLE user_permissions_history ADD COLUMN IF NOT EXISTS effect TEXT")
            cur.execute("ALTER TABLE user_permissions_history ADD COLUMN IF NOT EXISTS abteilung_id INTEGER")

            # Audit-Trigger-Funktionen auf die neuen Spalten erweitern (Muster v34)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_user_permissions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO user_permissions_history (
                        id, version, user_id, permission, effect, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission, NEW.effect, NEW.abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_user_permissions_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO user_permissions_history (
                            id, version, user_id, permission, effect, abteilung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.user_id, NEW.permission, NEW.effect, NEW.abteilung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_funktion_permission_funktion_id ON funktion_permission(funktion_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_funktion_permission_deleted_at ON funktion_permission(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_funktion_permission_history_id ON funktion_permission_history(id)")

            # Konsistenz-Check (nur WARN): mitglied_funktion.funktion ohne aktiven Katalog-Key.
            # Echte FK ist auf den partiellen Unique-Index nicht möglich (bekannte Altlast).
            cur.execute("""
                SELECT DISTINCT mf.funktion
                FROM mitglied_funktion mf
                WHERE mf.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM funktion f
                      WHERE f.key = mf.funktion AND f.deleted_at IS NULL
                  )
            """)
            verwaiste = [row['funktion'] for row in cur.fetchall()]
            if verwaiste:
                logger.warning(
                    "mitglied_funktion enthält Zuordnungen ohne aktiven Katalog-Eintrag: %s "
                    "– diese tragen keine Berechtigungen.", verwaiste
                )

            cur.execute("UPDATE schema_version SET version = 35 WHERE id = 1")

    def _migrate_v35_to_v36(self) -> None:
        """Rollen-Ablösung – Stufe D (siehe BERECHTIGUNGEN.md).

        Das Berechtigungssystem ist jetzt funktionsbasiert; feste Rollen entfallen.
        Es bleibt nur noch 'admin' (uneingeschränkt) und 'mitglied'. Alle anderen
        Bestands-Rollen ('user', 'readonly', 'special') werden auf 'mitglied'
        normalisiert.

        Niemand verliert dabei Rechte: Rollen-Defaults wurden seit jeher beim
        Anlegen in user_permissions materialisiert (es gab nie einen
        Rollen-Fallback zur Laufzeit). Diese Einträge bleiben als individuelle
        Grants bestehen.

        users_history bleibt unangetastet (immutable Audit-Historie) – die
        reduzierte CHECK-Constraint gilt nur für die Live-Tabelle.
        """
        with self.cursor() as cur:
            cur.execute("UPDATE users SET role = 'mitglied' WHERE role <> 'admin'")
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
            cur.execute("""
                ALTER TABLE users ADD CONSTRAINT users_role_check
                CHECK(role IN ('admin', 'mitglied'))
            """)
            cur.execute("UPDATE schema_version SET version = 36 WHERE id = 1")

    def _migrate_v36_to_v37(self) -> None:
        """Serverseitige Sessions – „eigene angemeldete Geräte" (Ticket #24).

        Bisher war die Authentifizierung zustandslos (JWT trägt nur sub+exp).
        Damit Nutzer ihre angemeldeten Geräte sehen und einzeln/„en bloc"
        abmelden können, wird je Login eine Session-Zeile gespeichert und ihre
        ID (sid) in den JWT eingebettet.

        Bestandstoken ohne sid bleiben bis zum Ablauf gültig (werden geduldet),
        tauchen mangels Datensatz aber nicht in der Geräteliste auf.

        Abmelden ist Soft-Revoke (revoked_at) – kein Hard-Delete; abgelaufene
        Sessions können später per Prune-Job entfernt werden.
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                  id            SERIAL PRIMARY KEY,
                  user_id       INTEGER NOT NULL REFERENCES users(id),
                  sid           TEXT UNIQUE NOT NULL,
                  user_agent    TEXT,
                  ip            TEXT,
                  device_label  TEXT,
                  expires_at    TEXT NOT NULL,
                  last_seen_at  TEXT,
                  revoked_at    TEXT,
                  revoked_by    TEXT,
                  version       INTEGER NOT NULL DEFAULT 1,
                  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions_history (
                  id            INTEGER NOT NULL,
                  version       INTEGER NOT NULL,
                  user_id       INTEGER NOT NULL,
                  sid           TEXT NOT NULL,
                  user_agent    TEXT,
                  ip            TEXT,
                  device_label  TEXT,
                  expires_at    TEXT NOT NULL,
                  last_seen_at  TEXT,
                  revoked_at    TEXT,
                  revoked_by    TEXT,
                  created_at    TEXT NOT NULL,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_user_sessions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO user_sessions_history (
                        id, version, user_id, sid, user_agent, ip, device_label,
                        expires_at, last_seen_at, revoked_at, revoked_by, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.sid, NEW.user_agent, NEW.ip, NEW.device_label,
                        NEW.expires_at, NEW.last_seen_at, NEW.revoked_at, NEW.revoked_by, NEW.created_at
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_user_sessions_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO user_sessions_history (
                            id, version, user_id, sid, user_agent, ip, device_label,
                            expires_at, last_seen_at, revoked_at, revoked_by, created_at
                        ) VALUES (
                            NEW.id, NEW.version, NEW.user_id, NEW.sid, NEW.user_agent, NEW.ip, NEW.device_label,
                            NEW.expires_at, NEW.last_seen_at, NEW.revoked_at, NEW.revoked_by, NEW.created_at
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_user_sessions_audit_insert
                AFTER INSERT ON user_sessions
                FOR EACH ROW EXECUTE FUNCTION fn_user_sessions_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_user_sessions_audit_update
                AFTER UPDATE ON user_sessions
                FOR EACH ROW EXECUTE FUNCTION fn_user_sessions_audit_update();
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_sid ON user_sessions(sid)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_revoked_at ON user_sessions(revoked_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_history_id ON user_sessions_history(id)")
            cur.execute("UPDATE schema_version SET version = 37 WHERE id = 1")

    def _migrate_v37_to_v38(self) -> None:
        """Verwaltete Kassen-Kategorien statt Freitext (TODO „Kassenbuch").

        Bisher war kassenbuchungen.kategorie ein freies Textfeld, was
        uneinheitliche Schreibweisen und damit zersplitterte Kategorien-Summen
        im Bericht erlaubte. Neue Stammdaten-Tabelle steuert die Auswahl bei der
        Erfassung (Dropdown). Geltungsbereich:
          kasse_id IS NULL → allgemeine Kategorie (bei jeder Kasse wählbar)
          kasse_id gesetzt → nur bei der zugeordneten Kasse wählbar.

        Die Buchung speichert die Kategorie weiterhin als Text (denormalisiert);
        Bestands-Buchungen behalten ihren Freitext unangetastet (Legacy).
        Soft-Delete-only; History via Trigger.
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen_kategorien (
                  id          SERIAL PRIMARY KEY,
                  kasse_id    INTEGER REFERENCES kassen(id),
                  name        TEXT NOT NULL,
                  version     INTEGER NOT NULL DEFAULT 1,
                  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by  TEXT NOT NULL,
                  updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_by  TEXT NOT NULL,
                  deleted_at  TEXT,
                  deleted_by  TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen_kategorien_history (
                  id          INTEGER NOT NULL,
                  version     INTEGER NOT NULL,
                  kasse_id    INTEGER,
                  name        TEXT,
                  created_at  TEXT,
                  created_by  TEXT,
                  updated_at  TEXT,
                  updated_by  TEXT,
                  deleted_at  TEXT,
                  deleted_by  TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO kassen_kategorien_history (
                        id, version, kasse_id, name,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.name,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO kassen_kategorien_history (
                            id, version, kasse_id, name,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.kasse_id, NEW.name,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_kassen_kategorien_audit_insert
                AFTER INSERT ON kassen_kategorien
                FOR EACH ROW EXECUTE FUNCTION fn_kassen_kategorien_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_kassen_kategorien_audit_update
                AFTER UPDATE ON kassen_kategorien
                FOR EACH ROW EXECUTE FUNCTION fn_kassen_kategorien_audit_update();
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_kategorien_kasse_id ON kassen_kategorien(kasse_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_kategorien_deleted_at ON kassen_kategorien(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_kategorien_history_id ON kassen_kategorien_history(id)")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uix_kassen_kategorien_scope_name "
                "ON kassen_kategorien (COALESCE(kasse_id, 0), lower(name)) WHERE deleted_at IS NULL"
            )
            cur.execute("UPDATE schema_version SET version = 38 WHERE id = 1")

    def _migrate_v38_to_v39(self) -> None:
        """Robuster Text→Datum-Cast `safe_to_date(text)` für die Statistik-Queries.

        Die Datumsfelder (geburtsdatum/eintrittsdatum/austrittsdatum) sind als TEXT
        gespeichert. Die bisherigen Aggregat-Queries schützten den ::date-Cast nur per
        Regex `^\\d{4}-\\d{2}-\\d{2}$`, der zwar das Format, aber nicht die kalendarische
        Gültigkeit prüft: format-gültige Unmöglichkeiten wie '2026-02-30' passierten den
        Guard und ließen den Cast – und damit die Query (HTTP 500) – fehlschlagen.
        Die Funktion fängt das ab und liefert in solchen Fällen NULL.
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE OR REPLACE FUNCTION safe_to_date(txt text) RETURNS date
                LANGUAGE plpgsql STABLE STRICT AS $$
                BEGIN
                    RETURN txt::date;
                EXCEPTION WHEN others THEN
                    RETURN NULL;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 39 WHERE id = 1")

    def _migrate_v39_to_v40(self) -> None:
        """Zugriffsprotokoll `access_log` – append-only Log für Anmelde- und
        Seitenaufruf-Ereignisse.

        Erfasst erfolgreiche/fehlgeschlagene Logins, Magic-Link-Vorgänge, Logout
        (category 'auth', dauerhaft) sowie Seitenaufrufe (category 'page', wird nach
        90 Tagen geprunt). Bewusst KEIN *_history/Soft-Delete/Audit-Trigger – das Log
        IST der Audit-Datensatz. Bei fehlgeschlagenem Login mit unbekanntem Benutzer
        wird der eingegebene Name als Text gespeichert (user_id NULL); Passwörter nie.
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_log (
                  id          BIGSERIAL PRIMARY KEY,
                  event_type  TEXT NOT NULL,
                  category    TEXT NOT NULL DEFAULT 'auth',
                  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                  username    TEXT,
                  ip          TEXT,
                  user_agent  TEXT,
                  detail      TEXT,
                  created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_access_log_created  ON access_log(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_access_log_event    ON access_log(event_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_access_log_user     ON access_log(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_access_log_category ON access_log(category, created_at)")
            cur.execute("UPDATE schema_version SET version = 40 WHERE id = 1")

    def _migrate_v40_to_v41(self) -> None:
        """Flexible Beitrags-Ausnahmen: `ausnahme_abteilung_ids INTEGER[]`.

        Bisher trug eine Regel EINE Ausnahme-Funktionsliste (`ausnahme_funktionen`)
        mit EINEM gemeinsamen Abteilungs-Bezug (`ausnahme_funktion_abteilung_id`).
        Das reichte für „Schiedsrichter nur Fußball", aber nicht für mehrere
        unterschiedlich begrenzte Ausnahmen (z.B. zusätzlich „Ehrenmitglied
        vereinsweit"). Neu: ein zu `ausnahme_funktionen` **index-gleiches** Array
        `ausnahme_abteilung_ids` – Eintrag i gilt für (Funktion i, Abteilung i),
        wobei NULL = vereinsweit. So sind beliebig viele, je eigen begrenzte
        Ausnahmen pro Regel möglich.

        Die alte Skalar-Spalte `ausnahme_funktion_abteilung_id` bleibt (vestigial,
        wie schon `ausnahme_funktion`/`bedingung_funktion` seit der Array-Umstellung)
        für Historie/Rollback erhalten; die App liest/schreibt sie nicht mehr.
        """
        with self.cursor() as cur:
            for tbl in ("beitragsregel", "beitragsregel_history"):
                cur.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS ausnahme_abteilung_ids INTEGER[]"
                )
            # Backfill: pro vorhandener Ausnahme-Funktion den alten gemeinsamen
            # Abteilungs-Bezug übernehmen → semantisch identisch zur bisherigen Regel.
            for tbl in ("beitragsregel", "beitragsregel_history"):
                cur.execute(
                    f"""
                    UPDATE {tbl}
                    SET ausnahme_abteilung_ids = CASE
                        WHEN ausnahme_funktionen IS NULL
                          OR cardinality(ausnahme_funktionen) = 0 THEN NULL
                        ELSE array_fill(ausnahme_funktion_abteilung_id,
                                        ARRAY[cardinality(ausnahme_funktionen)])
                    END
                    WHERE ausnahme_abteilung_ids IS NULL
                    """
                )
            # Audit-Trigger neu definieren, damit die neue Spalte mit in die Historie wandert.
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktionen, bedingung_funktion_abteilung_id,
                        ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktionen, bedingung_funktion_abteilung_id,
                            ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                            NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 41 WHERE id = 1")

    def _migrate_v41_to_v42(self) -> None:
        """Flexible Beitrags-Einschlüsse: `bedingung_abteilung_ids INTEGER[]`.

        Symmetrisch zu den flexiblen Ausnahmen (v41): bisher trug eine Regel EINE
        Einschluss-Funktionsliste (`bedingung_funktionen`) mit EINEM gemeinsamen
        Abteilungs-Bezug (`bedingung_funktion_abteilung_id`). Neu: ein zu
        `bedingung_funktionen` **index-gleiches** Array `bedingung_abteilung_ids`
        (NULL = vereinsweit). Eintrag i schließt (Funktion i, Abteilung i) ein;
        eingeschlossen wird, wer MINDESTENS einen Eintrag erfüllt (ODER). So sind
        z.B. „Trainer in Fußball" UND „Übungsleiter in Handball" in einer Regel
        möglich.

        Die alte Skalar-Spalte `bedingung_funktion_abteilung_id` bleibt (vestigial)
        für Historie/Rollback erhalten; die App liest/schreibt sie nicht mehr.
        """
        with self.cursor() as cur:
            for tbl in ("beitragsregel", "beitragsregel_history"):
                cur.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS bedingung_abteilung_ids INTEGER[]"
                )
            # Backfill: pro vorhandener Einschluss-Funktion den alten gemeinsamen
            # Abteilungs-Bezug übernehmen → semantisch identisch zur bisherigen Regel.
            for tbl in ("beitragsregel", "beitragsregel_history"):
                cur.execute(
                    f"""
                    UPDATE {tbl}
                    SET bedingung_abteilung_ids = CASE
                        WHEN bedingung_funktionen IS NULL
                          OR cardinality(bedingung_funktionen) = 0 THEN NULL
                        ELSE array_fill(bedingung_funktion_abteilung_id,
                                        ARRAY[cardinality(bedingung_funktionen)])
                    END
                    WHERE bedingung_abteilung_ids IS NULL
                    """
                )
            # Audit-Trigger neu definieren, damit die neue Spalte mit in die Historie wandert.
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktionen, bedingung_funktion_abteilung_id, bedingung_abteilung_ids,
                        ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id, NEW.bedingung_abteilung_ids,
                        NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktionen, bedingung_funktion_abteilung_id, bedingung_abteilung_ids,
                            ausnahme_funktionen, ausnahme_funktion_abteilung_id, ausnahme_abteilung_ids,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id, NEW.bedingung_abteilung_ids,
                            NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id, NEW.ausnahme_abteilung_ids,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 42 WHERE id = 1")

    def _migrate_v42_to_v43(self) -> None:
        """Zählprotokoll (Kassenzählung / Stückelung) – TODO „Kassenbuch".

        Neue Tabelle `kassen_zaehlungen` hält je Zählung die gezählte Stückelung
        (JSONB: Cent-Wert → Anzahl) sowie den Soll-/Ist-Abgleich. `soll_cent` wird
        beim Zählen eingefroren. Jede Zählung erzeugt eine „Zähl-Buchung"
        (`buchung_id`), an der das Protokoll-PDF hängt und über die Uhrzeit/Ersteller
        dokumentiert sind; eine evtl. auslösende Buchung (Kategorie-Trigger) wird in
        `ausloesende_buchung_id` referenziert.

        Außerdem Flag `loest_zaehlung_aus` auf `kassen_kategorien`: Buchungen mit so
        markierter Kategorie fordern eine Kassenzählung an. Die Kategorie-Audit-
        Funktionen werden um die neue Spalte ergänzt.

        Soft-Delete-only; History via Trigger.
        """
        with self.cursor() as cur:
            # --- Kategorie-Flag (+ History-Spalte + Audit-Funktionen) ---
            cur.execute(
                "ALTER TABLE kassen_kategorien "
                "ADD COLUMN IF NOT EXISTS loest_zaehlung_aus BOOLEAN NOT NULL DEFAULT false"
            )
            cur.execute(
                "ALTER TABLE kassen_kategorien_history "
                "ADD COLUMN IF NOT EXISTS loest_zaehlung_aus BOOLEAN"
            )
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO kassen_kategorien_history (
                        id, version, kasse_id, name, loest_zaehlung_aus,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.name, NEW.loest_zaehlung_aus,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO kassen_kategorien_history (
                            id, version, kasse_id, name, loest_zaehlung_aus,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.kasse_id, NEW.name, NEW.loest_zaehlung_aus,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            # --- Zählungen ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen_zaehlungen (
                  id                     SERIAL PRIMARY KEY,
                  kasse_id               INTEGER NOT NULL REFERENCES kassen(id),
                  buchung_id             INTEGER REFERENCES kassenbuchungen(id),
                  ausloesende_buchung_id INTEGER REFERENCES kassenbuchungen(id),
                  stueckelung            JSONB NOT NULL DEFAULT '{}',
                  ist_cent               INTEGER NOT NULL,
                  soll_cent              INTEGER NOT NULL,
                  differenz_cent         INTEGER NOT NULL,
                  notiz                  TEXT,
                  version                INTEGER NOT NULL DEFAULT 1,
                  created_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by             TEXT NOT NULL,
                  updated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_by             TEXT NOT NULL,
                  deleted_at             TEXT,
                  deleted_by             TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen_zaehlungen_history (
                  id                     INTEGER NOT NULL,
                  version                INTEGER NOT NULL,
                  kasse_id               INTEGER,
                  buchung_id             INTEGER,
                  ausloesende_buchung_id INTEGER,
                  stueckelung            JSONB,
                  ist_cent               INTEGER,
                  soll_cent              INTEGER,
                  differenz_cent         INTEGER,
                  notiz                  TEXT,
                  created_at             TEXT,
                  created_by             TEXT,
                  updated_at             TEXT,
                  updated_by             TEXT,
                  deleted_at             TEXT,
                  deleted_by             TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_zaehlungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO kassen_zaehlungen_history (
                        id, version, kasse_id, buchung_id, ausloesende_buchung_id,
                        stueckelung, ist_cent, soll_cent, differenz_cent, notiz,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchung_id, NEW.ausloesende_buchung_id,
                        NEW.stueckelung, NEW.ist_cent, NEW.soll_cent, NEW.differenz_cent, NEW.notiz,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_kassen_zaehlungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO kassen_zaehlungen_history (
                            id, version, kasse_id, buchung_id, ausloesende_buchung_id,
                            stueckelung, ist_cent, soll_cent, differenz_cent, notiz,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.kasse_id, NEW.buchung_id, NEW.ausloesende_buchung_id,
                            NEW.stueckelung, NEW.ist_cent, NEW.soll_cent, NEW.differenz_cent, NEW.notiz,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_kassen_zaehlungen_audit_insert
                AFTER INSERT ON kassen_zaehlungen
                FOR EACH ROW EXECUTE FUNCTION fn_kassen_zaehlungen_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_kassen_zaehlungen_audit_update
                AFTER UPDATE ON kassen_zaehlungen
                FOR EACH ROW EXECUTE FUNCTION fn_kassen_zaehlungen_audit_update();
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_zaehlungen_kasse_id ON kassen_zaehlungen(kasse_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_zaehlungen_deleted_at ON kassen_zaehlungen(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_zaehlungen_buchung_id ON kassen_zaehlungen(buchung_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_zaehlungen_history_id ON kassen_zaehlungen_history(id)")
            cur.execute("UPDATE schema_version SET version = 43 WHERE id = 1")

    def _migrate_v43_to_v44(self) -> None:
        """Audit/History für ticket_teilnehmer (TODO „nicht versionierte Tabellen").

        ticket_teilnehmer war ein reines Join-Table mit Hard-Delete. Umstellung auf das
        Standard-Muster (analog ticket_bereich_berechtigungen): Surrogat-`id` + `version`
        + Soft-Delete + Audit-Trigger. Aktive Teilnahme bleibt eindeutig über einen
        partiellen Unique-Index; nach Soft-Delete ist erneutes Hinzufügen möglich.

        Bestehende Zeilen werden mit created_*/updated_* befüllt (created_by = Username
        zu hinzugefuegt_von) und als v1 in die History übernommen.
        """
        with self.cursor() as cur:
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS id SERIAL")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS created_at TEXT")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS created_by TEXT")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS updated_at TEXT")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS updated_by TEXT")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS deleted_at TEXT")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD COLUMN IF NOT EXISTS deleted_by TEXT")
            # Audit-Felder aus den vorhandenen Hinzufügungs-Daten backfillen.
            cur.execute("""
                UPDATE ticket_teilnehmer t
                SET created_at = COALESCE(t.created_at, t.hinzugefuegt_am),
                    updated_at = COALESCE(t.updated_at, t.hinzugefuegt_am),
                    created_by = COALESCE(t.created_by,
                                          (SELECT u.username FROM users u WHERE u.id = t.hinzugefuegt_von),
                                          'SYSTEM'),
                    updated_by = COALESCE(t.updated_by,
                                          (SELECT u.username FROM users u WHERE u.id = t.hinzugefuegt_von),
                                          'SYSTEM')
            """)
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN created_at SET NOT NULL")
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN updated_at SET NOT NULL")
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN created_by SET NOT NULL")
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN updated_by SET NOT NULL")
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP")
            cur.execute("ALTER TABLE ticket_teilnehmer ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP")
            # PK von (ticket_id, user_id) auf die Surrogat-id umstellen.
            cur.execute("ALTER TABLE ticket_teilnehmer DROP CONSTRAINT IF EXISTS ticket_teilnehmer_pkey")
            cur.execute("ALTER TABLE ticket_teilnehmer ADD PRIMARY KEY (id)")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_ticket_teilnehmer_active
                ON ticket_teilnehmer (ticket_id, user_id) WHERE deleted_at IS NULL
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_teilnehmer_history (
                  id               INTEGER NOT NULL,
                  version          INTEGER NOT NULL,
                  ticket_id        INTEGER,
                  user_id          INTEGER,
                  hinzugefuegt_von INTEGER,
                  hinzugefuegt_am  TEXT,
                  created_at       TEXT,
                  created_by       TEXT,
                  updated_at       TEXT,
                  updated_by       TEXT,
                  deleted_at       TEXT,
                  deleted_by       TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_ticket_teilnehmer_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO ticket_teilnehmer_history (
                        id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.user_id, NEW.hinzugefuegt_von, NEW.hinzugefuegt_am,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_ticket_teilnehmer_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO ticket_teilnehmer_history (
                            id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.ticket_id, NEW.user_id, NEW.hinzugefuegt_von, NEW.hinzugefuegt_am,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_ticket_teilnehmer_audit_insert
                AFTER INSERT ON ticket_teilnehmer
                FOR EACH ROW EXECUTE FUNCTION fn_ticket_teilnehmer_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_ticket_teilnehmer_audit_update
                AFTER UPDATE ON ticket_teilnehmer
                FOR EACH ROW EXECUTE FUNCTION fn_ticket_teilnehmer_audit_update();
            """)
            # Bestehende Zeilen als v1 in die History übernehmen (Trigger feuern nur auf neue Writes).
            cur.execute("""
                INSERT INTO ticket_teilnehmer_history (
                    id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                )
                SELECT id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                FROM ticket_teilnehmer
                ON CONFLICT (id, version) DO NOTHING
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_teilnehmer_deleted_at ON ticket_teilnehmer(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_teilnehmer_history_id ON ticket_teilnehmer_history(id)")
            cur.execute("UPDATE schema_version SET version = 44 WHERE id = 1")

    def _migrate_v44_to_v45(self) -> None:
        """Altersbedingung für Aufnahmegebühren (Ticket #42).

        Gebühren erhalten – analog zu beitragsregel – `bedingung_alter_min`/`max`
        (Alter in Jahren am Stichtag). Damit kann bei Neuanlage/Neuzuordnung anhand
        des Geburtsdatums die altersrichtige Aufnahmegebühr vorgeschlagen werden.

        Bestehender Katalog kodiert Erwachsene/Kinder nur im Namen → Best-Effort-
        Backfill: „Kinder"/„Jugend" → bis 17 Jahre, „Erwachsene" → ab 18 Jahre.
        Der Backfill läuft ohne Versions-Bump (kein History-Eintrag).
        """
        with self.cursor() as cur:
            for tbl in ('gebuehr', 'gebuehr_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS bedingung_alter_min INTEGER")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS bedingung_alter_max INTEGER")
            # Audit-Trigger neu anlegen, damit die neuen Spalten mitgeschrieben werden.
            # Spaltensatz wie seit v30 (ohne zahler_kasse_id) + die neuen Felder.
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO gebuehr_history (
                        id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                        zahler_typ, bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                        NEW.zahler_typ, NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO gebuehr_history (
                            id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                            zahler_typ, bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                            NEW.zahler_typ, NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            # Best-Effort-Backfill aus dem Namen – ohne Versions-Bump (kein History-Rauschen).
            cur.execute("""
                UPDATE gebuehr SET bedingung_alter_max = 17
                WHERE bedingung_alter_max IS NULL AND bedingung_alter_min IS NULL
                  AND (name ILIKE '%kinder%' OR name ILIKE '%jugend%')
            """)
            cur.execute("""
                UPDATE gebuehr SET bedingung_alter_min = 18
                WHERE bedingung_alter_max IS NULL AND bedingung_alter_min IS NULL
                  AND name ILIKE '%erwachsene%'
            """)
            cur.execute("UPDATE schema_version SET version = 45 WHERE id = 1")

    def _migrate_v45_to_v46(self) -> None:
        """Fibu-Delta-Export der Sollstellungen (Format hmd FBASC).

        - Export-Lauf-Header `fibu_exporte` (+ History, Insert-Audit) analog kassenbuch_exporte.
        - Export-Markierungen an beitrag_sollstellung UND gebuehr_forderung:
          `exportiert_in_export_id` (Forderung exportiert) + `storno_exportiert_in_export_id`
          (Gegenbuchung exportiert) → voll rekonstruierbarer Re-Download je Lauf.
        - Konten-Stammdaten: `gegenkonto`/`steuerschluessel` an beitragsregel + gebuehr,
          zusätzlich `kostenstelle`/`kostentraeger` an gebuehr, `kostenstelle` an abteilung.
        - Globale Konfiguration `fibu_einstellungen` (Single-Row): Debitor-Konto-Basis,
          Default-Gegenkonto/-Steuerschlüssel, Verein-Kostenstelle (12), Kostenträger (1).
        Audit-Trigger-Funktionen werden um die neuen Spalten ergänzt.
        """
        with self.cursor() as cur:
            # --- Export-Lauf-Header -------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fibu_exporte (
                  id                  SERIAL PRIMARY KEY,
                  exportiert_am       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  exportiert_von      TEXT NOT NULL,
                  dateiname           TEXT NOT NULL,
                  format              TEXT NOT NULL DEFAULT 'fbasc',
                  anzahl_positionen   INTEGER NOT NULL DEFAULT 0,
                  summe_cent          INTEGER NOT NULL DEFAULT 0,
                  storno_von_export_id INTEGER REFERENCES fibu_exporte(id),
                  version             INTEGER NOT NULL DEFAULT 1,
                  created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by          TEXT NOT NULL,
                  deleted_at          TEXT,
                  deleted_by          TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fibu_exporte_history (
                  id                  INTEGER NOT NULL,
                  version             INTEGER NOT NULL,
                  exportiert_am       TEXT,
                  exportiert_von      TEXT,
                  dateiname           TEXT,
                  format              TEXT,
                  anzahl_positionen   INTEGER,
                  summe_cent          INTEGER,
                  storno_von_export_id INTEGER,
                  created_at          TEXT,
                  created_by          TEXT,
                  deleted_at          TEXT,
                  deleted_by          TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            # Idempotent für bereits angelegte v46-Tabellen (Storno-Verknüpfung des Gegenbuchungs-Laufs).
            cur.execute("ALTER TABLE fibu_exporte ADD COLUMN IF NOT EXISTS storno_von_export_id INTEGER REFERENCES fibu_exporte(id)")
            cur.execute("ALTER TABLE fibu_exporte_history ADD COLUMN IF NOT EXISTS storno_von_export_id INTEGER")
            cur.execute(_FN_FIBU_EXPORTE_AUDIT_INSERT)
            cur.execute(_FN_FIBU_EXPORTE_AUDIT_UPDATE)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_fibu_exporte_audit_insert
                AFTER INSERT ON fibu_exporte
                FOR EACH ROW EXECUTE FUNCTION fn_fibu_exporte_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_fibu_exporte_audit_update
                AFTER UPDATE ON fibu_exporte
                FOR EACH ROW EXECUTE FUNCTION fn_fibu_exporte_audit_update();
            """)

            # --- Globale Konfiguration (Single-Row) --------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fibu_einstellungen (
                  id                       INTEGER PRIMARY KEY DEFAULT 1,
                  debitor_konto_basis      INTEGER,
                  default_gegenkonto       TEXT,
                  default_steuerschluessel TEXT,
                  verein_kostenstelle      INTEGER NOT NULL DEFAULT 12,
                  default_kostentraeger    INTEGER NOT NULL DEFAULT 1,
                  version                  INTEGER NOT NULL DEFAULT 1,
                  created_at               TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by               TEXT,
                  updated_at               TEXT,
                  updated_by               TEXT,
                  CHECK (id = 1)
                )
            """)
            cur.execute("INSERT INTO fibu_einstellungen (id, debitor_konto_basis) VALUES (1, 200000) ON CONFLICT (id) DO NOTHING")

            # --- Konten-Spalten an den Stammdaten ----------------------------------
            for tbl in ('abteilung', 'abteilung_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS kostenstelle INTEGER")
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS gegenkonto TEXT")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS steuerschluessel TEXT")
            for tbl in ('gebuehr', 'gebuehr_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS gegenkonto TEXT")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS steuerschluessel TEXT")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS kostenstelle INTEGER")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS kostentraeger INTEGER")

            # --- Export-Markierungen an den Sollstellungen -------------------------
            for tbl in ('beitrag_sollstellung', 'gebuehr_forderung'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS exportiert_in_export_id INTEGER REFERENCES fibu_exporte(id)")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS storno_exportiert_in_export_id INTEGER REFERENCES fibu_exporte(id)")
                cur.execute(f"ALTER TABLE {tbl}_history ADD COLUMN IF NOT EXISTS exportiert_in_export_id INTEGER")
                cur.execute(f"ALTER TABLE {tbl}_history ADD COLUMN IF NOT EXISTS storno_exportiert_in_export_id INTEGER")

            # --- Audit-Trigger-Funktionen mit den neuen Spalten --------------------
            cur.execute(_FN_ABTEILUNG_AUDIT_INSERT)
            cur.execute(_FN_ABTEILUNG_AUDIT_UPDATE)
            cur.execute(_FN_BEITRAGSREGEL_AUDIT_INSERT)
            cur.execute(_FN_BEITRAGSREGEL_AUDIT_UPDATE)
            cur.execute(_FN_GEBUEHR_AUDIT_INSERT)
            cur.execute(_FN_GEBUEHR_AUDIT_UPDATE)
            cur.execute(_FN_BEITRAG_SOLLSTELLUNG_AUDIT_INSERT)
            cur.execute(_FN_BEITRAG_SOLLSTELLUNG_AUDIT_UPDATE)
            cur.execute(_FN_GEBUEHR_FORDERUNG_AUDIT_INSERT)
            cur.execute(_FN_GEBUEHR_FORDERUNG_AUDIT_UPDATE)

            # --- Indizes -----------------------------------------------------------
            for name, target in [
                ("idx_beitrag_sollstellung_export_id",        "beitrag_sollstellung(exportiert_in_export_id)"),
                ("idx_beitrag_sollstellung_storno_export_id", "beitrag_sollstellung(storno_exportiert_in_export_id)"),
                ("idx_gebuehr_forderung_export_id",           "gebuehr_forderung(exportiert_in_export_id)"),
                ("idx_gebuehr_forderung_storno_export_id",    "gebuehr_forderung(storno_exportiert_in_export_id)"),
                ("idx_fibu_exporte_storno_von_export_id",     "fibu_exporte(storno_von_export_id)"),
                ("idx_fibu_exporte_history_id",               "fibu_exporte_history(id)"),
            ]:
                cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")

            cur.execute("UPDATE schema_version SET version = 46 WHERE id = 1")

    def _migrate_v46_to_v47(self) -> None:
        """Magic-Link-Härtung (Ticket #48): Auth-Tokens nur noch als Hash speichern.

        Bisher lag der Token im Klartext in `auth_tokens.token` (und via Audit-Trigger
        gespiegelt in `auth_tokens_history`) – bei einem DB-Leak sofort missbrauchbar.
        Ab v47:
        - Spalte `token` → `token_hash` (in beiden Tabellen), Inhalt ist der
          SHA-256-Hex-Hash des Tokens.
        - Vorhandene Klartext-Tokens werden in-place gehasht, damit bereits
          verschickte Magic-Links bis zum Ablauf gültig bleiben.
        - Audit-Trigger-Funktionen + Index auf die neue Spalte umgestellt.

        Atomares Single-Use (UPDATE … RETURNING) und das Rate-Limiting sitzen im
        Repository bzw. im Auth-Endpoint und brauchen keine Schema-Änderung.
        """
        import hashlib

        def _sha256(value: str) -> str:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        with self.cursor() as cur:
            # 1) Spalte token → token_hash (idempotent: nur wenn 'token' noch existiert).
            #    Tabellennamen stammen aus dieser festen Liste, daher f-String unkritisch.
            for table in ("auth_tokens", "auth_tokens_history"):
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = %s AND column_name = 'token'
                    """,
                    (table,),
                )
                if cur.fetchone():
                    cur.execute(f"ALTER TABLE {table} RENAME COLUMN token TO token_hash")

            # 2) Audit-Trigger-Funktionen auf token_hash umstellen (vor dem Daten-Update,
            #    damit ein evtl. feuernder Trigger nicht die alte Spalte referenziert).
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO auth_tokens_history (
                        id, version, user_id, token_hash, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token_hash, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO auth_tokens_history (
                            id, version, user_id, token_hash, token_type, expires_at, used_at, created_at
                        ) VALUES (
                            NEW.id, NEW.version, NEW.user_id, NEW.token_hash, NEW.token_type,
                            NEW.expires_at, NEW.used_at, NEW.created_at
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            # 3) Bestehende Klartext-Werte hashen. Hash ist 64 Hex-Zeichen lang,
            #    token_urlsafe(32) nie → length(...) <> 64 erkennt noch ungehashte Zeilen
            #    und macht den Schritt re-run-sicher.
            cur.execute("SELECT id, token_hash FROM auth_tokens WHERE length(token_hash) <> 64")
            for row in cur.fetchall():
                cur.execute(
                    "UPDATE auth_tokens SET token_hash = %s WHERE id = %s",
                    (_sha256(row["token_hash"]), row["id"]),
                )
            cur.execute(
                "SELECT id, version, token_hash FROM auth_tokens_history WHERE length(token_hash) <> 64"
            )
            for row in cur.fetchall():
                cur.execute(
                    "UPDATE auth_tokens_history SET token_hash = %s WHERE id = %s AND version = %s",
                    (_sha256(row["token_hash"]), row["id"], row["version"]),
                )

            # 4) Indizes auf die neue Spalte ausrichten (Namensgleichheit mit Fresh-Schema).
            cur.execute("ALTER INDEX IF EXISTS idx_auth_tokens_token RENAME TO idx_auth_tokens_token_hash")
            cur.execute("ALTER INDEX IF EXISTS auth_tokens_token_key RENAME TO auth_tokens_token_hash_key")

            cur.execute("UPDATE schema_version SET version = 47 WHERE id = 1")

    def _migrate_v47_to_v48(self) -> None:
        """Prune-Konfiguration (Branch feature/prune): pro Entität einstellbare Tunables.

        Legt die Override-Tabelle `prune_einstellungen` an. Sie speichert NUR vom Admin
        gesetzte Abweichungen (Tage / Mindestanzahl / History-Tage) je Entität – nicht
        gesetzte Entitäten nutzen weiterhin die Code-Defaults aus dem PruneService. Damit
        bleibt die Entitäts-/Struktur-Registry alleinige Quelle der Wahrheit; die DB hält
        nur die Stellschrauben. Reines Config-Tabelle ⇒ kein Soft-Delete, keine History.
        """
        with self.cursor() as cur:
            self._create_prune_einstellungen(cur)
            cur.execute("UPDATE schema_version SET version = 48 WHERE id = 1")

    @staticmethod
    def _create_prune_einstellungen(cur) -> None:
        """CREATE der Prune-Override-Tabelle (idempotent, von Fresh-Schema + Migration genutzt)."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prune_einstellungen (
              entity                 TEXT PRIMARY KEY,
              retention_days         INTEGER NOT NULL,
              keep_min               INTEGER NOT NULL,
              history_retention_days INTEGER NOT NULL,
              updated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by             TEXT
            )
        """)

    def _migrate_v48_to_v49(self) -> None:
        """Prune Phase 1: fehlende deleted_at-Indizes für die Kandidaten-Scans (Performance)."""
        with self.cursor() as cur:
            self._create_prune_indexes(cur)
            cur.execute("UPDATE schema_version SET version = 49 WHERE id = 1")

    @staticmethod
    def _create_prune_indexes(cur) -> None:
        """deleted_at-Indizes für Prune-Bereiche, die noch keinen haben (idempotent)."""
        for table in ("mitglied", "mitglied_abteilung", "mitglied_funktion"):
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_deleted_at ON {table}(deleted_at)"
            )

    def _migrate_v49_to_v50(self) -> None:
        """Beitragsabrechnung: einstellbare Quartals-Rückschau (Aufhol-Abrechnung).

        Legt die globale Single-Row-Konfig `beitrag_einstellungen` an. `quartale_rueckschau`
        steuert, wie viele Quartale VOR dem aktuellen eine Abrechnung mitnimmt (Default 1 =
        Vorquartal als Sicherheitsnetz). Die harte Untergrenze 2026-04-01 lebt als Code-
        Konstante im BeitragsService und ist hier bewusst nicht abgebildet.
        """
        with self.cursor() as cur:
            self._create_beitrag_einstellungen(cur)
            cur.execute("UPDATE schema_version SET version = 50 WHERE id = 1")

    @staticmethod
    def _create_beitrag_einstellungen(cur) -> None:
        """CREATE der Beitrags-Konfig (Single-Row, idempotent; Fresh-Schema + Migration)."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitrag_einstellungen (
              id                  INTEGER PRIMARY KEY DEFAULT 1,
              quartale_rueckschau INTEGER NOT NULL DEFAULT 1,
              version             INTEGER NOT NULL DEFAULT 1,
              created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by          TEXT,
              updated_at          TEXT,
              updated_by          TEXT,
              CHECK (id = 1),
              CHECK (quartale_rueckschau >= 0)
            )
        """)
        cur.execute(
            "INSERT INTO beitrag_einstellungen (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

    def _migrate_v50_to_v51(self) -> None:
        """Zeitstempel-Stringenz: Audit-/Aktivitäts-Instants tabellenweit auf TIMESTAMPTZ.

        Bisher lagen created_at/updated_at/deleted_at (sowie exportiert_am, hochgeladen_am,
        hinzugefuegt_am, last_login, last_seen) je nach Tabelle als TEXT (timestamptz::text
        mit '+00') oder als naives TIMESTAMP vor. Dadurch trug der serialisierte Wert mal
        einen Offset, mal nicht – im Frontend führte das zu UTC-/GMT-Anzeige. Die Konvertierung
        auf TIMESTAMPTZ liefert über psycopg überall ein aware datetime mit Offset.

        Bewusst NICHT angefasst: reine Datumsfelder sowie die Auth-Token-/Session-Spalten
        (expires_at, used_at, revoked_at, last_seen_at), die im SQL bereits per
        ::timestamptz-Cast arbeiten und nicht angezeigt werden.
        """
        with self.cursor() as cur:
            self._normalize_audit_timestamps(cur)
            cur.execute("UPDATE schema_version SET version = 51 WHERE id = 1")

    def _migrate_v51_to_v52(self) -> None:
        """Fibu-Export-Storno-Spalte `fibu_exporte.storno_von_export_id` nachziehen.

        Die Spalte (Gegenbuchungs-Lauf → Original) wurde nachträglich in die v46-Migration
        aufgenommen. Datenbanken, die v46 schon vor dieser Ergänzung durchlaufen hatten,
        besitzen sie nicht – das Repository (SELECT … storno_von_export_id …) lief daher
        auf »UndefinedColumn«. Frisch erstellte Schemas haben die Spalte bereits, hier wird
        sie idempotent für Bestands-DBs nachgezogen: Spalte (Tabelle + History), Index und
        die beiden Audit-Trigger-Funktionen, die die Spalte mitschreiben.
        """
        with self.cursor() as cur:
            cur.execute("ALTER TABLE fibu_exporte ADD COLUMN IF NOT EXISTS "
                        "storno_von_export_id INTEGER REFERENCES fibu_exporte(id)")
            cur.execute("ALTER TABLE fibu_exporte_history ADD COLUMN IF NOT EXISTS "
                        "storno_von_export_id INTEGER")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fibu_exporte_storno_von_export_id "
                        "ON fibu_exporte(storno_von_export_id)")
            cur.execute(_FN_FIBU_EXPORTE_AUDIT_INSERT)
            cur.execute(_FN_FIBU_EXPORTE_AUDIT_UPDATE)
            cur.execute("UPDATE schema_version SET version = 52 WHERE id = 1")

    def _migrate_v52_to_v53(self) -> None:
        """Übungsleiter-Stundenerfassung: ul_abrechnung/ul_stunde/ul_satz (+History,
        Audit-Trigger, Indizes) sowie Standard-Berechtigungen je Funktion.

        Idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ON CONFLICT). Fresh-Schema und
        Migration teilen sich DDL/Trigger/Index-Definitionen (Modul-Konstanten), damit
        beide Pfade garantiert identische Schemata erzeugen.
        """
        with self.cursor() as cur:
            cur.execute(_DDL_UL_TABLES)
            # Audit-Trigger-Funktionen + Trigger
            for fn_sql in (
                _FN_UL_ABRECHNUNG_AUDIT_INSERT, _FN_UL_ABRECHNUNG_AUDIT_UPDATE,
                _FN_UL_STUNDE_AUDIT_INSERT, _FN_UL_STUNDE_AUDIT_UPDATE,
                _FN_UL_SATZ_AUDIT_INSERT, _FN_UL_SATZ_AUDIT_UPDATE,
            ):
                cur.execute(fn_sql)
            for name, event, table, fn in _UL_TRIGGERS:
                cur.execute(
                    f"CREATE OR REPLACE TRIGGER {name} AFTER {event} ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {fn}();"
                )
            for name, target in _UL_INDEXES:
                cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
            # Standard-Berechtigungen an die Funktionen 'uebungsleiter'/'abteilungsleiter' hängen
            for fkey, perm in _UL_FUNKTION_PERMISSIONS:
                cur.execute(
                    """
                    INSERT INTO funktion_permission (funktion_id, permission, created_by, updated_by)
                    SELECT f.id, %s, 'SYSTEM', 'SYSTEM' FROM funktion f
                    WHERE f.key=%s AND f.deleted_at IS NULL
                    ON CONFLICT (funktion_id, permission) DO NOTHING
                    """,
                    (perm, fkey),
                )
            # eingereicht_am/bestaetigt_am als TIMESTAMPTZ (gleiche Routine wie Fresh-Schema)
            self._normalize_audit_timestamps(cur)
            cur.execute("UPDATE schema_version SET version = 53 WHERE id = 1")

    def _migrate_v53_to_v54(self) -> None:
        """Mitglied-Stammdaten für den ÜL-Stundennachweis: trainerlizenz_nr, qualifikation.

        Spalten (Tabelle + History) idempotent nachziehen und die Mitglied-Audit-Trigger
        auf die neuen Spalten erweitern (geteilte Modul-Konstanten, identisch zum Fresh-Schema).
        """
        with self.cursor() as cur:
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS trainerlizenz_nr TEXT")
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS qualifikation TEXT")
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS trainerlizenz_nr TEXT")
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS qualifikation TEXT")
            cur.execute(_FN_MITGLIED_AUDIT_INSERT)
            cur.execute(_FN_MITGLIED_AUDIT_UPDATE)
            cur.execute("UPDATE schema_version SET version = 54 WHERE id = 1")

    def _migrate_v54_to_v55(self) -> None:
        """ÜL-Lizenz mit Gültigkeitsdatum: mitglied.trainerlizenz_gueltig_bis.

        Aus diesem Datum wird beim Anlegen einer Abrechnung die Lizenz-Klassifikation
        (mit/ohne Lizenz) abgeleitet, statt sie im Dialog abzufragen. Spalte (Tabelle +
        History) idempotent nachziehen und die Mitglied-Audit-Trigger auf die neue
        Spalte erweitern (geteilte Modul-Konstanten, identisch zum Fresh-Schema)."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS trainerlizenz_gueltig_bis TEXT")
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS trainerlizenz_gueltig_bis TEXT")
            cur.execute(_FN_MITGLIED_AUDIT_INSERT)
            cur.execute(_FN_MITGLIED_AUDIT_UPDATE)
            cur.execute("UPDATE schema_version SET version = 55 WHERE id = 1")

    def _migrate_v55_to_v56(self) -> None:
        """ÜL-Honorar im Fibu-Export (Kreditor je ÜL): Konten an fibu_einstellungen.

        Zwei einstellbare Konten zur globalen Fibu-Konfiguration nachziehen:
        `ul_aufwand_konto` (Soll-Sachkonto ÜL-Honorar = Gegenkonto) und
        `ul_kreditor_konto_basis` (Kreditor-Konto = Basis + Mitgliedsnummer). Die
        Kostenstelle stammt aus der Abteilung – dafür ist keine neue Spalte nötig.
        fibu_einstellungen ist eine Single-Row-Konfig ohne History/Trigger; die Spalten
        idempotent nachziehen (identisch zum Fresh-Schema)."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE fibu_einstellungen ADD COLUMN IF NOT EXISTS ul_aufwand_konto TEXT")
            cur.execute("ALTER TABLE fibu_einstellungen ADD COLUMN IF NOT EXISTS ul_kreditor_konto_basis INTEGER")
            cur.execute("UPDATE schema_version SET version = 56 WHERE id = 1")

    def _migrate_v56_to_v57(self) -> None:
        """Zutrittskontrolle/Schließsystem (TT-Lock): ttlock_konto, tuer_schloss,
        schluessel_chip, tuer_berechtigung (+History, Audit-Trigger) sowie das
        append-only tuer_zutritt_log; plus die drei schliessanlage.*-Permissions an
        bestehende Admin-User.

        Idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ON CONFLICT). Fresh-Schema und
        Migration teilen DDL/Trigger/Index-Konstanten (Modul-Konstanten), damit beide
        Pfade identische Schemata erzeugen.
        """
        with self.cursor() as cur:
            cur.execute(_DDL_ZUTRITT_TABLES)
            for fn_sql in (
                _FN_TUER_SCHLOSS_AUDIT_INSERT, _FN_TUER_SCHLOSS_AUDIT_UPDATE,
                _FN_SCHLUESSEL_CHIP_AUDIT_INSERT, _FN_SCHLUESSEL_CHIP_AUDIT_UPDATE,
                _FN_TUER_BERECHTIGUNG_AUDIT_INSERT, _FN_TUER_BERECHTIGUNG_AUDIT_UPDATE,
            ):
                cur.execute(fn_sql)
            for name, event, table, fn in _ZUTRITT_TRIGGERS:
                cur.execute(
                    f"CREATE OR REPLACE TRIGGER {name} AFTER {event} ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {fn}();"
                )
            for name, target in _ZUTRITT_INDEXES:
                cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
            for sql in _ZUTRITT_UNIQUE_INDEXES:
                cur.execute(sql)
            # Neue Permissions an Bestands-Admins hängen (Frisch-Schema seedet sie separat).
            for perm in _ZUTRITT_PERMISSIONS:
                cur.execute(
                    """
                    INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                    SELECT id, %s, 'SYSTEM', 'SYSTEM' FROM users
                    WHERE role='admin' AND deleted_at IS NULL
                    ON CONFLICT DO NOTHING
                    """,
                    (perm,),
                )
            self._normalize_audit_timestamps(cur)
            cur.execute("UPDATE schema_version SET version = 57 WHERE id = 1")

    def _migrate_v57_to_v58(self) -> None:
        """Kurzzeitige App-Betätigungs-Berechtigung: tuer_app_berechtigung (+History,
        Audit-Trigger, Indizes). Befristetes App-Öffnen je User+Schloss ohne Chip.

        Idempotent; geteilte DDL/Trigger/Index-Konstanten mit dem Fresh-Schema.
        """
        with self.cursor() as cur:
            cur.execute(_DDL_TUER_APP_BERECHTIGUNG)
            cur.execute(_FN_TUER_APP_BERECHTIGUNG_AUDIT_INSERT)
            cur.execute(_FN_TUER_APP_BERECHTIGUNG_AUDIT_UPDATE)
            for name, event, table, fn in _TUER_APP_BERECHTIGUNG_TRIGGERS:
                cur.execute(
                    f"CREATE OR REPLACE TRIGGER {name} AFTER {event} ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {fn}();"
                )
            for name, target in _TUER_APP_BERECHTIGUNG_INDEXES:
                cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
            # schliessanlage.oeffnen kam mit dem Fernöffnen (v58-Ära) dazu und stand bisher
            # nur im Fresh-Seed → Bestands-Admins beim Upgrade nachziehen (Fresh==Upgrade).
            cur.execute(
                """
                INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                SELECT id, 'schliessanlage.oeffnen', 'SYSTEM', 'SYSTEM' FROM users
                WHERE role='admin' AND deleted_at IS NULL
                ON CONFLICT DO NOTHING
                """
            )
            self._normalize_audit_timestamps(cur)
            cur.execute("UPDATE schema_version SET version = 58 WHERE id = 1")

    def _migrate_v58_to_v59(self) -> None:
        """Read-only Credential-Mirror je Schloss (tuer_credential): Fingerprints,
        Passcodes, App-/eKeys und IC-Karten aus der TTLock-Cloud spiegeln. Reiner Mirror
        (kein History/Audit/Soft-Delete) – macht Credential-Typen sichtbar, die NICHT über
        unsere App liefen (Fingerprints/Funk-Keys = bisheriger blinder Fleck).

        Idempotent; geteilte DDL (inkl. Indizes) mit dem Fresh-Schema.
        """
        with self.cursor() as cur:
            cur.execute(_DDL_TUER_CREDENTIAL)
            self._normalize_audit_timestamps(cur)
            cur.execute("UPDATE schema_version SET version = 59 WHERE id = 1")

    def _migrate_v59_to_v60(self) -> None:
        """ÜL-Lizenz koppeln + festschreiben (#63):
        - mitglied.trainerlizenz_gueltig_von (Lizenz-Startdatum) → mit/ohne Lizenz wird
          aus dem Fenster [gueltig_von, gueltig_bis] abgeleitet statt nur aus gueltig_bis.
        - ul_abrechnung.trainerlizenz_nr + qualifikation als Snapshot beim Einreichen,
          damit ein eingereichter/exportierter Beleg nicht rückwirkend von späteren
          Stammdatenänderungen abhängt (analog verguetung_pro_stunde).

        Spalten (Tabelle + History) idempotent nachziehen und BEIDE Audit-Trigger auf die
        neuen Spalten erweitern (geteilte Modul-Konstanten, identisch zum Fresh-Schema).
        """
        with self.cursor() as cur:
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS trainerlizenz_gueltig_von TEXT")
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS trainerlizenz_gueltig_von TEXT")
            cur.execute(_FN_MITGLIED_AUDIT_INSERT)
            cur.execute(_FN_MITGLIED_AUDIT_UPDATE)
            cur.execute("ALTER TABLE ul_abrechnung ADD COLUMN IF NOT EXISTS trainerlizenz_nr TEXT")
            cur.execute("ALTER TABLE ul_abrechnung ADD COLUMN IF NOT EXISTS qualifikation TEXT")
            cur.execute("ALTER TABLE ul_abrechnung_history ADD COLUMN IF NOT EXISTS trainerlizenz_nr TEXT")
            cur.execute("ALTER TABLE ul_abrechnung_history ADD COLUMN IF NOT EXISTS qualifikation TEXT")
            cur.execute(_FN_UL_ABRECHNUNG_AUDIT_INSERT)
            cur.execute(_FN_UL_ABRECHNUNG_AUDIT_UPDATE)
            cur.execute("UPDATE schema_version SET version = 60 WHERE id = 1")

    # Audit-/Aktivitäts-Zeitstempel, die als echte Instants (UTC) geführt werden.
    _AUDIT_TS_COLUMNS = (
        "created_at", "updated_at", "deleted_at",
        "exportiert_am", "hochgeladen_am", "hinzugefuegt_am",
        "last_login", "last_seen",
        "eingereicht_am", "bestaetigt_am",
    )

    def _normalize_audit_timestamps(self, cur) -> None:
        """Zieht alle Audit-Zeitstempel (TEXT/naives TIMESTAMP) auf TIMESTAMPTZ.

        Einzige Quelle der Wahrheit für Fresh-Schema UND Migration: beide Pfade rufen diese
        Routine, damit neue und migrierte Datenbanken garantiert identische Spaltentypen
        haben. Idempotent – bereits konvertierte (timestamptz) Spalten fallen über den
        data_type-Filter heraus.

        Werte gelten als UTC: Strings mit Offset ('…+00') tragen ihn explizit; offsetlose
        Strings und naive Timestamps werden dank fixer Session-TZ ebenfalls als UTC gelesen
        (so wurden sie via CURRENT_TIMESTAMP auch geschrieben).
        """
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        cur.execute(
            """
            SELECT table_name, column_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = ANY(%s)
              AND data_type IN ('text', 'timestamp without time zone')
            ORDER BY table_name, column_name
            """,
            (list(self._AUDIT_TS_COLUMNS),),
        )
        for r in cur.fetchall():
            tbl, col = r["table_name"], r["column_name"]
            has_default = r["column_default"] is not None
            if has_default:
                cur.execute(f'ALTER TABLE "{tbl}" ALTER COLUMN "{col}" DROP DEFAULT')
            cur.execute(
                f'ALTER TABLE "{tbl}" ALTER COLUMN "{col}" '
                f"TYPE TIMESTAMPTZ USING NULLIF({col}::text, '')::timestamptz"
            )
            if has_default:
                cur.execute(
                    f'ALTER TABLE "{tbl}" ALTER COLUMN "{col}" SET DEFAULT CURRENT_TIMESTAMP'
                )

    def _create_schema(self):
        """Erstellt das vollständige Schema auf einer frischen Datenbank.

        Hinweis: created_at/updated_at/deleted_at (u. a.) werden in den CREATE-Statements
        unten noch als TEXT deklariert und am Ende durch `_normalize_audit_timestamps`
        einheitlich auf TIMESTAMPTZ gezogen – dieselbe Routine wie in der Migration, damit
        frische und migrierte Datenbanken garantiert identische Spaltentypen haben.
        """
        with self.cursor() as cur:
            self._create_tables(cur)
            self._create_prune_einstellungen(cur)
            self._create_beitrag_einstellungen(cur)
            self._create_trigger_functions(cur)
            self._create_triggers(cur)
            self._create_indexes(cur)
            self._create_prune_indexes(cur)
            self._seed_data(cur)
            self._normalize_audit_timestamps(cur)
            cur.execute(
                "INSERT INTO schema_version (id, version) VALUES (1, %s)",
                (SCHEMA_VERSION,),
            )

    # -----------------------------------
    # Tabellen
    # -----------------------------------

    def _create_tables(self, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied (
              id                SERIAL PRIMARY KEY,
              mitgliedsnummer   INTEGER UNIQUE,
              vorname           TEXT NOT NULL,
              nachname          TEXT NOT NULL,
              geburtsdatum      TEXT,
              strasse           TEXT,
              plz               TEXT,
              ort               TEXT,
              land              TEXT,
              eintrittsdatum    TEXT,
              austrittsdatum    TEXT,
              status            TEXT NOT NULL DEFAULT 'aktiv',
              zahlungsart       TEXT NOT NULL,
              iban              TEXT,
              bic               TEXT,
              kontoinhaber      TEXT,
              abgerechnet_bis   TEXT,
              geschlecht        TEXT,
              bemerkungen       TEXT,
              sepa_mandatsref   TEXT,
              sepa_mandatsdatum TEXT,
              user_id           INTEGER,
              trainerlizenz_nr  TEXT,
              qualifikation     TEXT,
              trainerlizenz_gueltig_bis TEXT,
              trainerlizenz_gueltig_von TEXT,
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_history (
              id                INTEGER NOT NULL,
              version           INTEGER NOT NULL,
              mitgliedsnummer   INTEGER,
              vorname           TEXT,
              nachname          TEXT,
              geburtsdatum      TEXT,
              strasse           TEXT,
              plz               TEXT,
              ort               TEXT,
              land              TEXT,
              email             TEXT,
              telefon           TEXT,
              eintrittsdatum    TEXT,
              austrittsdatum    TEXT,
              status            TEXT,
              zahlungsart       TEXT,
              iban              TEXT,
              bic               TEXT,
              kontoinhaber      TEXT,
              abgerechnet_bis   TEXT,
              geschlecht        TEXT,
              bemerkungen       TEXT,
              sepa_mandatsref   TEXT,
              sepa_mandatsdatum TEXT,
              user_id           INTEGER,
              trainerlizenz_nr  TEXT,
              qualifikation     TEXT,
              trainerlizenz_gueltig_bis TEXT,
              trainerlizenz_gueltig_von TEXT,
              created_at        TEXT,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_kontakt (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              typ            TEXT NOT NULL,
              wert           TEXT NOT NULL,
              label          TEXT,
              ist_primaer    BOOLEAN NOT NULL DEFAULT FALSE,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_kontakt_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              typ            TEXT,
              wert           TEXT,
              label          TEXT,
              ist_primaer    BOOLEAN,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS abteilung (
              id            SERIAL PRIMARY KEY,
              name          TEXT NOT NULL,
              kuerzel       TEXT,
              beschreibung  TEXT,
              kostenstelle  INTEGER,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS abteilung_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              name          TEXT,
              kuerzel       TEXT,
              beschreibung  TEXT,
              kostenstelle  INTEGER,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_abteilung (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
              status         TEXT NOT NULL DEFAULT 'aktiv',
              von            TEXT,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_abteilung_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              abteilung_id   INTEGER,
              status         TEXT,
              von            TEXT,
              bis            TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_funktion (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              abteilung_id   INTEGER REFERENCES abteilung(id),
              funktion       TEXT NOT NULL,
              von            TEXT NOT NULL,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_funktion_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              abteilung_id   INTEGER,
              funktion       TEXT,
              von            TEXT,
              bis            TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitragsregel (
              id                           SERIAL PRIMARY KEY,
              name                         TEXT NOT NULL,
              abteilung_id                 INTEGER REFERENCES abteilung(id),
              betrag_pro_monat             REAL NOT NULL,
              einzug_turnus                TEXT NOT NULL,
              gueltig_ab                   TEXT NOT NULL,
              gueltig_bis                  TEXT,
              bedingung_raw                TEXT,
              bedingung_abteilung_status   TEXT,
              bedingung_funktionen         TEXT[],
              bedingung_funktion_abteilung_id INTEGER REFERENCES abteilung(id),
              bedingung_abteilung_ids      INTEGER[],
              ausnahme_funktionen          TEXT[],
              ausnahme_funktion_abteilung_id INTEGER REFERENCES abteilung(id),
              ausnahme_abteilung_ids       INTEGER[],
              bedingung_alter_min          INTEGER,
              bedingung_alter_max          INTEGER,
              zahler_typ                   TEXT NOT NULL DEFAULT 'mitglied',
              gegenkonto                   TEXT,
              steuerschluessel             TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitragsregel_history (
              id                           INTEGER NOT NULL,
              version                      INTEGER NOT NULL,
              name                         TEXT,
              abteilung_id                 INTEGER,
              betrag_pro_monat             REAL,
              einzug_turnus                TEXT,
              gueltig_ab                   TEXT,
              gueltig_bis                  TEXT,
              bedingung_raw                TEXT,
              bedingung_abteilung_status   TEXT,
              bedingung_funktionen         TEXT[],
              bedingung_funktion_abteilung_id INTEGER,
              bedingung_abteilung_ids      INTEGER[],
              ausnahme_funktionen          TEXT[],
              ausnahme_funktion_abteilung_id INTEGER,
              ausnahme_abteilung_ids       INTEGER[],
              bedingung_alter_min          INTEGER,
              bedingung_alter_max          INTEGER,
              zahler_typ                   TEXT,
              gegenkonto                   TEXT,
              steuerschluessel             TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitrag_sollstellung (
              id                SERIAL PRIMARY KEY,
              mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
              beitragsregel_id  INTEGER NOT NULL REFERENCES beitragsregel(id),
              zeitraum          TEXT NOT NULL,
              betrag_soll       REAL NOT NULL,
              faelligkeitsdatum TEXT,
              status            TEXT NOT NULL DEFAULT 'offen',
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER,
              exportiert_in_export_id        INTEGER,
              storno_exportiert_in_export_id INTEGER,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitrag_sollstellung_history (
              id                INTEGER NOT NULL,
              version           INTEGER NOT NULL,
              mitglied_id       INTEGER,
              beitragsregel_id  INTEGER,
              zeitraum          TEXT,
              betrag_soll       REAL,
              faelligkeitsdatum TEXT,
              status            TEXT,
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER,
              exportiert_in_export_id        INTEGER,
              storno_exportiert_in_export_id INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id                SERIAL PRIMARY KEY,
              username          TEXT NOT NULL,
              email             TEXT NOT NULL,
              password_hash     TEXT NOT NULL,
              role              TEXT NOT NULL CHECK(role IN ('admin', 'mitglied')),
              active            INTEGER NOT NULL DEFAULT 1,
              last_login        TEXT,
              last_seen         TEXT,
              telegram_id       TEXT,
              matrix_id         TEXT,
              preferred_contact TEXT DEFAULT 'email',
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT NOT NULL,
              updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by        TEXT NOT NULL,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users_history (
              id                INTEGER NOT NULL,
              version           INTEGER NOT NULL,
              username          TEXT NOT NULL,
              email             TEXT NOT NULL,
              password_hash     TEXT NOT NULL,
              role              TEXT NOT NULL,
              active            INTEGER NOT NULL,
              last_login        TEXT,
              last_seen         TEXT,
              telegram_id       TEXT,
              matrix_id         TEXT,
              preferred_contact TEXT,
              created_at        TEXT NOT NULL,
              created_by        TEXT NOT NULL,
              updated_at        TEXT NOT NULL,
              updated_by        TEXT NOT NULL,
              deleted_at        TEXT,
              deleted_by        TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
              id          SERIAL PRIMARY KEY,
              user_id     INTEGER NOT NULL REFERENCES users(id),
              token_hash  TEXT UNIQUE NOT NULL,
              token_type  TEXT NOT NULL CHECK(token_type IN ('magic_link', 'remember_me')),
              expires_at  TEXT NOT NULL,
              used_at     TEXT,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              user_id     INTEGER NOT NULL,
              token_hash  TEXT NOT NULL,
              token_type  TEXT NOT NULL,
              expires_at  TEXT NOT NULL,
              used_at     TEXT,
              created_at  TEXT NOT NULL,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
              id            SERIAL PRIMARY KEY,
              user_id       INTEGER NOT NULL REFERENCES users(id),
              sid           TEXT UNIQUE NOT NULL,
              user_agent    TEXT,
              ip            TEXT,
              device_label  TEXT,
              expires_at    TEXT NOT NULL,
              last_seen_at  TEXT,
              revoked_at    TEXT,
              revoked_by    TEXT,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              user_id       INTEGER NOT NULL,
              sid           TEXT NOT NULL,
              user_agent    TEXT,
              ip            TEXT,
              device_label  TEXT,
              expires_at    TEXT NOT NULL,
              last_seen_at  TEXT,
              revoked_at    TEXT,
              revoked_by    TEXT,
              created_at    TEXT NOT NULL,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
              id           SERIAL PRIMARY KEY,
              user_id      INTEGER NOT NULL REFERENCES users(id),
              permission   TEXT NOT NULL,
              effect       TEXT NOT NULL DEFAULT 'grant' CHECK (effect IN ('grant', 'deny')),
              abteilung_id INTEGER REFERENCES abteilung(id),
              version      INTEGER NOT NULL DEFAULT 1,
              created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by   TEXT NOT NULL,
              updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by   TEXT NOT NULL,
              deleted_at   TEXT,
              deleted_by   TEXT,
              UNIQUE (user_id, permission)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions_history (
              id           INTEGER NOT NULL,
              version      INTEGER NOT NULL,
              user_id      INTEGER NOT NULL,
              permission   TEXT NOT NULL,
              effect       TEXT,
              abteilung_id INTEGER,
              created_at   TEXT NOT NULL,
              created_by   TEXT NOT NULL,
              updated_at   TEXT NOT NULL,
              updated_by   TEXT NOT NULL,
              deleted_at   TEXT,
              deleted_by   TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS access_log (
              id          BIGSERIAL PRIMARY KEY,
              event_type  TEXT NOT NULL,
              category    TEXT NOT NULL DEFAULT 'auth',
              user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
              username    TEXT,
              ip          TEXT,
              user_agent  TEXT,
              detail      TEXT,
              created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen (
              id                  SERIAL PRIMARY KEY,
              name                TEXT NOT NULL,
              beschreibung        TEXT,
              anfangsbestand_cent INTEGER NOT NULL DEFAULT 0,
              abteilung_id        INTEGER REFERENCES abteilung(id),
              version             INTEGER NOT NULL DEFAULT 1,
              created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by          TEXT NOT NULL,
              updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by          TEXT NOT NULL,
              deleted_at          TEXT,
              deleted_by          TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_history (
              id                  INTEGER NOT NULL,
              version             INTEGER NOT NULL,
              name                TEXT,
              beschreibung        TEXT,
              anfangsbestand_cent INTEGER,
              abteilung_id        INTEGER,
              created_at          TEXT,
              created_by          TEXT,
              updated_at          TEXT,
              updated_by          TEXT,
              deleted_at          TEXT,
              deleted_by          TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuch_exporte (
              id               SERIAL PRIMARY KEY,
              kasse_id         INTEGER NOT NULL REFERENCES kassen(id),
              zeitraum_von     TEXT NOT NULL,
              zeitraum_bis     TEXT NOT NULL,
              exportiert_am    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              exportiert_von   TEXT NOT NULL,
              dateiname        TEXT NOT NULL,
              anzahl_buchungen INTEGER NOT NULL,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT NOT NULL,
              deleted_at       TEXT,
              deleted_by       TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuch_exporte_history (
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              kasse_id         INTEGER,
              zeitraum_von     TEXT,
              zeitraum_bis     TEXT,
              exportiert_am    TEXT,
              exportiert_von   TEXT,
              dateiname        TEXT,
              anzahl_buchungen INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuchungen (
              id                      SERIAL PRIMARY KEY,
              kasse_id                INTEGER NOT NULL REFERENCES kassen(id),
              buchungsdatum           TEXT NOT NULL,
              belegnummer             TEXT NOT NULL,
              buchungstext            TEXT NOT NULL,
              kategorie               TEXT NOT NULL,
              einnahme_cent           INTEGER NOT NULL DEFAULT 0,
              ausgabe_cent            INTEGER NOT NULL DEFAULT 0,
              notiz                   TEXT,
              exportiert_in_export_id INTEGER REFERENCES kassenbuch_exporte(id),
              version                 INTEGER NOT NULL DEFAULT 1,
              created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by              TEXT NOT NULL,
              updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by              TEXT NOT NULL,
              deleted_at              TEXT,
              deleted_by              TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuchungen_history (
              id                      INTEGER NOT NULL,
              version                 INTEGER NOT NULL,
              kasse_id                INTEGER,
              buchungsdatum           TEXT,
              belegnummer             TEXT,
              buchungstext            TEXT,
              kategorie               TEXT,
              einnahme_cent           INTEGER,
              ausgabe_cent            INTEGER,
              notiz                   TEXT,
              exportiert_in_export_id INTEGER,
              created_at              TEXT,
              created_by              TEXT,
              updated_at              TEXT,
              updated_by              TEXT,
              deleted_at              TEXT,
              deleted_by              TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kasse_berechtigungen (
              id               SERIAL PRIMARY KEY,
              kasse_id         INTEGER NOT NULL REFERENCES kassen(id),
              user_id          INTEGER NOT NULL REFERENCES users(id),
              darf_lesen       INTEGER NOT NULL DEFAULT 0,
              darf_schreiben   INTEGER NOT NULL DEFAULT 0,
              darf_exportieren INTEGER NOT NULL DEFAULT 0,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT NOT NULL,
              updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by       TEXT NOT NULL,
              deleted_at       TEXT,
              deleted_by       TEXT,
              UNIQUE (kasse_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kasse_berechtigungen_history (
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              kasse_id         INTEGER,
              user_id          INTEGER,
              darf_lesen       INTEGER,
              darf_schreiben   INTEGER,
              darf_exportieren INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_kategorien (
              id          SERIAL PRIMARY KEY,
              kasse_id    INTEGER REFERENCES kassen(id),
              name        TEXT NOT NULL,
              loest_zaehlung_aus BOOLEAN NOT NULL DEFAULT false,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_kategorien_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              kasse_id    INTEGER,
              name        TEXT,
              loest_zaehlung_aus BOOLEAN,
              created_at  TEXT,
              created_by  TEXT,
              updated_at  TEXT,
              updated_by  TEXT,
              deleted_at  TEXT,
              deleted_by  TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_zaehlungen (
              id                     SERIAL PRIMARY KEY,
              kasse_id               INTEGER NOT NULL REFERENCES kassen(id),
              buchung_id             INTEGER REFERENCES kassenbuchungen(id),
              ausloesende_buchung_id INTEGER REFERENCES kassenbuchungen(id),
              stueckelung            JSONB NOT NULL DEFAULT '{}',
              ist_cent               INTEGER NOT NULL,
              soll_cent              INTEGER NOT NULL,
              differenz_cent         INTEGER NOT NULL,
              notiz                  TEXT,
              version                INTEGER NOT NULL DEFAULT 1,
              created_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by             TEXT NOT NULL,
              updated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by             TEXT NOT NULL,
              deleted_at             TEXT,
              deleted_by             TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_zaehlungen_history (
              id                     INTEGER NOT NULL,
              version                INTEGER NOT NULL,
              kasse_id               INTEGER,
              buchung_id             INTEGER,
              ausloesende_buchung_id INTEGER,
              stueckelung            JSONB,
              ist_cent               INTEGER,
              soll_cent              INTEGER,
              differenz_cent         INTEGER,
              notiz                  TEXT,
              created_at             TEXT,
              created_by             TEXT,
              updated_at             TEXT,
              updated_by             TEXT,
              deleted_at             TEXT,
              deleted_by             TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereiche (
              id            SERIAL PRIMARY KEY,
              name          TEXT NOT NULL,
              beschreibung  TEXT,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT NOT NULL,
              updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by    TEXT NOT NULL,
              deleted_at    TEXT,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereiche_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              name          TEXT,
              beschreibung  TEXT,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kategorien (
              id          SERIAL PRIMARY KEY,
              name        TEXT NOT NULL,
              icon        TEXT,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kategorien_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              name        TEXT,
              icon        TEXT,
              created_at  TEXT,
              created_by  TEXT,
              updated_at  TEXT,
              updated_by  TEXT,
              deleted_at  TEXT,
              deleted_by  TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
              id              SERIAL PRIMARY KEY,
              titel           TEXT NOT NULL,
              beschreibung    TEXT NOT NULL,
              status          TEXT NOT NULL DEFAULT 'offen'
                              CHECK(status IN ('offen','in_pruefung','eingeplant','rueckfrage','erledigt','abgelehnt')),
              prioritaet      TEXT NOT NULL DEFAULT 'normal'
                              CHECK(prioritaet IN ('niedrig','normal','hoch','sicherheit')),
              bereich_id      INTEGER REFERENCES ticket_bereiche(id),
              kategorie_id    INTEGER REFERENCES ticket_kategorien(id),
              gemeldet_von    INTEGER NOT NULL REFERENCES users(id),
              zugewiesen_an   INTEGER REFERENCES users(id),
              faellig_am      TEXT,
              geschlossen_am  TEXT,
              geschlossen_von INTEGER REFERENCES users(id),
              version         INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by      TEXT NOT NULL,
              updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by      TEXT NOT NULL,
              deleted_at      TEXT,
              deleted_by      TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets_history (
              id              INTEGER NOT NULL,
              version         INTEGER NOT NULL,
              titel           TEXT,
              beschreibung    TEXT,
              status          TEXT,
              prioritaet      TEXT,
              bereich_id      INTEGER,
              kategorie_id    INTEGER,
              gemeldet_von    INTEGER,
              zugewiesen_an   INTEGER,
              faellig_am      TEXT,
              geschlossen_am  TEXT,
              geschlossen_von INTEGER,
              created_at      TEXT,
              created_by      TEXT,
              updated_at      TEXT,
              updated_by      TEXT,
              deleted_at      TEXT,
              deleted_by      TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kommentare (
              id            SERIAL PRIMARY KEY,
              ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
              autor_id      INTEGER NOT NULL REFERENCES users(id),
              inhalt        TEXT NOT NULL,
              sichtbarkeit  TEXT NOT NULL DEFAULT 'oeffentlich'
                            CHECK(sichtbarkeit IN ('oeffentlich', 'intern')),
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT NOT NULL,
              updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by    TEXT NOT NULL,
              deleted_at    TEXT,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kommentare_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              ticket_id     INTEGER,
              autor_id      INTEGER,
              inhalt        TEXT,
              sichtbarkeit  TEXT,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_anhaenge (
              id              SERIAL PRIMARY KEY,
              ticket_id       INTEGER NOT NULL REFERENCES tickets(id),
              kommentar_id    INTEGER REFERENCES ticket_kommentare(id),
              original_name   TEXT NOT NULL,
              stored_name     TEXT UNIQUE,
              mime_type       TEXT NOT NULL,
              dateigroesse    INTEGER NOT NULL,
              hochgeladen_von INTEGER NOT NULL REFERENCES users(id),
              hochgeladen_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              deleted_at      TEXT,
              deleted_by      TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_teilnehmer (
              id               SERIAL PRIMARY KEY,
              ticket_id        INTEGER NOT NULL REFERENCES tickets(id),
              user_id          INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_von INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT NOT NULL,
              updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by       TEXT NOT NULL,
              deleted_at       TEXT,
              deleted_by       TEXT
            )
        """)
        # Aktive Teilnahme eindeutig; nach Soft-Delete ist erneutes Hinzufügen möglich.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uix_ticket_teilnehmer_active
            ON ticket_teilnehmer (ticket_id, user_id) WHERE deleted_at IS NULL
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_teilnehmer_history (
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              ticket_id        INTEGER,
              user_id          INTEGER,
              hinzugefuegt_von INTEGER,
              hinzugefuegt_am  TEXT,
              created_at       TEXT,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereich_berechtigungen (
              id              SERIAL PRIMARY KEY,
              bereich_id      INTEGER NOT NULL REFERENCES ticket_bereiche(id),
              user_id         INTEGER NOT NULL REFERENCES users(id),
              darf_lesen      INTEGER NOT NULL DEFAULT 0,
              darf_bearbeiten INTEGER NOT NULL DEFAULT 0,
              darf_schliessen INTEGER NOT NULL DEFAULT 0,
              version         INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by      TEXT NOT NULL,
              updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by      TEXT NOT NULL,
              deleted_at      TEXT,
              deleted_by      TEXT,
              UNIQUE (bereich_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereich_berechtigungen_history (
              id              INTEGER NOT NULL,
              version         INTEGER NOT NULL,
              bereich_id      INTEGER,
              user_id         INTEGER,
              darf_lesen      INTEGER,
              darf_bearbeiten INTEGER,
              darf_schliessen INTEGER,
              created_at      TEXT,
              created_by      TEXT,
              updated_at      TEXT,
              updated_by      TEXT,
              deleted_at      TEXT,
              deleted_by      TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuchung_anhaenge (
              id              SERIAL PRIMARY KEY,
              buchung_id      INTEGER NOT NULL REFERENCES kassenbuchungen(id),
              original_name   TEXT NOT NULL,
              stored_name     TEXT UNIQUE,
              mime_type       TEXT NOT NULL,
              dateigroesse    INTEGER NOT NULL,
              hochgeladen_von INTEGER NOT NULL REFERENCES users(id),
              hochgeladen_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              deleted_at      TEXT,
              deleted_by      TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mannschaft (
              id             SERIAL PRIMARY KEY,
              abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
              name           TEXT NOT NULL,
              saison         TEXT,
              beschreibung   TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mannschaft_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              abteilung_id   INTEGER,
              name           TEXT,
              saison         TEXT,
              beschreibung   TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_mannschaft (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              mannschaft_id  INTEGER NOT NULL REFERENCES mannschaft(id),
              rolle          TEXT NOT NULL,
              von            TEXT NOT NULL,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_mannschaft_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              mannschaft_id  INTEGER,
              rolle          TEXT,
              von            TEXT,
              bis            TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr (
              id              SERIAL PRIMARY KEY,
              name            TEXT NOT NULL,
              abteilung_id    INTEGER REFERENCES abteilung(id),
              betrag          REAL NOT NULL,
              anlass          TEXT NOT NULL DEFAULT 'aufnahme',
              gueltig_ab      TEXT NOT NULL,
              gueltig_bis     TEXT,
              zahler_typ      TEXT NOT NULL DEFAULT 'mitglied',
              bedingung_alter_min INTEGER,
              bedingung_alter_max INTEGER,
              gegenkonto      TEXT,
              steuerschluessel TEXT,
              kostenstelle    INTEGER,
              kostentraeger   INTEGER,
              version         INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by      TEXT,
              updated_at      TEXT,
              updated_by      TEXT,
              deleted_at      TEXT,
              deleted_by      TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_history (
              id INTEGER NOT NULL, version INTEGER NOT NULL,
              name TEXT, abteilung_id INTEGER, betrag REAL, anlass TEXT,
              gueltig_ab TEXT, gueltig_bis TEXT, zahler_typ TEXT,
              bedingung_alter_min INTEGER, bedingung_alter_max INTEGER,
              gegenkonto TEXT, steuerschluessel TEXT, kostenstelle INTEGER, kostentraeger INTEGER,
              created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
              deleted_at TEXT, deleted_by TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_forderung (
              id                SERIAL PRIMARY KEY,
              mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
              gebuehr_id        INTEGER NOT NULL REFERENCES gebuehr(id),
              datum             TEXT NOT NULL,
              betrag_soll       REAL NOT NULL,
              status            TEXT NOT NULL DEFAULT 'offen',
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER REFERENCES kassenbuchungen(id),
              exportiert_in_export_id        INTEGER,
              storno_exportiert_in_export_id INTEGER,
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_forderung_history (
              id INTEGER NOT NULL, version INTEGER NOT NULL,
              mitglied_id INTEGER, gebuehr_id INTEGER, datum TEXT, betrag_soll REAL,
              status TEXT, bezahlt_am TEXT, kassenbuchung_id INTEGER,
              exportiert_in_export_id INTEGER, storno_exportiert_in_export_id INTEGER,
              created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
              deleted_at TEXT, deleted_by TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion (
              id            SERIAL PRIMARY KEY,
              key           TEXT NOT NULL,
              name          TEXT NOT NULL,
              beschreibung  TEXT,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT,
              updated_at    TIMESTAMP,
              updated_by    TEXT,
              deleted_at    TIMESTAMP,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uix_funktion_key_active
            ON funktion (key) WHERE deleted_at IS NULL
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion_history (
              id           INTEGER NOT NULL,
              version      INTEGER NOT NULL,
              key          TEXT,
              name         TEXT,
              beschreibung TEXT,
              created_at   TIMESTAMP,
              created_by   TEXT,
              updated_at   TIMESTAMP,
              updated_by   TEXT,
              deleted_at   TIMESTAMP,
              deleted_by   TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        # Berechtigungsmatrix pro Katalog-Funktion (siehe BERECHTIGUNGEN.md).
        # Referenz über funktion_id: FK auf den partiellen Unique-Index
        # uix_funktion_key_active ist nicht möglich; Key-Reuse nach Soft-Delete
        # darf alte Rechte nicht wiederbeleben.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion_permission (
              id           SERIAL PRIMARY KEY,
              funktion_id  INTEGER NOT NULL REFERENCES funktion(id),
              permission   TEXT NOT NULL,
              version      INTEGER NOT NULL DEFAULT 1,
              created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by   TEXT NOT NULL,
              updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by   TEXT NOT NULL,
              deleted_at   TEXT,
              deleted_by   TEXT,
              UNIQUE (funktion_id, permission)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion_permission_history (
              id           INTEGER NOT NULL,
              version      INTEGER NOT NULL,
              funktion_id  INTEGER NOT NULL,
              permission   TEXT NOT NULL,
              created_at   TEXT NOT NULL,
              created_by   TEXT NOT NULL,
              updated_at   TEXT NOT NULL,
              updated_by   TEXT NOT NULL,
              deleted_at   TEXT,
              deleted_by   TEXT,
              PRIMARY KEY (id, version)
            )
        """)

        # Übungsleiter-Stundenerfassung (Schema v53): Abrechnung (Header) + Einzeltermine
        # + konfigurierbare Vergütungssätze. DDL geteilt mit Migration v52→v53.
        cur.execute(_DDL_UL_TABLES)

        # Zutrittskontrolle/Schließsystem (Schema v57): TTLock-Konto, Schlösser, Chips,
        # Berechtigungen (+History) und append-only Zutrittslog. DDL geteilt mit v56→v57.
        cur.execute(_DDL_ZUTRITT_TABLES)
        # Kurzzeitige App-Betätigungs-Berechtigung (Schema v58). DDL geteilt mit v57→v58.
        cur.execute(_DDL_TUER_APP_BERECHTIGUNG)
        # Read-only Credential-Mirror je Schloss (Schema v59). DDL geteilt mit v58→v59.
        cur.execute(_DDL_TUER_CREDENTIAL)

        # Fibu-Export (Format hmd FBASC): Export-Lauf-Header + globale Konten-Konfiguration.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fibu_exporte (
              id                  SERIAL PRIMARY KEY,
              exportiert_am       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              exportiert_von      TEXT NOT NULL,
              dateiname           TEXT NOT NULL,
              format              TEXT NOT NULL DEFAULT 'fbasc',
              anzahl_positionen   INTEGER NOT NULL DEFAULT 0,
              summe_cent          INTEGER NOT NULL DEFAULT 0,
              storno_von_export_id INTEGER REFERENCES fibu_exporte(id),
              version             INTEGER NOT NULL DEFAULT 1,
              created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by          TEXT NOT NULL,
              deleted_at          TEXT,
              deleted_by          TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fibu_exporte_history (
              id                  INTEGER NOT NULL,
              version             INTEGER NOT NULL,
              exportiert_am       TEXT,
              exportiert_von      TEXT,
              dateiname           TEXT,
              format              TEXT,
              anzahl_positionen   INTEGER,
              summe_cent          INTEGER,
              storno_von_export_id INTEGER,
              created_at          TEXT,
              created_by          TEXT,
              deleted_at          TEXT,
              deleted_by          TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fibu_einstellungen (
              id                       INTEGER PRIMARY KEY DEFAULT 1,
              debitor_konto_basis      INTEGER,
              default_gegenkonto       TEXT,
              default_steuerschluessel TEXT,
              verein_kostenstelle      INTEGER NOT NULL DEFAULT 12,
              default_kostentraeger    INTEGER NOT NULL DEFAULT 1,
              ul_aufwand_konto         TEXT,
              ul_kreditor_konto_basis  INTEGER,
              version                  INTEGER NOT NULL DEFAULT 1,
              created_at               TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by               TEXT,
              updated_at               TEXT,
              updated_by               TEXT,
              CHECK (id = 1)
            )
        """)
        cur.execute("INSERT INTO fibu_einstellungen (id, debitor_konto_basis) VALUES (1, 200000) ON CONFLICT (id) DO NOTHING")

        # Forward-Referenzen: Diese FKs werden erst NACH allen CREATE TABLE gesetzt,
        # weil ihre Ziel-Tabelle in der Erzeugungsreihenfolge später kommt
        # (mitglied vor users, beitrag_sollstellung vor kassenbuchungen).
        # Inline-REFERENCES würden beim Frischaufbau mit UndefinedTable abbrechen.
        # Constraint-Namen entsprechen den Postgres-Defaults, damit frisch gebaute
        # und hochmigrierte DBs identisch sind.
        cur.execute("""
            ALTER TABLE mitglied
            ADD CONSTRAINT mitglied_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id)
        """)
        cur.execute("""
            ALTER TABLE beitrag_sollstellung
            ADD CONSTRAINT beitrag_sollstellung_kassenbuchung_id_fkey
            FOREIGN KEY (kassenbuchung_id) REFERENCES kassenbuchungen(id)
        """)
        for tbl in ('beitrag_sollstellung', 'gebuehr_forderung'):
            cur.execute(f"""
                ALTER TABLE {tbl}
                ADD CONSTRAINT {tbl}_exportiert_in_export_id_fkey
                FOREIGN KEY (exportiert_in_export_id) REFERENCES fibu_exporte(id)
            """)
            cur.execute(f"""
                ALTER TABLE {tbl}
                ADD CONSTRAINT {tbl}_storno_exportiert_in_export_id_fkey
                FOREIGN KEY (storno_exportiert_in_export_id) REFERENCES fibu_exporte(id)
            """)

    # -----------------------------------
    # Trigger-Funktionen (PL/pgSQL)
    # -----------------------------------

    def _create_trigger_functions(self, cur):
        # Robuster Text→Datum-Cast: liefert NULL statt einer Exception, wenn der
        # Wert leer/ungültig ist (format- ODER kalendarisch, z. B. '2026-02-30').
        # Genutzt von Aggregat-Queries (StatistikRepository), die auf den als TEXT
        # gespeicherten Datumsfeldern rechnen. STABLE, da der ::date-Cast vom
        # DateStyle abhängen kann; STRICT → NULL-Eingabe ergibt NULL.
        cur.execute("""
            CREATE OR REPLACE FUNCTION safe_to_date(txt text) RETURNS date
            LANGUAGE plpgsql STABLE STRICT AS $$
            BEGIN
                RETURN txt::date;
            EXCEPTION WHEN others THEN
                RETURN NULL;
            END; $$;
        """)
        cur.execute(_FN_MITGLIED_AUDIT_INSERT)
        cur.execute(_FN_MITGLIED_AUDIT_UPDATE)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_kontakt_history (
                    id, version, mitglied_id, typ, wert, label, ist_primaer,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_kontakt_history (
                        id, version, mitglied_id, typ, wert, label, ist_primaer,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mannschaft_history (
                    id, version, abteilung_id, name, saison, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mannschaft_history (
                        id, version, abteilung_id, name, saison, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_mannschaft_history (
                    id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_mannschaft_history (
                        id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute(_FN_GEBUEHR_AUDIT_INSERT)
        cur.execute(_FN_GEBUEHR_AUDIT_UPDATE)
        cur.execute(_FN_GEBUEHR_FORDERUNG_AUDIT_INSERT)
        cur.execute(_FN_GEBUEHR_FORDERUNG_AUDIT_UPDATE)
        cur.execute(_FN_UL_ABRECHNUNG_AUDIT_INSERT)
        cur.execute(_FN_UL_ABRECHNUNG_AUDIT_UPDATE)
        cur.execute(_FN_UL_STUNDE_AUDIT_INSERT)
        cur.execute(_FN_UL_STUNDE_AUDIT_UPDATE)
        cur.execute(_FN_UL_SATZ_AUDIT_INSERT)
        cur.execute(_FN_UL_SATZ_AUDIT_UPDATE)
        cur.execute(_FN_TUER_SCHLOSS_AUDIT_INSERT)
        cur.execute(_FN_TUER_SCHLOSS_AUDIT_UPDATE)
        cur.execute(_FN_SCHLUESSEL_CHIP_AUDIT_INSERT)
        cur.execute(_FN_SCHLUESSEL_CHIP_AUDIT_UPDATE)
        cur.execute(_FN_TUER_BERECHTIGUNG_AUDIT_INSERT)
        cur.execute(_FN_TUER_BERECHTIGUNG_AUDIT_UPDATE)
        cur.execute(_FN_TUER_APP_BERECHTIGUNG_AUDIT_INSERT)
        cur.execute(_FN_TUER_APP_BERECHTIGUNG_AUDIT_UPDATE)
        cur.execute(_FN_ABTEILUNG_AUDIT_INSERT)
        cur.execute(_FN_ABTEILUNG_AUDIT_UPDATE)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_abteilung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_abteilung_history (
                    id, version, mitglied_id, abteilung_id, status, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_abteilung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_abteilung_history (
                        id, version, mitglied_id, abteilung_id, status, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_users_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO users_history (
                    id, version, username, email, password_hash, role, active, last_login, last_seen,
                    telegram_id, matrix_id, preferred_contact,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                    NEW.active, NEW.last_login, NEW.last_seen, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_users_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login, last_seen,
                        telegram_id, matrix_id, preferred_contact,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.last_seen, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO auth_tokens_history (
                    id, version, user_id, token_hash, token_type, expires_at, used_at, created_at
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.token_hash, NEW.token_type,
                    NEW.expires_at, NEW.used_at, NEW.created_at
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO auth_tokens_history (
                        id, version, user_id, token_hash, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token_hash, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_sessions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO user_sessions_history (
                    id, version, user_id, sid, user_agent, ip, device_label,
                    expires_at, last_seen_at, revoked_at, revoked_by, created_at
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.sid, NEW.user_agent, NEW.ip, NEW.device_label,
                    NEW.expires_at, NEW.last_seen_at, NEW.revoked_at, NEW.revoked_by, NEW.created_at
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_sessions_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO user_sessions_history (
                        id, version, user_id, sid, user_agent, ip, device_label,
                        expires_at, last_seen_at, revoked_at, revoked_by, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.sid, NEW.user_agent, NEW.ip, NEW.device_label,
                        NEW.expires_at, NEW.last_seen_at, NEW.revoked_at, NEW.revoked_by, NEW.created_at
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_permissions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO user_permissions_history (
                    id, version, user_id, permission, effect, abteilung_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.permission, NEW.effect, NEW.abteilung_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_permissions_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO user_permissions_history (
                        id, version, user_id, permission, effect, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission, NEW.effect, NEW.abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_permission_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO funktion_permission_history (
                    id, version, funktion_id, permission,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.funktion_id, NEW.permission,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_permission_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO funktion_permission_history (
                        id, version, funktion_id, permission,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.funktion_id, NEW.permission,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassen_history (
                    id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent, NEW.abteilung_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassen_history (
                        id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent, NEW.abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuchungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassenbuchungen_history (
                    id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                    kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                    NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                    NEW.notiz, NEW.exportiert_in_export_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuchungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassenbuchungen_history (
                        id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                        kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                        NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                        NEW.notiz, NEW.exportiert_in_export_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuch_exporte_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassenbuch_exporte_history (
                    id, version, kasse_id, zeitraum_von, zeitraum_bis,
                    exportiert_am, exportiert_von, dateiname, anzahl_buchungen,
                    created_at, created_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.zeitraum_von, NEW.zeitraum_bis,
                    NEW.exportiert_am, NEW.exportiert_von, NEW.dateiname, NEW.anzahl_buchungen,
                    NEW.created_at, NEW.created_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute(_FN_FIBU_EXPORTE_AUDIT_INSERT)
        cur.execute(_FN_FIBU_EXPORTE_AUDIT_UPDATE)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kasse_berechtigungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kasse_berechtigungen_history (
                    id, version, kasse_id, user_id,
                    darf_lesen, darf_schreiben, darf_exportieren,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                    NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kasse_berechtigungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kasse_berechtigungen_history (
                        id, version, kasse_id, user_id,
                        darf_lesen, darf_schreiben, darf_exportieren,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassen_kategorien_history (
                    id, version, kasse_id, name, loest_zaehlung_aus,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.name, NEW.loest_zaehlung_aus,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_kategorien_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassen_kategorien_history (
                        id, version, kasse_id, name, loest_zaehlung_aus,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.name, NEW.loest_zaehlung_aus,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_zaehlungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassen_zaehlungen_history (
                    id, version, kasse_id, buchung_id, ausloesende_buchung_id,
                    stueckelung, ist_cent, soll_cent, differenz_cent, notiz,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.buchung_id, NEW.ausloesende_buchung_id,
                    NEW.stueckelung, NEW.ist_cent, NEW.soll_cent, NEW.differenz_cent, NEW.notiz,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_zaehlungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassen_zaehlungen_history (
                        id, version, kasse_id, buchung_id, ausloesende_buchung_id,
                        stueckelung, ist_cent, soll_cent, differenz_cent, notiz,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchung_id, NEW.ausloesende_buchung_id,
                        NEW.stueckelung, NEW.ist_cent, NEW.soll_cent, NEW.differenz_cent, NEW.notiz,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereiche_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_bereiche_history (
                    id, version, name, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereiche_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_bereiche_history (
                        id, version, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kategorien_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_kategorien_history (
                    id, version, name, icon,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.icon,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kategorien_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_kategorien_history (
                        id, version, name, icon,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.icon,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_tickets_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO tickets_history (
                    id, version, titel, beschreibung, status, prioritaet,
                    bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                    faellig_am, geschlossen_am, geschlossen_von,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                    NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                    NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_tickets_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO tickets_history (
                        id, version, titel, beschreibung, status, prioritaet,
                        bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                        faellig_am, geschlossen_am, geschlossen_von,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                        NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                        NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kommentare_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_kommentare_history (
                    id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kommentare_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_kommentare_history (
                        id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereich_berechtigungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_bereich_berechtigungen_history (
                    id, version, bereich_id, user_id,
                    darf_lesen, darf_bearbeiten, darf_schliessen,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.bereich_id, NEW.user_id,
                    NEW.darf_lesen, NEW.darf_bearbeiten, NEW.darf_schliessen,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereich_berechtigungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_bereich_berechtigungen_history (
                        id, version, bereich_id, user_id,
                        darf_lesen, darf_bearbeiten, darf_schliessen,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.bereich_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_bearbeiten, NEW.darf_schliessen,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)

        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_teilnehmer_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_teilnehmer_history (
                    id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.ticket_id, NEW.user_id, NEW.hinzugefuegt_von, NEW.hinzugefuegt_am,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_teilnehmer_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_teilnehmer_history (
                        id, version, ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.user_id, NEW.hinzugefuegt_von, NEW.hinzugefuegt_am,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)

        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_funktion_history (
                    id, version, mitglied_id, abteilung_id, funktion, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_funktion_history (
                        id, version, mitglied_id, abteilung_id, funktion, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute(_FN_BEITRAGSREGEL_AUDIT_INSERT)
        cur.execute(_FN_BEITRAGSREGEL_AUDIT_UPDATE)
        cur.execute(_FN_BEITRAG_SOLLSTELLUNG_AUDIT_INSERT)
        cur.execute(_FN_BEITRAG_SOLLSTELLUNG_AUDIT_UPDATE)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO funktion_history (
                    id, version, key, name, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                    NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO funktion_history (
                        id, version, key, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)

    # -----------------------------------
    # Trigger-Bindungen
    # -----------------------------------

    def _create_triggers(self, cur):
        for name, event, table, fn in [
            ('trig_mitglied_audit_insert',                          'INSERT', 'mitglied',                          'fn_mitglied_audit_insert'),
            ('trig_mitglied_audit_update',                          'UPDATE', 'mitglied',                          'fn_mitglied_audit_update'),
            ('trig_abteilung_audit_insert',                         'INSERT', 'abteilung',                         'fn_abteilung_audit_insert'),
            ('trig_abteilung_audit_update',                         'UPDATE', 'abteilung',                         'fn_abteilung_audit_update'),
            ('trig_mitglied_abteilung_audit_insert',                'INSERT', 'mitglied_abteilung',                'fn_mitglied_abteilung_audit_insert'),
            ('trig_mitglied_abteilung_audit_update',                'UPDATE', 'mitglied_abteilung',                'fn_mitglied_abteilung_audit_update'),
            ('trig_mitglied_funktion_audit_insert',                 'INSERT', 'mitglied_funktion',                 'fn_mitglied_funktion_audit_insert'),
            ('trig_mitglied_funktion_audit_update',                 'UPDATE', 'mitglied_funktion',                 'fn_mitglied_funktion_audit_update'),
            ('trig_mitglied_kontakt_audit_insert',                  'INSERT', 'mitglied_kontakt',                  'fn_mitglied_kontakt_audit_insert'),
            ('trig_mitglied_kontakt_audit_update',                  'UPDATE', 'mitglied_kontakt',                  'fn_mitglied_kontakt_audit_update'),
            ('trig_mannschaft_audit_insert',                        'INSERT', 'mannschaft',                        'fn_mannschaft_audit_insert'),
            ('trig_mannschaft_audit_update',                        'UPDATE', 'mannschaft',                        'fn_mannschaft_audit_update'),
            ('trig_mitglied_mannschaft_audit_insert',               'INSERT', 'mitglied_mannschaft',               'fn_mitglied_mannschaft_audit_insert'),
            ('trig_mitglied_mannschaft_audit_update',               'UPDATE', 'mitglied_mannschaft',               'fn_mitglied_mannschaft_audit_update'),
            ('trig_gebuehr_audit_insert',                           'INSERT', 'gebuehr',                           'fn_gebuehr_audit_insert'),
            ('trig_gebuehr_audit_update',                           'UPDATE', 'gebuehr',                           'fn_gebuehr_audit_update'),
            ('trig_gebuehr_forderung_audit_insert',                 'INSERT', 'gebuehr_forderung',                 'fn_gebuehr_forderung_audit_insert'),
            ('trig_gebuehr_forderung_audit_update',                 'UPDATE', 'gebuehr_forderung',                 'fn_gebuehr_forderung_audit_update'),
            ('trig_users_audit_insert',                             'INSERT', 'users',                             'fn_users_audit_insert'),
            ('trig_users_audit_update',                             'UPDATE', 'users',                             'fn_users_audit_update'),
            ('trig_auth_tokens_audit_insert',                       'INSERT', 'auth_tokens',                       'fn_auth_tokens_audit_insert'),
            ('trig_auth_tokens_audit_update',                       'UPDATE', 'auth_tokens',                       'fn_auth_tokens_audit_update'),
            ('trig_user_sessions_audit_insert',                     'INSERT', 'user_sessions',                     'fn_user_sessions_audit_insert'),
            ('trig_user_sessions_audit_update',                     'UPDATE', 'user_sessions',                     'fn_user_sessions_audit_update'),
            ('trig_user_permissions_audit_insert',                  'INSERT', 'user_permissions',                  'fn_user_permissions_audit_insert'),
            ('trig_user_permissions_audit_update',                  'UPDATE', 'user_permissions',                  'fn_user_permissions_audit_update'),
            ('trig_kassen_audit_insert',                            'INSERT', 'kassen',                            'fn_kassen_audit_insert'),
            ('trig_kassen_audit_update',                            'UPDATE', 'kassen',                            'fn_kassen_audit_update'),
            ('trig_kassenbuchungen_audit_insert',                   'INSERT', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_insert'),
            ('trig_kassenbuchungen_audit_update',                   'UPDATE', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_update'),
            ('trig_kassenbuch_exporte_audit_insert',                'INSERT', 'kassenbuch_exporte',                'fn_kassenbuch_exporte_audit_insert'),
            ('trig_fibu_exporte_audit_insert',                      'INSERT', 'fibu_exporte',                      'fn_fibu_exporte_audit_insert'),
            ('trig_fibu_exporte_audit_update',                      'UPDATE', 'fibu_exporte',                      'fn_fibu_exporte_audit_update'),
            ('trig_kasse_berechtigungen_audit_insert',              'INSERT', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_insert'),
            ('trig_kasse_berechtigungen_audit_update',              'UPDATE', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_update'),
            ('trig_kassen_kategorien_audit_insert',                 'INSERT', 'kassen_kategorien',                 'fn_kassen_kategorien_audit_insert'),
            ('trig_kassen_kategorien_audit_update',                 'UPDATE', 'kassen_kategorien',                 'fn_kassen_kategorien_audit_update'),
            ('trig_kassen_zaehlungen_audit_insert',                 'INSERT', 'kassen_zaehlungen',                 'fn_kassen_zaehlungen_audit_insert'),
            ('trig_kassen_zaehlungen_audit_update',                 'UPDATE', 'kassen_zaehlungen',                 'fn_kassen_zaehlungen_audit_update'),
            ('trig_ticket_bereiche_audit_insert',                   'INSERT', 'ticket_bereiche',                   'fn_ticket_bereiche_audit_insert'),
            ('trig_ticket_bereiche_audit_update',                   'UPDATE', 'ticket_bereiche',                   'fn_ticket_bereiche_audit_update'),
            ('trig_ticket_kategorien_audit_insert',                 'INSERT', 'ticket_kategorien',                 'fn_ticket_kategorien_audit_insert'),
            ('trig_ticket_kategorien_audit_update',                 'UPDATE', 'ticket_kategorien',                 'fn_ticket_kategorien_audit_update'),
            ('trig_tickets_audit_insert',                           'INSERT', 'tickets',                           'fn_tickets_audit_insert'),
            ('trig_tickets_audit_update',                           'UPDATE', 'tickets',                           'fn_tickets_audit_update'),
            ('trig_ticket_kommentare_audit_insert',                 'INSERT', 'ticket_kommentare',                 'fn_ticket_kommentare_audit_insert'),
            ('trig_ticket_kommentare_audit_update',                 'UPDATE', 'ticket_kommentare',                 'fn_ticket_kommentare_audit_update'),
            ('trig_ticket_bereich_berechtigungen_audit_insert',     'INSERT', 'ticket_bereich_berechtigungen',     'fn_ticket_bereich_berechtigungen_audit_insert'),
            ('trig_ticket_bereich_berechtigungen_audit_update',     'UPDATE', 'ticket_bereich_berechtigungen',     'fn_ticket_bereich_berechtigungen_audit_update'),
            ('trig_ticket_teilnehmer_audit_insert',                 'INSERT', 'ticket_teilnehmer',                 'fn_ticket_teilnehmer_audit_insert'),
            ('trig_ticket_teilnehmer_audit_update',                 'UPDATE', 'ticket_teilnehmer',                 'fn_ticket_teilnehmer_audit_update'),
            ('trig_beitragsregel_audit_insert',                     'INSERT', 'beitragsregel',                     'fn_beitragsregel_audit_insert'),
            ('trig_beitragsregel_audit_update',                     'UPDATE', 'beitragsregel',                     'fn_beitragsregel_audit_update'),
            ('trig_beitrag_sollstellung_audit_insert',              'INSERT', 'beitrag_sollstellung',              'fn_beitrag_sollstellung_audit_insert'),
            ('trig_beitrag_sollstellung_audit_update',              'UPDATE', 'beitrag_sollstellung',              'fn_beitrag_sollstellung_audit_update'),
            ('trig_funktion_audit_insert',                          'INSERT', 'funktion',                          'fn_funktion_audit_insert'),
            ('trig_funktion_audit_update',                          'UPDATE', 'funktion',                          'fn_funktion_audit_update'),
            ('trig_funktion_permission_audit_insert',               'INSERT', 'funktion_permission',               'fn_funktion_permission_audit_insert'),
            ('trig_funktion_permission_audit_update',               'UPDATE', 'funktion_permission',               'fn_funktion_permission_audit_update'),
            *_UL_TRIGGERS,
            *_ZUTRITT_TRIGGERS,
            *_TUER_APP_BERECHTIGUNG_TRIGGERS,
        ]:
            cur.execute(f"""
                CREATE OR REPLACE TRIGGER {name}
                AFTER {event} ON {table}
                FOR EACH ROW EXECUTE FUNCTION {fn}();
            """)

    # -----------------------------------
    # Indizes
    # -----------------------------------

    def _create_indexes(self, cur):
        for name, target in [
            ("idx_users_username",                                  "users(username)"),
            ("idx_users_email",                                     "users(email)"),
            ("idx_users_role",                                      "users(role)"),
            ("idx_users_active",                                    "users(active)"),
            ("idx_users_deleted_at",                                "users(deleted_at)"),
            ("idx_users_history_id",                                "users_history(id)"),
            ("idx_auth_tokens_token_hash",                          "auth_tokens(token_hash)"),
            ("idx_auth_tokens_user_id",                             "auth_tokens(user_id)"),
            ("idx_auth_tokens_expires_at",                          "auth_tokens(expires_at)"),
            ("idx_auth_tokens_token_type",                          "auth_tokens(token_type)"),
            ("idx_auth_tokens_history_id",                          "auth_tokens_history(id)"),
            ("idx_user_sessions_sid",                               "user_sessions(sid)"),
            ("idx_user_sessions_user_id",                           "user_sessions(user_id)"),
            ("idx_user_sessions_expires_at",                        "user_sessions(expires_at)"),
            ("idx_user_sessions_revoked_at",                        "user_sessions(revoked_at)"),
            ("idx_user_sessions_history_id",                        "user_sessions_history(id)"),
            ("idx_user_permissions_user_id",                        "user_permissions(user_id)"),
            ("idx_user_permissions_permission",                     "user_permissions(permission)"),
            ("idx_user_permissions_deleted_at",                     "user_permissions(deleted_at)"),
            ("idx_user_permissions_history_id",                     "user_permissions_history(id)"),
            ("idx_access_log_created",                              "access_log(created_at DESC)"),
            ("idx_access_log_event",                                "access_log(event_type)"),
            ("idx_access_log_user",                                 "access_log(user_id)"),
            ("idx_access_log_category",                             "access_log(category, created_at)"),
            ("idx_funktion_permission_funktion_id",                 "funktion_permission(funktion_id)"),
            ("idx_funktion_permission_deleted_at",                  "funktion_permission(deleted_at)"),
            ("idx_funktion_permission_history_id",                  "funktion_permission_history(id)"),
            *_UL_INDEXES,
            ("idx_kassen_deleted_at",                               "kassen(deleted_at)"),
            ("idx_kassen_abteilung_id",                             "kassen(abteilung_id)"),
            ("idx_kassenbuchungen_kasse_id",                        "kassenbuchungen(kasse_id)"),
            ("idx_kassenbuchungen_buchungsdatum",                   "kassenbuchungen(buchungsdatum)"),
            ("idx_kassenbuchungen_deleted_at",                      "kassenbuchungen(deleted_at)"),
            ("idx_kassenbuchungen_export_id",                       "kassenbuchungen(exportiert_in_export_id)"),
            ("idx_kassenbuchungen_belegnummer",                     "kassenbuchungen(kasse_id, belegnummer)"),
            ("idx_kassenbuchungen_history_id",                      "kassenbuchungen_history(id)"),
            ("idx_kassenbuch_exporte_kasse_id",                     "kassenbuch_exporte(kasse_id)"),
            ("idx_kassenbuch_exporte_zeitraum",                     "kassenbuch_exporte(zeitraum_von, zeitraum_bis)"),
            ("idx_kasse_berechtigungen_kasse_id",                   "kasse_berechtigungen(kasse_id)"),
            ("idx_kasse_berechtigungen_user_id",                    "kasse_berechtigungen(user_id)"),
            ("idx_kasse_berechtigungen_deleted_at",                 "kasse_berechtigungen(deleted_at)"),
            ("idx_kasse_berechtigungen_history_id",                 "kasse_berechtigungen_history(id)"),
            ("idx_kassen_kategorien_kasse_id",                      "kassen_kategorien(kasse_id)"),
            ("idx_kassen_kategorien_deleted_at",                    "kassen_kategorien(deleted_at)"),
            ("idx_kassen_kategorien_history_id",                    "kassen_kategorien_history(id)"),
            ("idx_kassen_zaehlungen_kasse_id",                      "kassen_zaehlungen(kasse_id)"),
            ("idx_kassen_zaehlungen_deleted_at",                    "kassen_zaehlungen(deleted_at)"),
            ("idx_kassen_zaehlungen_buchung_id",                    "kassen_zaehlungen(buchung_id)"),
            ("idx_kassen_zaehlungen_history_id",                    "kassen_zaehlungen_history(id)"),
            ("idx_ticket_bereiche_deleted_at",                      "ticket_bereiche(deleted_at)"),
            ("idx_ticket_kategorien_deleted_at",                    "ticket_kategorien(deleted_at)"),
            ("idx_tickets_status",                                  "tickets(status)"),
            ("idx_tickets_prioritaet",                              "tickets(prioritaet)"),
            ("idx_tickets_bereich_id",                              "tickets(bereich_id)"),
            ("idx_tickets_kategorie_id",                            "tickets(kategorie_id)"),
            ("idx_tickets_gemeldet_von",                            "tickets(gemeldet_von)"),
            ("idx_tickets_zugewiesen_an",                           "tickets(zugewiesen_an)"),
            ("idx_tickets_deleted_at",                              "tickets(deleted_at)"),
            ("idx_tickets_history_id",                              "tickets_history(id)"),
            ("idx_ticket_kommentare_ticket_id",                     "ticket_kommentare(ticket_id)"),
            ("idx_ticket_kommentare_autor_id",                      "ticket_kommentare(autor_id)"),
            ("idx_ticket_kommentare_deleted_at",                    "ticket_kommentare(deleted_at)"),
            ("idx_ticket_kommentare_history_id",                    "ticket_kommentare_history(id)"),
            ("idx_ticket_anhaenge_ticket_id",                       "ticket_anhaenge(ticket_id)"),
            ("idx_ticket_anhaenge_kommentar_id",                    "ticket_anhaenge(kommentar_id)"),
            ("idx_ticket_anhaenge_deleted_at",                      "ticket_anhaenge(deleted_at)"),
            ("idx_ticket_teilnehmer_ticket_id",                     "ticket_teilnehmer(ticket_id)"),
            ("idx_ticket_teilnehmer_user_id",                       "ticket_teilnehmer(user_id)"),
            ("idx_ticket_bereich_berechtigungen_bereich_id",        "ticket_bereich_berechtigungen(bereich_id)"),
            ("idx_ticket_bereich_berechtigungen_user_id",           "ticket_bereich_berechtigungen(user_id)"),
            ("idx_ticket_bereich_berechtigungen_deleted_at",        "ticket_bereich_berechtigungen(deleted_at)"),
            ("idx_ticket_bereich_berechtigungen_history_id",        "ticket_bereich_berechtigungen_history(id)"),
            ("idx_kassenbuchung_anhaenge_buchung_id",               "kassenbuchung_anhaenge(buchung_id)"),
            ("idx_kassenbuchung_anhaenge_deleted_at",               "kassenbuchung_anhaenge(deleted_at)"),
            ("idx_mitglied_kontakt_mitglied_id",                    "mitglied_kontakt(mitglied_id)"),
            ("idx_mitglied_kontakt_deleted_at",                     "mitglied_kontakt(deleted_at)"),
            ("idx_mitglied_kontakt_history_id",                     "mitglied_kontakt_history(id)"),
            ("idx_mannschaft_abteilung_id",                         "mannschaft(abteilung_id)"),
            ("idx_mannschaft_deleted_at",                           "mannschaft(deleted_at)"),
            ("idx_mannschaft_history_id",                           "mannschaft_history(id)"),
            ("idx_mitglied_mannschaft_mitglied_id",                 "mitglied_mannschaft(mitglied_id)"),
            ("idx_mitglied_mannschaft_mannschaft_id",               "mitglied_mannschaft(mannschaft_id)"),
            ("idx_mitglied_mannschaft_deleted_at",                  "mitglied_mannschaft(deleted_at)"),
            ("idx_mitglied_mannschaft_history_id",                  "mitglied_mannschaft_history(id)"),
            ("idx_gebuehr_abteilung_id",                            "gebuehr(abteilung_id)"),
            ("idx_gebuehr_deleted_at",                              "gebuehr(deleted_at)"),
            ("idx_gebuehr_history_id",                              "gebuehr_history(id)"),
            ("idx_gebuehr_forderung_mitglied_id",                   "gebuehr_forderung(mitglied_id)"),
            ("idx_gebuehr_forderung_gebuehr_id",                    "gebuehr_forderung(gebuehr_id)"),
            ("idx_gebuehr_forderung_status",                        "gebuehr_forderung(status)"),
            ("idx_gebuehr_forderung_deleted_at",                    "gebuehr_forderung(deleted_at)"),
            ("idx_gebuehr_forderung_history_id",                    "gebuehr_forderung_history(id)"),
            ("idx_beitrag_sollstellung_export_id",                  "beitrag_sollstellung(exportiert_in_export_id)"),
            ("idx_beitrag_sollstellung_storno_export_id",           "beitrag_sollstellung(storno_exportiert_in_export_id)"),
            ("idx_gebuehr_forderung_export_id",                     "gebuehr_forderung(exportiert_in_export_id)"),
            ("idx_gebuehr_forderung_storno_export_id",              "gebuehr_forderung(storno_exportiert_in_export_id)"),
            ("idx_fibu_exporte_storno_von_export_id",               "fibu_exporte(storno_von_export_id)"),
            ("idx_fibu_exporte_history_id",                         "fibu_exporte_history(id)"),
            *_ZUTRITT_INDEXES,
            *_TUER_APP_BERECHTIGUNG_INDEXES,
        ]:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")

        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_user_id       ON mitglied (user_id)  WHERE user_id IS NOT NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_kontakt_primaer ON mitglied_kontakt (mitglied_id, typ) WHERE ist_primaer AND deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_email_active    ON users (email)       WHERE deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_username_active ON users (username)    WHERE deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_telegram_id     ON users (telegram_id) WHERE telegram_id IS NOT NULL AND deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_matrix_id       ON users (matrix_id)   WHERE matrix_id   IS NOT NULL AND deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_kassen_kategorien_scope_name ON kassen_kategorien (COALESCE(kasse_id, 0), lower(name)) WHERE deleted_at IS NULL")
        for sql in _ZUTRITT_UNIQUE_INDEXES:
            cur.execute(sql)

    # -----------------------------------
    # Seed-Daten
    # -----------------------------------

    def _seed_data(self, cur):
        _ADMIN_PERMS = {
            'personen.read', 'personen.write', 'personen.delete', 'personen.permissions',
            'abteilungen.read', 'abteilungen.write', 'abteilungen.delete',
            'mannschaften.read', 'mannschaften.write', 'mannschaften.delete',
            'beitraege.read', 'beitraege.write', 'beitraege.abrechnen',
            'gebuehren.read', 'gebuehren.write', 'gebuehren.abrechnen',
            'fibu.export',
            'ulstunden.erfassen', 'ulstunden.erfassen_fremd', 'ulstunden.bestaetigen', 'ulstunden.verwalten',
            'berichte.read', 'berichte.export',
            'system.config',
            'tickets.access',
            'tickets.bereiche_verwalten',
            'schliessanlage.read', 'schliessanlage.verwalten', 'schliessanlage.protokoll',
            'schliessanlage.oeffnen',
        }

        pw_hash = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode()
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, active, created_by, updated_by)
            VALUES (%s, %s, %s, 'admin', 1, 'SYSTEM', 'SYSTEM')
            RETURNING id
        """, ('admin', 'admin@verein.local', pw_hash))
        admin_id = cur.fetchone()['id']
        logger.warning("Standard-Admin erstellt: Username='admin', Passwort='admin123' - BITTE ÄNDERN!")

        for perm in _ADMIN_PERMS:
            cur.execute("""
                INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
                ON CONFLICT DO NOTHING
            """, (admin_id, perm))

        for name, beschreibung in [
            ('Platz 1',      'Hauptspielfeld'),
            ('Platz 2',      'Nebenspielfeld'),
            ('Kabinen',      'Umkleiden und Sanitaranlagen'),
            ('Vereinsheim',  'Clubhaus und Gastraum'),
            ('Aussenanlage', 'Zaeune, Wege, Parkplatz'),
            ('Sonstiges',    None),
        ]:
            cur.execute("""
                INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
                RETURNING id
            """, (name, beschreibung))
            bereich_id = cur.fetchone()['id']
            cur.execute("""
                INSERT INTO ticket_bereich_berechtigungen
                    (bereich_id, user_id, darf_lesen, darf_bearbeiten, darf_schliessen, created_by, updated_by)
                VALUES (%s, %s, 1, 1, 1, 'SYSTEM', 'SYSTEM')
                ON CONFLICT DO NOTHING
            """, (bereich_id, admin_id))

        for name, icon in [
            ('Schaden',      'wrench'),
            ('Sicherheit',   'shield-alert'),
            ('Ausstattung',  'package'),
            ('Reinigung',    'sparkles'),
            ('IT / Technik', 'monitor'),
            ('Sonstiges',    'circle-help'),
        ]:
            cur.execute("""
                INSERT INTO ticket_kategorien (name, icon, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
            """, (name, icon))

        for key, name in [
            ('schiedsrichter',   'Schiedsrichter'),
            ('uebungsleiter',    'Übungsleiter'),
            ('abteilungsleiter', 'Abteilungsleiter'),
        ]:
            cur.execute("""
                INSERT INTO funktion (key, name, created_by)
                SELECT %s, %s, 'SYSTEM'
                WHERE NOT EXISTS (
                    SELECT 1 FROM funktion WHERE key = %s AND deleted_at IS NULL
                )
            """, (key, name, key))

        # Standard-Berechtigungen der ÜL-Stundenerfassung an die Funktionen hängen.
        for fkey, perm in _UL_FUNKTION_PERMISSIONS:
            cur.execute("""
                INSERT INTO funktion_permission (funktion_id, permission, created_by, updated_by)
                SELECT f.id, %s, 'SYSTEM', 'SYSTEM' FROM funktion f
                WHERE f.key=%s AND f.deleted_at IS NULL
                ON CONFLICT (funktion_id, permission) DO NOTHING
            """, (perm, fkey))
