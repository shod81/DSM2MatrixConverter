# Sicherheit

## Unterstützte Versionen

| Version | Unterstützt |
|---|---|
| 1.x | ja |

## Sicherheitslücken melden

Bitte **keine** öffentlichen Issues für Sicherheitslücken. Nutze stattdessen
GitHub Security Advisories:

<https://github.com/shod81/DSM2MatrixConverter-OpenFree/security/advisories/new>

Bitte gib an:

- betroffene Version und Betriebsart (GUI, CLI, EXE oder Quellcode)
- Reproduktionsschritte oder ein minimales Beispieleingabepaket
- erwartetes und tatsächliches Verhalten
- mögliche Auswirkung

Wir bestätigen den Eingang innerhalb von 7 Tagen und stimmen das weitere
Vorgehen und eine Veröffentlichung mit dir ab.

## Sicherheitsmodell

- Das Werkzeug arbeitet **offline** und führt keine Paketinhalte aus.
- DSM-Quellpakete werden ausschließlich lesend geöffnet.
- Der KI-Modus ist standardmäßig deaktiviert und nur per Opt-in aktiv.
  Bei Aktivierung werden maskierte Ausschnitte an den konfigurierten Anbieter
  gesendet; API-Schlüssel liegen im Windows Credential Manager.
- Kompilierte EXEs sind nicht signiert; prüfe beim Bezug die SHA-256-Prüfsumme
  der Release-Dateien.
