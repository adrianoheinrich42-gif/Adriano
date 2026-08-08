# Anleitungen — was nur du selbst tun kannst

Alles in diesem Ordner richtet sich an **dich**, nicht an Claude Code. Es
sind die Dinge, für die es ein Konto, eine Kreditkarte oder ein echtes iPhone
braucht — die kann keine Programmiersitzung übernehmen.

Jede Datei setzt **kein Vorwissen** voraus und erklärt auch, *warum* der
Schritt nötig ist.

## Reihenfolge

| Datei | Thema | Dauer | Nötig für |
|---|---|---|---|
| `01-Supabase-einrichten.docx` | Anmeldedienst + Datenbank | ~15 min | **Ohne das kann sich niemand anmelden** |
| `02-Amadeus-Zugang.docx` | Flugdaten | ~10 min | Ohne das findet der Worker nichts |
| `03-Anthropic-Schluessel.docx` | Claude-Texte | ~10 min | Optional — ohne das schreibt der Baukasten |
| `04-VAPID-Schluesselpaar.docx` | Push-Ausweis | ~2 min | Ohne das geht keine Benachrichtigung raus |
| `05-Deployment.docx` | App ins Netz bringen | 1–2 h | Voraussetzung für Push aufs iPhone |
| `06-iPhone-Push-testen.docx` | Der letzte offene Test | ~15 min | Braucht Schritt 5 |

**1, 2 und 4 sind die Pflicht.** 3 ist Komfort — ohne Anthropic-Schlüssel
läuft die App vollständig, nur weniger schön formuliert.

## Und dann?

`00-PROMPT-fuer-die-naechste-Session.txt` enthält einen fertigen Text, den du
in eine neue Claude-Code-Sitzung einfügen kannst. Er sagt der Sitzung, wo das
Projekt steht, was du inzwischen eingerichtet hast und was als Nächstes
drankommt — du musst dafür nicht in `HANDOFF.md` nachschlagen.
