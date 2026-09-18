from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .backup import (
    analyse_bridge_restore,
    create_bridge_backup,
    load_bridge_backup,
    restore_bridge_backup,
    save_bridge_backup,
)
from .client import HueApiError, HueBridgeClient
from .config import BridgeProfile, ConfigStore
from .migration import (
    MigrationError,
    analyse,
    apply_snapshot,
    create_selection_snapshot,
    load_snapshot,
    save_snapshot,
)

app = typer.Typer(help="Selective Philips Hue migration between bridges.")
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
def discover() -> None:
    """Discover local Hue bridges through the official Hue discovery broker."""
    try:
        data = HueBridgeClient.discover()
    except Exception as exc:
        console.print(f"[red]Discovery failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print_json(data=data)


@app.command()
def rooms(bridge: str) -> None:
    """List rooms exposed by a bridge."""
    client = _client(bridge)
    table = Table("Room", "v2 id", "v1 id", "devices")
    room_list = sorted(
        client.v2_get("room"),
        key=lambda x: x.get("metadata", {}).get("name", ""),
    )
    for room in room_list:
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
    room: list[str] = typer.Option(..., "--room", "-r", help="Room to include; repeatable"),
    output: Path = typer.Option(..., "--output", "-o", help="Snapshot JSON path"),
) -> None:
    """Export a non-destructive migration snapshot for one or more rooms."""
    try:
        payload = create_selection_snapshot(_client(bridge), room)
        save_snapshot(payload, output)
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Snapshot failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    external = sum(1 for item in payload.get("dependencies", []) if item.get("external"))
    external_v2 = sum(
        1 for item in payload.get("behavior_dependencies", []) if item.get("external")
    )
    console.print(
        f"[green]Snapshot saved[/green] {output}: "
        f"{len(payload['rooms'])} rooms, "
        f"{len(payload['devices'])} devices, "
        f"{len(payload['scenes'])} scenes, "
        f"{len(payload['v1']['rules'])} rules, "
        f"{len(payload.get('behavior_instances', []))} v2 automation(s), "
        f"{external + external_v2} configuration(s) with external dependencies"
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


@app.command("backup")
def backup_cmd(
    bridge: str,
    output: Path = typer.Option(..., "--output", "-o", help="Backup JSON path"),
) -> None:
    """Create a full bridge archive plus a portable logical restore snapshot."""
    try:
        payload = create_bridge_backup(_client(bridge))
        save_bridge_backup(payload, output)
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Backup failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    raw_v1 = payload.get("raw", {}).get("clip_v1", {})
    logical = payload.get("logical_restore", {})
    console.print(
        f"[green]Backup saved[/green] {output}: "
        f"{len(raw_v1.get('lights', {}))} lights, "
        f"{len(raw_v1.get('sensors', {}))} sensors, "
        f"{len(logical.get('rooms', []))} rooms, "
        f"{len(logical.get('zones', []))} zones, "
        f"{len(logical.get('behavior_instances', []))} v2 automations"
    )


@app.command("restore")
def restore_cmd(
    backup_file: Path,
    destination: str,
    execute: bool = typer.Option(False, "--execute", help="Actually restore resources"),
) -> None:
    """Plan or restore a full bridge backup after physical devices are re-paired."""
    try:
        payload = load_bridge_backup(backup_file)
        client = _client(destination)
        report = analyse_bridge_restore(payload, client)
        if not execute:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print(
                "[yellow]Dry-run only.[/yellow] Re-run with --execute after every "
                "physical light/accessory has been paired to the destination."
            )
            if not report["ready"]:
                raise typer.Exit(2)
            return
        if not report["ready"]:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print("[red]Restore aborted:[/red] physical resources are missing.")
            raise typer.Exit(2)
        result = restore_bridge_backup(payload, client, prune_external=False)
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Restore failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(json.dumps(result, indent=2, ensure_ascii=False))
    console.print(
        "[green]Logical restore completed.[/green] Zigbee pairing/network keys are not restored."
    )


@app.command()
def scan(destination: str, kind: str = typer.Option("lights", help="lights or sensors")) -> None:
    """Start a destination-bridge search for lights or accessories."""
    try:
        if kind == "lights":
            result = _client(destination).v1_post("/lights", {})
        elif kind == "sensors":
            result = _client(destination).v1_post("/sensors", {})
        else:
            raise typer.BadParameter("kind must be lights or sensors")
    except (HueApiError, OSError) as exc:
        console.print(f"[red]Scan failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(result)


@app.command()
def apply(
    snapshot_file: Path,
    destination: str,
    execute: bool = typer.Option(False, "--execute", help="Actually create resources"),
    keep_external_strict: bool = typer.Option(
        False,
        "--keep-external-strict",
        help="Skip rules with out-of-scope references instead of pruning them",
    ),
) -> None:
    """Apply a snapshot. Without --execute this is a dry-run only."""
    try:
        payload = load_snapshot(snapshot_file)
        client = _client(destination)
        report = analyse(payload, client)

        if not execute:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print("[yellow]Dry-run only.[/yellow] Re-run with --execute to create resources.")
            if not report["ready"]:
                raise typer.Exit(2)
            return

        if not report["ready"]:
            console.print(json.dumps(report, indent=2, ensure_ascii=False))
            console.print("[red]Aborted:[/red] physical resources are still missing on destination.")
            raise typer.Exit(2)

        result = apply_snapshot(
            payload,
            client,
            prune_external=not keep_external_strict,
        )
    except (MigrationError, HueApiError, OSError) as exc:
        console.print(f"[red]Migration failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(json.dumps(result, indent=2, ensure_ascii=False))
    console.print("[green]Done.[/green] The source bridge was not modified.")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Listen address"),
    port: int = typer.Option(8787, help="Listen port"),
) -> None:
    """Start the local HueManager web interface."""
    from .web import run

    console.print(f"HueManager web: http://{host}:{port}")
    run(host=host, port=port)


if __name__ == "__main__":
    app()
