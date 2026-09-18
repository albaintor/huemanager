from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .client import HueApiError, HueBridgeClient
from .config import BridgeProfile, ConfigStore
from .migration import (
    MigrationError,
    analyse,
    apply_snapshot,
    create_snapshot,
    load_snapshot,
    save_snapshot,
)

app = typer.Typer(help="Selective Philips Hue room migration between bridges.")
console = Console()


def _client(name: str) -> HueBridgeClient:
    try:
        profile = ConfigStore().get_bridge(name)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return HueBridgeClient(profile)


@app.command()
def pair(
    name: str = typer.Argument(..., help="Local profile name, e.g. old or pro"),
    host: str = typer.Argument(..., help="Bridge IP address or hostname"),
    verify_tls: bool = typer.Option(False, help="Verify bridge TLS certificate"),
) -> None:
    """Pair HueManager with a bridge. Press the bridge link button first."""
    try:
        credentials = HueBridgeClient.pair(host, verify_tls=verify_tls)
    except Exception as exc:
        console.print(f"[red]Pairing failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    ConfigStore().save_bridge(
        name,
        BridgeProfile(
            host=host,
            app_key=credentials["username"],
            client_key=credentials.get("clientkey"),
            verify_tls=verify_tls,
        ),
    )
    console.print(f"[green]Saved bridge profile[/green] {name!r} ({host})")


@app.command("bridges")
def bridges_cmd() -> None:
    table = Table("Name", "Host", "TLS verification")
    for name, bridge in ConfigStore().list_bridges().items():
        table.add_row(name, bridge.host, "yes" if bridge.verify_tls else "no")
    console.print(table)


@app.command()
def rooms(bridge: str) -> None:
    """List rooms exposed by a bridge."""
    client = _client(bridge)
    table = Table("Room", "v2 id", "v1 id", "devices")
    rooms = sorted(
        client.v2_get("room"),
        key=lambda x: x.get("metadata", {}).get("name", ""),
    )
    for room in rooms:
        table.add_row(
            room.get("metadata", {}).get("name", "?"),
            room.get("id", "?"),
            room.get("id_v1", "-"),
            str(len(room.get("children", []))),
        )
    console.print(table)


@app.command()
def snapshot(
    bridge: str,
    room: str = typer.Option(..., "--room", "-r", help="Exact Hue room name"),
    output: Path = typer.Option(..., "--output", "-o", help="Snapshot JSON path"),
) -> None:
    """Export a non-destructive migration snapshot for one room."""
    try:
        payload = create_snapshot(_client(bridge), room)
        save_snapshot(payload, output)
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Snapshot failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(
        f"[green]Snapshot saved[/green] {output}: "
        f"{len(payload['devices'])} devices, "
        f"{len(payload['scenes'])} scenes, "
        f"{len(payload['v1']['rules'])} dependent rules"
    )


@app.command()
def plan(snapshot_file: Path, destination: str) -> None:
    """Check whether snapshotted physical resources are paired to destination."""
    try:
        result = analyse(load_snapshot(snapshot_file), _client(destination))
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Plan failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ready"]:
        raise typer.Exit(2)


@app.command()
def scan(destination: str) -> None:
    """Start a destination-bridge search for new lights."""
    try:
        result = _client(destination).v1_post("/lights", {})
    except (HueApiError, OSError) as exc:
        console.print(f"[red]Scan failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(result)
    console.print(
        "Light search started. Pair/reset accessories with the Hue app as required."
    )


@app.command()
def apply(
    snapshot_file: Path,
    destination: str,
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Actually create room/scenes/rules",
    ),
    room_name: str | None = typer.Option(
        None,
        help="Override destination room name",
    ),
) -> None:
    """Apply a snapshot. Without --execute this is a dry-run only."""
    try:
        payload = load_snapshot(snapshot_file)
        client = _client(destination)
        report = analyse(payload, client)

        if not execute:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print(
                "[yellow]Dry-run only.[/yellow] "
                "Re-run with --execute to create resources."
            )
            if not report["ready"]:
                raise typer.Exit(2)
            return

        if not report["ready"]:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print(
                "[red]Aborted:[/red] not every physical resource is paired "
                "to the destination."
            )
            raise typer.Exit(2)

        result = apply_snapshot(payload, client, room_name=room_name)
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Migration failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(json.dumps(result, indent=2, ensure_ascii=False))
    console.print("[green]Done.[/green] The source bridge was not modified.")


if __name__ == "__main__":
    app()
