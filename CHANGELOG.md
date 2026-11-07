# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [1.0.0] – 2026-11-07

Erste Open-Source-Veröffentlichung.

### Enthalten

- Regelbasierte Konvertierung von Ivanti-DSM-Paketen in Matrix42-Empirum-Pakete
  (`Install/Setup.inf`, `Files/`, PDF-Manual)
- GUI-Wizard (fünf Schritte) und Batch-Fenster
- CLI mit `migrate`, `batch`, `validate`, `selftest`
- Zweistufige Validierung (AST und Text) der erzeugten `Setup.inf`
- Migrationsberichte als HTML und Markdown inklusive KPI-Export
- Optionaler, standardmäßig deaktivierter KI-Modus zur Unterstützung bei
  unbekannten Konstrukten
- Offline-Betrieb, Nur-Lese-Zugriff auf Quellpakete, SHA-256-Integritätsprüfung
- Gebündelte Referenz-Setup.inf-Vorlagen für Parser- und Validator-Tests
