# Build & Packaging (T-100)

Das Tool wird als **zwei eigenständige Single-EXE-Dateien** ausgeliefert (Kapitel 9.6).
Beide enthalten die komplette Anwendung inkl. aller Ressourcen —
keine Installation, keine Python-Installation auf dem Zielrechner, kein Netzwerkzugriff.

| Datei | Typ | Zweck |
|---|---|---|
| `Dsm2Empirum.exe` | GUI (`--noconsole`) | Wizard/Batch-Dashboard; mit Kommandozeilen-Argumenten verhält sie sich wie die CLI (Ausgabe dann unsichtbar, nur Exit-Code). |
| `Dsm2EmpirumCmd.exe` | CLI (`--console`) | Skripting, Batch-Läufe, `selftest`; dafür ist sie gedacht und getestet. |

## Voraussetzungen (nur fürs Bauen)

- Windows 10/11 x64
- Python 3.12 (+ venv), Repository ausgecheckt
- **Kein** UPX im `PATH` — die Spec deaktiviert UPX zusätzlich hart (`upx=False`),
  weil Packer zu Antivirus-False-Positives führen (Risiko R-08).

## Bauen

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,gui]"
pytest -q                     # Qualitätstor: muss grün sein (Projektregel 9)
.\packaging\build.ps1
```

`build.ps1` führt in dieser Reihenfolge aus: Requirements installieren →
Test-Suite als Gate (mit `-SkipTests` überspringbar — nicht für Releases!) →
`pyinstaller packaging\dsm2emp.spec` → Smoke-Test der CLI-EXE
(`Dsm2EmpirumCmd.exe --version` und `selftest`, AK-5).

Ausgabe:

```
packaging\dist\Dsm2Empirum.exe      (GUI, ca. 60-90 MB)
packaging\dist\Dsm2EmpirumCmd.exe   (CLI,  gleicher Umfang)
```

Zwischenartefakte landen in `packaging\build\` (beides ist git-ignoriert).

## Mitgebündelte Ressourcen

Die Spec packt alle schreibgeschützten Laufzeit-Ressourcen ins Bundle. Zur Laufzeit
löst `dsm2emp._resources.resource_root()` sie auf (Dev: Repository-Root, Frozen:
`sys._MEIPASS`) — deshalb dürfen Loader **keine** eigenen `Path(__file__).parents[…]`-Ketten
mehr bauen; der Regressionstest `tests/test_resources.py` sichert das ab.

- `assets/report_template.html.j2` — HTML-Report-Template
- `assets/icon.ico` — Anwendungsicon (EXE-Resource **und** Fenster-/Taskleisten-Icon)
- `assets/prompts/`, `assets/schemas/` — KI-Prompt-Templates und JSON-Schemas
- `rules/dsm_to_empirum.yaml` — Standard-Regelkatalog
- `dsm2emp/reference/*.yaml` — Empirum-Syntaxreferenz (liegt im Paket)

Das Icon wird aus `assets/icon.svg` generiert (`python tools/make_icon.py`, benötigt
Pillow + PySide6 im venv): mehrere Größen (256/128/64/48/32/24/16 px, 16+24 px in
vereinfachter Variante) landen in `assets/icon.ico`; die Spec hängt die Datei per
`icon=...` an beide EXEs und bündelt sie zusätzlich als Laufzeit-Ressource, damit
`dsm2emp.gui.app.app_icon()` das Fenster-Icon setzen kann.

## Qt-Minimierung

Die GUI nutzt nur QtCore/QtGui/QtWidgets. Die Spec schließt alle weiteren Qt-Module
(WebEngine, Quick/Qml, Multimedia, 3D, Bluetooth, …) über `excludes`, sodass
PyInstaller auch die zugehörigen Plugins und DLLs nicht mitnimmt. Die verbleibenden
Plugins (u. a. `platforms/qwindows.dll`, Image-Formats) wählt `pyinstaller-hooks-contrib`
anhand der tatsächlichen Imports aus.

## Abnahme auf sauberer VM (AK-5)

1. `Dsm2EmpirumCmd.exe selftest` → Exit-Code 0, Ausgabe endet mit
   `DSM2Empirum self-test: OK` (läuft vollständig offline auf einem synthetischen Paket).
2. `Dsm2Empirum.exe` (ohne Argumente) startet den Wizard; Ordnerauswahl funktioniert.
3. Ein reales Paket migrate → Zielordner wird erzeugt, Report öffnet sich, **Quellordner
   bleibt byte-identisch** (NFR-001/FR-001, Protokoll: `docs/AK-7-OFFLINE-PROTOKOLL.md`).
4. Flugmodus/ohne Netz: gleiches Ergebnis; `--ai on` degradiert sauber mit Warnung (AK-7).

## Antivirus-False-Positives (R-08 / R-09)

PyInstaller-Onefile-EXEs ohne Signatur werden gelegentlich von AV-Scannern
falschpositiv gemeldet. Strategie (Kap. 10.1):

1. **Kein UPX** — Packer sind der Haupttrigger. Die Spec erzwingt `upx=False`.
2. **Codesignierung** (empfohlen für jede Auslieferung):
   ```powershell
   signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
     /a packaging\dist\Dsm2Empirum.exe packaging\dist\Dsm2EmpirumCmd.exe
   ```
   Mit Firmenzertifikat (OV/EV) verschwinden die meisten Meldungen; EV zusätzlich sofort.
3. **Submission bei evt. verbleibenden Meldungen:**
   - Microsoft: <https://www.microsoft.com/en-us/wdsi/filesubmission> („Software developer“,
     nach Signierung erneut einreichen — Virenscannern wird der Signature-Trust angerechnet).
   - Kunden hinweisen: EXE unter `packaging\dist\` vom Build-Rechner beziehen, Hash
     vergleichen (`Get-FileHash`), SmartScreen-Meldung via „Trotzdem ausführen“ +
     Freigabe durch IT.

## Bekannte Einschränkungen

- **Startzeit**: Onefile entpackt beim Start nach `%TEMP%` (1–3 s, bei AV-Scanning auch
  länger). Für Skript-Batches `Dsm2EmpirumCmd.exe` verwenden.
- **KI-Modus in der EXE**: Opt-in (`--ai on`). Die Erkennung von `keyring`-Backends im
  Frozen-Bundle kann eingeschränkt sein; ohne gespeicherten Schlüssel degradiert der
  KI-Modus ohnehin sauber (KI aus + Warnung, AK-7-Verhalten).
- **GUI mit Argumenten**: `Dsm2Empirum.exe migrate …` führt die CLI aus, zeigt aber
  wegen `--noconsole` keine Konsoleausgabe — für sichtbare Ausgaben `Dsm2EmpirumCmd.exe`.
