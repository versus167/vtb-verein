---
description: VTB-App-Tickets aus der laufenden App holen und besprechen
argument-hint: "[--all]"
allowed-tools: Bash(python3 tools/vtb_tickets.py:*)
---
Aktuelle Tickets aus dem Bereich „VTB-App":

!`python3 tools/vtb_tickets.py pull $ARGUMENTS`

Fasse die offenen Tickets kurz zusammen (nach Priorität geordnet) und frage,
welches ich als Nächstes angehen soll. Wenn ein Ticket erledigt ist, kann ich
mit `python3 tools/vtb_tickets.py resolve <id> -m "<commit>" --intern` Status und
Kommentar zurückschreiben.
