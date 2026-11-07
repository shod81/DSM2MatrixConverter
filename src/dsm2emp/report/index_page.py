"""HTML package index generator for Empirum output directories.

Generates a self-contained, interactive Paketindex.html in the Empirum_Output
directory containing package names, versions, vendors, folder/GUID paths,
and direct links / clipboard copy buttons for fast Windows Explorer navigation.
"""

from __future__ import annotations

import datetime
import html
import re
from dataclasses import dataclass
from pathlib import Path

from dsm2emp.io.encoding import read_text


@dataclass
class PackageIndexEntry:
    """Metadata of a converted package found in the output directory."""

    folder_name: str
    rel_path: str
    abs_path: str
    product_name: str
    version: str
    developer_name: str
    setup_inf_rel_path: str | None
    setup_inf_abs_path: str | None
    has_setup_inf: bool
    status: str
    modified_time: str


def _extract_setup_inf_meta(setup_inf_path: Path) -> dict[str, str]:
    """Extract ProductName, Version, and DeveloperName from a Setup.inf file."""
    meta: dict[str, str] = {
        "product_name": "",
        "version": "",
        "developer_name": "",
    }
    if not setup_inf_path.exists():
        return meta

    # BOM-aware read (the builder writes UTF-8 with BOM); detects UTF-8/UTF-16
    # first and falls back to cp1252 so non-ASCII names are not mojibaked.
    try:
        content, _ = read_text(setup_inf_path)
    except OSError:
        return meta

    # Extract [Application] fields using regex
    name_m = re.search(r"^\s*ProductName\s*=\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if name_m:
        meta["product_name"] = name_m.group(1).strip().strip('"').strip("'")

    ver_m = re.search(r"^\s*Version\s*=\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if ver_m:
        meta["version"] = ver_m.group(1).strip().strip('"').strip("'")

    dev_m = re.search(
        r"^\s*(?:DeveloperName|Developer)\s*=\s*(.+)$",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if dev_m:
        meta["developer_name"] = dev_m.group(1).strip().strip('"').strip("'")

    return meta


def _find_setup_inf(pkg_dir: Path) -> Path | None:
    """Find Setup.inf in Install/Setup.inf or root of package directory."""
    candidates = [
        pkg_dir / "Install" / "Setup.inf",
        pkg_dir / "install" / "Setup.inf",
        pkg_dir / "Install" / "setup.inf",
        pkg_dir / "install" / "setup.inf",
        pkg_dir / "Setup.inf",
        pkg_dir / "setup.inf",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def scan_output_directory(output_dir: Path) -> list[PackageIndexEntry]:
    """Scan an Empirum output directory and return all package entries."""
    resolved_root = output_dir.resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return []

    entries: list[PackageIndexEntry] = []
    candidates: list[Path] = []

    # 1. Identify direct subdirectories
    for item in sorted(resolved_root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue
        # Ignore common non-package folders or hidden folders
        if item.name.startswith(".") or item.name.lower() in ("__pycache__", "temp", "tmp"):
            continue

        setup_inf = _find_setup_inf(item)
        if setup_inf is not None:
            candidates.append(item)
        else:
            # Check 1 level deeper (e.g. Vendor/Product/Install/Setup.inf)
            found_sub = False
            for sub in sorted(item.iterdir(), key=lambda p: p.name.lower()):
                if sub.is_dir() and _find_setup_inf(sub) is not None:
                    candidates.append(sub)
                    found_sub = True
            # If no subpackages were found, still list the directory as a candidate
            if not found_sub:
                candidates.append(item)

    # 2. Extract metadata for each candidate
    for cand in candidates:
        setup_inf = _find_setup_inf(cand)
        has_setup_inf = setup_inf is not None

        try:
            rel_path = str(cand.relative_to(resolved_root)).replace("\\", "/")
        except ValueError:
            rel_path = cand.name

        try:
            mtime = datetime.datetime.fromtimestamp(cand.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            mtime = "-"

        if setup_inf:
            meta = _extract_setup_inf_meta(setup_inf)
            product_name = meta["product_name"] or cand.name
            version = meta["version"] or "-"
            developer_name = meta["developer_name"] or "-"
            try:
                setup_rel = str(setup_inf.relative_to(resolved_root)).replace("\\", "/")
            except ValueError:
                setup_rel = str(setup_inf)
            setup_abs = str(setup_inf.resolve())
            status = "Bereit"
        else:
            product_name = cand.name
            version = "-"
            developer_name = "-"
            setup_rel = None
            setup_abs = None
            status = "Ohne Setup.inf"

        entries.append(
            PackageIndexEntry(
                folder_name=cand.name,
                rel_path=rel_path,
                abs_path=str(cand.resolve()),
                product_name=product_name,
                version=version,
                developer_name=developer_name,
                setup_inf_rel_path=setup_rel,
                setup_inf_abs_path=setup_abs,
                has_setup_inf=has_setup_inf,
                status=status,
                modified_time=mtime,
            )
        )

    # Sort deterministically by product_name, then folder_name
    entries.sort(key=lambda e: (e.product_name.lower(), e.folder_name.lower()))
    return entries


def render_index_html(
    entries: list[PackageIndexEntry],
    output_dir: Path,
    timestamp: datetime.datetime | None = None,
) -> str:
    """Render self-contained HTML page for the package index."""
    ts = timestamp or datetime.datetime.now()
    ts_str = ts.strftime("%d.%m.%Y %H:%M:%S")
    out_path_str = str(output_dir.resolve())
    total_count = len(entries)
    ready_count = sum(1 for e in entries if e.has_setup_inf)

    # Build table rows HTML
    rows_html: list[str] = []
    for e in entries:
        prod_escaped = html.escape(e.product_name)
        ver_escaped = html.escape(e.version)
        dev_escaped = html.escape(e.developer_name)
        folder_escaped = html.escape(e.folder_name)
        rel_escaped = html.escape(e.rel_path)
        # Two contexts: JS string literal inside a double-quoted HTML attribute.
        # Escape for JS first, then HTML-escape the attribute value.
        abs_js_escaped = html.escape(e.abs_path.replace("\\", "\\\\").replace("'", "\\'"))

        # Status badge
        if e.has_setup_inf:
            badge_html = '<span class="badge badge-success">✓ Bereit</span>'
        else:
            badge_html = '<span class="badge badge-warning">⚠ Keine Setup.inf</span>'

        # Action links
        actions: list[str] = []
        actions.append(
            f'<a href="./{rel_escaped}/" class="btn btn-secondary"'
            ' title="Ordner im Browser/Explorer öffnen">📂 Ordner</a>'
        )
        if e.setup_inf_rel_path:
            setup_escaped = html.escape(e.setup_inf_rel_path)
            actions.append(
                f'<a href="./{setup_escaped}" class="btn btn-primary"'
                ' title="Setup.inf anzeigen">📄 Setup.inf</a>'
            )
        actions.append(
            f'<button type="button" class="btn btn-outline"'
            f" onclick=\"copyPath('{abs_js_escaped}', this)\""
            ' title="Vollständigen Pfad in die Zwischenablage kopieren">📋 Pfad kopieren</button>'
        )
        actions_html = " ".join(actions)

        search_data = (
            f"{prod_escaped.lower()} {ver_escaped.lower()} "
            f"{dev_escaped.lower()} {folder_escaped.lower()}"
        )
        rows_html.append(
            f"""      <tr class="package-row" data-search="{search_data}">
        <td class="col-name">
          <div class="product-title">{prod_escaped}</div>
          <div class="folder-subtext">Ordner / GUID: <code>{folder_escaped}</code></div>
        </td>
        <td class="col-ver"><span class="ver-pill">{ver_escaped}</span></td>
        <td class="col-dev">{dev_escaped}</td>
        <td class="col-status">{badge_html}</td>
        <td class="col-time">{e.modified_time}</td>
        <td class="col-actions">{actions_html}</td>
      </tr>"""
        )

    table_rows = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Paketindex – Empirum Output</title>
  <style>
    :root {{
      --bg-primary: #0f172a;
      --bg-secondary: #1e293b;
      --bg-card: #1e293b;
      --bg-card-hover: #283548;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --success: #10b981;
      --warning: #f59e0b;
      --border: #334155;
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: var(--font-family);
      background-color: var(--bg-primary);
      color: var(--text-main);
      padding: 24px 32px;
      line-height: 1.5;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }}
    .header-title h1 {{
      font-size: 26px;
      font-weight: 700;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .header-title p {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 4px;
    }}
    .header-stats {{
      display: flex;
      gap: 16px;
    }}
    .stat-card {{
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 18px;
      text-align: right;
    }}
    .stat-value {{
      font-size: 22px;
      font-weight: 700;
      color: var(--accent);
    }}
    .stat-label {{
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .search-bar-container {{
      display: flex;
      gap: 12px;
      margin-bottom: 20px;
      align-items: center;
    }}
    .search-input-wrapper {{
      position: relative;
      flex: 1;
    }}
    .search-input {{
      width: 100%;
      padding: 12px 16px 12px 42px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background-color: var(--bg-secondary);
      color: var(--text-main);
      font-size: 15px;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .search-input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
    }}
    .search-icon {{
      position: absolute;
      left: 14px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 16px;
      pointer-events: none;
    }}
    .count-indicator {{
      color: var(--text-muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    .table-container {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 14px;
    }}
    thead th {{
      background-color: #1a2234;
      padding: 14px 16px;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.5px;
    }}
    tbody tr {{
      border-bottom: 1px solid var(--border);
      transition: background-color 0.15s;
    }}
    tbody tr:hover {{
      background-color: var(--bg-card-hover);
    }}
    tbody tr:last-child {{
      border-bottom: none;
    }}
    td {{
      padding: 14px 16px;
      vertical-align: middle;
    }}
    .product-title {{
      font-weight: 600;
      font-size: 15px;
      color: var(--text-main);
    }}
    .folder-subtext {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 3px;
    }}
    .folder-subtext code {{
      background: rgba(255, 255, 255, 0.08);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: Consolas, monospace;
      color: #cbd5e1;
    }}
    .ver-pill {{
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      padding: 4px 10px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 12px;
      white-space: nowrap;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .badge-success {{
      background-color: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }}
    .badge-warning {{
      background-color: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.3);
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.15s ease-in-out;
      border: 1px solid transparent;
      user-select: none;
    }}
    .btn-primary {{
      background-color: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border-color: rgba(56, 189, 248, 0.3);
    }}
    .btn-primary:hover {{
      background-color: var(--accent);
      color: #0f172a;
    }}
    .btn-secondary {{
      background-color: rgba(148, 163, 184, 0.15);
      color: #cbd5e1;
      border-color: rgba(148, 163, 184, 0.25);
    }}
    .btn-secondary:hover {{
      background-color: rgba(148, 163, 184, 0.3);
      color: #fff;
    }}
    .btn-outline {{
      background-color: transparent;
      color: var(--text-muted);
      border-color: var(--border);
    }}
    .btn-outline:hover {{
      background-color: rgba(255, 255, 255, 0.06);
      color: var(--text-main);
      border-color: #64748b;
    }}
    .col-actions {{
      white-space: nowrap;
      text-align: right;
    }}
    .empty-state {{
      text-align: center;
      padding: 48px;
      color: var(--text-muted);
    }}
    .footer {{
      margin-top: 24px;
      font-size: 12px;
      color: var(--text-muted);
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-title">
      <h1>📦 DSM2Empirum Paket-Index</h1>
      <p>
        Übersicht aller konvertierten Empirum-Pakete &bull;
        Speicherort: <code>{html.escape(out_path_str)}</code>
      </p>
    </div>
    <div class="header-stats">
      <div class="stat-card">
        <div class="stat-value" id="stat-total">{total_count}</div>
        <div class="stat-label">Pakete Gesamt</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" id="stat-ready">{ready_count}</div>
        <div class="stat-label">Bereit</div>
      </div>
    </div>
  </div>

  <div class="search-bar-container">
    <div class="search-input-wrapper">
      <span class="search-icon">🔍</span>
      <input type="text" id="searchInput" class="search-input"
        placeholder="Pakete durchsuchen (Name, GUID, Ordner, Version, Hersteller)..." autofocus>
    </div>
    <div class="count-indicator" id="filterCount">
      Zeige {total_count} von {total_count} Paketen
    </div>
  </div>

  <div class="table-container">
    <table id="packageTable">
      <thead>
        <tr>
          <th>Paketname & Ordner</th>
          <th>Version</th>
          <th>Hersteller</th>
          <th>Status</th>
          <th>Aktualisiert</th>
          <th style="text-align: right;">Aktionen</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
    <div id="noResults" class="empty-state" style="display: none;">
      Keine passenden Pakete für diesen Suchbegriff gefunden.
    </div>
  </div>

  <div class="footer">
    Erstellt am {ts_str} durch DSM2Empirum Converter &bull; Vollständig offlinefähig
  </div>

  <script>
    // Live Search Filter
    const searchInput = document.getElementById('searchInput');
    const table = document.getElementById('packageTable');
    const rows = document.querySelectorAll('.package-row');
    const filterCount = document.getElementById('filterCount');
    const noResults = document.getElementById('noResults');
    const totalCount = {total_count};

    searchInput.addEventListener('input', function() {{
      const query = this.value.trim().toLowerCase();
      let visible = 0;

      rows.forEach(row => {{
        const text = row.getAttribute('data-search') || '';
        if (!query || text.includes(query)) {{
          row.style.display = '';
          visible++;
        }} else {{
          row.style.display = 'none';
        }}
      }});

      filterCount.textContent = `Zeige ${{visible}} von ${{totalCount}} Paketen`;
      noResults.style.display = visible === 0 ? 'block' : 'none';
      table.style.display = visible === 0 ? 'none' : 'table';
    }});

    // Clipboard Copy Helper
    function copyPath(path, btn) {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(path).then(() => {{
          showCopiedFeedback(btn);
        }}).catch(() => {{
          fallbackCopy(path, btn);
        }});
      }} else {{
        fallbackCopy(path, btn);
      }}
    }}

    function fallbackCopy(text, btn) {{
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      try {{
        document.execCommand('copy');
        showCopiedFeedback(btn);
      }} catch (err) {{
        alert('Kopieren fehlgeschlagen: ' + text);
      }}
      document.body.removeChild(textArea);
    }}

    function showCopiedFeedback(btn) {{
      const originalText = btn.innerHTML;
      btn.innerHTML = '✓ Kopiert!';
      btn.style.color = '#34d399';
      btn.style.borderColor = '#10b981';
      setTimeout(() => {{
        btn.innerHTML = originalText;
        btn.style.color = '';
        btn.style.borderColor = '';
      }}, 1500);
    }}
  </script>
</body>
</html>
"""


def generate_package_index(output_dir: Path) -> Path:
    """Scan output directory, generate Paketindex.html, and write to disk.

    Returns the absolute Path to the generated Paketindex.html.
    """
    resolved = output_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)

    entries = scan_output_directory(resolved)
    html_content = render_index_html(entries, resolved)

    index_file = resolved / "Paketindex.html"
    index_file.write_text(html_content, encoding="utf-8")
    return index_file
