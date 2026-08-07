# iOS-App (M0)

SwiftUI-App, die den Status des eigenen Backends anzeigt. Sie beweist, dass die
Kette **App → API → Datenbank** durchgängig funktioniert. Ab M4 ersetzt die
Alarm-Liste diesen Bildschirm.

## Öffnen

```bash
open ios/FlugAlarm.xcodeproj
```

Dann Schema `FlugAlarm`, Simulator „iPhone 16", ⌘R.

**Wichtig:** Das Backend muss laufen (siehe Haupt-README), sonst zeigt die App
den Fehlerzustand — was ebenfalls korrekt ist und die Fehlerbehandlung beweist.

## Was schon drin ist

| Datei | Zweck |
|---|---|
| `FlugAlarmApp.swift` | Einstiegspunkt |
| `ContentView.swift` | M0-Bildschirm mit Lade-, Erfolgs- und Fehlerzustand + drei Previews |
| `Core/AppConfig.swift` | **Einzige** Konfiguration: die Backend-URL |
| `Core/Networking/APIClient.swift` | `URLSession` + `async/await`, hinter einem Protokoll |
| `Core/Networking/APIError.swift` | Fehler mit deutschen Texten für die UI |
| `Models/HealthStatus.swift` | `Codable`-Spiegel der `/health`-Antwort |
| `Features/Health/HealthViewModel.swift` | `@Observable`, Zustandsmuster idle → loading → loaded/failed |

Die Ordnerstruktur entspricht dem Projektplan, Abschnitt 6.2.

## Drei Dinge, die du vor M8 ändern musst

1. **Bundle Identifier.** Steht auf `de.example.flugalarm`. Ändere ihn auf
   etwas Eigenes (Projekt → Target → Signing & Capabilities). Für Push muss er
   mit der App ID im Apple Developer Portal übereinstimmen.
2. **Signing Team.** Ist leer. Trage dein Team ein, sobald du auf einem echten
   Gerät testest.
3. **`AppConfig.apiBaseURL`.** `127.0.0.1` funktioniert nur im Simulator. Für
   ein echtes iPhone brauchst du die WLAN-IP deines Macs:
   ```bash
   ipconfig getifaddr en0     # z. B. 192.168.1.42
   ```

## Warum manche Dinge so sind

**Swift-Sprachversion 5, nicht 6.** Der strikte Concurrency-Modus von Swift 6
erzeugt am Anfang viele Warnungen, die vom Eigentlichen ablenken. Umstellen
kannst du jederzeit: Build Settings → `SWIFT_VERSION` auf `6.0`. Sinnvoller
Zeitpunkt ist nach M4, wenn die Grundstruktur steht.

**`NSAllowsLocalNetworking` in `Info.plist`.** iOS erlaubt normalerweise nur
HTTPS. Für `http://127.0.0.1:8000` in der Entwicklung braucht es diese Ausnahme.
Sie gilt nur für lokale Adressen. Vor dem Deployment (M12) ersatzlos löschen.

**Synchronisierte Ordnergruppe.** Das Projekt nutzt Xcodes neue
`PBXFileSystemSynchronizedRootGroup`: Alles im Ordner `FlugAlarm/` gehört
automatisch zum Target. Du kannst Dateien anlegen, verschieben und löschen,
ohne sie in Xcode zu registrieren — und es gibt keine Merge-Konflikte in der
`project.pbxproj`.

## Falls Xcode das Projekt nicht öffnet

Die `project.pbxproj` wurde ohne Xcode erzeugt und ist strukturell geprüft,
aber nicht kompiliert. Sollte Xcode meckern, dauert der Neuaufbau zwei Minuten
— **der eigentliche Code bleibt unverändert erhalten**:

1. Xcode → File → New → Project → iOS → App
2. Product Name `FlugAlarm`, Interface **SwiftUI**, Language **Swift**,
   Storage **None**, Tests aus
3. Speicherort: irgendwo *außerhalb* dieses Repos
4. Im neuen Projekt den generierten `FlugAlarm`-Ordner löschen („Move to Trash")
5. Den Ordner `ios/FlugAlarm/` aus diesem Repo per Drag & Drop in den
   Projektnavigator ziehen, „Create folder references" bzw. die synchronisierte
   Gruppe wählen
6. Target → Build Settings: `IPHONEOS_DEPLOYMENT_TARGET` = 17.0,
   `INFOPLIST_FILE` auf die mitgelieferte `ios/Info.plist` zeigen lassen
   (oder die ATS-Ausnahme im generierten Info.plist eintragen)
7. `.xcodeproj` an die Stelle von `ios/FlugAlarm.xcodeproj` verschieben

Sag mir Bescheid, falls das nötig war — dann korrigiere ich die Projektdatei.
