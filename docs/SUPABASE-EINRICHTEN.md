# Supabase einrichten — Schritt für Schritt

Diese Anleitung setzt **kein Vorwissen** voraus. Am Ende kannst du dich in der
Flugalarm-App mit E-Mail und Passwort anmelden. Dauer: etwa 15 Minuten,
davon 3 Minuten Warten.

---

## 0. Was ist Supabase überhaupt?

Jede App mit Nutzerkonten braucht zwei Dinge:

1. **Eine Datenbank** — der Ort, an dem die Daten liegen.
2. **Eine Anmeldung** — Registrieren, Einloggen, Passwort vergessen,
   E-Mail bestätigen.

Beides könnte man selbst bauen. Die Anmeldung selbst zu bauen ist aber die
Sorte Aufgabe, bei der Fehler teuer sind: Passwörter müssen richtig
verschlüsselt gespeichert werden, Zurücksetzen-Links dürfen nicht erratbar
sein, und wer das falsch macht, merkt es erst, wenn die Passwörter seiner
Nutzer im Netz stehen.

**Supabase ist ein Anbieter, der beides fertig bereitstellt.** Du klickst dir
ein Projekt zusammen und bekommst eine PostgreSQL-Datenbank und einen
Anmeldedienst. Für kleine Projekte ist es kostenlos. Man kann es sich vorstellen
wie einen Vermieter: Du mietest eine fertige Wohnung mit Türschloss, statt
selbst ein Haus zu bauen und über Schlösser nachzudenken.

### Wie das in unserer App zusammenspielt

```
   Browser  ──1── Supabase        "hier ist E-Mail + Passwort"
            ◀─2──                  "stimmt, hier dein Ausweis (Token)"
            ──3── dein Backend    "hier mein Ausweis, zeig mir meine Alarme"
            ◀─4──                  prüft den Ausweis, antwortet
```

Wichtig dabei:

- **Dein Passwort geht nie über deinen eigenen Server** (Schritt 1 geht direkt
  zu Supabase). Deshalb kann dein Backend es auch nicht versehentlich
  mitschreiben.
- **Dein Backend redet nie mit Supabase.** Es prüft in Schritt 4 nur die
  Unterschrift auf dem Token — dafür braucht es ein gemeinsames Geheimnis,
  aber keine Internetverbindung zu Supabase.
- Der „Ausweis" heißt **JWT** (JSON Web Token). Das ist eine lange
  Zeichenkette, die sagt „ich bin Nutzer Nr. 123", und die mit einem geheimen
  Schlüssel unterschrieben ist, sodass man sie nicht fälschen kann.

Von Supabase nutzen wir **nur die Anmeldung**, nicht die Datenbank — unsere
eigenen Tabellen liegen weiter in unserem eigenen PostgreSQL.

---

## 1. Konto anlegen

1. Gehe auf **https://supabase.com** und klicke oben rechts auf
   **„Start your project"**.
2. Melde dich mit GitHub an (am einfachsten) oder mit einer E-Mail-Adresse.
3. Falls gefragt: Du legst eine **Organization** an. Nimm irgendeinen Namen
   (z. B. deinen eigenen), Typ **Personal**, Plan **Free**.

---

## 2. Projekt anlegen

Klicke auf **„New project"** und fülle aus:

| Feld | Was eintragen |
|---|---|
| **Name** | `flugalarm` |
| **Database Password** | Klick auf „Generate a password" |
| **Region** | `Central EU (Frankfurt)` |
| **Plan** | Free |

> ⚠️ **Das Datenbank-Passwort sofort speichern**, bevor du weiterklickst — es
> wird danach nicht mehr angezeigt. Schreib es in deinen Passwortmanager.
> Wir brauchen es für diese App zwar nicht (wir nutzen nur die Anmeldung),
> aber ohne kommst du später nicht mehr an die Supabase-Datenbank.

Dann **„Create new project"**. Jetzt dauert es **etwa 2–3 Minuten**, bis das
Projekt bereit ist. Kaffee holen.

---

## 3. Die drei Werte abholen

Wenn das Projekt fertig ist, brauchst du drei Werte. Alle findest du in den
Projekteinstellungen — **Zahnrad-Symbol unten links → „API Keys"** bzw.
**„Data API"** (Supabase benennt die Menüpunkte gelegentlich um; suche nach
„API").

### a) Project URL

Sieht so aus:

```
https://abcdefghijklmnop.supabase.co
```

→ Diese Adresse kommt an **zwei** Stellen: in `web/config.js` und in
`backend/.env`.

### b) anon public key

Ein sehr langer Text, der mit `eyJ...` anfängt (oder neuer: `sb_publishable_...`).
Daneben steht **„anon"** und **„public"**.

→ Kommt nur in `web/config.js`.

> **Ist es schlimm, dass der im Quelltext des Browsers steht?**
> Nein — dieser Schlüssel ist genau dafür gemacht. Er erlaubt für sich allein
> nichts außer „einen Anmeldeversuch stellen". In jeder Supabase-Web-App der
> Welt steht er im Quelltext.
>
> ⚠️ Direkt daneben liegt aber der **`service_role`** Schlüssel (manchmal
> „secret" genannt). Der darf **alles** und gehört **niemals** in den Browser
> und **niemals** ins Git-Repository. Verwechsle die beiden nicht.

### c) JWT Secret

Das ist der geheime Schlüssel, mit dem Supabase die Ausweise unterschreibt —
und mit dem dein Backend prüft, ob ein Ausweis echt ist.

Zu finden unter **Project Settings → JWT Keys** (früher: „API → JWT Settings").

> **Wenn du dort nur „JWT Signing Keys" mit `ECC (P-256)` oder `RSA` siehst:**
> Neuere Supabase-Projekte unterschreiben standardmäßig anders (asymmetrisch).
> Suche dann nach **„Legacy JWT Secret"** oder **„JWT Secret"** und schalte es
> gegebenenfalls frei — unser Backend erwartet aktuell das symmetrische
> Verfahren (HS256).
>
> Findest du es partout nicht, ist das kein Beinbruch: Sag Bescheid, dann wird
> `backend/app/core/security.py` auf das asymmetrische Verfahren erweitert.
> Betroffen ist genau diese eine Datei — alle Endpunkte bleiben unverändert.

→ Kommt nur in `backend/.env`. **Nie in den Browser, nie ins Repository.**

---

## 4. E-Mail-Bestätigung ausschalten (nur zum Entwickeln)

Standardmäßig schickt Supabase nach der Registrierung eine Bestätigungsmail.
Beim Ausprobieren ist das lästig, und der kostenlose Mailversand ist auf wenige
Mails pro Stunde begrenzt.

**Authentication → Sign In / Providers → Email** → Schalter
**„Confirm email"** auf **aus**.

> Vor dem echten Livegang wieder **einschalten**. Sonst kann sich jeder mit
> einer erfundenen Adresse registrieren.

Die App kommt mit beiden Einstellungen zurecht: Ist die Bestätigung an, zeigt
sie nach dem Registrieren den Hinweis, in die E-Mails zu schauen.

---

## 5. Die Werte eintragen

### Backend — `backend/.env`

Falls die Datei noch nicht existiert (nach frischem Klonen ist sie nie da):

```bash
cd backend
cp .env.example .env
```

Dann in `backend/.env` diese zwei Zeilen ergänzen bzw. das `#` entfernen:

```
SUPABASE_URL=https://abcdefghijklmnop.supabase.co
SUPABASE_JWT_SECRET=hier-das-lange-jwt-secret-einfuegen
```

> `.env` steht in `.gitignore` und landet **nie** im Repository. Genau dafür
> ist sie da.

### Frontend — `web/config.js`

```js
supabaseUrl: "https://abcdefghijklmnop.supabase.co",
supabaseAnonKey: "eyJhbGciOi...",   // der anon public key
```

---

## 6. Ausprobieren

Drei Fenster, drei Befehle:

```bash
# 1. Datenbank
docker compose up -d db

# 2. Backend  (aus backend/)
uv run uvicorn app.main:app --reload

# 3. Frontend (aus web/)
python -m http.server 3000
```

Dann **http://localhost:3000** im Browser öffnen.

Du solltest sehen:

1. Das Anmeldeformular, darunter in klein **„Server erreichbar."**
   *(Steht dort etwas anderes, läuft das Backend nicht — Punkt 2 oben.)*
2. Nach **„Neues Konto anlegen"** mit beliebiger E-Mail und einem Passwort
   (mindestens 6 Zeichen): die Ansicht **„Deine Alarme"** mit dem Hinweis
   „Noch kein Alarm".
3. Über **„+ Neuer Alarm"** einen Alarm anlegen — er erscheint sofort in der
   Liste.

---

## 7. Wenn etwas nicht klappt

| Was du siehst | Woran es liegt |
|---|---|
| „Die App ist noch nicht mit Supabase verbunden" | `supabaseUrl` oder `supabaseAnonKey` in `web/config.js` ist noch leer. |
| „Keine Verbindung zum Server. Läuft das Backend …" | Backend läuft nicht, oder `apiBaseURL` in `config.js` stimmt nicht. |
| „Server erreichbar, aber ohne Datenbank" | PostgreSQL läuft nicht (`docker compose up -d db`). |
| „E-Mail-Adresse oder Passwort stimmt nicht." | Tippfehler — oder das Konto existiert noch nicht (erst „Neues Konto anlegen"). |
| „Bitte bestätige zuerst den Link …" | E-Mail-Bestätigung ist an (Schritt 4). |
| Anmelden klappt, aber die Alarmliste zeigt „Sitzung ist abgelaufen" | Das `SUPABASE_JWT_SECRET` in `backend/.env` passt nicht zum Supabase-Projekt. Neu kopieren und das Backend **neu starten** — `.env` wird nur beim Start gelesen. |
| Nichts geht mehr nach ein paar Wochen Pause | Kostenlose Supabase-Projekte werden nach etwa einer Woche ohne Nutzung **pausiert**. Im Dashboard auf „Restore" klicken. |

---

## 8. Woran du beim Livegang denken musst

- **E-Mail-Bestätigung wieder einschalten** (Schritt 4).
- **Site URL und Redirect URLs** unter *Authentication → URL Configuration* auf
  deine echte Adresse setzen.
- **HTTPS ist Pflicht**, sobald die App nicht mehr auf `localhost` läuft —
  sonst funktionieren später auch die Push-Benachrichtigungen auf dem iPhone
  nicht.
- Das `service_role`-Geheimnis hat in keiner dieser Dateien etwas zu suchen.
