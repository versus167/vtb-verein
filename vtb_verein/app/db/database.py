'''
PostgreSQL database connection and schema management.
Rewritten 2026-05-18: sqlite3 → psycopg3, single consolidated schema (v15).
'''

import os
import bcrypt
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

SCHEMA_VERSION = 15


class Database:
    """Manages PostgreSQL connection and schema."""

    def __init__(self, database_url: str):
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
            self._create_schema()
        elif row['version'] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema-Version {row['version']} gefunden, "
                f"erwartet {SCHEMA_VERSION}. Bitte Alembic-Migration ausführen."
            )

    def _create_schema(self):
        """Erstellt das vollständige Schema (v15) auf einer frischen Datenbank."""
        with self.cursor() as cur:
            self._create_tables(cur)
            self._create_trigger_functions(cur)
            self._create_triggers(cur)
            self._create_indexes(cur)
            self._seed_data(cur)
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
              email             TEXT,
              telefon           TEXT,
              eintrittsdatum    TEXT,
              austrittsdatum    TEXT,
              status            TEXT NOT NULL DEFAULT 'aktiv',
              zahlungsart       TEXT NOT NULL,
              iban              TEXT,
              bic               TEXT,
              kontoinhaber      TEXT,
              abgerechnet_bis   TEXT,
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
            CREATE TABLE IF NOT EXISTS abteilung (
              id            SERIAL PRIMARY KEY,
              name          TEXT NOT NULL,
              kuerzel       TEXT,
              beschreibung  TEXT,
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
            CREATE TABLE IF NOT EXISTS beitragsregel (
              id             SERIAL PRIMARY KEY,
              name           TEXT NOT NULL,
              abteilung_id   INTEGER REFERENCES abteilung(id),
              betrag         REAL NOT NULL,
              periode        TEXT NOT NULL,
              gueltig_ab     TEXT NOT NULL,
              gueltig_bis    TEXT,
              bedingung_raw  TEXT,
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
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              name           TEXT,
              abteilung_id   INTEGER,
              betrag         REAL,
              periode        TEXT,
              gueltig_ab     TEXT,
              gueltig_bis    TEXT,
              bedingung_raw  TEXT,
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
              id               SERIAL PRIMARY KEY,
              mitglied_id      INTEGER NOT NULL REFERENCES mitglied(id),
              beitragsregel_id INTEGER NOT NULL REFERENCES beitragsregel(id),
              zeitraum         TEXT NOT NULL,
              betrag_soll      REAL NOT NULL,
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
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              mitglied_id      INTEGER,
              beitragsregel_id INTEGER,
              zeitraum         TEXT,
              betrag_soll      REAL,
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
              username          TEXT UNIQUE NOT NULL,
              email             TEXT UNIQUE NOT NULL,
              password_hash     TEXT NOT NULL,
              role              TEXT NOT NULL CHECK(role IN ('admin', 'user', 'readonly', 'special')),
              active            INTEGER NOT NULL DEFAULT 1,
              last_login        TEXT,
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
              token       TEXT UNIQUE NOT NULL,
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
              token       TEXT NOT NULL,
              token_type  TEXT NOT NULL,
              expires_at  TEXT NOT NULL,
              used_at     TEXT,
              created_at  TEXT NOT NULL,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
              id          SERIAL PRIMARY KEY,
              user_id     INTEGER NOT NULL REFERENCES users(id),
              permission  TEXT NOT NULL,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT,
              UNIQUE (user_id, permission)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              user_id     INTEGER NOT NULL,
              permission  TEXT NOT NULL,
              created_at  TEXT NOT NULL,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT,
              PRIMARY KEY (id, version)
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
              ticket_id        INTEGER NOT NULL REFERENCES tickets(id),
              user_id          INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_von INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (ticket_id, user_id)
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

    # -----------------------------------
    # Trigger-Funktionen (PL/pgSQL)
    # -----------------------------------

    def _create_trigger_functions(self, cur):
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_history (
                    id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                    strasse, plz, ort, land, email, telefon,
                    eintrittsdatum, austrittsdatum, status,
                    zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                    NEW.strasse, NEW.plz, NEW.ort, NEW.land, NEW.email, NEW.telefon,
                    NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                    NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
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
                        strasse, plz, ort, land, email, telefon,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land, NEW.email, NEW.telefon,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_abteilung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO abteilung_history (
                    id, version, name, kuerzel, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_abteilung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO abteilung_history (
                        id, version, name, kuerzel, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
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
                    id, version, username, email, password_hash, role, active, last_login,
                    telegram_id, matrix_id, preferred_contact,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                    NEW.active, NEW.last_login, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
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
                        id, version, username, email, password_hash, role, active, last_login,
                        telegram_id, matrix_id, preferred_contact,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
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
                    id, version, user_id, token, token_type, expires_at, used_at, created_at
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
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
                        id, version, user_id, token, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_permissions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO user_permissions_history (
                    id, version, user_id, permission,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.permission,
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
                        id, version, user_id, permission,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission,
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
            ('trig_users_audit_insert',                             'INSERT', 'users',                             'fn_users_audit_insert'),
            ('trig_users_audit_update',                             'UPDATE', 'users',                             'fn_users_audit_update'),
            ('trig_auth_tokens_audit_insert',                       'INSERT', 'auth_tokens',                       'fn_auth_tokens_audit_insert'),
            ('trig_auth_tokens_audit_update',                       'UPDATE', 'auth_tokens',                       'fn_auth_tokens_audit_update'),
            ('trig_user_permissions_audit_insert',                  'INSERT', 'user_permissions',                  'fn_user_permissions_audit_insert'),
            ('trig_user_permissions_audit_update',                  'UPDATE', 'user_permissions',                  'fn_user_permissions_audit_update'),
            ('trig_kassen_audit_insert',                            'INSERT', 'kassen',                            'fn_kassen_audit_insert'),
            ('trig_kassen_audit_update',                            'UPDATE', 'kassen',                            'fn_kassen_audit_update'),
            ('trig_kassenbuchungen_audit_insert',                   'INSERT', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_insert'),
            ('trig_kassenbuchungen_audit_update',                   'UPDATE', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_update'),
            ('trig_kassenbuch_exporte_audit_insert',                'INSERT', 'kassenbuch_exporte',                'fn_kassenbuch_exporte_audit_insert'),
            ('trig_kasse_berechtigungen_audit_insert',              'INSERT', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_insert'),
            ('trig_kasse_berechtigungen_audit_update',              'UPDATE', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_update'),
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
            ("idx_auth_tokens_token",                               "auth_tokens(token)"),
            ("idx_auth_tokens_user_id",                             "auth_tokens(user_id)"),
            ("idx_auth_tokens_expires_at",                          "auth_tokens(expires_at)"),
            ("idx_auth_tokens_token_type",                          "auth_tokens(token_type)"),
            ("idx_auth_tokens_history_id",                          "auth_tokens_history(id)"),
            ("idx_user_permissions_user_id",                        "user_permissions(user_id)"),
            ("idx_user_permissions_permission",                     "user_permissions(permission)"),
            ("idx_user_permissions_deleted_at",                     "user_permissions(deleted_at)"),
            ("idx_user_permissions_history_id",                     "user_permissions_history(id)"),
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
        ]:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")

        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_telegram_id ON users (telegram_id) WHERE telegram_id IS NOT NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_matrix_id   ON users (matrix_id)   WHERE matrix_id   IS NOT NULL")

    # -----------------------------------
    # Seed-Daten
    # -----------------------------------

    def _seed_data(self, cur):
        _ADMIN_PERMS = {
            'mitglieder.read', 'mitglieder.write', 'mitglieder.delete',
            'abteilungen.read', 'abteilungen.write', 'abteilungen.delete',
            'beitraege.read', 'beitraege.write',
            'berichte.read', 'berichte.export',
            'users.read', 'users.manage',
            'system.config',
            'tickets.access',
            'tickets.bereiche_verwalten',
        }

        pw_hash = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode()
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, active, created_by, updated_by)
            VALUES (%s, %s, %s, 'admin', 1, 'SYSTEM', 'SYSTEM')
            RETURNING id
        """, ('admin', 'admin@verein.local', pw_hash))
        admin_id = cur.fetchone()['id']
        print("⚠️  Standard-Admin erstellt: Username='admin', Passwort='admin123' - BITTE ÄNDERN!")

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
