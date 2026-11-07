"""CLI interface for DSM2Empirum."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from dsm2emp import __version__
from dsm2emp.validator import validate_file

app = typer.Typer(
    name="dsm2emp",
    help="Migration tool: Ivanti DSM packages to Matrix42 Empirum Setup.inf",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold green]dsm2emp[/bold green] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DSM2Empirum CLI Entry Point."""
    pass


@app.command()
def selftest() -> None:
    """Run self tests and reference verification on a synthetic package."""
    import tempfile

    from dsm2emp.fixtures.make_packages import create_p01_pure_msi
    from dsm2emp.orchestrator import MigrationOptions, migrate_single

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        pkg_src = create_p01_pure_msi(root / "source")
        pkg_tgt = root / "target"
        res = migrate_single(pkg_src, pkg_tgt, MigrationOptions(developer_name="Matrix42"))
        if not res.success or res.exit_code not in (0, 1):
            console.print(f"[bold red]Selftest failed: {res.error_message}[/bold red]")
            raise typer.Exit(code=1)

        inf_path = pkg_tgt / "Install" / "Setup.inf"
        if not inf_path.exists():
            console.print("[bold red]Selftest failed: Setup.inf not created[/bold red]")
            raise typer.Exit(code=1)

    console.print("[bold green]DSM2Empirum self-test: OK[/bold green]")


@app.command()
def scan(
    source_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to DSM package source directory to scan.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
) -> None:
    """Scan and inventory a DSM software package in read-only mode."""
    from dsm2emp.scanner.scanner import scan as scan_pkg

    inv = scan_pkg(source_dir)
    table = Table(title=f"Package Inventory: {source_dir.name}")
    table.add_column("Relative Path", style="bold cyan")
    table.add_column("Kind", style="green")
    table.add_column("Size", justify="right")
    table.add_column("Encoding")
    table.add_column("Hash (SHA-256 preview)")
    table.add_column("Reason / Notes")

    for a in inv.artifacts:
        kind_color = "green" if a.kind != "unknown" else "yellow"
        enc_info = a.encoding or ("Binary" if a.is_binary else "n/a")
        table.add_row(
            str(a.rel_path),
            f"[{kind_color}]{a.kind}[/{kind_color}]",
            str(a.size_bytes),
            enc_info,
            f"{a.sha256[:12]}...",
            a.reason or "",
        )

    console.print(table)
    console.print(
        f"Artifacts: [bold]{len(inv.artifacts)}[/bold] total | "
        f"Scripts: [bold]{len(inv.scripts)}[/bold] | "
        f"Media: [bold]{len(inv.media)}[/bold] | "
        f"Registry: [bold]{len(inv.nirs + inv.regs)}[/bold] | "
        f"Unknown: [bold yellow]{len(inv.unknowns)}[/bold yellow]"
    )
    console.print(f"Tree Hash: [bold green]{inv.tree_hash}[/bold green]")


@app.command()
def migrate(
    source_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to DSM package source directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    target_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to target Empirum package directory.",
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite target directory if not empty."),
    ] = False,
    charset: Annotated[
        str,
        typer.Option(
            "--charset",
            "-c",
            help="Output Setup.inf charset: cp1252 (default, Empirum ANSI), utf-8, utf-16",
        ),
    ] = "cp1252",
    developer_name: Annotated[
        str,
        typer.Option("--developer-name", help="Developer / vendor name"),
    ] = "Matrix42",
    product_name: Annotated[
        str | None,
        typer.Option("--product-name", help="Product name override"),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version-str", help="Package version override"),
    ] = None,
    rules_file: Annotated[
        Path | None,
        typer.Option("--rules-file", help="Optional custom rules.yaml path"),
    ] = None,
    allow_undocumented: Annotated[
        bool,
        typer.Option(
            "--allow-undocumented",
            help=(
                "Allow undocumented class-1 interpreter commands "
                "(CollapseEnv, RenDir, Extract, BlockInput)"
            ),
        ),
    ] = False,
) -> None:
    """Migrate an Ivanti DSM package to a Matrix42 Empirum package."""
    from dsm2emp.orchestrator import MigrationOptions, migrate_single

    valid_charset = charset if charset in ("cp1252", "utf-8", "utf-16") else "cp1252"
    opts = MigrationOptions(
        charset=valid_charset,  # type: ignore[arg-type]
        force=force,
        developer_name=developer_name,
        product_name=product_name,
        version=version,
        rules_path=rules_file,
        allow_undocumented=allow_undocumented,
    )

    console.print(f"Starting migration: [cyan]{source_dir}[/cyan] -> [green]{target_dir}[/green]")
    res = migrate_single(source_dir, target_dir, opts)

    if not res.success:
        console.print(
            f"[bold red]Migration FAILED (Exit {res.exit_code}):[/bold red] {res.error_message}"
        )
        if res.issues:
            for issue in res.issues:
                if issue.severity == "error":
                    console.print(f"  [red]Error:[/red] {issue.message}")
        raise typer.Exit(code=res.exit_code)

    console.print(f"[bold green]Migration SUCCEEDED[/bold green] (Exit {res.exit_code})")
    console.print(f"Output package written to: [bold]{target_dir}[/bold]")
    if res.transform_result:
        avg_pct = res.transform_result.average_confidence * 100
        console.print(
            f"Average confidence: [bold green]{avg_pct:.1f}%[/bold green] | "
            f"Traces: {len(res.transform_result.traces)} | "
            f"TODOs: {res.transform_result.todo_count}"
        )
    raise typer.Exit(code=res.exit_code)


@app.command()
def batch(
    source_dir: Annotated[
        Path,
        typer.Argument(
            help="Root directory containing DSM software packages to migrate.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    target_dir: Annotated[
        Path,
        typer.Argument(
            help="Target root directory for converted Empirum packages.",
        ),
    ],
    jobs: Annotated[
        int,
        typer.Option("--jobs", "-j", help="Number of concurrent worker threads"),
    ] = 1,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from state.ndjson skipping completed packages"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow writing into non-empty target directories"),
    ] = False,
    charset: Annotated[
        str,
        typer.Option(
            "--charset", help="Target encoding (cp1252 default/Empirum ANSI, utf-8, utf-16)"
        ),
    ] = "cp1252",
    developer_name: Annotated[
        str,
        typer.Option("--developer", help="Developer/Manufacturer override"),
    ] = "Matrix42",
    rules_file: Annotated[
        Path | None,
        typer.Option("--rules-file", help="Optional custom rules.yaml path"),
    ] = None,
    allow_undocumented: Annotated[
        bool,
        typer.Option(
            "--allow-undocumented",
            help=(
                "Allow undocumented class-1 interpreter commands "
                "(CollapseEnv, RenDir, Extract, BlockInput)"
            ),
        ),
    ] = False,
) -> None:
    """Migrate a batch of Ivanti DSM packages concurrently with state tracking."""
    from dsm2emp.batch import BatchOptions, migrate_batch

    valid_charset = charset if charset in ("cp1252", "utf-8", "utf-16") else "cp1252"
    opts = BatchOptions(
        jobs=jobs,
        resume=resume,
        force=force,
        charset=valid_charset,  # type: ignore[arg-type]
        developer_name=developer_name,
        rules_path=rules_file,
        allow_undocumented=allow_undocumented,
    )

    console.print(
        f"Starting batch migration: [cyan]{source_dir}[/cyan] -> [green]{target_dir}[/green]"
    )
    res = migrate_batch(source_dir, target_dir, opts)

    console.print(
        f"[bold]Batch Summary:[/bold] Total: {res.total_packages} | "
        f"[green]Clean: {res.successful}[/green] | "
        f"[yellow]Warnings: {res.warnings}[/yellow] | "
        f"[red]Failed: {res.failed}[/red] | "
        f"[cyan]Skipped: {res.skipped}[/cyan]"
    )
    index_file = target_dir / "Paketindex.html"
    if index_file.exists():
        console.print(f"[bold green]Paketindex generiert:[/bold green] {index_file}")
    raise typer.Exit(code=res.overall_exit_code)


@app.command()
def index(
    output_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing converted Empirum packages (e.g. Empirum_Output).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
) -> None:
    """Generate or refresh Paketindex.html for an Empirum output directory."""
    from dsm2emp.report.index_page import generate_package_index

    console.print(f"Scanning packages and generating index in: [cyan]{output_dir}[/cyan]")
    index_path = generate_package_index(output_dir)
    console.print(f"[bold green]Paketindex erfolgreich erstellt:[/bold green] {index_path}")


@app.command()
def validate(
    inf_file: Annotated[
        Path,
        typer.Argument(
            help="Path to Setup.inf file to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
) -> None:
    """Validate a Matrix42 Empirum Setup.inf file for syntax and semantic correctness."""
    issues = validate_file(inf_file)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if not issues:
        console.print(f"[bold green]OK:[/bold green] '{inf_file}' is valid (0 errors, 0 warnings).")
        raise typer.Exit(code=0)

    table = Table(title=f"Validation Results: {inf_file.name}")
    table.add_column("Severity", style="bold")
    table.add_column("Code")
    table.add_column("Message")

    for i in issues:
        color = "red" if i.severity == "error" else "yellow" if i.severity == "warning" else "blue"
        table.add_row(f"[{color}]{i.severity.upper()}[/{color}]", i.code, i.message)

    console.print(table)
    summary_msg = (
        f"Total: [bold red]{len(errors)} errors[/bold red], "
        f"[bold yellow]{len(warnings)} warnings[/bold yellow]."
    )
    console.print(summary_msg)

    if errors:
        raise typer.Exit(code=2)
    if warnings:
        raise typer.Exit(code=1)


rules_app = typer.Typer(help="Manage and inspect transformation rules.", no_args_is_help=True)
app.add_typer(rules_app, name="rules")


@rules_app.command(name="list")
def rules_list(
    rules_path: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Optional path to custom rules.yaml"),
    ] = None,
) -> None:
    """List all available transformation rules."""
    from dsm2emp.rules.loader import load_rules

    ruleset = load_rules(rules_path)
    table = Table(title=f"Transformation Rules (Version {ruleset.version})")
    table.add_column("ID", style="bold cyan")
    table.add_column("Category", style="green")
    table.add_column("Kind")
    table.add_column("Confidence")
    table.add_column("Description")

    for r in ruleset.rules:
        conf_color = (
            "green" if r.confidence == "high" else "yellow" if r.confidence == "medium" else "red"
        )
        table.add_row(
            r.id,
            r.category,
            r.kind,
            f"[{conf_color}]{r.confidence}[/{conf_color}]",
            r.description,
        )

    console.print(table)
    console.print(f"Total rules: [bold]{len(ruleset.rules)}[/bold]")


@rules_app.command(name="lint")
def rules_lint(
    rules_path: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Optional path to custom rules.yaml"),
    ] = None,
) -> None:
    """Validate rule definitions for completeness, uniqueness, and consistency."""
    from dsm2emp.rules.loader import lint_rules, load_rules

    ruleset = load_rules(rules_path)
    issues = lint_rules(ruleset)

    if not issues:
        count = len(ruleset.rules)
        console.print(
            f"[bold green]OK:[/bold green] Rule set is valid ({count} rules checked, 0 issues)."
        )
        raise typer.Exit(code=0)

    for issue in issues:
        console.print(f"[bold red]ERROR:[/bold red] {issue}")
    console.print(f"[bold red]Failed:[/bold red] Found {len(issues)} issues in rule definitions.")
    raise typer.Exit(code=1)


@app.command(name="gui")
def gui_cmd() -> None:
    """Launch the PySide6 Graphical User Interface."""
    try:
        from dsm2emp.gui.app import run_gui
    except ImportError as exc:
        console.print(
            f"[bold red]GUI error:[/bold red] PySide6 not installed or failed to load: {exc}\n"
            "Please install with: pip install dsm2emp[gui]"
        )
        raise typer.Exit(code=64) from exc
    exit_code = run_gui()
    raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
