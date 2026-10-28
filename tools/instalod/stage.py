"""
Copy a ModelUnify master GLB into tools/instalod/inbox for InstaLOD Studio.

Pioneer InstaLOD has no CLI — this script only stages files.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# tools/instalod/stage.py → repo root
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_config() -> dict:
    """Read config.yaml without importing scripts.engine (avoids torch/trimesh)."""
    path = ROOT / "config.yaml"
    try:
        import yaml  # project dependency
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {
            "paths": {
                "instalod_dir": "tools/instalod",
                "bms_export_dir": "bms_export",
                "outputs_dir": "outputs",
            }
        }


def _instalod_root(cfg: dict) -> Path:
    rel = (cfg.get("paths") or {}).get("instalod_dir", "tools/instalod")
    return (ROOT / rel).resolve()


def _bms_export_root(cfg: dict) -> Path:
    rel = (cfg.get("paths") or {}).get("bms_export_dir", "bms_export")
    return (ROOT / rel).resolve()


def _outputs_root(cfg: dict) -> Path:
    rel = (cfg.get("paths") or {}).get("outputs_dir", "outputs")
    return (ROOT / rel).resolve()


def resolve_source_glb(
    cfg: dict,
    name: Optional[str],
    glb: Optional[Path],
) -> tuple[Path, str]:
    """Return (source_glb, asset_name)."""
    if glb is not None:
        src = Path(glb).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"GLB not found: {src}")
        asset = (name or src.stem).strip()
        if not asset:
            raise ValueError("Asset name is empty.")
        return src, asset

    if not name or not str(name).strip():
        raise ValueError("Pass --name <asset> or --glb <path>.")

    asset = str(name).strip()
    if Path(asset).name != asset or asset in ('.', '..') or any(c in asset for c in '/\\:'):
        raise ValueError('Asset name must be a single directory name.')
    asset_dir = _bms_export_root(cfg) / asset
    master = asset_dir / "Model_0.glb"
    if master.is_file():
        return master.resolve(), asset

    current_output = _outputs_root(cfg) / asset / f'{asset}.glb'
    if current_output.is_file():
        return current_output.resolve(), asset
    out_glb = _outputs_root(cfg) / f"{asset}.glb"
    if out_glb.is_file():
        return out_glb.resolve(), asset

    raise FileNotFoundError(
        f"No Model_0.glb in {asset_dir} and no {out_glb}. "
        "Generate the asset first or pass --glb."
    )


def stage_master(
    name: Optional[str] = None,
    glb: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """Copy the master mesh to inbox/<name>/Model_0.glb. Returns dest path."""
    cfg = load_config()
    src, asset = resolve_source_glb(cfg, name, glb)
    if Path(asset).name != asset or asset in ('.', '..') or any(c in asset for c in '/\\:'):
        raise ValueError('Asset name must be a single directory name.')
    dest_dir = _instalod_root(cfg) / "inbox" / asset
    dest = dest_dir / "Model_0.glb"
    if dest.exists() and not overwrite:
        raise FileExistsError(f'Refusing overwrite: {dest}. Use a fresh name or --overwrite.')
    if dest.is_symlink() or not dest.resolve().is_relative_to(_instalod_root(cfg)):
        raise ValueError('Staging destination escapes its workspace.')
    print(f'Source: {src}; destination: {dest}; copying GLB intact (UVs/materials/hierarchy retained).')
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _print_next_steps(dest: Path, cfg: dict) -> None:
    instalod = _instalod_root(cfg)
    asset = dest.parent.name
    profiles = instalod / "profiles"
    saved = list(profiles.glob("*.json"))
    print(f"Staged: {dest}")
    print()
    print("Next (InstaLOD Studio — Pioneer GUI, not this script):")
    print(f"  1. Import {dest}")
    if saved:
        print(f"  2. File → Open Profile: {saved[0]}")
    else:
        print(f"  2. Build the profile from {profiles / 'RECIPES.md'}")
        print("     then File → Save Profile into tools/instalod/profiles/")
    print("  3. Click Start")
    print(f"  4. Export Model_1.glb … Model_6.glb to {instalod / 'outbox' / asset}")
    print(f"  5. Copy those over bms_export/{asset}/ (keep Model_0 from ModelUnify)")
    print("  6. Continue Blender + BMS plugin for .bml")


def main(argv: Optional[list[str]] = None) -> int:
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    parser = argparse.ArgumentParser(
        description="Stage a ModelUnify GLB into tools/instalod/inbox for InstaLOD Studio.",
    )
    parser.add_argument("--name", "-n", default=None,
                        help="Asset folder name under bms_export/ (or outputs/<name>.glb)")
    parser.add_argument("--glb", type=Path, default=None,
                        help="Explicit master GLB path")
    parser.add_argument('--overwrite', action='store_true', help='Explicitly replace an existing staged master')
    args = parser.parse_args(argv)
    try:
        dest = stage_master(name=args.name, glb=args.glb, overwrite=args.overwrite)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    _print_next_steps(dest, load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
