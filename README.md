# DSM2Empirum – Migrationstool Ivanti DSM → Matrix42 Empirum

> Lokales Windows-Werkzeug (GUI & CLI), das **Ivanti-DSM-Paketordner** vollautomatisch in
> konforme **Matrix42-Empirum-Paketstrukturen** mit fehlerfreier `Setup.inf` umwandelt.

---

## Features

### Konvertierung
| Funktion | Details |
|---|---|
| **Regelbasierte Transformation** | 90+ Regeln gemäß Matrix42 Setup.inf-Spezifikation (MSI, Unattended, Skripte, Shell-Links, Registry) |
| **_ExpInfo.xml-Auswertung** | Produktname, Hersteller, Version und Beschreibung werden aus der DSM-Exportdatei gelesen |
| **extern$- & .\\-Handling** | Dateien aus `extern$` / `Extern$` und Paketwurzel werden nach `Files\` kopiert; Skriptpfade (`.\`, relative Pfade und `extern$`) automatisch auf `%SRC%\Files` umgeschrieben |
| **xcopy-Härtung** | Alle Kopiervorgänge über `xcopy /S /H /E /V` statt `Copy` für robuste Dateiübertragung |
| **CallHidden** | Alle Programmaufrufe werden mit `CallHidden` gestartet (unsichtbar für den Endnutzer) |
| **Uninstall-Reihenfolge** | Befehle in `[Set:Deinstallation]` werden korrekt **umgekehrt** emittiert (letzter DSM-Befehl → erster Empirum-Befehl). Grund: Empirum führt bei `Setup.exe /U` Sektionen und Befehle **von unten nach oben** aus (KB Abschnitt 7.1) – die Umkehrung stellt die korrekte Rückwärts-Reihenfolge sicher. Sub-Sections (`SectionRef`-Ziele) werden **nicht** umgekehrt, da sie beim Ansprung vorwärts laufen |
| **Synthetisierte Deinstallation** | Fehlt im DSM-Paket `$BeginUninstallScript`, wird automatisch eine `Set:Deinstallation` durch Umkehrung der Installationsbefehle (MSI `/x`, Registry-Löschung, Dateibereinigung, `DelTree`) in Rückwärtsreihenfolge erzeugt |
| **Ordner-Löschungen via DelTree** | DSM `Delete()` auf Verzeichnisse (keine Dateiendung) wird zu `DelTree` emittiert – in Install- und Deinstall-Kontext; Dateien bleiben `Del`. Abschließende Backslashes werden entfernt (`DelTree "Pfad\"` würde fehlschlagen) |
| **Product-Section-Konformität** | `#Set:Product, DONTDELETE` und `#Set:Deinstallation, DELETE` – Sektionsaufrufe in `[Product]` erhalten kein führendes `-`-Zeichen |
| **Registry-Präfix-Regelung** | `-`-Präfix in `[Reg:Product]` nur in echten Deinstall-Sections; Install-Sections erhalten keinen `-`-Präfix |
| **NIR-Import** | `.nir`-Dateien (Registry-Importdateien) werden vollständig in `[Reg:Product]` übernommen |

### Paketausgabe
| Funktion | Details |
|---|---|
| **Standardkonforme Struktur** | `<GUID>\Install\Setup.inf`, `Files\`, `Manual\<Paketname>.pdf` |
| **PDF-Manual** | Automatisch generierte Paketdokumentation mit Metadaten, Installationsparametern und SHA-256-Prüfsummen |
| **Zweistufige Validierung** | AST- und textbasierte Syntax- und Semantikprüfung jeder erzeugten `Setup.inf`; die Standard-Fehlersektionen (`Set:InstallationError`, `Set:ReinstallationError`, `Set:DeInstallationError`) gelten dabei als erlaubte, referenzlose Boilerplate |
| **Migrationsberichte** | HTML/Markdown-Berichte mit Konfidenz-Scoring, Regeltracing und Nacharbeitsliste (TODOs) |

### Sicherheit & Integrität
- **Nur-Lese-Zugriff** auf DSM-Quellpakete – keine Veränderung der Originaldaten
- **SHA-256-Validierung** für alle Nutzlastdateien (vollständig im PDF-Manual ausgeschrieben)
- Keine Netzwerkverbindung erforderlich – vollständig offline nutzbar

---

## Systemvoraussetzungen

- Windows 10/11 (x64)
- Keine Python-Installation nötig für die kompilierte `.exe`

---

## Verwendung (kompilierte EXE)

### GUI
Doppelklick auf `Dsm2Empirum.exe` – Pakete per Drag & Drop oder Ordnerauswahl konvertieren.

### CLI
```powershell
# Einzelnes Paket konvertieren
Dsm2EmpirumCmd.exe migrate <DSM-Paketordner> -o <Empirum-Zielordner>

# Mehrere Pakete (Batch)
Dsm2EmpirumCmd.exe batch <Ordner-mit-DSM-Paketen> -o <Zielordner>

# Setup.inf validieren
Dsm2EmpirumCmd.exe validate <Setup.inf>

# Version & Selbsttest
Dsm2EmpirumCmd.exe --version
Dsm2EmpirumCmd.exe selftest
```

---

## Entwicklung

```powershell
# Virtuelle Umgebung erstellen
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Abhängigkeiten installieren (inkl. dev/gui/build extras)
pip install -e ".[dev,gui]"

# Tests ausführen
pytest -q

# Linting & Typprüfung
ruff check .
mypy src tests

# EXE kompilieren (Quality Gate: alle Tests müssen grün sein)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

---

## Projektstruktur

```
DSM2MatrixConverter/
├── src/dsm2emp/
│   ├── parser/         # DSM eScript, .nir und _ExpInfo.xml Parser
│   ├── rules/          # Regelengine (90+ Transformationsregeln)
│   ├── emitter/        # Setup.inf AST → Text-Renderer
│   ├── validator/      # Syntax- und Semantikvalidierung
│   ├── manual/         # PDF-Manual-Generator
│   └── orchestrator.py # Paket-Konvertierungspipeline
├── tests/              # 193+ Tests (Unit, Integration, Golden, E2E)
├── packaging/          # PyInstaller Build-Skripte & .spec
├── rules/              # Regelkatalog (YAML)
└── docs/               # Entwicklerdokumentation
```

---

## Lizenz

Internes Werkzeug – nicht für die öffentliche Verbreitung bestimmt.
