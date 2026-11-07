# Build & Packaging

Das Tool wird als **zwei eigenständige Single-EXE-Dateien** ausgeliefert.
Beide enthalten die komplette Anwendung inkl. aller Ressourcen —
keine Installation, keine Python-Installation auf dem Zielrechner, kein Netzwerkzugriff.

| Datei | Typ | Zweck |
|---|---|---|
| `Dsm2Empirum.exe` | GUI (`--noconsole`) | Wizard/Batch-Dashboard; mit Kommandozeilen-Argumenten verhält sie sich wie die CLI (Ausgabe dann unsichtbar, nur Exit-Code). |
| `Dsm2EmpirumCmd.exe` | CLI (`--console`) | Skripting, Batch-Läufe, `selftest`. |

## Voraussetzungen (nur fürs Bauen)

- Windows 10/11 x64
- Python 3.11+ (+ venv), Repository ausgecheckt
- **Kein** UPX im `PATH` — die Spec deaktiviert UPX zusätzlich hart (`upx=False`),
  weil Packer zu Antivirus-False-Positives führen.

## Bauen

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,gui]"
pytest -q                     # Qualitätstor: muss grün sein
.\packaging\build.ps1
```

`build.ps1` führt in dieser Reihenfolge aus: Requirements installieren →
Test-Suite als Gate (mit `-SkipTests` überspringbar — nicht für Releases!) →
`pyinstaller packaging\dsm2emp.spec` → Smoke-Test der CLI-EXE
(`Dsm2EmpirumCmd.exe --version` und `selftest`).

Ausgabe:

```
packaging\dist\Dsm2Empirum.exe      (GUI, ca. 60-90 MB)
packaging\dist\Dsm2EmpirumCmd.exe   (CLI,  gleicher Umfang)
```

Zwischenartefakte landen in `packaging\build\` (beides ist git-ignoriert).

## Mitgebündelte Ressourcen

Die Spec packt alle schreibgeschützten Laufzeit-Ressourcen ins Bundle. Zur Laufzeit
löst `dsm2emp._resources.resource_root()` sie auf — in der Quelle, im installierten
Wheel und im PyInstaller-Bundle gleichermaßen. Deshalb dürfen Loader **keine**
eigenen `Path(__file__).parents[…]`-Ketten bauen; der Regressionstest
`tests/test_resources.py` sichert das ab.

- `dsm2emp/data/assets/report_template.html.j2` — HTML-Report-Template
- `dsm2emp/data/assets/icon.ico` — Anwendungsicon (EXE-Resource **und** Fenster-/Taskleisten-Icon)
- `dsm2emp/data/assets/prompts/`, `dsm2emp/data/assets/schemas/` — KI-Prompt-Templates und JSON-Schemas
- `dsm2emp/data/rules/dsm_to_empirum.yaml` — Standard-Regelkatalog
- `dsm2emp/reference/*.yaml` — Empirum-Syntaxreferenz

Das Icon wird aus `assets/icon.svg` generiert (`python tools/make_icon.py`, benötigt
Pillow + PySide6 im venv): mehrere Größen (256/128/64/48/32/24/16 px, 16+24 px in
vereinfachter Variante) landen in `src/dsm2emp/data/assets/icon.ico`; die Spec hängt
die Datei per `icon=...` an beide EXEs und bündelt sie zusätzlich als
Laufzeit-Ressource, damit `dsm2emp.gui.app.app_icon()` das Fenster-Icon setzen kann.

## Qt-Minimierung

Die GUI nutzt nur QtCore/QtGui/QtWidgets. Die Spec schließt alle weiteren Qt-Module
(WebEngine, Quick/Qml, Multimedia, 3D, Bluetooth, …) über `excludes`, sodass
PyInstaller auch die zugehörigen Plugins und DLLs nicht mitnimmt. Die verbleibenden
Plugins (u. a. `platforms/qwindows.dll`, Image-Formats) wählt `pyinstaller-hooks-contrib`
anhand der tatsächlichen Imports aus.

## Abnahme auf sauberer VM

1. `Dsm2EmpirumCmd.exe selftest` → Exit-Code 0, Ausgabe endet mit
   `DSM2Empirum self-test: OK` (läuft vollständig offline auf einem synthetischen Paket).
2. `Dsm2Empirum.exe` (ohne Argumente) startet den Wizard; Ordnerauswahl funktioniert.
3. Ein Paket migrieren → Zielordner wird erzeugt, Report öffnet sich, **Quellordner
   bleibt byte-identisch**.
4. Flugmodus/ohne Netz: gleiches Ergebnis; `--ai on` degradiert sauber mit Warnung.

## Antivirus-False-Positives

PyInstaller-Onefile-EXEs ohne Signatur werden gelegentlich von AV-Scannern
falschpositiv gemeldet. Strategie:

1. **Kein UPX** — Packer sind der Haupttrigger. Die Spec erzwingt `upx=False`.
2. **Codesignierung** (empfohlen für jede Auslieferung):
   ```powershell
   signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
     /a packaging\dist\Dsm2Empirum.exe packaging\dist\Dsm2EmpirumCmd.exe
   ```
   Mit Zertifikat (OV/EV) verschwinden die meisten Meldungen; EV zusätzlich sofort.
3. **Submission bei evt. verbleibenden Meldungen:**
   - Microsoft: <https://www.microsoft.com/en-us/wdsi/filesubmission> („Software developer",
     nach Signierung erneut einreichen — Virenscannern wird der Signature-Trust angerechnet).
   - Nutzer hinweisen: EXE vom Build-Rechner beziehen, Hash vergleichen
     (`Get-FileHash`), SmartScreen-Meldung via „Trotzdem ausführen" quittieren.

## Bekannte Einschränkungen

- **Startzeit**: Onefile entpackt beim Start nach `%TEMP%` (1–3 s, bei AV-Scanning auch
  länger). Für Skript-Batches `Dsm2EmpirumCmd.exe` verwenden.
- **KI-Modus in der EXE**: Opt-in (`--ai on`). Die Erkennung von `keyring`-Backends im
  Frozen-Bundle kann eingeschränkt sein; ohne gespeicherten Schlüssel degradiert der
  KI-Modus sauber (KI aus + Warnung).
- **GUI mit Argumenten**: `Dsm2Empirum.exe migrate …` führt die CLI aus, zeigt aber
  wegen `--noconsole` keine Konsoleausgabe — für sichtbare Ausgaben `Dsm2EmpirumCmd.exe`.
