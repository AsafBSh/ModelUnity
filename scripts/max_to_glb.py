"""
Convert an Autodesk 3ds Max scene (.max) to GLB/OBJ via headless Blender.

Why Blender: `.max` is a proprietary, undocumented scene format. trimesh,
pymeshlab and assimp all lack a reader, and no Autodesk license is available
in this pipeline. The only free option that parses `.max` directly is the
Blender extension `io_scene_max` (Sebastian Sille / NRGSille), a pure-Python
parser built on olefile and FreeCAD's Importer3D.

That extension is **GPL-2.0**, so it is deliberately NOT vendored into this
repo — we invoke Blender as a separate process instead, which keeps
ModelUnify's own licensing unaffected.

Platform: Windows-native like the rest of ModelUnify; the Blender lookup also
covers common Linux/macOS paths. No GPU required, this is CPU-only parsing.

Setup (one time):
    1. Install Blender 4.2+          winget install BlenderFoundation.Blender
    2. Blender > Edit > Preferences > Get Extensions > search "Autodesk MAX"
       > Install. (Or: Add-ons > Install from Disk with the repo zip from
       https://github.com/nrgsille76/io_scene_max)

Usage:
    python scripts/max_to_glb.py inputs/ground/Rampage/rampage.max
    python scripts/max_to_glb.py <file.max> --out outputs/rampage.glb --format obj
    python scripts/max_to_glb.py <file.max> --inspect        # report only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Streams that every 3ds Max scene container carries. Their presence is how we
# tell a real .max from a renamed file before spending time on Blender startup.
_MAX_STREAMS = ("Scene", "ClassDirectory3", "ClassData")

_ADDON_MODULES = (
    # Extension id (Blender 4.2+ extensions platform) then legacy add-on names.
    "bl_ext.blender_org.io_scene_max",
    "bl_ext.user_default.io_scene_max",
    "io_scene_max",
    "io_import_max",
)


def load_config() -> dict:
    """Read config.yaml without importing scripts.engine (avoids torch)."""
    try:
        import yaml
        with (ROOT / "config.yaml").open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Pre-flight: can this file be parsed at all?
# ---------------------------------------------------------------------------

def inspect_max(path: Path) -> dict:
    """Report what's inside a .max before attempting conversion.

    Catches the two failure modes that otherwise waste a Blender launch:
    a file that isn't really a .max, and the compressed container Autodesk
    introduced in 3ds Max 2024 which `io_scene_max` cannot read.
    """
    info: dict = {"path": str(path), "size": path.stat().st_size if path.exists() else -1}
    if not path.exists():
        info["error"] = "file does not exist"
        return info

    with path.open("rb") as f:
        magic = f.read(8)
    info["ole2"] = magic == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if not info["ole2"]:
        info["error"] = (f"not an OLE2 compound document (magic {magic.hex(' ')}). "
                         "A .max saved by 3ds Max 2024+ with the new compression, "
                         "or a mislabelled file.")
        return info

    try:
        import olefile
    except ImportError:
        info["error"] = "olefile not installed - run: pip install olefile"
        return info

    ole = olefile.OleFileIO(str(path))
    try:
        streams = {"/".join(s): ole.get_size(s) for s in ole.listdir()}
        info["streams"] = streams
        missing = [s for s in _MAX_STREAMS if s not in streams]
        if missing:
            info["error"] = f"missing expected 3ds Max streams: {missing}"
            return info

        # A compressed 2024+ scene keeps the OLE2 shell but the Scene stream is
        # a deflate blob rather than Max's chunk format. Chunk headers start
        # with a 2-byte id + 4-byte length, so a plausible length near the top
        # is a decent uncompressed signal; zlib/zip magic is a definite fail.
        head = ole.openstream("Scene").read(4096)
        info["scene_bytes"] = streams.get("Scene", 0)
        if head[:2] in (b"PK", b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
            info["compressed"] = True
            info["error"] = ("Scene stream is compressed. io_scene_max only reads "
                             "uncompressed or .zip scenes from 3ds Max <= 2023.")
            return info
        info["compressed"] = False

        # Author-machine texture paths, so missing maps can be chased down.
        assets: list[str] = []
        if ole.exists("FileAssetMetaData3"):
            import re
            txt = ole.openstream("FileAssetMetaData3").read().decode("utf-16-le", "ignore")
            for s in re.findall(r"[ -~]{6,}", txt):
                if "." in s and s not in assets and s != "Bitmap":
                    assets.append(s)
        info["referenced_assets"] = assets
        info["missing_assets"] = [
            a for a in assets
            if not (path.parent / Path(a.replace("\\", "/")).name).exists()
        ]
    finally:
        ole.close()

    info["convertible"] = True
    return info


# ---------------------------------------------------------------------------
# Blender discovery
# ---------------------------------------------------------------------------

def find_blender(explicit: Optional[str] = None) -> Optional[Path]:
    """Locate a Blender executable: flag, config, env var, PATH, then defaults."""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    cfg_path = ((load_config().get("paths") or {}).get("blender_exe"))
    if cfg_path:
        candidates.append(str(cfg_path))
    if os.environ.get("BLENDER_EXE"):
        candidates.append(os.environ["BLENDER_EXE"])

    which = shutil.which("blender")
    if which:
        candidates.append(which)

    if sys.platform == "win32":
        for base in (Path(r"C:\Program Files\Blender Foundation"),
                     Path(r"C:\Program Files (x86)\Blender Foundation")):
            if base.is_dir():
                # Newest version first.
                for d in sorted(base.iterdir(), reverse=True):
                    candidates.append(str(d / "blender.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Blender.app/Contents/MacOS/Blender")
    else:
        candidates += ["/usr/bin/blender", "/usr/local/bin/blender",
                       "/snap/bin/blender"]

    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    return None


# Runs inside Blender's own Python. Kept as a string because Blender needs a
# script file, and this avoids shipping a second module that only ever runs
# under bpy.
_BLENDER_SCRIPT = r'''
import json, sys, traceback
import bpy
import addon_utils

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst, fmt, report_path = argv[0], argv[1], argv[2], argv[3]
report = {"ok": False, "addon": None, "objects": [], "meshes": 0,
          "tris": 0, "uv_layers": [], "materials": [], "images": [], "error": None}

try:
    # Enable whichever packaging of the MAX importer is installed.
    for mod in %(modules)s:
        try:
            addon_utils.enable(mod, default_set=False, persistent=False)
            if hasattr(bpy.ops.import_scene, "max"):
                report["addon"] = mod
                break
        except Exception:
            continue
    if not hasattr(bpy.ops.import_scene, "max"):
        raise RuntimeError(
            "The Autodesk MAX importer is not installed in this Blender. "
            "Install it via Edit > Preferences > Get Extensions > search "
            "'Autodesk MAX', or from https://github.com/nrgsille76/io_scene_max")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.max(filepath=src)

    for ob in bpy.data.objects:
        report["objects"].append({"name": ob.name, "type": ob.type})
    for me in bpy.data.meshes:
        me.calc_loop_triangles()
        report["meshes"] += 1
        report["tris"] += len(me.loop_triangles)
        for uvl in me.uv_layers:
            report["uv_layers"].append("%%s:%%s" %% (me.name, uvl.name))
    report["materials"] = [m.name for m in bpy.data.materials]
    report["images"] = [i.name for i in bpy.data.images]

    if report["tris"] == 0:
        raise RuntimeError(
            "Import produced no triangles. The scene's geometry probably only "
            "exists after 3ds Max evaluates a modifier stack, or it is made of "
            "NURBS/patch surfaces or V-Ray proxies, none of which third-party "
            "readers can evaluate. Export FBX from 3ds Max instead.")

    # Select meshes only; cameras/lights/helpers are noise for our pipeline.
    bpy.ops.object.select_all(action="DESELECT")
    for ob in bpy.data.objects:
        if ob.type == "MESH":
            ob.select_set(True)

    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB",
                                  use_selection=True, export_yup=True,
                                  export_apply=True)
    elif fmt == "obj":
        bpy.ops.wm.obj_export(filepath=dst, export_selected_objects=True,
                              export_materials=True, export_uv=True,
                              export_normals=True, forward_axis="NEGATIVE_Z",
                              up_axis="Y")
    else:
        raise ValueError("unsupported format: " + fmt)

    report["ok"] = True
except Exception as exc:
    report["error"] = "%%s: %%s" %% (type(exc).__name__, exc)
    report["traceback"] = traceback.format_exc()

with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
''' % {"modules": repr(list(_ADDON_MODULES))}


def convert(src: Path, dst: Path, fmt: str = "glb",
            blender: Optional[str] = None) -> dict:
    """Import `src` (.max) in headless Blender and export to `dst`."""
    exe = find_blender(blender)
    if exe is None:
        raise RuntimeError(
            "Blender not found. Install it (winget install BlenderFoundation.Blender), "
            "then pass --blender <path>, set BLENDER_EXE, or add "
            "paths.blender_exe to config.yaml.")

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="modelunify_max_"))
    script = tmpdir / "convert.py"
    report_path = tmpdir / "report.json"
    script.write_text(_BLENDER_SCRIPT, encoding="utf-8")

    cmd = [str(exe), "--background", "--factory-startup",
           "--python", str(script), "--",
           str(src), str(dst), fmt, str(report_path)]
    print(f"[max_to_glb] {exe.name} --background  ({src.name} -> {dst.name})")
    proc = subprocess.run(cmd, capture_output=True, text=True)

    report: dict = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    shutil.rmtree(tmpdir, ignore_errors=True)

    if not report:
        raise RuntimeError(
            "Blender produced no report. Exit code "
            f"{proc.returncode}.\n--- stdout ---\n{proc.stdout[-2000:]}"
            f"\n--- stderr ---\n{proc.stderr[-2000:]}")
    if not report.get("ok"):
        raise RuntimeError(f"Conversion failed: {report.get('error')}\n"
                           f"{report.get('traceback', '')}")
    report["output"] = str(dst)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_inspection(info: dict) -> None:
    print(f"\nSource   {info['path']}")
    print(f"Size     {info['size']:,} bytes")
    print(f"OLE2     {info.get('ole2')}")
    if "scene_bytes" in info:
        print(f"Scene    {info['scene_bytes']:,} bytes"
              f"  compressed={info.get('compressed')}")
    for asset in info.get("referenced_assets", []):
        missing = asset in info.get("missing_assets", [])
        print(f"  texture {'MISSING ' if missing else 'present '} {asset}")
    if info.get("error"):
        print(f"\nBLOCKED  {info['error']}")
    else:
        print("\nConvertible by io_scene_max.")


def main(argv: Optional[list[str]] = None) -> int:
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    ap = argparse.ArgumentParser(
        description="Convert a 3ds Max .max scene to GLB/OBJ using headless Blender.")
    ap.add_argument("source", type=Path, help="input .max file")
    ap.add_argument("--out", type=Path, default=None,
                    help="output path (default: alongside the source)")
    ap.add_argument("--format", choices=("glb", "obj"), default="glb")
    ap.add_argument("--blender", default=None, help="path to blender executable")
    ap.add_argument("--inspect", action="store_true",
                    help="report the file's contents and exit without converting")
    args = ap.parse_args(argv)

    info = inspect_max(args.source)
    _print_inspection(info)
    if info.get("error"):
        return 2
    if args.inspect:
        return 0

    dst = args.out or args.source.with_suffix("." + args.format)
    try:
        report = convert(args.source, dst, args.format, args.blender)
    except RuntimeError as exc:
        print(f"\nERROR {exc}")
        return 1

    print(f"\nImporter  {report['addon']}")
    print(f"Objects   {len(report['objects'])}  meshes={report['meshes']}  "
          f"triangles={report['tris']:,}")
    print(f"UV layers {report['uv_layers'] or 'NONE - LODs will fall back to flat colour'}")
    print(f"Materials {report['materials']}")
    print(f"Images    {report['images']}")
    print(f"Written   {report['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
