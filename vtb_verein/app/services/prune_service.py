"""
PruneService – endgültiges Entfernen alter, nicht mehr abhängiger Soft-Deletes.

Hintergrund (siehe Soft-Delete-Only-Prinzip): Es wird nie hart gelöscht, weder im
Request-Pfad noch durch Cascades. Stattdessen landen Datensätze im "Papierkorb"
(``deleted_at IS NOT NULL``) und sind über ``restore_*`` wiederherstellbar. Dieser
Service räumt den Papierkorb kontrolliert auf, OHNE die Wiederherstellung auszuhebeln.

Prune-Modell – ein Original-Datensatz ist nur dann endgültig löschbar, wenn ALLE Tore
gelten:
  1. Soft-deleted (``deleted_at`` gesetzt) – aktive Datensätze werden nie angefasst.
  2. Alt genug (Datum): ``deleted_at`` älter als ``retention_days``. Dieses Fenster IST
     die Restore-Garantie.
  3. Mindestanzahl (Anzahl): die ``keep_min`` zuletzt gelöschten Datensätze bleiben pro
     Entität immer erhalten, egal wie alt.
  4. Nicht mehr abhängig: keine Kind-Referenz mehr (aktiv ODER soft-deleted). Die FK-
     Constraints (ohne ON DELETE CASCADE) erzwingen das ohnehin auf DB-Ebene – wir
     prüfen es vorab, damit der Report stimmt und Eltern nicht fälschlich als löschbar
     erscheinen.
  5. History-frei: keine ``*_history``-Zeile mehr vorhanden. History ist die tiefste
     Recovery-/Audit-Schicht und wird ZUERST geprunt (nach eigenem, längerem Fenster);
     erst wenn für einen Datensatz keine History mehr übrig bliebe, darf das Original weg.

Phase 0 (dieser Stand): NUR Dry-Run-Report (``report()``) – es wird NICHTS gelöscht.
Die SQL-Bausteine sind als reine Funktionen ausgelagert und damit ohne DB testbar.
Das echte Löschen (``prune()``) folgt in den nächsten Phasen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional


# --- Default-Aufbewahrung (später konfigurierbar) ---------------------------------
DEFAULT_RETENTION_DAYS = 90      # Original: Mindest-Verweildauer im Papierkorb
DEFAULT_KEEP_MIN = 10            # Original: so viele zuletzt Gelöschte bleiben immer
DEFAULT_HISTORY_RETENTION_DAYS = 365   # History: eigenes, längeres Fenster

# --- Sonder-Bereiche: Protokolle & gerätegebundene Tabellen (siehe LogRule) --------
# Kein Soft-Delete/Papierkorb, sondern Hard-Delete nach Alter. Schlüssel sind stabil und
# in der Override-Tabelle `prune_einstellungen` einstellbar wie jede PruneEntity.
ACCESS_LOG_PAGE = "access_log_page"
DEFAULT_PAGE_VIEW_RETENTION_DAYS = 90

TICKET_ZUGRIFF_LOG = "ticket_zugriff_log"
DEFAULT_TICKET_VIEW_RETENTION_DAYS = 180

# Protokolle mit Personenbezug (wer war wann wo / hat was gesehen): 1 Jahr.
DEFAULT_PROTOKOLL_RETENTION_DAYS = 365
# Rein technische Protokolle ohne Personenbezug (Batteriestand, Schloss-Status): 90 Tage.
DEFAULT_TECHNIK_LOG_RETENTION_DAYS = 90
# Gerätebindungen, nachdem sie tot sind (abgelaufen bzw. widerrufen): 90 Tage Nachlauf.
DEFAULT_GERAET_NACHLAUF_DAYS = 90

# Alters-Archivierung (generisch, siehe ArchiveRule): datierte Datensätze werden nach
# Alter auf soft-deleted gesetzt (in den Papierkorb verschoben) – KEIN Hard-Delete.
# Danach greift der reguläre Prune wie bei jedem anderen Papierkorb-Eintrag. Erste Regel:
# vergangene Mannschafts-Termine (#104). Dieselbe Mechanik ist später wiederverwendbar
# (z.B. ausgeschiedene Mitglieder per austrittsdatum + passenden Kind-Kaskaden).
TERMIN_ALTER = "termin_alter"
DEFAULT_TERMIN_ALTER_RETENTION_DAYS = 5 * 365   # ~5 Jahre (Standard, per Override änderbar)

# Abgeschlossene Tickets (erledigt/abgelehnt) wandern nach Alter in den Papierkorb
# (Alters-Archivierung wie Termine); der reguläre Ticket-Prune räumt sie danach ab.
TICKET_ABGESCHLOSSEN_ALTER = "ticket_abgeschlossen_alter"
DEFAULT_TICKET_ABGESCHLOSSEN_RETENTION_DAYS = 5 * 365   # ~5 Jahre

# Steuerliche Aufbewahrung: 10 Jahre, gerechnet AB JAHRESENDE des Belegdatums (dafür
# sorgt `_ab_jahresende`). Bewusst der konservative Wert – die kürzere Frist für reine
# Buchungsbelege ist nicht genommen worden. Wie alles andere in `prune_einstellungen`
# nachjustierbar, falls die Kassenprüfung etwas anderes verlangt.
DEFAULT_FINANZ_RETENTION_DAYS = 10 * 365

# Ausgeschiedene Mitglieder: bewusst dasselbe Fenster wie die Finanzdaten. Kürzer wäre
# wirkungslos – solange Sollstellungen und Buchungen des Mitglieds aufbewahrt werden
# müssen, hält Tor 4 den Stammsatz ohnehin fest, sonst hingen Belege an einer leeren ID.
DEFAULT_MITGLIED_AUSTRITT_RETENTION_DAYS = 10 * 365

# Rechte-Zuweisungen (individuelle Grants/Denies, Kassen-ACL): länger als der 90-Tage-
# Standard, weil ein Rechte-Entzug nachvollziehbar bleiben soll.
DEFAULT_RECHTE_RETENTION_DAYS = 365

# Deaktivierte Benutzerkonten. KEIN Ablauf wegen Inaktivität – ein aktives Konto bleibt,
# auch wenn sich lange niemand anmeldet; erst das Deaktivieren startet die Uhr.
DEFAULT_USERS_RETENTION_DAYS = 365

# Verwaiste Anhang-Dateien: liegen auf der Platte, ohne dass eine DB-Zeile sie kennt –
# typischerweise ein Upload, der nach dem Schreiben der Datei abgebrochen ist. Die Frist
# ist bewusst großzügig: zwischen Datei-Schreiben und DB-Insert liegen Millisekunden,
# aber ein zu enges Fenster würde bei einer langsamen Anfrage die Datei unter einem
# gerade entstehenden Anhang wegziehen.
DATEI_VERWAIST = "datei_verwaist"
DEFAULT_VERWAISTE_DATEI_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ChildRef:
    """Eine Live-Tabelle, die auf die Eltern-Tabelle zeigt.

    Standard: ``child.fk == parent.id`` (echte FK). Manche Bezüge laufen aber NICHT über
    die id, sondern über eine andere Eltern-Spalte (z.B. mitglied_funktion.funktion ==
    funktion.key, lose ohne FK) – dafür ``parent_col`` setzen.
    """
    table: str
    fk: str
    parent_col: str = "id"
    # Manche Blatt-Tabellen (z.B. ticket_anhaenge) haben Soft-Delete OHNE version/History –
    # dann darf der Archiv-Kind-Soft-Delete kein `version = version + 1` schreiben.
    has_version: bool = True


@dataclass(frozen=True)
class ParentRef:
    """Eltern-Datensatz, der ein Blatt am Leben hält, bis er selbst so weit ist (Tor 6).

    Gegenrichtung zu ChildRef: ChildRef verhindert, dass ein Eltern-Datensatz VOR seinen
    Kindern verschwindet. ParentRef verhindert, dass ein Kind LANGE VOR seinem
    Eltern-Datensatz verschwindet — ein Kassenbeleg soll nicht neun Monate vor der
    Buchung weg sein, an der er hängt. Die Schere entsteht, weil Anhänge keine History
    haben: Ihr Fenster ist nur die Papierkorb-Frist, das der Buchung zusätzlich das
    deutlich längere History-Fenster.

    Bewusst KEIN spiegelbildliches „erst NACH dem Eltern-Datensatz": zusammen mit Tor 4
    wäre das eine Verklemmung – beide warteten für immer aufeinander. Das Tor hält das
    Kind nur so lange, wie der Eltern-Datensatz selbst im Papierkorb sitzt und dessen
    eigene Frist läuft. Danach fallen beide, das Kind einen Lauf früher – die
    Reihenfolge, die Tor 4 ohnehin erzwingt.

    Ein eigenständig gelöschtes Kind (falsches Foto an einer AKTIVEN Buchung) bleibt
    unberührt: Dort liegt der Eltern-Datensatz nicht im Papierkorb, das Tor greift nicht,
    und die kurze eigene Frist des Kindes gilt weiter – ein versehentlich hochgeladenes
    Dokument soll nicht ein Jahr liegen bleiben.
    """
    entity: str                     # Name der Eltern-PruneEntity (liefert deren Fristen)
    table: str                      # deren Live-Tabelle
    fk: str                         # Spalte im Kind, die auf parent.id zeigt


@dataclass(frozen=True)
class PruneEntity:
    """Deklarative Beschreibung einer prunebaren Entität.

    Struktur (table/history/children) ist fix; retention_days/keep_min/history_retention_days
    sind nur die CODE-DEFAULTS – zur Laufzeit überschreibbar via `prune_einstellungen`.
    """
    name: str                       # technischer Schlüssel
    label: str                      # Anzeigename (DE)
    table: str                      # Live-Tabelle
    history_table: Optional[str] = None
    history_id_col: str = "id"      # Spalte in der History, die auf table.id zeigt
    children: tuple[ChildRef, ...] = field(default_factory=tuple)
    # Spalte mit dem Datei-Namen auf der Platte (Anhänge); gesetzt -> beim Prune wird
    # die Datei via AnhangService zusätzlich gelöscht. Domänen-unabhängiger Storage-Layer.
    stored_name_col: Optional[str] = None
    # Gesetzt, wenn dieses Blatt seinen Eltern-Datensatz nicht deutlich überleben lassen
    # darf, ohne selbst zu warten (Tor 6, siehe ParentRef). Höchstens einer – mehr hat
    # bisher keine Entität gebraucht.
    parent: Optional[ParentRef] = None
    retention_days: int = DEFAULT_RETENTION_DAYS
    keep_min: int = DEFAULT_KEEP_MIN
    history_retention_days: int = DEFAULT_HISTORY_RETENTION_DAYS


@dataclass(frozen=True)
class SaldoVortrag:
    """Wohin die Summe der archivierten Zeilen wandert, damit ein Saldo nicht springt (#189).

    Nötig überall dort, wo ein Bestand als Summe über die AKTIVEN Zeilen einer
    Bewegungstabelle gerechnet wird: Archivieren heißt Soft-Delete, die Zeilen fallen
    aus der Summe – und der Bestand ändert sich, obwohl fachlich nichts passiert ist.
    Der Vortrag rechnet die Summe der fälligen Zeilen VOR dem Archivieren auf ein
    Ankerfeld am Eltern-Datensatz (Kasse) und schreibt den Stichtag daneben.

    Damit ist der Vortrag rollierend: Beim nächsten Lauf ist der alte Vortrag schon Teil
    von ``ziel_col``, dazu kommt nur die neue Tranche. Es bleibt genau EIN Ankerwert je
    Kasse, keine Kette von Vorträgen.
    """
    ziel_table: str                 # Eltern-Tabelle mit dem Ankerfeld, z.B. "kassen"
    ziel_fk: str                    # Spalte in rule.table, die dorthin zeigt, z.B. "kasse_id"
    ziel_col: str                   # Ankerfeld, z.B. "anfangsbestand_cent"
    betrag_expr: str                # vorzeichenbehafteter Betrag je Zeile
    # Optionales Feld am Eltern-Datensatz, das festhält, AB WANN der Anker gilt. Es
    # bekommt den Tag nach der letzten mitgenommenen Zeile (``stichtag_expr`` liefert
    # deren Datum) – nicht den Prune-Cutoff: Fällig wird nach Jahresende, es überleben
    # also Zeilen aus dem Cutoff-Jahr, und der Cutoff läge fälschlich hinter ihnen.
    stichtag_col: Optional[str] = None
    stichtag_expr: Optional[str] = None   # Datum der Zeile, z.B. "buchungsdatum"


@dataclass(frozen=True)
class ArchiveRule:
    """Generische Alters-Archivierung: aktive, datierte Datensätze werden nach Alter
    (Tage) auf ``deleted_at`` gesetzt (in den Papierkorb verschoben) – erst der
    Saldovortrag (``vortrag``), dann die Kinder (``children``, Blatt zuerst), dann der
    Datensatz selbst. Das ist ein reversibler Soft-Delete; das endgültige Entfernen
    übernimmt danach der reguläre Prune über die passende ``PruneEntity``.

    ``date_expr`` ist ein SQL-Ausdruck auf ``table`` (TEXT/ISO oder Timestamp); über den
    Datumsanteil (``LEFT(...,10)``) entscheidet sich die Fälligkeit. Bewusst schlank und
    domänen-neutral gehalten, damit weitere Regeln (z.B. ausgeschiedene Mitglieder per
    ``austrittsdatum``) nur ein weiterer Registry-Eintrag sind.
    """
    name: str                       # Schlüssel (auch in prune_einstellungen nutzbar)
    label: str                      # Anzeigename (DE)
    table: str                      # Live-Tabelle
    date_expr: str                  # z.B. "COALESCE(NULLIF(ende, ''), beginn)"
    default_days: int = DEFAULT_TERMIN_ALTER_RETENTION_DAYS
    children: tuple[ChildRef, ...] = field(default_factory=tuple)
    # Gesetzt, wenn das Archivieren einen laufenden Saldo verfälschen würde.
    vortrag: Optional[SaldoVortrag] = None


@dataclass(frozen=True)
class LogRule:
    """Append-only-Tabelle ohne Papierkorb: Hard-Delete nach Alter, sonst nichts.

    Deckt zwei Sorten ab, die dieselbe Mechanik brauchen:
      * **Protokolle** (`access_log`, `*_zugriff_log`, `tuer_zutritt_log`, …) – das Log IST
        der Audit-Datensatz, es gibt kein `deleted_at` und keine History.
      * **Gerätebindungen und deren History** (`user_sessions`, `auth_tokens`,
        `push_subscriptions`) – sie sterben nicht per Soft-Delete, sondern indem sie
        ablaufen oder widerrufen werden.

    ``ts_expr`` ist der Zeitpunkt, ab dem die Zeile *tot* ist und die Frist läuft: bei
    Protokollen der Anfall (``created_at``), bei Gerätebindungen der Tod
    (``COALESCE(revoked_at, expires_at)``). Ergibt der Ausdruck NULL, ist die Zeile nie
    fällig – so bleiben aktive Sessions und nie widerrufene Abos unangetastet, ohne dass
    es dafür eine Sonderregel braucht. ``where`` schränkt zusätzlich ein (z.B. auf eine
    ``access_log``-Kategorie), ``gruppe`` bündelt die Zeilen nur in der UI.
    """
    name: str                       # Schlüssel (auch in prune_einstellungen nutzbar)
    label: str                      # Anzeigename (DE)
    table: str
    ts_expr: str = "created_at"     # Zeitpunkt, ab dem die Frist läuft
    where: str = ""                 # zusätzliche Einschränkung, ohne führendes AND
    default_days: int = DEFAULT_PROTOKOLL_RETENTION_DAYS
    gruppe: str = "Protokolle"      # Überschrift in der Admin-UI


# Reihenfolge: Blatt → Wurzel. So sind beim echten Lauf die Kinder schon weg, bevor
# das Eltern-Element drankommt. History wird je Entität separat (und vorgelagert) geprunt.
#
# Grundsatz (Entscheidung 2026-08-11): Es gibt KEINE Daten, die dauerhaft bleiben. Wo
# früher „bewusst nicht drin" stand, war das meist eine offene Frage und kein Entschluss –
# inzwischen hat jede Tabelle ein Fenster, nur unterschiedlich lange. Daten mit
# Aufbewahrungspflicht (Finanzen) und ausgeschiedene Mitglieder werden nicht hier
# geführt, sondern über die ARCHIVE_REGISTRY: sie sind aktiv und hätten nie ein
# `deleted_at`, an dem Tor 1 greifen könnte. Erst schiebt die Archivierung sie nach
# Ablauf der Frist in den Papierkorb, dann räumt der reguläre Prune sie hier ab.
# Protokolle und Gerätebindungen (kein Papierkorb, Hard-Delete nach Alter) stehen in der
# LOG_REGISTRY.
# Vollständigkeit der Child-Refs wird per Schema-Drift-Test (test_prune_integration.py)
# gegen die echten FKs abgesichert – neue FK auf eine geprunte Tabelle -> Test rot.
# `test_jede_tabelle_hat_einen_loeschpfad` bewacht zusätzlich, dass überhaupt jede
# Tabelle in einer der drei Registries auftaucht.
#
# Child-Refs listen ALLE eingehenden FKs (auch aus nicht-geprunten Tabellen) – fehlt
# einer, würde der DB-FK (RESTRICT) das echte Löschen blockieren. Anhänge sind reine
# Blätter ohne History/Version; stored_name_col aktiviert das Datei-Löschen.
PRUNE_REGISTRY: tuple[PruneEntity, ...] = (
    # --- Anhänge (Blätter mit Disk-Datei) ---
    PruneEntity("ticket_anhang", "Ticket-Anhänge", "ticket_anhaenge",
                stored_name_col="stored_name"),
    # Tor 6: Der Beleg darf nicht lange vor der Buchung endgültig verschwinden, an der
    # er hängt – sonst stünde die stornierte Buchung monatelang ohne ihren Kassenbon im
    # Papierkorb. Betrifft auch das Zählprotokoll-PDF, das als normaler Anhang an der
    # Zähl-Buchung hängt.
    PruneEntity("kassenbuchung_anhang", "Kassen-Anhänge", "kassenbuchung_anhaenge",
                stored_name_col="stored_name",
                parent=ParentRef("kassenbuchung", "kassenbuchungen", "buchung_id")),
    # Belege gelöschter Rechnungs-Entwürfe. Die Rechnung selbst wird NICHT geprunt
    # (Finanzdaten, siehe Kopfkommentar) – gelöscht werden kann ein Beleg ohnehin nur
    # im Entwurf, also bevor irgendetwas freigegeben oder exportiert wurde.
    PruneEntity("rechnung_anhang", "Rechnungs-Belege", "rechnung_anhaenge",
                stored_name_col="stored_name"),
    # --- Schließanlage / Zutritt (Blatt → Wurzel) ---
    # Steht VOR mitglied/abteilung: schluessel_chip hängt an mitglied, tuer_schloss an
    # abteilung. tuer_zutritt_log, tuer_credential, tuer_schloss_status_log sind KEINE
    # Prune-Entitäten (Dauerprotokolle/kein Soft-Delete) – tauchen nur als Child-Guards auf.
    PruneEntity("tuer_app_berechtigung", "App-Türberechtigungen", "tuer_app_berechtigung",
                history_table="tuer_app_berechtigung_history"),
    PruneEntity("tuer_berechtigung", "Chip-Türberechtigungen", "tuer_berechtigung",
                history_table="tuer_berechtigung_history"),
    # Rechtegruppen (#169): die beiden Paar-Tabellen sind Blätter, die Gruppe ihre
    # Wurzel. tuer_berechtigung hängt über gruppe_id ebenfalls an der Gruppe und muss
    # als Child-Guard mit, sonst blockiert der FK das echte Löschen.
    PruneEntity("chip_gruppe_schloss", "Gruppen-Türen", "chip_gruppe_schloss",
                history_table="chip_gruppe_schloss_history"),
    PruneEntity("chip_gruppe_zuordnung", "Gruppen-Zuordnungen", "chip_gruppe_zuordnung",
                history_table="chip_gruppe_zuordnung_history"),
    PruneEntity("chip_gruppe", "Chip-Rechtegruppen", "chip_gruppe",
                history_table="chip_gruppe_history",
                children=(
                    ChildRef("chip_gruppe_schloss", "gruppe_id"),
                    ChildRef("chip_gruppe_zuordnung", "gruppe_id"),
                    ChildRef("tuer_berechtigung", "gruppe_id"),
                )),
    PruneEntity("tuer_schloss", "Schlösser", "tuer_schloss",
                history_table="tuer_schloss_history",
                children=(
                    ChildRef("tuer_app_berechtigung", "schloss_id"),
                    ChildRef("tuer_berechtigung", "schloss_id"),
                    ChildRef("chip_gruppe_schloss", "schloss_id"),
                    ChildRef("tuer_credential", "schloss_id"),
                    ChildRef("tuer_schloss_status_log", "schloss_id"),
                    ChildRef("tuer_zutritt_log", "schloss_id"),
                )),
    PruneEntity("schluessel_chip", "Schlüssel-Chips", "schluessel_chip",
                history_table="schluessel_chip_history",
                children=(
                    ChildRef("tuer_berechtigung", "chip_id"),
                    ChildRef("chip_gruppe_zuordnung", "chip_id"),
                    ChildRef("tuer_zutritt_log", "chip_id"),
                )),
    # --- Übungsleiter-Abrechnung (Blatt → Wurzel) ---
    PruneEntity("ul_stunde", "ÜL-Stunden", "ul_stunde",
                history_table="ul_stunde_history"),
    PruneEntity("ul_abrechnung", "ÜL-Abrechnungen", "ul_abrechnung",
                history_table="ul_abrechnung_history",
                children=(ChildRef("ul_stunde", "abrechnung_id"),)),
    PruneEntity("ul_satz", "ÜL-Sätze", "ul_satz",
                history_table="ul_satz_history"),
    # --- Passwort-Tresor (Blatt → Wurzel) ---
    # tresor_zugriff_log ist append-only (kein Soft-Delete, keine FK auf tresor/-eintrag)
    # und daher KEINE Prune-Entität – es taucht auch nicht als Child-Guard auf.
    PruneEntity("tresor_eintrag", "Tresor-Einträge", "tresor_eintrag",
                history_table="tresor_eintrag_history"),
    PruneEntity("tresor_kontakt", "Tresor-Kontakte", "tresor_kontakt",
                history_table="tresor_kontakt_history"),
    PruneEntity("tresor_freigabe", "Tresor-Freigaben", "tresor_freigabe",
                history_table="tresor_freigabe_history"),
    PruneEntity("tresor", "Passwort-Tresore", "tresor",
                history_table="tresor_history",
                children=(
                    ChildRef("tresor_eintrag", "tresor_id"),
                    ChildRef("tresor_kontakt", "tresor_id"),
                    ChildRef("tresor_freigabe", "tresor_id"),
                )),
    # --- Teamkasse/Clubdeckel (#98, Blatt → Wurzel, vor mannschaft/mitglied) ---
    PruneEntity("clubdeckel_buchung", "Teamkassen-Buchungen", "clubdeckel_buchung",
                history_table="clubdeckel_buchung_history"),
    PruneEntity("clubdeckel_artikel", "Teamkassen-Artikel", "clubdeckel_artikel",
                history_table="clubdeckel_artikel_history",
                children=(ChildRef("clubdeckel_buchung", "artikel_id"),)),
    PruneEntity("clubdeckel_gruppe", "Teamkassen-Artikelgruppen", "clubdeckel_gruppe",
                history_table="clubdeckel_gruppe_history",
                children=(
                    ChildRef("clubdeckel_artikel", "gruppe_id"),
                    # Selbstbezug der Generationen (#167, v100): Die erste
                    # Generation trägt die stamm_id aller späteren, darf also
                    # nicht vor ihnen verschwinden. Löst sich über mehrere Läufe
                    # auf — genau wie andere Selbstbezüge in dieser Registry.
                    ChildRef("clubdeckel_gruppe", "stamm_id"),
                )),
    PruneEntity("clubdeckel_berechtigung", "Teamkassen-Warte", "clubdeckel_berechtigung",
                history_table="clubdeckel_berechtigung_history"),
    PruneEntity("clubdeckel_beitrag_befreiung", "Teamkassen-Beitragsbefreiungen",
                "clubdeckel_beitrag_befreiung",
                history_table="clubdeckel_beitrag_befreiung_history"),
    PruneEntity("clubdeckel_event_opt_out", "Teamkassen-Sammlungs-Opt-outs",
                "clubdeckel_event_opt_out",
                history_table="clubdeckel_event_opt_out_history"),
    PruneEntity("clubdeckel_event", "Teamkassen-Sammlungen", "clubdeckel_event",
                history_table="clubdeckel_event_history",
                children=(ChildRef("clubdeckel_buchung", "event_id"),)),
    PruneEntity("clubdeckel", "Teamkassen", "clubdeckel",
                history_table="clubdeckel_history",
                children=(
                    ChildRef("clubdeckel_buchung", "deckel_id"),
                    ChildRef("clubdeckel_artikel", "deckel_id"),
                    ChildRef("clubdeckel_gruppe", "deckel_id"),
                    ChildRef("clubdeckel_berechtigung", "deckel_id"),
                    ChildRef("clubdeckel_beitrag_befreiung", "deckel_id"),
                    ChildRef("clubdeckel_event", "deckel_id"),
                    ChildRef("clubdeckel_event_opt_out", "deckel_id"),
                )),
    # --- Spielbetrieb: Mannschafts-Termine (#95, Blatt vor mannschaft) ---
    PruneEntity("termin_zusage", "Termin-Zusagen", "termin_zusage",
                history_table="termin_zusage_history"),
    PruneEntity("termin_abweichung", "Termin-Abweichungen", "termin_abweichung",
                history_table="termin_abweichung_history"),
    PruneEntity("termin", "Termine", "termine",
                history_table="termine_history",
                children=(
                    ChildRef("termin_zusage", "termin_id"),
                    ChildRef("termin_abweichung", "termin_id"),
                    # Teamkassen-Buchungen (#167) zeigen auf den Termin, an dem sie
                    # entstanden. Sie sind KEIN Kind im Lösch-Sinn – die Referenz hält
                    # den Termin nur über Tor 4 im Papierkorb fest, solange noch eine
                    # Buchung auf ihn zeigt. Deshalb steht sie hier, aber bewusst NICHT
                    # in der ArchiveRule weiter unten.
                    ChildRef("clubdeckel_buchung", "termin_id"),
                    # Ebenso der Sortiments-Stand „gilt ab diesem Spieltag"
                    # (#167): Er begründet Preis, Bezeichnung und Verkäufer
                    # alter Buchungen und darf nicht mit dem Termin verschwinden.
                    ChildRef("clubdeckel_gruppe", "gilt_ab_termin_id"),
                )),
    PruneEntity("termin_serie", "Terminserien", "termin_serie",
                history_table="termin_serie_history",
                children=(ChildRef("termine", "serie_id"),)),
    # Spielstätten stehen nach Termin/Serie: Solange ein Termin auf einen Platz
    # zeigt, hält die Kind-Referenz ihn im Papierkorb fest (Tor 4) – ein
    # gelöschter Platz reißt also keine Termine mit.
    PruneEntity("spielstaette", "Spielstätten", "spielstaette",
                history_table="spielstaette_history",
                children=(
                    ChildRef("termine", "spielstaette_id"),
                    ChildRef("termin_serie", "spielstaette_id"),
                    ChildRef("termin_abweichung", "spielstaette_id"),
                )),
    # Kalender-Abos (#153): Blatt ohne Kinder. Hängt an users, und users werden
    # nicht geprunt – deshalb genügt der eigene Eintrag, kein ChildRef nach oben.
    PruneEntity("kalender_abo", "Kalender-Abos", "kalender_abo",
                history_table="kalender_abo_history"),
    # --- Finanzdaten (Blatt → Wurzel, steht VOR mitglied/abteilung) ---
    # Diese Entitäten löschen NICHT nach Alter des Belegs, sondern wie jede andere: erst
    # muss die Zeile im Papierkorb liegen. Dorthin bringt sie die ARCHIVE_REGISTRY nach
    # Ablauf der Aufbewahrungsfrist. Ein von Hand gelöschter Beleg (Tippfehler im Entwurf)
    # läuft dagegen über das kurze Standard-Fenster – Tor 4 verhindert trotzdem, dass ein
    # Beleg verschwindet, an dem noch etwas hängt.
    PruneEntity("kassen_zaehlung", "Kassenzählungen", "kassen_zaehlungen",
                history_table="kassen_zaehlungen_history"),
    PruneEntity("beitrag_sollstellung", "Beitrags-Sollstellungen", "beitrag_sollstellung",
                history_table="beitrag_sollstellung_history"),
    PruneEntity("gebuehr_forderung", "Gebühren-Forderungen", "gebuehr_forderung",
                history_table="gebuehr_forderung_history"),
    PruneEntity("sepa_lauf_position", "SEPA-Positionen", "sepa_lauf_position",
                history_table="sepa_lauf_position_history"),
    PruneEntity("sepa_lauf", "SEPA-Einzugsläufe", "sepa_lauf",
                history_table="sepa_lauf_history",
                children=(ChildRef("sepa_lauf_position", "sepa_lauf_id"),)),
    PruneEntity("rechnung", "Rechnungen", "rechnung",
                history_table="rechnung_history",
                children=(ChildRef("rechnung_anhaenge", "rechnung_id"),)),
    PruneEntity("rechnung_kategorie", "Rechnungs-Kategorien", "rechnung_kategorie",
                history_table="rechnung_kategorie_history",
                children=(ChildRef("rechnung", "kategorie_id"),)),
    PruneEntity("rechnung_export", "Rechnungs-Exporte", "rechnung_exporte",
                history_table="rechnung_exporte_history",
                children=(ChildRef("rechnung", "exportiert_in_export_id"),)),
    PruneEntity("kassenbuchung", "Kassenbuchungen", "kassenbuchungen",
                history_table="kassenbuchungen_history",
                children=(
                    ChildRef("beitrag_sollstellung", "kassenbuchung_id"),
                    ChildRef("gebuehr_forderung", "kassenbuchung_id"),
                    ChildRef("kassen_zaehlungen", "ausloesende_buchung_id"),
                    ChildRef("kassen_zaehlungen", "buchung_id"),
                    ChildRef("kassenbuchung_anhaenge", "buchung_id"),
                )),
    PruneEntity("kassenbuch_export", "Kassenbuch-Exporte", "kassenbuch_exporte",
                history_table="kassenbuch_exporte_history",
                children=(ChildRef("kassenbuchungen", "exportiert_in_export_id"),)),
    # Storno-Exporte zeigen auf den Ur-Export (Selbstbezug) – der Guard verhindert, dass
    # der Ur-Export vor seinem Storno verschwindet.
    PruneEntity("fibu_export", "Fibu-Exporte", "fibu_exporte",
                history_table="fibu_exporte_history",
                children=(
                    ChildRef("beitrag_sollstellung", "exportiert_in_export_id"),
                    ChildRef("beitrag_sollstellung", "storno_exportiert_in_export_id"),
                    ChildRef("gebuehr_forderung", "exportiert_in_export_id"),
                    ChildRef("gebuehr_forderung", "storno_exportiert_in_export_id"),
                    ChildRef("fibu_exporte", "storno_von_export_id"),
                )),
    PruneEntity("gebuehr", "Gebühren", "gebuehr",
                history_table="gebuehr_history",
                children=(ChildRef("gebuehr_forderung", "gebuehr_id"),)),
    PruneEntity("beitragsregel", "Beitragsregeln", "beitragsregel",
                history_table="beitragsregel_history",
                children=(ChildRef("beitrag_sollstellung", "beitragsregel_id"),)),
    PruneEntity("kassen_kategorie", "Kassen-Kategorien", "kassen_kategorien",
                history_table="kassen_kategorien_history"),
    PruneEntity("kasse_berechtigung", "Kassen-Berechtigungen", "kasse_berechtigungen",
                history_table="kasse_berechtigungen_history",
                retention_days=DEFAULT_RECHTE_RETENTION_DAYS),
    PruneEntity("kasse", "Kassen", "kassen",
                history_table="kassen_history",
                children=(
                    ChildRef("kasse_berechtigungen", "kasse_id"),
                    ChildRef("kassen_kategorien", "kasse_id"),
                    ChildRef("kassen_zaehlungen", "kasse_id"),
                    ChildRef("kassenbuch_exporte", "kasse_id"),
                    ChildRef("kassenbuchungen", "kasse_id"),
                )),
    # --- Mitglied-Domäne (Blatt → Wurzel) ---
    PruneEntity("mitglied_kontakt", "Kontaktdaten", "mitglied_kontakt",
                history_table="mitglied_kontakt_history"),
    PruneEntity("mitglied_abteilung", "Abteilungs-Zuordnungen", "mitglied_abteilung",
                history_table="mitglied_abteilung_history"),
    PruneEntity("mitglied_funktion", "Funktions-Zuordnungen", "mitglied_funktion",
                history_table="mitglied_funktion_history"),
    PruneEntity("mitglied_mannschaft", "Mannschafts-Zuordnungen", "mitglied_mannschaft",
                history_table="mitglied_mannschaft_history"),
    PruneEntity("mannschaft_dfbnet_alias", "DFBnet-Aliasse", "mannschaft_dfbnet_alias",
                history_table="mannschaft_dfbnet_alias_history"),
    PruneEntity("mannschaft", "Mannschaften", "mannschaft",
                history_table="mannschaft_history",
                children=(
                    ChildRef("clubdeckel", "mannschaft_id"),
                    ChildRef("mitglied_mannschaft", "mannschaft_id"),
                    ChildRef("termin_serie", "mannschaft_id"),
                    ChildRef("termine", "mannschaft_id"),
                    ChildRef("mannschaft_dfbnet_alias", "mannschaft_id"),
                )),
    PruneEntity("mitglied", "Mitglieder", "mitglied",
                history_table="mitglied_history",
                children=(
                    ChildRef("beitrag_sollstellung", "mitglied_id"),
                    ChildRef("clubdeckel", "zahlungsempfaenger_mitglied_id"),
                    ChildRef("clubdeckel_beitrag_befreiung", "mitglied_id"),
                    ChildRef("clubdeckel_berechtigung", "mitglied_id"),
                    ChildRef("clubdeckel_buchung", "mitglied_id"),
                    ChildRef("clubdeckel_event", "fuer_mitglied_id"),
                    ChildRef("clubdeckel_event_opt_out", "mitglied_id"),
                    ChildRef("clubdeckel_gruppe", "verkaeufer_mitglied_id"),
                    ChildRef("gebuehr_forderung", "mitglied_id"),
                    ChildRef("mitglied_abteilung", "mitglied_id"),
                    ChildRef("mitglied_funktion", "mitglied_id"),
                    ChildRef("mitglied_kontakt", "mitglied_id"),
                    ChildRef("mitglied_mannschaft", "mitglied_id"),
                    ChildRef("rechnung", "empfaenger_mitglied_id"),
                    ChildRef("schluessel_chip", "mitglied_id"),
                    ChildRef("sepa_lauf_position", "mitglied_id"),   # Finanzdaten: nie geprunt
                    ChildRef("termin_zusage", "mitglied_id"),
                    ChildRef("tuer_zutritt_log", "mitglied_id"),   # Dauerprotokoll: nie soft-deleted
                    ChildRef("ul_abrechnung", "mitglied_id"),
                    ChildRef("ul_satz", "mitglied_id"),
                )),
    # --- Tickets-Domäne (Blatt → Wurzel) ---
    PruneEntity("ticket_teilnehmer", "Ticket-Teilnehmer", "ticket_teilnehmer",
                history_table="ticket_teilnehmer_history"),
    PruneEntity("ticket_bereich_berechtigung", "Ticket-Bereichsrechte",
                "ticket_bereich_berechtigungen",
                history_table="ticket_bereich_berechtigungen_history"),
    PruneEntity("ticket_kommentar", "Ticket-Kommentare", "ticket_kommentare",
                history_table="ticket_kommentare_history",
                children=(ChildRef("ticket_anhaenge", "kommentar_id"),)),
    PruneEntity("ticket", "Tickets", "tickets",
                history_table="tickets_history",
                children=(
                    ChildRef("ticket_kommentare", "ticket_id"),
                    ChildRef("ticket_anhaenge", "ticket_id"),
                    ChildRef("ticket_teilnehmer", "ticket_id"),
                )),
    PruneEntity("ticket_kategorie", "Ticket-Kategorien", "ticket_kategorien",
                history_table="ticket_kategorien_history",
                children=(ChildRef("tickets", "kategorie_id"),)),
    PruneEntity("ticket_bereich", "Ticket-Bereiche", "ticket_bereiche",
                history_table="ticket_bereiche_history",
                children=(
                    ChildRef("tickets", "bereich_id"),
                    ChildRef("ticket_bereich_berechtigungen", "bereich_id"),
                )),
    # --- Stammdaten (Blatt → Wurzel) ---
    # Individuelle Grants/Denies: hoher Durchsatz (jede Rechteänderung legt die alte Zeile
    # in den Papierkorb), deshalb überhaupt prunenswert – aber mit längerem Fenster.
    PruneEntity("user_permission", "Individuelle Rechte", "user_permissions",
                history_table="user_permissions_history",
                retention_days=DEFAULT_RECHTE_RETENTION_DAYS),
    PruneEntity("funktion_permission", "Funktionsrechte", "funktion_permission",
                history_table="funktion_permission_history"),
    PruneEntity("funktion", "Funktionen", "funktion",
                history_table="funktion_history",
                children=(
                    ChildRef("funktion_permission", "funktion_id"),       # FK auf funktion.id
                    ChildRef("mitglied_funktion", "funktion", parent_col="key"),  # lose über key
                )),
    PruneEntity("abteilung", "Abteilungen", "abteilung",
                history_table="abteilung_history",
                children=(
                    ChildRef("mitglied_abteilung", "abteilung_id"),
                    ChildRef("mitglied_funktion", "abteilung_id"),
                    ChildRef("mannschaft", "abteilung_id"),
                    ChildRef("beitragsregel", "abteilung_id"),
                    ChildRef("beitragsregel", "ausnahme_funktion_abteilung_id"),
                    ChildRef("beitragsregel", "bedingung_funktion_abteilung_id"),
                    ChildRef("gebuehr", "abteilung_id"),
                    ChildRef("kassen", "abteilung_id"),
                    ChildRef("user_permissions", "abteilung_id"),
                    ChildRef("tuer_schloss", "abteilung_id"),
                    ChildRef("ul_abrechnung", "abteilung_id"),
                    ChildRef("ul_satz", "abteilung_id"),
                    ChildRef("rechnung", "abteilung_id"),
                )),
    # Benutzerkonten stehen ganz am Ende: fast alles trägt eine Urheber-Spalte auf users.
    # Ein deaktiviertes Konto verschwindet daher erst, wenn auch die letzte Spur davon
    # weg ist (Tor 4) – in der Praxis oft erst Jahre später über die Protokoll-Fristen.
    # Der Last-Admin-Schutz liegt im Repository und wird hiervon nicht berührt: geprunt
    # wird nur, was ohnehin schon deaktiviert (soft-deleted) ist.
    PruneEntity("user", "Benutzerkonten", "users",
                history_table="users_history",
                retention_days=DEFAULT_USERS_RETENTION_DAYS,
                children=(
                    ChildRef("access_log", "user_id"),
                    ChildRef("auth_tokens", "user_id"),
                    ChildRef("kalender_abo", "user_id"),
                    ChildRef("kasse_berechtigungen", "user_id"),
                    ChildRef("kassenbuchung_anhaenge", "hochgeladen_von"),
                    ChildRef("mitglied", "user_id"),
                    ChildRef("push_subscriptions", "user_id"),
                    ChildRef("rechnung", "ersteller_user_id"),
                    ChildRef("schluessel_chip", "user_id"),
                    ChildRef("ticket_anhaenge", "hochgeladen_von"),
                    ChildRef("ticket_bereich_berechtigungen", "user_id"),
                    ChildRef("ticket_kommentare", "autor_id"),
                    ChildRef("ticket_teilnehmer", "hinzugefuegt_von"),
                    ChildRef("ticket_teilnehmer", "user_id"),
                    ChildRef("ticket_zugriff_log", "user_id"),
                    ChildRef("tickets", "gemeldet_von"),
                    ChildRef("tickets", "geschlossen_von"),
                    ChildRef("tickets", "zugewiesen_an"),
                    ChildRef("tresor_zugriff_log", "user_id"),
                    ChildRef("tuer_app_berechtigung", "erteilt_von"),
                    ChildRef("tuer_app_berechtigung", "user_id"),
                    ChildRef("tuer_berechtigung", "erteilt_von"),
                    ChildRef("tuer_zutritt_log", "user_id"),
                    ChildRef("user_permissions", "user_id"),
                    ChildRef("user_sessions", "user_id"),
                )),
)


def _ab_jahresende(spalte: str) -> str:
    """Datums-Ausdruck, der die Frist erst am JAHRESENDE des Belegdatums starten lässt.

    Aufbewahrungsfristen laufen ab Schluss des Kalenderjahres, in dem der Beleg entstand –
    ein Beleg vom 04.03.2015 ist also wie einer vom 31.12.2015 zu behandeln. Genau das
    tut der Ausdruck: er ersetzt das Datum durch den Silvestertag seines Jahres.

    ``NULLIF(..., '')`` ist hier kein Beiwerk, sondern die Sicherung: ohne sie ergäbe eine
    leere Datumsspalte den Text ``-12-31``, der vor jedem Stichtag liegt – ein undatierter
    Beleg würde sofort archiviert. Mit NULLIF wird der ganze Ausdruck NULL und damit nie
    fällig.
    """
    return f"(NULLIF(LEFT({spalte}::text, 4), '') || '-12-31')"


# Alters-Archivierung (siehe ArchiveRule): fällige Datensätze wandern in den Papierkorb;
# ihre Kinder werden mit-soft-gelöscht (Blatt zuerst). Das endgültige Entfernen erledigt
# danach der reguläre Prune (PRUNE_REGISTRY). Die passenden PruneEntity-Einträge (termin,
# termin_zusage) existieren bereits – hier wird nur der Eintritt in den Papierkorb datiert.
ARCHIVE_REGISTRY: tuple[ArchiveRule, ...] = (
    # clubdeckel_buchung steht hier bewusst NICHT als Kind: Archivieren heißt
    # Mit-Soft-Löschen, und eine Getränkebuchung darf nicht verschwinden, weil der
    # Termin alt geworden ist – sie gehört ins Ledger, nicht zum Terminkalender. Der
    # Termin bleibt dann eben im Papierkorb liegen (ChildRef in PRUNE_REGISTRY), bis
    # auch die Buchung regulär geprunt ist.
    ArchiveRule(
        TERMIN_ALTER, "Vergangene Termine", "termine",
        date_expr="COALESCE(NULLIF(ende, ''), beginn)",
        default_days=DEFAULT_TERMIN_ALTER_RETENTION_DAYS,
        children=(
            ChildRef("termin_zusage", "termin_id"),
            ChildRef("termin_abweichung", "termin_id"),
        ),
    ),
    # Abgeschlossene Tickets: nur erledigt/abgelehnt sind fällig (CASE liefert sonst NULL →
    # nie fällig), datiert über den Abschlusszeitpunkt (geschlossen_am, sonst updated_at).
    # Kinder werden mit-archiviert, damit der reguläre Prune das Ticket später (kinderlos,
    # Tor 4) hart löschen kann. ticket_anhaenge hat kein version → has_version=False.
    ArchiveRule(
        TICKET_ABGESCHLOSSEN_ALTER, "Abgeschlossene Tickets", "tickets",
        date_expr="CASE WHEN status IN ('erledigt','abgelehnt') "
                  "THEN COALESCE(NULLIF(geschlossen_am, ''), updated_at::text) END",
        default_days=DEFAULT_TICKET_ABGESCHLOSSEN_RETENTION_DAYS,
        children=(
            ChildRef("ticket_kommentare", "ticket_id"),
            ChildRef("ticket_teilnehmer", "ticket_id"),
            ChildRef("ticket_anhaenge", "ticket_id", has_version=False),
        ),
    ),

    # --- Finanzdaten: 10 Jahre ab Jahresende des Belegdatums ---
    # Jede Regel datiert über ihren eigenen Beleg, nicht über den Kopfsatz: eine
    # Sollstellung hängt zwar an einer Regel, ist aber selbst der aufbewahrungspflichtige
    # Posten. Stammdaten (Kassen, Gebühren, Beitragsregeln, Kategorien) haben bewusst
    # KEINE Regel – die altern nicht, die werden von Hand gelöscht und laufen dann über
    # das Standard-Fenster.
    # Als einzige Regel mit Saldovortrag: Der Kassenbestand ist die Summe über die
    # AKTIVEN Buchungen, ein Archivieren würde ihn also um die Summe der archivierten
    # Zeilen verschieben (#189). Die wandert deshalb vorher in den Anfangsbestand.
    ArchiveRule(
        "kassenbuchung_alter", "Kassenbuchungen (Aufbewahrung)", "kassenbuchungen",
        date_expr=_ab_jahresende("buchungsdatum"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
        children=(
            ChildRef("kassen_zaehlungen", "buchung_id"),
            ChildRef("kassen_zaehlungen", "ausloesende_buchung_id"),
            ChildRef("kassenbuchung_anhaenge", "buchung_id", has_version=False),
        ),
        vortrag=SaldoVortrag(
            ziel_table="kassen", ziel_fk="kasse_id", ziel_col="anfangsbestand_cent",
            betrag_expr="COALESCE(einnahme_cent, 0) - COALESCE(ausgabe_cent, 0)",
            stichtag_col="anfangsbestand_ab", stichtag_expr="buchungsdatum",
        ),
    ),
    ArchiveRule(
        "beitrag_sollstellung_alter", "Beitrags-Sollstellungen (Aufbewahrung)",
        "beitrag_sollstellung",
        date_expr=_ab_jahresende("faelligkeitsdatum"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
    ),
    ArchiveRule(
        "gebuehr_forderung_alter", "Gebühren-Forderungen (Aufbewahrung)", "gebuehr_forderung",
        date_expr=_ab_jahresende("datum"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
    ),
    ArchiveRule(
        "rechnung_alter", "Rechnungen (Aufbewahrung)", "rechnung",
        date_expr=_ab_jahresende("rechnungsdatum"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
        children=(ChildRef("rechnung_anhaenge", "rechnung_id", has_version=False),),
    ),
    ArchiveRule(
        "sepa_lauf_alter", "SEPA-Einzugsläufe (Aufbewahrung)", "sepa_lauf",
        date_expr=_ab_jahresende("ausfuehrungsdatum"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
        children=(ChildRef("sepa_lauf_position", "sepa_lauf_id"),),
    ),
    ArchiveRule(
        "kassenbuch_export_alter", "Kassenbuch-Exporte (Aufbewahrung)", "kassenbuch_exporte",
        date_expr=_ab_jahresende("exportiert_am"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
    ),
    ArchiveRule(
        "fibu_export_alter", "Fibu-Exporte (Aufbewahrung)", "fibu_exporte",
        date_expr=_ab_jahresende("exportiert_am"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
    ),
    ArchiveRule(
        "rechnung_export_alter", "Rechnungs-Exporte (Aufbewahrung)", "rechnung_exporte",
        date_expr=_ab_jahresende("exportiert_am"),
        default_days=DEFAULT_FINANZ_RETENTION_DAYS,
    ),

    # --- Ausgeschiedene Mitglieder ---
    # Nur wer ein Austrittsdatum trägt, altert überhaupt (sonst NULL → nie fällig). Die
    # Kinder sind die Mitgliedschafts-Artefakte; die Finanz-Kinder bleiben bewusst außen
    # vor, die haben ihre eigene, gleich lange Uhr und werden nicht vorzeitig entwertet.
    ArchiveRule(
        "mitglied_austritt_alter", "Ausgeschiedene Mitglieder", "mitglied",
        date_expr=_ab_jahresende("NULLIF(austrittsdatum, '')"),
        default_days=DEFAULT_MITGLIED_AUSTRITT_RETENTION_DAYS,
        children=(
            ChildRef("mitglied_kontakt", "mitglied_id"),
            ChildRef("mitglied_abteilung", "mitglied_id"),
            ChildRef("mitglied_funktion", "mitglied_id"),
            ChildRef("mitglied_mannschaft", "mitglied_id"),
            ChildRef("termin_zusage", "mitglied_id"),
            ChildRef("schluessel_chip", "mitglied_id"),
            ChildRef("clubdeckel_berechtigung", "mitglied_id"),
            ChildRef("clubdeckel_beitrag_befreiung", "mitglied_id"),
            ChildRef("clubdeckel_event_opt_out", "mitglied_id"),
        ),
    ),
)


# Protokolle und Gerätebindungen (siehe LogRule): Hard-Delete nach Alter, kein Papierkorb.
#
# `access_log` ist nach Kategorie aufgeteilt, weil Seitenaufrufe (Bewegungsrauschen) ein
# anderes Fenster verdienen als Login-Versuche. Die letzte Regel ist bewusst ein
# Auffangbecken über alle ÜBRIGEN Kategorien: so bekommt auch eine künftig neu
# eingeführte Kategorie automatisch eine Frist, statt still liegen zu bleiben.
LOG_REGISTRY: tuple[LogRule, ...] = (
    LogRule(ACCESS_LOG_PAGE, "Seitenaufrufe (Protokoll)", "access_log",
            where="category = 'page'", default_days=DEFAULT_PAGE_VIEW_RETENTION_DAYS),
    LogRule("access_log_auth", "Anmelde-Ereignisse (Protokoll)", "access_log",
            where="category = 'auth'"),
    LogRule("access_log_schliessanlage", "Schließanlagen-Ereignisse (Protokoll)", "access_log",
            where="category = 'schliessanlage'"),
    LogRule("access_log_uebrige", "Übrige Protokoll-Ereignisse", "access_log",
            where="category NOT IN ('page', 'auth', 'schliessanlage')"),
    LogRule(TICKET_ZUGRIFF_LOG, "Ticket-Sichten (Gesehen)", "ticket_zugriff_log",
            default_days=DEFAULT_TICKET_VIEW_RETENTION_DAYS),
    LogRule("tuer_zutritt_log", "Tür-Zutritte (Protokoll)", "tuer_zutritt_log"),
    LogRule("tresor_zugriff_log", "Tresor-Zugriffe (Protokoll)", "tresor_zugriff_log"),
    LogRule("tuer_schloss_status_log", "Schloss-Status (Technik)", "tuer_schloss_status_log",
            default_days=DEFAULT_TECHNIK_LOG_RETENTION_DAYS),
    # Die History des Spielplan-Imports ist faktisch ein Protokoll: je Import eine
    # Zeile, nie ein Soft-Delete. Frist läuft ab `importiert_am` – `created_at` trägt
    # in jeder Version den Zeitpunkt der ERSTEN Zeile und wäre als Alter untauglich.
    LogRule("dfbnet_import_stand_history", "Spielplan-Importe (Protokoll)",
            "dfbnet_import_stand_history", ts_expr="importiert_am"),

    # --- Gerätebindungen: Frist läuft ab dem Tod der Zeile, nicht ab Anlage ---
    # Für diese drei gab es die Cleanup-Methoden schon lange (cleanup_expired /
    # cleanup_revoked / cleanup_expired_tokens) – sie wurden nur nie aufgerufen. Jetzt
    # laufen sie über dieselbe Registry wie alles andere und sind einstellbar.
    LogRule("user_sessions", "Abgelaufene Sitzungen", "user_sessions",
            ts_expr="COALESCE(NULLIF(revoked_at, ''), NULLIF(expires_at, ''))",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),
    LogRule("user_sessions_history", "Sitzungs-Historie", "user_sessions_history",
            ts_expr="COALESCE(NULLIF(revoked_at, ''), NULLIF(expires_at, ''))",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),
    LogRule("auth_tokens", "Verbrauchte Anmelde-Token", "auth_tokens",
            ts_expr="COALESCE(NULLIF(used_at, ''), NULLIF(expires_at, ''))",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),
    LogRule("auth_tokens_history", "Token-Historie", "auth_tokens_history",
            ts_expr="COALESCE(NULLIF(used_at, ''), NULLIF(expires_at, ''))",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),
    # Aktive Abos haben kein revoked_at -> ts_expr NULL -> nie fällig.
    LogRule("push_subscriptions", "Widerrufene Push-Abos", "push_subscriptions",
            ts_expr="NULLIF(revoked_at, '')",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),
    LogRule("push_subscriptions_history", "Push-Abo-Historie", "push_subscriptions_history",
            ts_expr="NULLIF(revoked_at, '')",
            default_days=DEFAULT_GERAET_NACHLAUF_DAYS, gruppe="Gerätebindungen"),

    # --- Historie von Einstellungs-Singletons ---
    # Die Einstellungen selbst sind je eine einzige Zeile, die nie gelöscht wird; nur ihre
    # Änderungs-Historie wächst. Ohne Eltern-PruneEntity gibt es dafür keinen Tor-5-Bezug,
    # also läuft sie schlicht nach Alter ab.
    LogRule("beitrag_einstellungen_history", "Beitrags-Einstellungen (Historie)",
            "beitrag_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
    LogRule("fibu_einstellungen_history", "Fibu-Einstellungen (Historie)",
            "fibu_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
    LogRule("prune_einstellungen_history", "Bereinigungs-Einstellungen (Historie)",
            "prune_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
    LogRule("schliessanlage_einstellungen_history", "Schließanlagen-Einstellungen (Historie)",
            "schliessanlage_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
    LogRule("ticket_erinnerung_einstellungen_history", "Ticket-Erinnerungen (Historie)",
            "ticket_erinnerung_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
    LogRule("termin_erinnerung_einstellungen_history", "Termin-Erinnerungen (Historie)",
            "termin_erinnerung_einstellungen_history",
            ts_expr="COALESCE(updated_at, created_at)", gruppe="Einstellungs-Historie"),
)

LOG_BY_NAME: dict[str, LogRule] = {r.name: r for r in LOG_REGISTRY}


# --- Reine SQL-Bausteine (ohne DB testbar) ----------------------------------------
# Hilfsausdruck: deleted_at/created_at-Spalten sind teils TEXT (ISO-Strings), teils
# TIMESTAMP. Erst nach ::text casten – dann ist NULLIF(...,'') für beide Typen gültig
# (bei TIMESTAMP gäbe der direkte Vergleich mit '' einen Cast-Fehler) – und zurück nach
# timestamptz. Leere Strings (TEXT) werden zu NULL.
def _ts(col: str) -> str:
    return f"NULLIF({col}::text, '')::timestamptz"


# Zeitspalten einer History-Zeile in absteigender Aussagekraft: Lösch- vor Änderungs-
# vor Anlagezeit. Nicht jede History führt alle drei – die Export-Köpfe (fibu_exporte,
# kassenbuch_exporte, rechnung_exporte) kennen kein `updated_at`, weil ein Export nie
# geändert, sondern nur angelegt und beim Un-Export gelöscht wird. Der Service reicht
# deshalb die tatsächlich vorhandenen Spalten herein; die Reihenfolge bleibt.
HISTORY_TS_COLS: tuple[str, ...] = ("deleted_at", "updated_at", "created_at")


def _history_effective_ts(prefix: str = "",
                          cols: tuple[str, ...] = HISTORY_TS_COLS) -> str:
    """Effektiver Zeitstempel einer History-Zeile: Lösch- vor Änderungs- vor Anlagezeit."""
    p = f"{prefix}." if prefix else ""
    return f"COALESCE({', '.join(_ts(p + c) for c in cols)})"


def build_papierkorb_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Gesamtzahl im Papierkorb (soft-deleted) – Kontext für den Report."""
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.table} "
        f"WHERE deleted_at IS NOT NULL AND deleted_at::text <> ''"
    )
    return sql, []


def build_active_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Zahl der aktiven (nicht gelöschten) Einträge – reines Mengengefühl, wird nie geprunt."""
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.table} "
        f"WHERE deleted_at IS NULL OR deleted_at::text = ''"
    )
    return sql, []


def build_original_candidate_ids_sql(
    entity: PruneEntity,
    retention_days: int,
    keep_min: int,
    history_retention_days: int,
    history_ts_cols: tuple[str, ...] = HISTORY_TS_COLS,
    parent_hold_days: int = 0,
) -> tuple[str, list]:
    """SELECT der IDs aller endgültig löschbaren Original-Datensätze (alle 6 Tore).

    Einzige Quelle der Tor-Logik – COUNT (Report) und DELETE (Prune) bauen beide darauf
    auf, damit „Vorschau = Aktion" garantiert ist. Tunables werden explizit übergeben;
    ``parent_hold_days`` ist das Fenster des Eltern-Datensatzes und nur bei Entitäten
    mit ``parent`` (Tor 6) von Bedeutung.
    """
    params: list = []
    where = [
        f"r.del < now() - make_interval(days => %s)",   # Tor 2: Datum
        "r.rn > %s",                                      # Tor 3: Mindestanzahl
    ]
    params.append(retention_days)
    params.append(keep_min)

    for child in entity.children:                         # Tor 4: keine Kind-Referenz
        if child.parent_col == "id":
            cond = "c.{fk} = r.id".format(fk=child.fk)
        else:                                             # Bezug über andere Eltern-Spalte
            cond = (
                f"c.{child.fk} = (SELECT p.{child.parent_col} "
                f"FROM {entity.table} p WHERE p.id = r.id)"
            )
        where.append(f"NOT EXISTS (SELECT 1 FROM {child.table} c WHERE {cond})")

    if entity.history_table:                              # Tor 5: history-frei
        where.append(
            f"NOT EXISTS (SELECT 1 FROM {entity.history_table} h "
            f"WHERE h.{entity.history_id_col} = r.id "
            f"AND {_history_effective_ts('h', history_ts_cols)} >= now() - make_interval(days => %s))"
        )
        params.append(history_retention_days)

    if entity.parent:                                     # Tor 6: Eltern-Datensatz wartet
        # Greift nur, solange der Eltern-Datensatz IM PAPIERKORB liegt und seine eigene
        # Frist läuft. Ein aktiver Eltern-Datensatz hält nichts fest (eigenständig
        # gelöschtes Kind), ein bereits entfernter erst recht nicht – deshalb keine
        # Verklemmung mit Tor 4.
        p = entity.parent
        where.append(
            f"NOT EXISTS (SELECT 1 FROM {p.table} p "
            f"WHERE p.id = (SELECT ch.{p.fk} FROM {entity.table} ch WHERE ch.id = r.id) "
            f"AND p.deleted_at IS NOT NULL AND p.deleted_at::text <> '' "
            f"AND {_ts('p.deleted_at')} >= now() - make_interval(days => %s))"
        )
        params.append(parent_hold_days)

    sql = (
        "WITH ranked AS ("
        f"  SELECT id, {_ts('deleted_at')} AS del, "
        f"         ROW_NUMBER() OVER (ORDER BY {_ts('deleted_at')} DESC NULLS LAST, id DESC) AS rn "
        f"  FROM {entity.table} "
        "   WHERE deleted_at IS NOT NULL AND deleted_at::text <> '' "
        ") "
        "SELECT r.id FROM ranked r WHERE " + " AND ".join(where)
    )
    return sql, params


def build_original_candidate_count_sql(
    entity: PruneEntity,
    retention_days: int,
    keep_min: int,
    history_retention_days: int,
    history_ts_cols: tuple[str, ...] = HISTORY_TS_COLS,
    parent_hold_days: int = 0,
) -> tuple[str, list]:
    """Zahl der endgültig löschbaren Original-Datensätze (zählt das ID-SELECT)."""
    ids_sql, params = build_original_candidate_ids_sql(
        entity, retention_days, keep_min, history_retention_days, history_ts_cols,
        parent_hold_days,
    )
    return f"SELECT COUNT(*) AS n FROM ({ids_sql}) c", params


def build_history_prune_count_sql(
    entity: PruneEntity, history_ts_cols: tuple[str, ...] = HISTORY_TS_COLS
) -> tuple[str, list]:
    """Zahl der History-Zeilen, die das (vorgelagerte) History-Prune entfernen würde.

    Datums-only und ohne Mindestanzahl: die History muss vollständig abfließen können,
    sonst würde das zugehörige Original nie history-frei (Tor 5).
    """
    assert entity.history_table is not None
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.history_table} "
        f"WHERE {_history_effective_ts('', history_ts_cols)} < now() - make_interval(days => %s)"
    )
    return sql, []  # history_retention_days wird vom Service als Param ergänzt


def build_history_total_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Gesamtzahl der aktuell vorhandenen History-Zeilen (Kontext für den Report)."""
    assert entity.history_table is not None
    return f"SELECT COUNT(*) AS n FROM {entity.history_table}", []


def build_history_prune_delete_sql(
    entity: PruneEntity, history_ts_cols: tuple[str, ...] = HISTORY_TS_COLS
) -> tuple[str, list]:
    """DELETE der abgeflossenen History-Zeilen – gleiche WHERE-Logik wie der Zähler."""
    assert entity.history_table is not None
    sql = (
        f"DELETE FROM {entity.history_table} "
        f"WHERE {_history_effective_ts('', history_ts_cols)} < now() - make_interval(days => %s)"
    )
    return sql, []  # history_retention_days wird vom Service als Param ergänzt


# --- Protokolle & Gerätebindungen (LogRule) ---------------------------------------
# Alle drei Bausteine teilen sich dieselbe WHERE-Klausel, damit „Vorschau = Aktion" auch
# hier gilt: gezählt wird exakt das, was gelöscht wird. Der Alters-Parameter (%s, Tage)
# ist immer der letzte.
def _log_faellig_where(rule: LogRule) -> str:
    bedingung = f"{_ts('(' + rule.ts_expr + ')')} < now() - make_interval(days => %s)"
    return f"{rule.where} AND {bedingung}" if rule.where else bedingung


def build_log_total_sql(rule: LogRule) -> str:
    """Gesamtzahl der Zeilen im Bereich – Mengengefühl für den Report (ohne Alters-Param)."""
    where = f" WHERE {rule.where}" if rule.where else ""
    return f"SELECT COUNT(*) AS n FROM {rule.table}{where}"


def build_log_due_count_sql(rule: LogRule) -> str:
    """Zahl der fälligen (löschbaren) Zeilen. Param: Alter in Tagen."""
    return f"SELECT COUNT(*) AS n FROM {rule.table} WHERE {_log_faellig_where(rule)}"


def build_log_delete_sql(rule: LogRule) -> str:
    """Hard-Delete der fälligen Zeilen. Param: Alter in Tagen."""
    return f"DELETE FROM {rule.table} WHERE {_log_faellig_where(rule)}"


# --- Alters-Archivierung (ArchiveRule) --------------------------------------------
# Alle Bausteine erwarten den Stichtag (ISO-Datum 'YYYY-MM-DD') als %s-Parameter; ein
# Datensatz ist fällig, wenn sein Datumsanteil VOR dem Stichtag liegt und er noch aktiv
# ist. Datums-only (kein keep_min/History) – die Rückholung sichert danach der Papierkorb.
def _archive_faellig_where(rule: ArchiveRule) -> str:
    return f"deleted_at IS NULL AND LEFT(({rule.date_expr})::text, 10) < %s"


def build_archive_count_sql(rule: ArchiveRule) -> str:
    """Zahl der aktuell fälligen (zu archivierenden) Datensätze. Param: Stichtag."""
    return f"SELECT COUNT(*) AS n FROM {rule.table} WHERE {_archive_faellig_where(rule)}"


def build_archive_active_sql(rule: ArchiveRule) -> str:
    """Zahl der aktiven Datensätze insgesamt (Mengengefühl für den Report)."""
    return f"SELECT COUNT(*) AS n FROM {rule.table} WHERE deleted_at IS NULL"


def build_archive_parent_delete_sql(rule: ArchiveRule) -> str:
    """Soft-Delete der fälligen Datensätze (version-Bump → Audit-History).
    Params: deleted_by, Stichtag."""
    return (
        f"UPDATE {rule.table} SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
        f"version = version + 1 WHERE {_archive_faellig_where(rule)}"
    )


def build_archive_child_delete_sql(rule: ArchiveRule, child: ChildRef) -> str:
    """Soft-Delete der aktiven Kinder fälliger Datensätze (VOR dem Eltern-Soft-Delete).
    Params: deleted_by, Stichtag. Tabellen ohne version/History (``has_version=False``)
    bekommen kein version-Bump (sonst SQL-Fehler auf der fehlenden Spalte)."""
    set_clause = "deleted_at = CURRENT_TIMESTAMP, deleted_by = %s"
    if child.has_version:
        set_clause += ", version = version + 1"
    return (
        f"UPDATE {child.table} SET {set_clause} "
        f"WHERE deleted_at IS NULL AND {child.fk} IN ("
        f"SELECT {child.parent_col} FROM {rule.table} WHERE {_archive_faellig_where(rule)})"
    )


def build_archive_vortrag_sum_sql(rule: ArchiveRule) -> str:
    """Summe (vorzeichenbehaftet), die der nächste Lauf vortragen würde. Param: Stichtag.

    Für den Report – zeigt dem Admin, um welchen Betrag sich der Anker verschiebt,
    bevor er den Lauf auslöst.
    """
    v = rule.vortrag
    return (
        f"SELECT COALESCE(SUM({v.betrag_expr}), 0) AS n FROM {rule.table} "
        f"WHERE {_archive_faellig_where(rule)}"
    )


def build_archive_vortrag_update_sql(rule: ArchiveRule) -> str:
    """Trägt die Summe der fälligen Zeilen auf den Anker am Eltern-Datensatz vor.

    Muss VOR dem Soft-Delete laufen: ``_archive_faellig_where`` wählt aktive Zeilen,
    nach dem Archivieren fände die Summe nichts mehr. Der ``version``-Bump ist Absicht
    – so landet die Verschiebung samt altem Wert im Audit-Trail des Eltern-Datensatzes
    und ist später nachvollziehbar.

    Benannte Parameter (``actor``, ``stichtag``), weil der Stichtag zweimal vorkommt.
    """
    v = rule.vortrag
    stichtag_select = (
        f", (MAX(LEFT(({v.stichtag_expr})::text, 10))::date + 1)::text AS stichtag"
        if v.stichtag_col else ""
    )
    # GREATEST statt schlichter Zuweisung: Eine nachträglich rückdatierte Zeile darf den
    # Stichtag nicht wieder nach hinten ziehen. (PostgreSQL ignoriert NULL in GREATEST,
    # der erste Vortrag setzt den Wert also sauber.)
    stichtag_set = (
        f"{v.stichtag_col} = GREATEST(z.{v.stichtag_col}, q.stichtag),\n            "
        if v.stichtag_col else ""
    )
    return f"""
        UPDATE {v.ziel_table} z
        SET {v.ziel_col} = z.{v.ziel_col} + q.summe,
            {stichtag_set}version = z.version + 1,
            updated_at = CURRENT_TIMESTAMP,
            updated_by = %(actor)s
        FROM (
            SELECT {v.ziel_fk} AS ziel_id, SUM({v.betrag_expr}) AS summe{stichtag_select}
            FROM {rule.table}
            WHERE deleted_at IS NULL
              AND LEFT(({rule.date_expr})::text, 10) < %(stichtag)s
            GROUP BY {v.ziel_fk}
        ) q
        WHERE z.id = q.ziel_id
    """


class PruneService:
    """Orchestriert die Prune-Registry. Phase 0: ausschließlich Dry-Run-Report.

    Tunables (Tage/Anzahl/History-Tage) sind pro Entität einstellbar: gespeicherte
    Overrides (``prune_einstellungen``) überschreiben die Code-Defaults der Registry.
    """

    def __init__(self, db):
        self._db = db
        self._history_cols_cache: Optional[dict[str, tuple[str, ...]]] = None

    def _history_ts_cols(self, entity: PruneEntity) -> tuple[str, ...]:
        """Welche der drei Zeitspalten führt die History dieser Entität wirklich?

        Einmal pro Service-Instanz aus dem Schema gelesen, statt sie an der Registry zu
        pflegen: eine gepflegte Liste wäre eine zweite Wahrheit neben dem Schema und
        würde beim nächsten `_DDL_*` still falsch werden.
        """
        if self._history_cols_cache is None:
            with self._db.cursor() as cur:
                cur.execute(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = ANY(%s)",
                    (list(HISTORY_TS_COLS),),
                )
                vorhanden: dict[str, set] = {}
                for row in cur.fetchall():
                    vorhanden.setdefault(row["table_name"], set()).add(row["column_name"])
            self._history_cols_cache = {
                t: tuple(c for c in HISTORY_TS_COLS if c in cols)
                for t, cols in vorhanden.items()
            }
        if not entity.history_table:
            return HISTORY_TS_COLS
        return self._history_cols_cache.get(entity.history_table) or HISTORY_TS_COLS

    def _count(self, sql: str, params: list) -> int:
        with self._db.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    @staticmethod
    def _parent_hold_days(entity: PruneEntity, cfg: dict[str, dict]) -> int:
        """Wie lange Tor 6 ein Blatt an seinem Eltern-Datensatz festhält.

        Maßstab ist das *wirksame* Fenster des Eltern-Datensatzes – Papierkorb-Frist bzw.
        History-Fenster, je nachdem was länger bindet. Bewusst aus der Konfiguration
        gelesen statt als Konstante: Wer die Frist der Buchung verkürzt, verkürzt damit
        auch die Wartezeit ihres Belegs, sonst liefen die beiden wieder auseinander.
        """
        if not entity.parent:
            return 0
        c = cfg[entity.parent.entity]
        eltern = next(e for e in PRUNE_REGISTRY if e.name == entity.parent.entity)
        tage = c["retention_days"]
        if eltern.history_table:
            tage = max(tage, c["history_retention_days"])
        return tage

    def effective_config(self) -> dict[str, dict]:
        """Wirksame Tunables je Entität: Override (falls gesetzt) sonst Code-Default."""
        overrides = self._db.prune_einstellungen.get_all()
        result: dict[str, dict] = {}
        for entity in PRUNE_REGISTRY:
            o = overrides.get(entity.name, {})
            result[entity.name] = {
                "retention_days": o.get("retention_days", entity.retention_days),
                "keep_min": o.get("keep_min", entity.keep_min),
                "history_retention_days": o.get(
                    "history_retention_days", entity.history_retention_days
                ),
                "is_override": entity.name in overrides,
            }
        return result

    def log_retention(self, rule: LogRule) -> tuple[int, bool]:
        """Wirksames Alters-Fenster (Tage) einer LogRule + ob ein Override gesetzt ist."""
        o = self._db.prune_einstellungen.get_all().get(rule.name)
        if o:
            return o["retention_days"], True
        return rule.default_days, False

    def page_view_retention(self) -> tuple[int, bool]:
        """Aufbewahrung der Protokoll-Seitenaufrufe in Tagen (Bequemlichkeits-Zugriff)."""
        return self.log_retention(LOG_BY_NAME[ACCESS_LOG_PAGE])

    def ticket_view_retention(self) -> tuple[int, bool]:
        """Aufbewahrung des Ticket-„Gesehen"-Logs in Tagen (Bequemlichkeits-Zugriff)."""
        return self.log_retention(LOG_BY_NAME[TICKET_ZUGRIFF_LOG])

    # --- Verwaiste Anhang-Dateien ------------------------------------------------
    def datei_retention(self) -> tuple[int, bool]:
        """Schonfrist für verwaiste Dateien in Tagen + ob ein Override gesetzt ist."""
        o = self._db.prune_einstellungen.get_all().get(DATEI_VERWAIST)
        if o:
            return o["retention_days"], True
        return DEFAULT_VERWAISTE_DATEI_RETENTION_DAYS, False

    def _bekannte_dateinamen(self) -> set[str]:
        """Alle Dateinamen, die irgendeine DB-Zeile beansprucht – inklusive der
        soft-gelöschten. Ein Anhang im Papierkorb ist wiederherstellbar, seine Datei
        gehört also nicht zu den Verwaisten."""
        namen: set[str] = set()
        with self._db.cursor() as cur:
            for entity in PRUNE_REGISTRY:
                if not entity.stored_name_col:
                    continue
                cur.execute(
                    f"SELECT {entity.stored_name_col} AS sn FROM {entity.table} "
                    f"WHERE {entity.stored_name_col} IS NOT NULL"
                )
                namen.update(r["sn"] for r in cur.fetchall())
        return namen

    def verwaiste_dateien(self, days: Optional[int] = None) -> list:
        """Dateien im Upload-Verzeichnis, die keine DB-Zeile kennt und die älter als die
        Schonfrist sind. Gibt ``Path``-Objekte zurück (Reihenfolge: Name).

        Maßstab ist die Änderungszeit der Datei: sie ist der einzige Zeitstempel, den ein
        verwaistes Fragment überhaupt noch hat – eine DB-Zeile mit ``created_at`` gibt es
        ja gerade nicht.
        """
        if days is None:
            days, _ = self.datei_retention()
        dienst = self._db.anhang_service
        verzeichnis = dienst.upload_path
        if not verzeichnis.is_dir():
            return []
        bekannt = self._bekannte_dateinamen()
        grenze = datetime.now(timezone.utc).timestamp() - days * 86400
        treffer = []
        for pfad in sorted(verzeichnis.iterdir()):
            if not pfad.is_file() or pfad.name in bekannt:
                continue
            if pfad.stat().st_mtime < grenze:
                treffer.append(pfad)
        return treffer

    def _datei_report_row(self) -> dict:
        """Sonder-Bereich „Verwaiste Dateien": kein DB-Bereich, sondern das Upload-Verzeichnis."""
        days, is_override = self.datei_retention()
        dienst = self._db.anhang_service
        verzeichnis = dienst.upload_path
        gesamt = sum(1 for p in verzeichnis.iterdir() if p.is_file()) \
            if verzeichnis.is_dir() else 0
        return {
            "name": DATEI_VERWAIST,
            "label": "Verwaiste Dateien (Upload-Verzeichnis)",
            "table": str(verzeichnis),
            "gruppe": "Dateien",
            "soft_delete": False,
            "retention_days": days,
            "keep_min": None,
            "history_retention_days": None,
            "is_override": is_override,
            "eintraege": gesamt,
            "im_papierkorb": None,
            "loeschbar": len(self.verwaiste_dateien(days)),
            "history_table": None,
            "history_gesamt": None,
            "history_loeschbar": None,
        }

    def _log_report_row(self, rule: LogRule) -> dict:
        """Report-Zeile eines Protokoll-/Gerätebereichs: Hard-Delete nach Alter, kein Papierkorb."""
        days, is_override = self.log_retention(rule)
        return {
            "name": rule.name,
            "label": rule.label,
            "table": rule.table,
            "gruppe": rule.gruppe,
            "soft_delete": False,            # kein Papierkorb/keep_min/History
            "retention_days": days,
            "keep_min": None,
            "history_retention_days": None,
            "is_override": is_override,
            "eintraege": self._count(build_log_total_sql(rule), []),
            "im_papierkorb": None,
            "loeschbar": self._count(build_log_due_count_sql(rule), [days]),
            "history_table": None,
            "history_gesamt": None,
            "history_loeschbar": None,
        }

    def archive_retention(self, rule: ArchiveRule) -> tuple[int, bool]:
        """Wirksames Alters-Fenster (Tage) einer ArchiveRule + ob ein Override gesetzt ist."""
        o = self._db.prune_einstellungen.get_all().get(rule.name)
        if o:
            return o["retention_days"], True
        return rule.default_days, False

    def _archive_report_row(self, rule: ArchiveRule) -> dict:
        """Report-Zeile einer Alters-Archivierung: ``archivierbar`` = fällige Datensätze,
        die der nächste Lauf in den Papierkorb verschiebt (reversibel, KEIN Hard-Delete –
        daher ``loeschbar = 0`` und nicht in ``summe_loeschbar``).

        ``vortrag_cent`` ist der Betrag, den der Lauf auf den Anker vorträgt (None ohne
        ``SaldoVortrag``) – damit der Admin die Verschiebung vor dem Auslösen sieht."""
        days, is_override = self.archive_retention(rule)
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        vortrag = (self._count(build_archive_vortrag_sum_sql(rule), [cutoff])
                   if rule.vortrag else None)
        return {
            "name": rule.name,
            "label": rule.label,
            "table": rule.table,
            "gruppe": "Aufbewahrungsfristen",
            "soft_delete": False,            # kein Papierkorb-Ausgangspunkt/keep_min/History
            "retention_days": days,          # hier: Alters-Fenster in Tagen
            "keep_min": None,
            "history_retention_days": None,
            "is_override": is_override,
            "eintraege": self._count(build_archive_active_sql(rule), []),
            "im_papierkorb": None,
            "loeschbar": 0,
            "archivierbar": self._count(build_archive_count_sql(rule), [cutoff]),
            "archiviert_statt_geloescht": True,
            "vortrag_cent": vortrag,
            "history_table": None,
            "history_gesamt": None,
            "history_loeschbar": None,
        }

    def einstellungen(self) -> list[dict]:
        """Konfigurations-Sicht für die Admin-UI: Struktur + wirksame Tunables je Entität."""
        cfg = self.effective_config()
        rows = [
            {
                "name": e.name,
                "label": e.label,
                "table": e.table,
                "history_table": e.history_table,
                "gruppe": "Papierkorb",
                "soft_delete": True,
                **cfg[e.name],
            }
            for e in PRUNE_REGISTRY
        ]
        rows.extend(self._archive_report_row(r) for r in ARCHIVE_REGISTRY)
        rows.extend(self._log_report_row(r) for r in LOG_REGISTRY)
        rows.append(self._datei_report_row())
        return rows

    def report(self) -> dict:
        """Dry-Run: was *würde* ein vollständiger Prune-Lauf entfernen? Löscht NICHTS."""
        cfg = self.effective_config()
        entities: list[dict] = []
        summe_loeschbar = 0
        summe_history = 0
        summe_history_gesamt = 0

        for entity in PRUNE_REGISTRY:
            c = cfg[entity.name]
            pk_sql, pk_params = build_papierkorb_count_sql(entity)
            im_papierkorb = self._count(pk_sql, pk_params)
            akt_sql, akt_params = build_active_count_sql(entity)
            eintraege = self._count(akt_sql, akt_params)

            ts_cols = self._history_ts_cols(entity)
            cand_sql, cand_params = build_original_candidate_count_sql(
                entity, c["retention_days"], c["keep_min"], c["history_retention_days"],
                ts_cols, self._parent_hold_days(entity, cfg),
            )
            loeschbar = self._count(cand_sql, cand_params)

            history_loeschbar: Optional[int] = None
            history_gesamt: Optional[int] = None
            if entity.history_table:
                ht_sql, ht_params = build_history_total_count_sql(entity)
                history_gesamt = self._count(ht_sql, ht_params)
                h_sql, h_params = build_history_prune_count_sql(entity, ts_cols)
                history_loeschbar = self._count(h_sql, h_params + [c["history_retention_days"]])
                summe_history += history_loeschbar
                summe_history_gesamt += history_gesamt

            summe_loeschbar += loeschbar
            entities.append({
                "name": entity.name,
                "label": entity.label,
                "table": entity.table,
                "gruppe": "Papierkorb",
                "soft_delete": True,
                "retention_days": c["retention_days"],
                "keep_min": c["keep_min"],
                "history_retention_days": c["history_retention_days"],
                "is_override": c["is_override"],
                "eintraege": eintraege,
                "im_papierkorb": im_papierkorb,
                "loeschbar": loeschbar,
                "history_table": entity.history_table,
                "history_gesamt": history_gesamt,
                "history_loeschbar": history_loeschbar,
            })

        # Alters-Archivierung: fällige datierte Datensätze -> Papierkorb (reversibel,
        # separat von summe_loeschbar, da KEIN endgültiges Löschen).
        summe_archivierbar = 0
        for rule in ARCHIVE_REGISTRY:
            row = self._archive_report_row(rule)
            summe_archivierbar += row["archivierbar"]
            entities.append(row)

        # Sonder-Bereiche: Protokolle und Gerätebindungen (Hard-Delete nach Alter)
        for rule in LOG_REGISTRY:
            row = self._log_report_row(rule)
            summe_loeschbar += row["loeschbar"]
            entities.append(row)

        # Sonder-Bereich: verwaiste Dateien (zählt zu den Dateien, nicht zu den Zeilen)
        datei_row = self._datei_report_row()
        entities.append(datei_row)

        return {
            "dry_run": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "summe_loeschbar": summe_loeschbar,
            "summe_archivierbar": summe_archivierbar,
            "summe_history_loeschbar": summe_history,
            "summe_history_gesamt": summe_history_gesamt,
            "summe_verwaiste_dateien": datei_row["loeschbar"],
        }

    def prune(self, dry_run: bool = True) -> dict:
        """Führt die Bereinigung aus (oder zeigt sie als Dry-Run).

        ``dry_run=True`` liefert exakt den ``report()``. Bei ``dry_run=False`` wird in EINER
        Transaktion gelöscht – atomar, bei Fehler vollständiger Rollback. Reihenfolge:

          1. History zuerst (datums-only) – ändert keine der Original-Tore (Tor 5 prüft nur
             Zeilen NEUER als der History-Cutoff, die hier nicht angefasst werden).
          2. Kandidaten-IDs je Entität einmalig einsammeln (= Snapshot, = Report-Zahlen);
             bei Anhang-Entitäten zusätzlich die Datei-Namen der Kandidaten.
          3. Diese IDs Blatt→Wurzel löschen.
          4. NACH dem Commit die zugehörigen Dateien von der Platte entfernen (best-effort):
             eine verwaiste Datei ist der harmlosere Fehlerfall als eine fehlende Datei zu
             einer noch existierenden Zeile.

        Durch das Einsammeln VOR dem Löschen gilt „Vorschau = Aktion": es wird genau das
        entfernt, was der Report zeigte – ein in diesem Lauf kinderlos gewordenes Eltern-
        Element wird NICHT mitgerissen, sondern erst im nächsten Lauf entfernt.
        """
        if dry_run:
            return self.report()

        cfg = self.effective_config()
        entities: list[dict] = []
        summe_loeschbar = 0
        summe_history = 0
        # Datei-Namen je Entität, die nach erfolgreichem Commit von Platte sollen.
        dateien: dict[str, list] = {}

        # 0) Alters-Archivierung: fällige datierte Datensätze in den Papierkorb (soft-delete,
        #    Kinder zuerst). Eigene Transaktion – reversibel und unabhängig vom Hard-Delete.
        #    Frisch archivierte Zeilen (deleted_at = jetzt) sind für den folgenden Hard-Delete
        #    noch nicht alt genug, daher bleibt „Vorschau = Aktion" für das Löschen erhalten.
        archiv_entities: list[dict] = []
        summe_archiviert = 0
        for rule in ARCHIVE_REGISTRY:
            days, _ = self.archive_retention(rule)
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            vortrag_cent = None
            with self._db.cursor() as cur:
                # Saldovortrag ZUERST: Er summiert über die noch aktiven fälligen Zeilen,
                # nach dem Soft-Delete unten fände er nichts mehr (#189).
                if rule.vortrag:
                    # Auf DEMSELBEN Cursor: self._count() öffnet einen eigenen und würde
                    # per commit() die laufende Transaktion vorzeitig abschließen.
                    cur.execute(build_archive_vortrag_sum_sql(rule), (cutoff,))
                    zeile = cur.fetchone()
                    vortrag_cent = int(zeile["n"]) if zeile else 0
                    cur.execute(build_archive_vortrag_update_sql(rule),
                                {"actor": "SYSTEM-PRUNE", "stichtag": cutoff})
                for child in rule.children:
                    cur.execute(build_archive_child_delete_sql(rule, child),
                                ("SYSTEM-PRUNE", cutoff))
                cur.execute(build_archive_parent_delete_sql(rule), ("SYSTEM-PRUNE", cutoff))
                n = cur.rowcount
            summe_archiviert += n
            archiv_entities.append({
                "name": rule.name,
                "label": rule.label,
                "archiviert": n,
                "geloescht": 0,
                "history_geloescht": None,
                "dateien_geloescht": 0,
                "vortrag_cent": vortrag_cent,
            })

        with self._db.cursor() as cur:
            # 1) History prunen (datums-only)
            history_geloescht: dict[str, int] = {}
            for entity in PRUNE_REGISTRY:
                if entity.history_table:
                    hsql, hparams = build_history_prune_delete_sql(
                        entity, self._history_ts_cols(entity))
                    cur.execute(hsql, tuple(hparams + [cfg[entity.name]["history_retention_days"]]))
                    history_geloescht[entity.name] = cur.rowcount

            # 2) Kandidaten-IDs einsammeln (Snapshot vor jeglicher Original-Löschung)
            kandidaten: dict[str, list] = {}
            for entity in PRUNE_REGISTRY:
                c = cfg[entity.name]
                ids_sql, params = build_original_candidate_ids_sql(
                    entity, c["retention_days"], c["keep_min"], c["history_retention_days"],
                    self._history_ts_cols(entity), self._parent_hold_days(entity, cfg),
                )
                cur.execute(ids_sql, tuple(params))
                ids = [row["id"] for row in cur.fetchall()]
                kandidaten[entity.name] = ids
                # Datei-Namen der Kandidaten merken (vor dem Löschen lesbar)
                if entity.stored_name_col and ids:
                    cur.execute(
                        f"SELECT {entity.stored_name_col} AS sn FROM {entity.table} "
                        f"WHERE id = ANY(%s) AND {entity.stored_name_col} IS NOT NULL",
                        (ids,),
                    )
                    dateien[entity.name] = [r["sn"] for r in cur.fetchall()]

            # 3) Originale löschen – Blatt→Wurzel (Registry-Reihenfolge)
            for entity in PRUNE_REGISTRY:
                ids = kandidaten[entity.name]
                geloescht = 0
                if ids:
                    cur.execute(
                        f"DELETE FROM {entity.table} WHERE id = ANY(%s)", (ids,)
                    )
                    geloescht = cur.rowcount
                summe_loeschbar += geloescht
                hist = history_geloescht.get(entity.name)
                if hist is not None:
                    summe_history += hist
                entities.append({
                    "name": entity.name,
                    "label": entity.label,
                    "geloescht": geloescht,
                    "history_geloescht": hist,
                    "dateien_geloescht": 0,  # wird nach Commit gesetzt
                })

        # 4) Dateien NACH dem Commit löschen (best-effort, no-raise im AnhangService).
        summe_dateien = 0
        eintrag_by_name = {e["name"]: e for e in entities}
        for name, namen in dateien.items():
            anzahl = sum(1 for sn in namen if self._db.anhang_service.loesche(sn))
            eintrag_by_name[name]["dateien_geloescht"] = anzahl
            summe_dateien += anzahl

        # 5) Sonder-Bereiche: Protokolle und Gerätebindungen (Hard-Delete nach Alter).
        #    Je eigene Transaktion und bewusst NACH dem Original-Prune: ein Fehler hier
        #    darf den Papierkorb-Lauf nicht zurückrollen, und umgekehrt hängt kein
        #    Protokoll an den gelöschten Originalen (alle FK-frei bzw. Snapshot-Spalten).
        for rule in LOG_REGISTRY:
            days, _ = self.log_retention(rule)
            with self._db.cursor() as cur:
                cur.execute(build_log_delete_sql(rule), (days,))
                n = cur.rowcount
            summe_loeschbar += n
            entities.append({
                "name": rule.name,
                "label": rule.label,
                "geloescht": n,
                "history_geloescht": None,
                "dateien_geloescht": 0,
            })

        # 6) Verwaiste Dateien vom Upload-Verzeichnis entfernen. Ganz am Schluss und mit
        #    frisch gelesener Namensliste: die gerade geprunten Anhänge sind aus der DB
        #    raus, ihre Dateien hat Schritt 4 bereits genommen – was hier noch übrig
        #    bleibt, kennt wirklich niemand mehr.
        datei_days, _ = self.datei_retention()
        verwaist_geloescht = 0
        for pfad in self.verwaiste_dateien(datei_days):
            if self._db.anhang_service.loesche(pfad.name):
                verwaist_geloescht += 1
        summe_dateien += verwaist_geloescht
        entities.append({
            "name": DATEI_VERWAIST,
            "label": "Verwaiste Dateien (Upload-Verzeichnis)",
            "geloescht": 0,
            "history_geloescht": None,
            "dateien_geloescht": verwaist_geloescht,
        })

        # Archiv-Zeilen anhängen, damit die UI sie je Bereich anzeigen kann.
        entities.extend(archiv_entities)

        return {
            "dry_run": False,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "summe_geloescht": summe_loeschbar,
            "summe_archiviert": summe_archiviert,
            "summe_history_geloescht": summe_history,
            "summe_dateien_geloescht": summe_dateien,
        }
