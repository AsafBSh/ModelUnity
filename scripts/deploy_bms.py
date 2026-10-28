"""
deploy_bms — copy a generated LOD set into a Falcon BMS theater.

This is the LAST step of the workflow, AFTER you've used Blender + the
BMS Blender Plugin to convert each Model_N.glb into Model_N.bml + Materials.mtl
+ Parent.dat. See docs/BMS_WORKFLOW.md for the manual steps.

Usage:
    python scripts/deploy_bms.py <bms_export/asset_name> --parent-id 12345

This copies:
    <bms_export>/<name>/Model_0.bml .. Model_6.bml
    <bms_export>/<name>/Parent.dat
    <bms_export>/<name>/Materials.mtl
    <bms_export>/<name>/*.dds                 (textures)

...into:
    <BMS install>/Data/TerrData/Objects/Models/<parent-id>/
    <BMS install>/Data/TerrData/Objects/KoreaObj/*.dds      (textures)
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import typer
from rich import print

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine import load_config        # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Deploy a Blender-exported BML asset into a Falcon BMS theater.")


@app.command()
def deploy(
    asset_dir: Path = typer.Argument(..., exists=True, file_okay=False,
                                     help="Folder containing Model_0.bml..Model_6.bml + Parent.dat + Materials.mtl + textures"),
    parent_id: int = typer.Option(..., "--parent-id", help="Numeric model ID — must be unused in the DB"),
    bms_install: Optional[Path] = typer.Option(None, "--bms-install",
                                               help="Override BMS root. Default: from config.yaml"),
    theater_obj_folder: str = typer.Option("KoreaObj", "--obj-folder",
                                           help="Texture folder under TerrData/Objects (e.g. KoreaObj, BalkansObj)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Explicitly allow replacing existing destination files"),
):
    cfg = load_config()
    bms_root = bms_install or (cfg.get("bms", {}) or {}).get("bms_install")
    if not bms_root:
        print("[red]No BMS install path configured. Set bms.bms_install in config.yaml or pass --bms-install.[/red]")
        raise typer.Exit(2)
    bms_root = Path(bms_root)
    if not bms_root.exists():
        print(f"[red]BMS install path does not exist:[/red] {bms_root}")
        raise typer.Exit(2)

    models_root = bms_root / "Data" / "TerrData" / "Objects" / "Models"
    obj_root = bms_root / "Data" / "TerrData" / "Objects" / theater_obj_folder
    target = models_root / str(parent_id)
    if parent_id < 0 or not theater_obj_folder or theater_obj_folder in (".", "..") or any(c in theater_obj_folder for c in '/\\:'):
        raise typer.BadParameter("Use a nonnegative parent ID and a single texture folder name.")
    objects = (bms_root / "Data" / "TerrData" / "Objects").resolve()
    if not objects.is_dir():
        raise typer.BadParameter("BMS root must contain Data/TerrData/Objects.")
    if not target.resolve().is_relative_to(objects) or not obj_root.resolve().is_relative_to(objects):
        raise typer.BadParameter("Deployment destination escapes the Objects directory.")

    # Required files
    required = ["Parent.dat", "Materials.mtl"]
    bml_files = sorted(asset_dir.glob("Model_*.bml"))
    if not bml_files:
        print(f"[red]No Model_*.bml files in {asset_dir}. "
              "Did you run the BMS Blender Plugin export yet?[/red]")
        raise typer.Exit(2)
    for r in required:
        if not (asset_dir / r).exists():
            print(f"[red]Missing {r} in {asset_dir}[/red]")
            raise typer.Exit(2)

    import re
    indices = []
    for file in bml_files:
        match = re.fullmatch(r"Model_([0-6])\.bml", file.name)
        if not match or not file.is_file() or file.stat().st_size == 0:
            raise typer.BadParameter(f"Invalid/empty BML file: {file.name}")
        indices.append(int(match[1]))
    if sorted(indices) != list(range(len(indices))):
        raise typer.BadParameter("BML levels must be contiguous starting at Model_0.")
    for filename in required:
        if not (asset_dir / filename).is_file() or (asset_dir / filename).stat().st_size == 0:
            raise typer.BadParameter(f"Empty required file: {filename}")
    # A Wavefront MTL is not the BMS exporter's JSON Materials.mtl.
    import json
    try:
        json.loads((asset_dir / 'Materials.mtl').read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise typer.BadParameter("Materials.mtl must be the BMS exporter's JSON, not a Wavefront MTL.") from exc

    dds_files = sorted(asset_dir.glob("*.dds"))
    plan = [(f, target / f.name) for f in bml_files]
    plan += [(asset_dir / r, target / r) for r in required]
    plan += [(f, target / f.name) for f in sorted(asset_dir.glob("Model_*.mti"))]
    plan += [(f, obj_root / f.name) for f in dds_files]
    for source, destination in plan:
        if source.resolve() == destination.resolve():
            raise typer.BadParameter("Source and destination must differ.")
        if destination.is_symlink() or not destination.resolve().is_relative_to(objects):
            raise typer.BadParameter(f"Refusing a symlink destination: {destination}")
    conflicts = [str(dst) for _, dst in plan if dst.exists()]
    if not overwrite and (conflicts or target.exists()):
        raise typer.BadParameter("Destination is occupied; choose an unused parent ID or explicitly use --overwrite. " + ', '.join(conflicts))

    # All validation and collision checks finish before the first filesystem write.
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        if dds_files:
            obj_root.mkdir(parents=True, exist_ok=True)

    print(f"[cyan]→ Target model folder:[/cyan] {target}")
    print(f"[cyan]→ Target texture folder:[/cyan] {obj_root}")

    def _copy(src: Path, dst: Path):
        msg = f"  {'[dry]' if dry_run else '[copy]'} {src.name}  ->  {dst}"
        print(msg)
        if not dry_run:
            shutil.copy2(src, dst)

    # Copy BML + Parent.dat + Materials.mtl into the numbered model folder.
    for f in bml_files:
        _copy(f, target / f.name)
    _copy(asset_dir / "Parent.dat", target / "Parent.dat")
    _copy(asset_dir / "Materials.mtl", target / "Materials.mtl")

    # Optional per-LOD material indexers.
    for mti in asset_dir.glob("Model_*.mti"):
        _copy(mti, target / mti.name)

    # Textures: DDS files go in the theater's KoreaObj-style folder.
    dds_files = list(asset_dir.glob("*.dds"))
    if not dds_files:
        print("[yellow]No .dds textures found in asset folder — that's OK if your model is untextured "
              "or you've already placed them manually.[/yellow]")
    for d in dds_files:
        _copy(d, obj_root / d.name)

    verb = "Planned (dry run)" if dry_run else "Deployed"
    print(f"[green]✓ {verb} asset {asset_dir.name} as parent id {parent_id}[/green]")
    print(f"[yellow]Next:[/yellow] open the Falcon BMS Editor and verify model {parent_id} loads correctly.")


if __name__ == "__main__":
    app()
