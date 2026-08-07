"""Der Worker — alles, was im Zeittakt läuft statt auf Anfrage.

Zweiter Prozess neben der API (siehe `CLAUDE.md`, Abschnitt „Architektur").
Getrennt, weil ein Prüflauf langsame externe Aufrufe macht: Er darf die API
nicht blockieren, und ein Neustart der API darf ihn nicht mitreißen.

Starten:  `uv run python -m app.jobs.worker`   (Kürzel: `make worker`)
"""
