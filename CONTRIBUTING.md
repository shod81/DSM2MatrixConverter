# Mitwirken

Danke für dein Interesse an DSM2Empirum. Dieses Dokument beschreibt, wie du
Fehler meldest, Änderungen einreichst und was wir von Beiträgen erwarten.

## Entwicklungsumgebung

```powershell
git clone https://github.com/shod81/DSM2MatrixConverter-OpenFree.git
cd DSM2MatrixConverter-OpenFree
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,gui]"
pytest -q
```

Die Testsuite läuft vollständig offline. Der optionale KI-Modus wird in den
Tests nicht benötigt.

## Bevor du einen Pull Request öffnest

1. **Tests**: `pytest -q` muss grün sein.
2. **Neue Regeln**: Jede Mapping-Regel braucht eine ID, einen `doc_ref` und
   mindestens einen Test. Neue Befehle oder Flags ohne Referenzeintrag in
   `src/dsm2emp/reference/*.yaml` werden nicht angenommen.
3. **Keine echten Kundendaten**: Fixtures, Golden Files und Tests dürfen
   ausschließlich synthetische oder generische Beispieldaten enthalten – keine
   realen Paketnamen, GUIDs, Servernamen oder Firmenbezeichnungen.
4. **Emitter-Regel**: `Setup.inf`-Zeilen werden ausschließlich im Emitter
   erzeugt. String-Konkatenation außerhalb von `src/dsm2emp/emitter/` ist nicht
   zulässig.
5. **Quellschutz**: Paketquellen werden nur lesend geöffnet. Tests in
   `tests/e2e/` sichern das ab.

`ruff check .` und `mypy src tests` sind empfohlen; derzeit existiert noch ein
bekannter Altbestand an Befunden. Neue Befunde sollen nicht hinzukommen.

## Commits und Pull Requests

- Ein Pull Request = ein abgegrenztes Thema.
- Commit-Nachrichten nach [Conventional Commits](https://www.conventionalcommits.org/)
  (`fix:`, `feat:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Beschreibe im PR, was sich ändert und wie du es geprüft hast.

## Fehler melden

Bitte mit Reproduktionsschritten, erwartetem und tatsächlichem Verhalten sowie
der verwendeten Version (`Dsm2EmpirumCmd.exe --version`). **Keine**
vertraulichen Paketinhalte oder Kundendaten in öffentliche Issues einfügen.

Sicherheitsrelevante Meldungen bitte gemäß [SECURITY.md](SECURITY.md).
