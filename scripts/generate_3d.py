"""
generate_3d — CLI for Modelunify (Integrated 3D AI Creation).

Examples
--------
# Single image -> single .glb
python scripts/generate_3d.py single inputs/satellite/airbase.png

# Batch a whole folder
python scripts/generate_3d.py batch inputs/satellite --pattern "*.png"

# Generate full LOD set for Falcon BMS
python scripts/generate_3d.py bms-lods inputs/satellite/hangar.jpg --name hangar_01

# Stage master GLB for InstaLOD Studio (Pioneer GUI)
python scripts/generate_3d.py instalod-stage --name hangar_01

# Print env / cuda info
python scripts/generate_3d.py info
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Windows legacy console (cp1252) chokes on the Unicode characters that Rich
# uses in its help panels. Force UTF-8 stdout/stderr before importing Rich.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import typer
from rich import print
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gpu_lifecycle import operation

from scripts.engine import (         # noqa: E402
    engine_from_config,
    load_config,
    decimate,
    export_glb_and_obj,
)
from scripts.texture import planar_project_front   # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="ModelUnify — TripoSG, Hunyuan3D and native ComfyUI 3D generators")


@app.command(name="comfy")
def comfy_generate(
    model: str = typer.Option("trellis", "--model", help="trellis / pixal / pixal-mv"),
    front: Optional[Path] = typer.Option(None,"--front",exists=True),
    left: Optional[Path] = typer.Option(None,"--left",exists=True),
    back: Optional[Path] = typer.Option(None,"--back",exists=True),
    right: Optional[Path] = typer.Option(None,"--right",exists=True),
    output_dir: Path = typer.Option(...,"--output-dir","-o",help="Fresh folder; preserves raw master and workflow"),
    resolution: int = typer.Option(1024,"--resolution"),
    seed: int = typer.Option(42,"--seed"),
    structure_steps: int = typer.Option(12,"--structure-steps"),
    shape_steps: int = typer.Option(20,"--shape-steps"),
    upsample_steps: int = typer.Option(12,"--upsample-steps"),
    texture_steps: int = typer.Option(12,"--texture-steps"),
    guidance: float = typer.Option(7.5,"--guidance"),
    texture_guidance: float = typer.Option(1.,"--texture-guidance"),
    texture: bool = typer.Option(True,"--texture/--no-texture"),
    texture_size: int = typer.Option(2048,"--texture-size"),
    fov: float = typer.Option(20.,"--fov"),
    auto_fov: bool = typer.Option(True,"--auto-fov/--manual-fov"),
    bg: str = typer.Option("none","--bg",help="none / rembg / rmbg"),
    remesh: bool = typer.Option(True,"--remesh/--no-remesh",help="Solid remesh working copy; raw master retained"),
    remesh_resolution: int = typer.Option(768,"--remesh-resolution"),
    remesh_qef: bool = typer.Option(False,"--remesh-qef"),
    faces: int = typer.Option(700000,"--faces",help="Working mesh triangle budget; 0 disables decimation"),
):
    """Generate using the installed local ComfyUI host; never install/download implicitly."""
    from scripts.comfyui_workflows import BACKENDS, ComfyRequest
    from scripts.workbench.pipelines import execute
    from scripts.workbench import runtime
    from dataclasses import asdict
    if model not in ("trellis","pixal","pixal-mv"):
        raise typer.BadParameter("Use trellis, pixal or pixal-mv.")
    if model!="pixal-mv" and any((left,back,right)):
        raise typer.BadParameter("Only pixal-mv accepts additional named views.")
    options = ComfyRequest(backend=BACKENDS[0] if model=="trellis" else BACKENDS[1],
        multiview=model=="pixal-mv",resolution=resolution,seed=seed,structure_steps=structure_steps,
        shape_steps=shape_steps,upsample_steps=upsample_steps,texture_steps=texture_steps,
        guidance=guidance,texture_guidance=texture_guidance,texture=texture,
        texture_size=texture_size,fov=fov,auto_fov=auto_fov,remesh=remesh,
        remesh_resolution=remesh_resolution,remesh_qef=remesh_qef,faces=faces)
    settings = {"c_"+k:v for k,v in asdict(options).items() if k!="backend"}
    settings.update(backend=options.backend,preparation={"provider":bg})
    runtime.CFG = load_config()
    output,report = execute("Generate",{"settings":settings,"mesh":None,
        "images":{k:str(v.resolve()) for k,v in dict(front=front,left=left,back=back,right=right).items() if v}},
        output_dir.resolve(),lambda message,progress:print(message))
    print(f"Completed: {output}")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    )


# ---------------------------------------------------------------- info
@app.command()
def info():
    """Show GPU / torch / engine status."""
    import torch
    print(f"[bold]Python:[/bold] {sys.version.split()[0]}")
    print(f"[bold]Torch:[/bold]  {torch.__version__}")
    print(f"[bold]CUDA:[/bold]   available={torch.cuda.is_available()}  "
          f"version={torch.version.cuda}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"[bold]GPU:[/bold]    {p.name}  ({p.total_memory // (1024 ** 2)} MiB)")
    cfg = load_config()
    print(f"[bold]Config:[/bold] {cfg.get('model', {}).get('triposg', {})}")
    print(f"[bold]Root:[/bold]   {ROOT}")


# ---------------------------------------------------------------- single
@app.command()
@operation()
def single(
    image: Path = typer.Argument(..., exists=True, readable=True, help="Input image"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Output .glb path (default: outputs/<stem>.glb)"),
    seed: int = typer.Option(42, "--seed"),
    steps: int = typer.Option(50, "--steps", help="Diffusion steps (25–75; higher=cleaner)"),
    guidance: float = typer.Option(7.0, "--guidance",
                                   help="Higher=stricter to input (3–15)"),
    octree_depth: int = typer.Option(9, "--octree-depth",
                                     help="Mesh resolution: 7=fast/coarse, 9=default, 10=fine (4x VRAM)"),
    faces: int = typer.Option(-1, "--faces", help="Decimate to this face count (-1 = no limit)"),
    no_bg_removal: bool = typer.Option(False, "--no-bg-removal", help="Skip background removal"),
    no_texture: bool = typer.Option(False, "--no-texture",
                                    help="Skip planar texture projection from source image"),
):
    """Generate one 3D model from one image."""
    cfg = load_config()
    eng = engine_from_config(cfg)
    out = output or (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs")
                     / f"{image.stem}.glb")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[cyan]→ Generating from[/cyan] {image}")
    mesh = eng.generate(
        str(image),
        seed=seed,
        num_inference_steps=steps,
        guidance_scale=guidance,
        faces=faces,
        remove_background=not no_bg_removal,
        octree_depth=octree_depth,
    )

    if not no_texture:
        print("[cyan]→ Baking planar texture from source image[/cyan]")
        mesh = planar_project_front(mesh, image)

    export_glb_and_obj(mesh, out)
    obj_companion = Path(out).with_suffix(".obj")
    print(f"[green]✓ Saved[/green] {out}  ({mesh.vertices.shape[0]} verts, {mesh.faces.shape[0]} faces)")
    print(f"[green]✓ Saved[/green] {obj_companion}  (editable Wavefront OBJ + MTL)")


# ---------------------------------------------------------------- batch
@app.command()
@operation()
def batch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of input images"),
    pattern: str = typer.Option("*.png", "--pattern", "-p"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    seed: int = typer.Option(42),
    steps: int = typer.Option(50),
    guidance: float = typer.Option(7.0),
    faces: int = typer.Option(-1),
    no_bg_removal: bool = typer.Option(False),
    no_texture: bool = typer.Option(False),
):
    """Generate 3D models for every image matching pattern in folder."""
    cfg = load_config()
    eng = engine_from_config(cfg)
    out_dir = output_dir or (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs"))
    out_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(folder.glob(pattern))
    if not images:
        print(f"[yellow]No images matching {pattern} in {folder}[/yellow]")
        raise typer.Exit(1)

    eng.load()
    with _make_progress() as bar:
        task = bar.add_task("Generating", total=len(images))
        for img in images:
            try:
                mesh = eng.generate(
                    str(img),
                    seed=seed,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    faces=faces,
                    remove_background=not no_bg_removal,
                )
                if not no_texture:
                    mesh = planar_project_front(mesh, img)
                out_path = out_dir / f"{img.stem}.glb"
                export_glb_and_obj(mesh, out_path)
                print(f"  [green]✓[/green] {img.name} -> {out_path.name} (+ .obj)  "
                      f"({mesh.faces.shape[0]} faces)")
            except Exception as e:
                print(f"  [red]✗[/red] {img.name}: {e}")
                eng.unload()
            bar.advance(task)


# ---------------------------------------------------------------- bms-lods
@app.command(name="bms-lods")
@operation()
def bms_lods(
    image: Path = typer.Argument(..., exists=True, readable=True),
    name: str = typer.Option(..., "--name", "-n", help="Asset name (used for folder + filenames)"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o",
                                              help="Default: bms_export/<name>/"),
    seed: int = typer.Option(42),
    steps: int = typer.Option(50),
    guidance: float = typer.Option(7.0),
    lod_count: int = typer.Option(7, "--lod-count", min=1, max=7),
    lod_faces: Optional[str] = typer.Option(None, "--lod-faces", help="Comma-separated face budgets; first is master"),
):
    """Generate a full LOD0..LOD6 set + Parent.dat skeleton for Falcon BMS."""
    cfg = load_config()
    eng = engine_from_config(cfg)
    lods = cfg.get("bms_lods", {})
    lod_targets = [
        ("Model_0", lods.get("lod0_faces", 40000)),
        ("Model_1", lods.get("lod1_faces", 8000)),
        ("Model_2", lods.get("lod2_faces", 3000)),
        ("Model_3", lods.get("lod3_faces", 1000)),
        ("Model_4", lods.get("lod4_faces", 400)),
        ("Model_5", lods.get("lod5_faces", 150)),
        ("Model_6", lods.get("lod6_faces", 60)),
    ]
    if lod_faces:
        try:
            budgets = [int(value.strip()) for value in lod_faces.split(",")]
            if not 1 <= len(budgets) <= 7 or any(value <= 0 for value in budgets):
                raise ValueError()
        except ValueError:
            raise typer.BadParameter("--lod-faces requires 1–7 positive integer budgets.")
        lod_targets = [(f"Model_{i}", value) for i, value in enumerate(budgets)]
    else:
        lod_targets = lod_targets[:lod_count]


    out_dir = output_dir or (ROOT / cfg.get("paths", {}).get("bms_export_dir", "bms_export") / name)

    print(f"[cyan]→ Generating high-detail mesh[/cyan]")
    base = eng.generate(str(image), seed=seed, num_inference_steps=steps, guidance_scale=guidance, faces=-1)

    print(f"[cyan]→ Baking texture[/cyan]")
    base = planar_project_front(base, image)

    eng.unload()
    from scripts.lod_export import make_lod_set
    out_dir = make_lod_set(base, out_dir.name, lod_targets, out_dir.parent)
    print(f"[green]✓ LOD set written to[/green] {out_dir}")
    print(f"[yellow]Next:[/yellow] open the .glb files in Blender and use the BMS plugin "
          f"to export each to .bml — see docs/BMS_WORKFLOW.md")


# ============================================================
# Multi-view (Hunyuan3D-2mv) commands
# ============================================================

def _collect_views(front, left, back, right):
    """Build the {'front':..., ...} dict from CLI options, dropping None."""
    raw = {"front": front, "left": left, "back": back, "right": right}
    views = {k: str(v) for k, v in raw.items() if v is not None}
    if not views:
        raise typer.BadParameter(
            "Provide at least one of --front / --left / --back / --right"
        )
    return views


@app.command()
@operation()
def multiview(
    front: Optional[Path] = typer.Option(None, "--front", exists=True, readable=True),
    left:  Optional[Path] = typer.Option(None, "--left",  exists=True, readable=True),
    back:  Optional[Path] = typer.Option(None, "--back",  exists=True, readable=True),
    right: Optional[Path] = typer.Option(None, "--right", exists=True, readable=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Output .glb path (default: outputs/<name>.glb)"),
    name: str = typer.Option("multiview", "--name",
                             help="Base name when --output isn't given"),
    seed: int = typer.Option(12345, "--seed"),
    steps: int = typer.Option(50, "--steps"),
    octree: int = typer.Option(380, "--octree", help="Octree resolution (256–512)"),
    faces: int = typer.Option(-1, "--faces"),
    bake_view: str = typer.Option("front", "--bake-view",
                                   help="Which view to bake as planar texture: front/left/back/right or 'none'"),
):
    """Generate one fused 3D model from 1–4 views (front/left/back/right)."""
    from scripts.engine_hunyuan import engine_from_config as h_engine_from_config

    cfg = load_config()
    views = _collect_views(front, left, back, right)
    out = output or (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs") / f"{name}.glb")
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}. Choose a fresh name/output path.")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[cyan]→ Multi-view generation with {len(views)} view(s):[/cyan] "
          f"{', '.join(views.keys())}")
    eng = h_engine_from_config(cfg)
    mesh = eng.generate_multiview(
        views,
        seed=seed,
        num_inference_steps=steps,
        octree_resolution=octree,
    )

    if faces > 0:
        mesh = decimate(mesh, faces)

    if bake_view != "none" and bake_view in views:
        print(f"[cyan]→ Baking planar texture from '{bake_view}' view[/cyan]")
        mesh = planar_project_front(mesh, views[bake_view])
    elif bake_view != "none":
        # fall back to the first provided view
        first = next(iter(views))
        print(f"[yellow]→ '{bake_view}' not supplied; baking from '{first}' instead[/yellow]")
        mesh = planar_project_front(mesh, views[first])

    mesh.export(out)
    print(f"[green]✓ Saved[/green] {out}  "
          f"({mesh.vertices.shape[0]} verts, {mesh.faces.shape[0]} faces)")


@app.command(name="multiview-bms-lods")
@operation()
def multiview_bms_lods(
    name: str = typer.Option(..., "--name", "-n"),
    front: Optional[Path] = typer.Option(None, "--front", exists=True, readable=True),
    left:  Optional[Path] = typer.Option(None, "--left",  exists=True, readable=True),
    back:  Optional[Path] = typer.Option(None, "--back",  exists=True, readable=True),
    right: Optional[Path] = typer.Option(None, "--right", exists=True, readable=True),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    seed: int = typer.Option(12345, "--seed"),
    steps: int = typer.Option(50, "--steps"),
    octree: int = typer.Option(380, "--octree"),
    bake_view: str = typer.Option("front", "--bake-view"),
    lod_count: int = typer.Option(7, "--lod-count", min=1, max=7),
    lod_faces: Optional[str] = typer.Option(None, "--lod-faces", help="Comma-separated face budgets; first is master"),
):
    """Multi-view → full LOD0..LOD6 set + Parent.dat skeleton for Falcon BMS."""
    from scripts.engine_hunyuan import engine_from_config as h_engine_from_config

    cfg = load_config()
    views = _collect_views(front, left, back, right)
    out_dir = output_dir or (ROOT / cfg.get("paths", {}).get("bms_export_dir", "bms_export") / name)

    print(f"[cyan]→ Multi-view generation with {len(views)} view(s):[/cyan] "
          f"{', '.join(views.keys())}")
    eng = h_engine_from_config(cfg)
    base = eng.generate_multiview(
        views,
        seed=seed,
        num_inference_steps=steps,
        octree_resolution=octree,
    )

    if bake_view in views:
        base = planar_project_front(base, views[bake_view])
    elif views:
        base = planar_project_front(base, next(iter(views.values())))

    lods = cfg.get("bms_lods", {})
    lod_targets = [
        ("Model_0", lods.get("lod0_faces", 40000)),
        ("Model_1", lods.get("lod1_faces", 8000)),
        ("Model_2", lods.get("lod2_faces", 3000)),
        ("Model_3", lods.get("lod3_faces", 1000)),
        ("Model_4", lods.get("lod4_faces", 400)),
        ("Model_5", lods.get("lod5_faces", 150)),
        ("Model_6", lods.get("lod6_faces", 60)),
    ]
    if lod_faces:
        try:
            budgets = [int(value.strip()) for value in lod_faces.split(",")]
            if not 1 <= len(budgets) <= 7 or any(value <= 0 for value in budgets):
                raise ValueError()
        except ValueError:
            raise typer.BadParameter("--lod-faces requires 1–7 positive integer budgets.")
        lod_targets = [(f"Model_{i}", value) for i, value in enumerate(budgets)]
    else:
        lod_targets = lod_targets[:lod_count]


    eng.unload()
    from scripts.lod_export import make_lod_set
    out_dir = make_lod_set(base, out_dir.name, lod_targets, out_dir.parent)
    print(f"[green]✓ LOD set written to[/green] {out_dir}")
    print(f"[yellow]Next:[/yellow] open the .glb files in Blender and use the BMS plugin "
          f"to export each to .bml — see docs/BMS_WORKFLOW.md")


# ============================================================
# PBR Texture painting (Hunyuan3D-2.1)
# ============================================================

def _resolve_low_vram(cli_value: Optional[bool], cfg: Optional[dict] = None) -> bool:
    """Mirror of `web_ui._detect_low_vram_default` for the CLI.

    Resolution order:
      1. If the user passed `--low-vram` / `--no-low-vram` explicitly,
         honour that.
      2. Otherwise, return True when CUDA reports < 16 GB total VRAM
         (the painter normally peaks at ~21 GB; sub-16 GB cards need
         mmgp to fit).
      3. Otherwise, fall back to `model.paint.low_vram_mode` from
         config.yaml so the CLI honours the same project default as
         the web UI.
    """
    if cli_value is not None:
        return bool(cli_value)
    try:
        import torch as _t
        if _t.cuda.is_available():
            _, total = _t.cuda.mem_get_info(0)
            if total < 16 * (1024 ** 3):
                return True
    except Exception:
        pass
    cfg = cfg if cfg is not None else load_config()
    return bool(
        (cfg.get("model", {}) or {}).get("paint", {}).get("low_vram_mode", False)
    )


def _print_mmgp_status(painter, requested: bool) -> None:
    """Echo the mmgp outcome to the terminal in a CLI-friendly form."""
    if requested:
        if getattr(painter, "last_mmgp_applied", False):
            print("[green]Low-VRAM mode: mmgp offload used during paint (released)[/green]")
        else:
            print("[yellow]Low-VRAM mode: requested but NOT active "
                  "(see warnings)[/yellow]")
    else:
        print("Low-VRAM mode: OFF (full-VRAM path)")
    for _w in getattr(painter, "load_warnings", []) or []:
        print(f"[yellow]⚠ {_w}[/yellow]")


@app.command()
@operation()
def paint(
    mesh: Path = typer.Argument(..., exists=True, readable=True,
                                help="Untextured .glb (or .obj) to paint"),
    ref: Path = typer.Option(..., "--ref", "-r", exists=True, readable=True,
                             help="Reference image (front view used to generate the mesh)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Output path. Default: <mesh_stem>_textured.glb"),
    views: int = typer.Option(6, "--views", help="Virtual baking views (4–6)"),
    resolution: int = typer.Option(512, "--resolution", help="Diffusion resolution per view"),
    no_remesh: bool = typer.Option(False, "--no-remesh", help="Skip remeshing (faster, lower quality)"),
    low_vram: Optional[bool] = typer.Option(
        None, "--low-vram/--no-low-vram",
        help="Force mmgp CPU<->VRAM offload on or off. Defaults to ON when "
             "CUDA reports <16 GB total VRAM, or when config.yaml has "
             "paint.low_vram_mode: true. Requires `pip install mmgp`."),
):
    """Paint PBR texture (albedo + MR) onto an untextured mesh using Hunyuan3D-2.1."""
    from scripts.engine_paint import Hunyuan3DPainter, PaintConfig, rasterizer_ready

    if not rasterizer_ready():
        print("[red]custom_rasterizer_kernel not compiled.[/red]")
        print("Run the compile commands shown at the top of scripts/engine_paint.py first.")
        raise typer.Exit(1)

    low_vram_eff = _resolve_low_vram(low_vram)
    out = output or mesh.parent / f"{mesh.stem}_textured.glb"
    painter = Hunyuan3DPainter(PaintConfig(
        max_num_view=views,
        resolution=resolution,
        use_remesh=not no_remesh,
        low_vram_mode=low_vram_eff,
    ))
    print(f"[cyan]→ Painting[/cyan] {mesh.name}  ref={ref.name}  "
          f"(low_vram={low_vram_eff})")
    result = painter.paint(mesh, ref, out)
    _print_mmgp_status(painter, low_vram_eff)
    print(f"[green]✓ Textured mesh saved:[/green] {result}")


@app.command(name="multiview-textured")
@operation()
def multiview_textured(
    name: str = typer.Option(..., "--name", "-n", help="Asset name"),
    front: Optional[Path] = typer.Option(None, "--front", exists=True, readable=True),
    left:  Optional[Path] = typer.Option(None, "--left",  exists=True, readable=True),
    back:  Optional[Path] = typer.Option(None, "--back",  exists=True, readable=True),
    right: Optional[Path] = typer.Option(None, "--right", exists=True, readable=True),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    seed:   int = typer.Option(12345, "--seed"),
    steps:  int = typer.Option(50, "--steps"),
    octree: int = typer.Option(380, "--octree"),
    views:  int = typer.Option(6, "--views",      help="Baking views for painter (4–6)"),
    resolution: int = typer.Option(512, "--resolution"),
    no_remesh: bool = typer.Option(False, "--no-remesh"),
    low_vram: Optional[bool] = typer.Option(
        None, "--low-vram/--no-low-vram",
        help="Force mmgp CPU<->VRAM offload on or off. Defaults to ON when "
             "CUDA reports <16 GB total VRAM, or when config.yaml has "
             "paint.low_vram_mode: true."),
):
    """Multi-view shape + PBR texture in one shot (Hunyuan3D-2mv shape + 2.1 painter)."""
    from scripts.engine_hunyuan import engine_from_config as h_engine_from_config
    from scripts.engine_paint import Hunyuan3DPainter, PaintConfig, rasterizer_ready

    if not rasterizer_ready():
        print("[red]custom_rasterizer_kernel not compiled.[/red]")
        print("Run the compile commands in the PowerShell block first.")
        raise typer.Exit(1)

    cfg = load_config()
    low_vram_eff = _resolve_low_vram(low_vram, cfg)
    views_dict = _collect_views(front, left, back, right)
    from scripts.export_contracts import fresh_asset_dir
    out_dir = output_dir or (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs") / name)
    out_dir = fresh_asset_dir(out_dir.parent, out_dir.name)
    white_glb = out_dir / f"{name}_white.glb"
    textured_glb = out_dir / f"{name}_textured.glb"

    # Step 1: shape
    print(f"[cyan]→ Step 1/2: Generating shape ({len(views_dict)} views)[/cyan]")
    shape_eng = h_engine_from_config(cfg)
    mesh = shape_eng.generate_multiview(views_dict, seed=seed,
                                        num_inference_steps=steps,
                                        octree_resolution=octree)
    mesh.export(str(white_glb))
    shape_eng.unload()
    print(f"  White mesh: {white_glb}")

    # Step 2: paint
    ref_image = views_dict.get("front") or next(iter(views_dict.values()))
    print(f"[cyan]→ Step 2/2: Painting texture (ref={Path(ref_image).name})  "
          f"(low_vram={low_vram_eff})[/cyan]")
    painter = Hunyuan3DPainter(PaintConfig(
        max_num_view=views,
        resolution=resolution,
        use_remesh=not no_remesh,
        low_vram_mode=low_vram_eff,
    ))
    painter.paint(white_glb, ref_image, textured_glb)
    _print_mmgp_status(painter, low_vram_eff)
    print(f"[green]✓ Textured .glb:[/green] {textured_glb}")


# ---------------------------------------------------------------- instalod-stage
@app.command(name="instalod-stage")
def instalod_stage(
    name: Optional[str] = typer.Option(
        None, "--name", "-n",
        help="Asset name under bms_export/ (uses Model_0.glb) or outputs/<name>.glb",
    ),
    glb: Optional[Path] = typer.Option(
        None, "--glb",
        help="Explicit master GLB path",
    ),
    overwrite: bool = typer.Option(False, '--overwrite', help='Explicitly replace an existing staged master'),
):
    """Copy a master GLB into tools/instalod/inbox for InstaLOD Studio (Pioneer)."""
    from tools.instalod import stage as instalod_stage_mod

    argv: list[str] = []
    if name:
        argv.extend(["--name", name])
    if glb is not None:
        argv.extend(["--glb", str(glb)])
    if overwrite:
        argv.append('--overwrite')
    code = instalod_stage_mod.main(argv)
    if code:
        raise typer.Exit(code)


if __name__ == "__main__":
    app()
