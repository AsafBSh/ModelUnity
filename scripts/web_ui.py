"""
Gradio web UI for Modelunify - Integrated 3D AI Creation.

Compact one-screen layout: every tab fits in a 1080p viewport without scrolling.
Native progress bars (`gr.Progress`) show stage names and elapsed time, including
the upstream tqdm bars from the diffusion pipelines.
"""
from __future__ import annotations

import base64
import html
import os
import sys
import time
from pathlib import Path

# Windows defaults sys.stdout / sys.stderr to the OEM codepage (cp1252 on
# en-US Windows), which cannot encode the Unicode block-drawing chars
# ▏▎▍▌▋▊▉█ that tqdm uses inside its progress bar. Every tqdm.refresh()
# call from inside a vendor pipeline (TripoSG, Hunyuan, diffusers, etc.)
# then raises `UnicodeEncodeError: 'charmap' codec can't encode character
# '\u258f'`, which propagates out of `progress_bar.update()` and aborts
# the whole inference call.
#
# Reconfigure both streams to UTF-8 at startup so every Unicode char tqdm
# (or anything else) wants to emit is encodable. `errors="replace"` is
# defensive: UTF-8 can encode every codepoint, but if Python is ever
# launched with a non-TextIOWrapper stdout (e.g. piped to a non-text
# stream) the substitution prevents a second crash.
#
# Must run BEFORE we import torch / gradio / diffusers because those
# libraries grab references to sys.stdout at import time for their own
# logging handlers; reconfiguring the underlying TextIOWrapper updates
# the encoding in place so existing references stay valid.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        # reconfigure() exists on TextIOWrapper (Python 3.7+); if stdout
        # was replaced with something else (test runner capture, jupyter,
        # subprocess.PIPE), just skip - those backends usually handle
        # Unicode natively.
        pass

import gradio as gr
import torch
from PIL import Image

# --- gradio_client schema patch (bool schemas) ---
try:
    import gradio_client.utils as _gcu
    _orig_schema = _gcu._json_schema_to_python_type
    def _safe_schema(schema, defs=None):
        if isinstance(schema, bool):
            return "Any" if schema else "None"
        return _orig_schema(schema, defs)
    _gcu._json_schema_to_python_type = _safe_schema
    _orig_get_type = _gcu.get_type
    def _safe_get_type(schema):
        if isinstance(schema, bool):
            return "Any" if schema else "None"
        return _orig_get_type(schema)
    _gcu.get_type = _safe_get_type
except Exception:
    pass

# --- Disable Gradio 6.x brotli middleware ---
# Gradio 6.17 compresses responses with brotli but doesn't update Content-Length.
# This causes "Too much/little data for declared Content-Length" h11 errors and
# leaves image thumbnails as broken placeholders in the UI. Make it a passthrough.
try:
    import gradio.brotli_middleware as _bm
    async def _passthrough_brotli(self, scope, receive, send):
        await self.app(scope, receive, send)
    _bm.BrotliMiddleware.__call__ = _passthrough_brotli
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._version import MODELUNIFY_VERSION                         # noqa: E402,F401
from scripts.engine import engine_from_config, load_config, decimate, export_glb_and_obj    # noqa: E402
from scripts.export_contracts import fresh_asset_dir
from scripts.gpu_lifecycle import operation
from scripts.engine_hunyuan import engine_from_config as h_engine_from_config   # noqa: E402
from scripts.engine_paint import painter_from_config, rasterizer_ready  # noqa: E402
from scripts.texture import planar_project_front                        # noqa: E402
from scripts.lod_export import (                                        # noqa: E402
    make_lod_set, make_textured_lod_set, bake_normal_map,
)

CFG = load_config()
ENGINE = engine_from_config(CFG)
MV_ENGINE = h_engine_from_config(CFG)
OUT_DIR = ROOT / CFG.get("paths", {}).get("outputs_dir", "outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
BMS_DIR = ROOT / CFG.get("paths", {}).get("bms_export_dir", "bms_export")
BMS_DIR.mkdir(parents=True, exist_ok=True)
INPUTS_DIR = ROOT / CFG.get("paths", {}).get("inputs_dir", "inputs")
INPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _detect_low_vram_default() -> bool:
    """Initial value for the 'Low-VRAM mode' checkbox in both paint tabs.

    Returns True when EITHER:
      - `config.yaml` declares `model.paint.low_vram_mode: true` (the
        project default for the RTX 3500 Ada, 12 GB), OR
      - we detect a CUDA device with < 16 GB total memory at startup
        (covers laptops / second machines where the config wasn't tuned
        for their hardware).

    Either condition is sufficient; the user can untick the checkbox
    per-run to force the full-VRAM path (e.g. on a 24 GB card when
    benchmarking, or to confirm an OOM theory).
    """
    cfg_default = bool(
        (CFG.get("model", {}) or {}).get("paint", {}).get("low_vram_mode", False)
    )
    try:
        if torch.cuda.is_available():
            _, total = torch.cuda.mem_get_info(0)
            # 16 GiB threshold: Hunyuan3D-2.1 paint peaks at ~21 GB without
            # offload, so 16 GB cards are the boundary where mmgp goes from
            # "nice-to-have" to "required".
            if total < 16 * (1024 ** 3):
                return True
    except Exception:
        # No CUDA, no driver, or torch hiccup - fall back to config value.
        pass
    return cfg_default


PAINT_LOW_VRAM_DEFAULT = _detect_low_vram_default()


# =============================================================================
# Brand assets - Modelunify logo
# =============================================================================
#
# The header logo and the browser favicon both read from one canonical
# file: `<repo>/assets/logo.png`. Treat that file as a checked-in source
# artifact - committed alongside the code - and the UI reads it directly.
#
# An earlier version of this module had a runtime "bootstrap" that
# scanned Cursor's per-project chat-paste folder for the newest square
# PNG and copied it in. That dance was a workaround for not being able
# to copy a binary file from inside the agent, and it had a hostile
# failure mode: any unrelated square PNG paste (a render preview, a
# screenshot, an icon experiment) would silently overwrite the real
# logo on the next launcher restart. Removed. If the file at
# `assets/logo.png` is wrong, the fix is to overwrite the file - not
# to make the program guess which PNG you meant.
#
# When the file is missing entirely (fresh clone, deleted by accident)
# the header falls back to the inline SVG mark below so it never
# renders empty.
ASSETS_DIR = ROOT / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


def _load_logo_data_url() -> str | None:
    """Read `assets/logo.png` and return it as a base64 data URL.

    Embedding the logo as a data URL keeps the header self-contained -
    no Gradio file-serving route, no `/file=...` URL plumbing, and the
    rendered HTML still works if the project gets moved on disk.

    Returns None if the file is missing or unreadable; the caller falls
    back to the inline SVG mark.
    """
    if not LOGO_PATH.exists():
        print(f"[modelunify] logo file missing at {LOGO_PATH}; "
              f"header will use the SVG fallback mark.")
        return None
    try:
        with open(LOGO_PATH, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        print(f"[modelunify] logo loaded from {LOGO_PATH} "
              f"({LOGO_PATH.stat().st_size:,} bytes)")
        return f"data:image/png;base64,{data}"
    except OSError as e:
        print(f"[modelunify] WARN: could not read logo at {LOGO_PATH}: {e}")
        return None


# Inline SVG fallback that picks up the same brand cues as the PNG
# (teal-to-blue crystals, central "AI" dot, thin ring) so the header
# never renders empty even when the PNG isn't on disk.
_LOGO_SVG_FALLBACK = (
    "<svg viewBox='0 0 64 64' xmlns='http://www.w3.org/2000/svg' "
    "role='img' aria-label='Modelunify'>"
    "<defs>"
    "<linearGradient id='mu-g1' x1='0' y1='0' x2='1' y2='1'>"
    "<stop offset='0%' stop-color='#2DD4BF'/>"
    "<stop offset='100%' stop-color='#3D8FE0'/>"
    "</linearGradient>"
    "</defs>"
    "<circle cx='32' cy='32' r='28' fill='none' stroke='url(#mu-g1)' "
    "stroke-width='2'/>"
    "<polygon points='20,32 32,16 44,32 32,48' fill='url(#mu-g1)' "
    "opacity='0.85'/>"
    "<circle cx='32' cy='32' r='5' fill='#0F1A2E'/>"
    "<text x='32' y='35' text-anchor='middle' font-family='Inter, "
    "sans-serif' font-size='6' font-weight='700' fill='#A8E0D5'>AI</text>"
    "</svg>"
)

ASSETS_DIR.mkdir(parents=True, exist_ok=True)
LOGO_DATA_URL = _load_logo_data_url()


# =============================================================================
# Quality presets
# =============================================================================

TRIPOSG_PRESETS = {
    "Fast":     {"steps": 25, "guidance": 7.0, "octree": 8,  "faces": 15000},
    "Balanced": {"steps": 50, "guidance": 7.0, "octree": 9,  "faces": 25000},
    "HQ":       {"steps": 75, "guidance": 8.5, "octree": 10, "faces": 50000},
}
HUNYUAN_MV_PRESETS = {
    "Fast":     {"steps": 25, "octree": 256, "guidance": 4.0, "chunks": 10000},
    "Balanced": {"steps": 50, "octree": 380, "guidance": 5.0, "chunks": 20000},
    "HQ":       {"steps": 75, "octree": 512, "guidance": 6.0, "chunks": 30000},
}
PAINT_PRESETS = {
    # texture_size is the dominant factor for runtime because of cv2.inpaint.
    # Paint VRAM footprint goes up with: views, resolution, AND (most of all)
    # render_size. HQ at render_size=2048 crashed with OOM on a 12 GB card
    # because the painter loads both diffusion + super-res models eagerly and
    # leaves only ~3.2 GB free for activations. Dropping HQ render_size to
    # 1024 keeps the 4K final texture quality (super-res still upsamples 4x)
    # while halving activation memory.
    "Speed":    {"views": 4, "resolution": 256, "render_size": 512,  "texture_size": 1024},
    "Balanced": {"views": 6, "resolution": 512, "render_size": 1024, "texture_size": 2048},
    "HQ":       {"views": 8, "resolution": 512, "render_size": 1024, "texture_size": 4096},
}


# =============================================================================
# Helpers
# =============================================================================

def _bms_lod_targets() -> list[tuple[str, int]]:
    lods = CFG.get("bms_lods", {})
    return [
        ("Model_0", lods.get("lod0_faces", 20000)),
        ("Model_1", lods.get("lod1_faces", 8000)),
        ("Model_2", lods.get("lod2_faces", 3000)),
        ("Model_3", lods.get("lod3_faces", 1000)),
        ("Model_4", lods.get("lod4_faces", 400)),
        ("Model_5", lods.get("lod5_faces", 150)),
        ("Model_6", lods.get("lod6_faces", 60)),
    ]


def _build_lod_targets(num_lods, l0, l1, l2, l3, l4, l5, l6) -> list[tuple[str, int]]:
    """Build the [(Model_0, faces), ...] list for the chosen LOD count."""
    n = max(1, min(7, int(num_lods)))
    all_targets = [
        ("Model_0", int(l0)), ("Model_1", int(l1)),
        ("Model_2", int(l2)), ("Model_3", int(l3)),
        ("Model_4", int(l4)), ("Model_5", int(l5)),
        ("Model_6", int(l6)),
    ]
    return all_targets[:n]


def _square_pad(img: Image.Image, color=(255, 255, 255)) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    mode = img.mode if img.mode in ("RGB", "RGBA") else "RGB"
    bg = Image.new(mode, (s, s), color if mode == "RGB" else (*color, 0))
    bg.paste(img, ((s - w) // 2, (s - h) // 2), img if img.mode == "RGBA" else None)
    return bg


def _shorten_gpu_name(name: str) -> str:
    """Trim the marketing fluff off a CUDA device name so it fits in a
    topbar pill. Examples:
      'NVIDIA RTX 3500 Ada Generation Laptop GPU' -> 'RTX 3500 Ada'
      'NVIDIA GeForce RTX 4080 Laptop GPU'        -> 'RTX 4080'
      'NVIDIA A100-SXM4-80GB'                     -> 'A100-SXM4-80GB'
    """
    s = (name or "").strip()
    for prefix in ("NVIDIA ", "GeForce "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    for fragment in (" Generation Laptop GPU", " Laptop GPU", " Generation",
                     " Workstation", " GPU"):
        s = s.replace(fragment, "")
    s = " ".join(s.split())
    return s if len(s) <= 24 else s[:23] + "…"


def _status_html() -> str:
    """Render the dark-themed topbar: GPU pill with usage bar, loaded
    models pill, paint-extension pill. Each pill carries a colored dot
    that reflects the underlying state (green = healthy, amber = busy /
    partial, red = missing). The percentages and pixel widths are
    pre-computed server-side so the markup is pure CSS - no extra JS
    needed for the bar to fill correctly. GPU name is trimmed of
    marketing fluff so the whole row fits in the banner column."""
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        free, total = torch.cuda.mem_get_info(0)
        used = total - free
        used_gb = used / 1024 ** 3
        total_gb = total / 1024 ** 3
        pct = max(0.0, min(100.0, (used / total) * 100.0)) if total else 0.0
        gpu_dot = "ok" if pct < 75 else ("warn" if pct < 92 else "err")
        gpu_short = _shorten_gpu_name(p.name)
        gpu_pill = (
            f"<span class='tb-pill' title='{html.escape(p.name)}'>"
            f"<span class='dot {gpu_dot}'></span>"
            f"<b>{html.escape(gpu_short)}</b>"
            f"<span class='gpu-bar'><span style='width:{pct:.1f}%'></span></span>"
            f"<span class='label'>{used_gb:.1f} / {total_gb:.1f} GB</span>"
            f"</span>"
        )
    else:
        gpu_pill = (
            "<span class='tb-pill'>"
            "<span class='dot err'></span>"
            "<b>no CUDA GPU</b>"
            "</span>"
        )

    loaded = []
    if getattr(ENGINE, "_pipe", None) is not None: loaded.append("TripoSG")
    if getattr(MV_ENGINE, "_pipe", None) is not None: loaded.append("Hunyuan-MV")
    loaded_dot = "warn" if loaded else "ok"
    loaded_text = ", ".join(loaded) if loaded else "idle"
    loaded_pill = (
        f"<span class='tb-pill'>"
        f"<span class='dot {loaded_dot}'></span>"
        f"<span class='label'>Loaded</span> <b>{html.escape(loaded_text)}</b>"
        f"</span>"
    )

    rast_ok = rasterizer_ready()
    paint_pill = (
        f"<span class='tb-pill'>"
        f"<span class='dot {'ok' if rast_ok else 'err'}'></span>"
        f"<span class='label'>Paint ext</span> <b>{'✓' if rast_ok else '✗'}</b>"
        f"</span>"
    )

    return f"<div class='topbar'>{gpu_pill}{loaded_pill}{paint_pill}</div>"


def _open(path):
    p = Path(path)
    if not p.exists():
        return gr.Info(f"Path does not exist: {p}")
    try:
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            import subprocess; subprocess.Popen(["open", str(p)])
        else:
            import subprocess; subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        return gr.Info(f"Open failed: {e}")
    return gr.Info(f"Opened {p}")


# =============================================================================
# Stage-tracking helper for gr.Progress
# =============================================================================

class StageTracker:
    """Drives a gr.Progress object through a known sequence of stages.

    Each .step(label) advances the bar by 1/total_stages.
    Use .start(total) once, then .step("name") at each stage.
    """
    def __init__(self, progress: gr.Progress):
        self.p = progress
        self.t0 = time.time()
        self.total = 1
        self.done = 0

    def start(self, total: int):
        self.t0 = time.time()
        self.total = max(1, total)
        self.done = 0
        self.p(0.0, desc="Starting…")

    def step(self, label: str):
        self.done = min(self.done + 1, self.total)
        elapsed = time.time() - self.t0
        if self.done > 0:
            eta = elapsed / self.done * (self.total - self.done)
            eta_str = f" · ETA ~{int(eta)}s" if eta > 1 else ""
        else:
            eta_str = ""
        self.p(self.done / self.total,
               desc=f"[{int(elapsed)}s] {label}{eta_str}")

    def finish(self, label: str = "Done"):
        elapsed = time.time() - self.t0
        self.p(1.0, desc=f"✓ {label} ({int(elapsed)}s)")


# =============================================================================
# Tab 1: Preprocess
# =============================================================================

def _do_preprocess_single(image, size, bg_model, output_format, crop_str,
                          progress=gr.Progress()):
    if image is None: raise gr.Error("Upload an image.")
    tr = StageTracker(progress); tr.start(4)
    tr.step("Loading image"); img = image.convert("RGBA")
    if crop_str and crop_str.strip():
        try:
            l, t, r, b = [int(x) for x in crop_str.split(",")]
            img = img.crop((l, t, r, b))
        except ValueError:
            raise gr.Error("Crop must be 'left,top,right,bottom' in pixels.")
    tr.step("Cropping")
    if bg_model and bg_model != "none":
        from rembg import remove, new_session
        tr.step(f"Removing background ({bg_model})")
        img = remove(img, session=new_session(model_name=bg_model))
    else:
        tr.step("Skipping background removal")
    img = _square_pad(img).resize((int(size), int(size)), Image.LANCZOS)
    out_dir = INPUTS_DIR / "preprocessed"; out_dir.mkdir(parents=True, exist_ok=True)
    ext = {"PNG": ".png", "JPG": ".jpg", "WEBP": ".webp"}.get(output_format, ".png")
    save_img = img if ext == ".png" else img.convert("RGB")
    out_path = out_dir / f"prep_{int(time.time())}{ext}"
    save_img.save(out_path)
    tr.finish(f"Saved {out_path.name}")
    return img, f"✓ `{out_path}` ({int(size)}×{int(size)}, {output_format})"


def _do_preprocess_batch(folder_path, pattern, size, bg_model, output_format,
                         progress=gr.Progress()):
    if not folder_path or not folder_path.strip(): raise gr.Error("Enter a folder path.")
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir(): raise gr.Error(f"Not found: {folder}")
    exts = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
    images = [p for p in sorted(folder.glob(pattern.strip() or "*.*")) if p.suffix.lower() in exts]
    if not images: raise gr.Error(f"No images matching {pattern!r}")

    session = None
    if bg_model and bg_model != "none":
        from rembg import new_session
        session = new_session(model_name=bg_model)

    out_dir = INPUTS_DIR / f"preprocessed_{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = {"PNG": ".png", "JPG": ".jpg", "WEBP": ".webp"}.get(output_format, ".png")

    tr = StageTracker(progress); tr.start(len(images))
    msgs = []
    for i, p in enumerate(images, 1):
        tr.step(f"{p.name} ({i}/{len(images)})")
        try:
            img = Image.open(p).convert("RGBA")
            if session is not None:
                from rembg import remove; img = remove(img, session=session)
            img = _square_pad(img).resize((int(size), int(size)), Image.LANCZOS)
            (img if ext == ".png" else img.convert("RGB")).save(out_dir / f"{p.stem}{ext}")
            msgs.append(f"✓ {p.name}")
        except Exception as e:
            msgs.append(f"✗ {p.name}: {e}")
    tr.finish(f"{len(images)} files")
    return "\n".join(msgs) + f"\n\n→ `{out_dir}`"


# =============================================================================
# Tab 2: TripoSG - Single sub-tab handler
# =============================================================================

@operation(ENGINE, MV_ENGINE)
def _do_single(image, name_, preset, steps, guidance, octree_depth, dense_octree, bounds,
               rmbg_backend, seed, faces, bake_texture,
               # BMS pipeline (advanced) ----
               bms_enable, bms_name, bms_num_lods,
               bms_lod0, bms_lod1, bms_lod2, bms_lod3, bms_lod4, bms_lod5, bms_lod6,
               # NOTE: track_tqdm=False - on Windows Gradio's tqdm-tracking
               # patch (gradio/helpers.py init_tqdm) replaces the inner tqdm
               # `file` arg with `open(os.devnull, "w")` which defaults to
               # the OS codepage (cp1252). Tqdm's progress-bar block chars
               # (▏▎▍▌▋▊▉█) then crash the cp1252 encoder mid-inference and
               # abort the whole generate(). Our explicit StageTracker
               # handles visible progress anyway.
               progress=gr.Progress(track_tqdm=False)):
    if image is None: raise gr.Error("Upload an image.")
    if bms_enable and not (bms_name and bms_name.strip()):
        raise gr.Error("BMS pipeline requires an asset name.")

    stages = 4 + (1 if bms_enable else 0)
    tr = StageTracker(progress); tr.start(stages)
    tr.step("Loading TripoSG"); ENGINE.load()
    tr.step(f"Diffusion ({int(steps)} steps)")
    mesh = ENGINE.generate(
        image, seed=int(seed), num_inference_steps=int(steps),
        guidance_scale=float(guidance), faces=int(faces),
        remove_background=(rmbg_backend != "none"), rmbg_backend=rmbg_backend,
        octree_depth=int(octree_depth), dense_octree_depth=int(dense_octree),
        bounds=float(bounds),
    )
    if bake_texture:
        tr.step("Baking planar texture")
        mesh = planar_project_front(mesh, image)
    else:
        tr.step("Skipping texture")

    # Per-asset folder: outputs/<asset_name>/<asset_name>.glb. Falls
    # back to a `webui_<timestamp>` name when the user hasn't typed
    # one, so unnamed runs still get a folder of their own and never
    # collide with each other.
    asset_name = (name_ or "").strip() or f"webui_{int(time.time())}"
    asset_dir = fresh_asset_dir(OUT_DIR, asset_name)
    out_path = asset_dir / f"{asset_name}.glb"
    # Writes both `<asset>.glb` and `<asset>.obj` (+ `.mtl` + texture PNG
    # if a planar bake is enabled). GLB is what the Model3D viewer below
    # loads; OBJ + MTL is the Blender/Maya-friendly companion.
    export_glb_and_obj(mesh, out_path)
    obj_companion = out_path.with_suffix(".obj")

    msg = (f"✓ `{out_path}` · {mesh.vertices.shape[0]:,}V / "
           f"{mesh.faces.shape[0]:,}F\n"
           f"Editable OBJ: `{obj_companion}`\n"
           f"Asset folder: `{asset_dir}`")
    if bms_enable:
        lod_targets = _build_lod_targets(bms_num_lods, bms_lod0, bms_lod1, bms_lod2,
                                          bms_lod3, bms_lod4, bms_lod5, bms_lod6)
        tr.step(f"Building BMS LOD set ({len(lod_targets)} LODs)")
        # Hard-coded "low" (mesh-derived NumPy bake) for the BMS LOD
        # normal map. The user-facing dropdown was removed from
        # TripoSG Single because it implied it applied to the
        # standalone GLB output, which it didn't (the bake needs UVs
        # that the bare TripoSG mesh doesn't have). "Low" is the only
        # baker that ever made sense here: free, no AI deps, no albedo
        # required - and it silently skips if the mesh has no UVs at
        # all. Users who want AI normal bakes should go through the
        # Multi-view + Paint pipeline where albedos exist.
        bms_normal_baker = "low"
        asset_dir = make_lod_set(mesh, bms_name.strip(), lod_targets, BMS_DIR,
                                 normal_baker=bms_normal_baker)
        msg += (f"\n→ BMS LODs ({len(lod_targets)}, "
                f"normal={bms_normal_baker}): `{asset_dir}`")
    tr.finish(f"{mesh.faces.shape[0]:,} faces")
    return str(out_path), msg


# =============================================================================
# Tab 2: TripoSG - Folder sub-tab handler
# =============================================================================

@operation(ENGINE, MV_ENGINE)
def _do_batch(folder_path, pattern, preset, steps, guidance, octree_depth,
              dense_octree, bounds, rmbg_backend, seed, faces, bake_texture, skip_existing,
              # track_tqdm=False: see explanation on _do_single. Same
              # Gradio/Windows cp1252 + tqdm-block-chars crash applies.
              progress=gr.Progress(track_tqdm=False)):
    if not folder_path or not folder_path.strip(): raise gr.Error("Enter a folder path.")
    folder = Path(folder_path)
    if not folder.exists(): raise gr.Error(f"Not found: {folder}")
    images = sorted(folder.glob(pattern.strip() or "*.png"))
    if not images: raise gr.Error(f"No images matching {pattern!r}")

    ENGINE.load()
    out_dir = OUT_DIR / f"batch_{int(time.time())}"; out_dir.mkdir(parents=True, exist_ok=True)
    tr = StageTracker(progress); tr.start(len(images))

    msgs, last_glb = [], None
    for i, img_path in enumerate(images, 1):
        out_path = out_dir / f"{img_path.stem}.glb"
        if skip_existing and out_path.exists():
            tr.step(f"⊘ {img_path.name} (skipped)")
            msgs.append(f"⊘ {img_path.name}")
            continue
        tr.step(f"{img_path.name} ({i}/{len(images)})")
        try:
            mesh = ENGINE.generate(
                str(img_path), seed=int(seed), num_inference_steps=int(steps),
                guidance_scale=float(guidance), faces=int(faces),
                remove_background=(rmbg_backend != "none"), rmbg_backend=rmbg_backend,
                octree_depth=int(octree_depth), dense_octree_depth=int(dense_octree),
                bounds=float(bounds),
            )
            if bake_texture: mesh = planar_project_front(mesh, img_path)
            # Writes both `<stem>.glb` and `<stem>.obj` (+ MTL + texture
            # PNG when a planar bake ran). The helper renames the material
            # to `<stem>` so the OBJ/MTL/texture files for different
            # images in this shared batch folder never overwrite each
            # other.
            export_glb_and_obj(mesh, out_path); last_glb = str(out_path)
            msgs.append(f"✓ {img_path.name} → {mesh.faces.shape[0]:,}F (+ .obj)")
        except Exception as e:
            msgs.append(f"✗ {img_path.name}: {e}")
            ENGINE.unload()
    tr.finish(f"{len(images)} images")
    return last_glb, "\n".join(msgs) + f"\n\n→ `{out_dir}`"


# =============================================================================
# Tab 3: Multi-view (Hunyuan3D-2mv) — unified shape + optional PBR paint
# =============================================================================
#
# This tab merges what used to be two tabs ("3·Multi-view" shape-only and
# "4·MV+PBR" shape+paint). A single `Paint` checkbox toggles the PBR
# pipeline. When Paint is on, the same handler:
#   1. Generates shape via Hunyuan3D-2mv.
#   2. Frees shape VRAM.
#   3. Runs the Hunyuan3D-2.1 paint pipeline.
#   4. Bakes + embeds a tangent-space normal map into the textured GLB,
#      so normal mapping is a first-class part of the PBR output (no longer
#      conditional on BMS LOD export).
# When Paint is off, the handler behaves like the old MV tab: shape only,
# optional planar bake of one view, optional BMS LOD set.

def _append_normal_to_mtl(mtl_path: Path, normal_filename: str) -> None:
    """Add `map_Bump` + `norm` references to an existing Wavefront MTL.

    Idempotent: if the MTL already references this normal map (e.g. because
    the user re-ran the same generation), the existing reference is left
    in place and no duplicates are added.

    The dual-directive write (`map_Bump` AND `norm`) mirrors the convention
    used elsewhere in this codebase (`lod_export._compose_mtl_lines`) and
    maximises compatibility: older OBJ importers (Maya, classic Blender)
    read `map_Bump`; modern glTF-aware ones read `norm`.
    """
    text = mtl_path.read_text(encoding="utf-8", errors="replace")
    needs_bump = f"map_Bump {normal_filename}" not in text
    needs_norm = f"norm {normal_filename}" not in text
    if not (needs_bump or needs_norm):
        return
    # Ensure trailing newline so our appended lines don't fuse onto a
    # pre-existing last line (e.g. if the painter's MTL didn't end with
    # one).
    if not text.endswith("\n"):
        text += "\n"
    if needs_bump:
        text += f"map_Bump {normal_filename}\n"
    if needs_norm:
        text += f"norm {normal_filename}\n"
    mtl_path.write_text(text, encoding="utf-8")


def _embed_normal_map_in_glb(glb_path: Path, baker: str) -> Path | None:
    """Bake a tangent-space normal map and embed it into a painted GLB.

    Hunyuan3D-2.1 paint outputs only albedo + metallicRoughness; it uses
    the normal direction as a CONDITIONING input but does not emit a normal
    texture. This helper synthesises one with the selected baker
    ("low"/"medium"/"high") and rewrites `glb_path` with the new map
    attached to the PBR material.

    The baked normal map is ALSO saved as a standalone PNG inside the
    asset folder, using the painter's naming convention so it sits
    next to the other texture maps:

        outputs/<asset_name>/
          <asset_name>.glb                          (this glb_path)
          <asset_name>_textured.jpg                  (albedo)
          <asset_name>_textured_metallic.jpg
          <asset_name>_textured_roughness.jpg
          <asset_name>_textured_normal.png           <-- this function adds this

    Without that on-disk PNG the "Normal map: Low/Medium/High" control
    appeared to do nothing (the embedded copy inside the GLB is
    invisible in a file explorer).

    Returns the path to the saved standalone normal-map PNG on success.
    Returns None if the bake was skipped (`baker == "off"`) or failed.
    """
    baker = (baker or "off").lower()
    if baker == "off":
        return None
    try:
        import trimesh
        import trimesh.visual.material as _mat
        loaded = trimesh.load(str(glb_path), force="mesh", process=False)
        if not isinstance(loaded, trimesh.Trimesh):
            print(f"[mv-unified] WARN: could not load {glb_path} as a single mesh "
                  f"for normal-map embed.")
            return None
        mat = getattr(loaded.visual, "material", None)
        if getattr(mat, "normalTexture", None) is not None:
            return None
        albedo = getattr(mat, "baseColorTexture", None) if mat is not None else None
        ref_size = max(albedo.size) if (albedo is not None and getattr(albedo, "size", None)) else 2048
        normal_img = bake_normal_map(loaded, albedo, baker=baker, uv_size=int(ref_size))
        if normal_img is None:
            return None
        if mat is None or not isinstance(mat, _mat.PBRMaterial):
            loaded.visual.material = _mat.PBRMaterial(
                name=getattr(mat, "name", "material") if mat is not None else "material",
                baseColorTexture=albedo,
            )
        import json
        (glb_path.with_suffix(".normal_bake.json")).write_text(json.dumps({
            "requested": baker, "actual": normal_img.info.get("modelunify_baker", "unknown")
        }), encoding="utf-8")
        loaded.visual.material.normalTexture = normal_img
        loaded.export(str(glb_path))

        # Save the baked normal as a real PNG next to the painter's
        # other texture files. The naming mirrors what the painter
        # itself writes (`<stem>_textured_metallic.jpg`,
        # `<stem>_textured_roughness.jpg`) so all four PBR channels
        # show up together in the asset folder.
        normal_png = glb_path.with_name(f"{glb_path.stem}_textured_normal.png")
        try:
            normal_img.save(str(normal_png))
            print(f"[mv-unified] Normal map saved: {normal_png}")
        except Exception as _e:
            print(f"[mv-unified] WARN: could not save standalone normal PNG: {_e}")
            return None

        # Also link the normal map into the painter's MTL file so the
        # OBJ companion (which 3D editors like Blender / Maya open
        # directly) carries the full PBR set instead of just albedo +
        # metallic + roughness. We use both `map_Bump` and `norm`
        # directives - same dual-line convention `_compose_mtl_lines`
        # uses in lod_export.py - which maximises compatibility:
        # older OBJ importers read `map_Bump`, glTF-aware ones read
        # `norm`.
        mtl_path = glb_path.with_name(f"{glb_path.stem}_textured.mtl")
        if mtl_path.exists():
            try:
                _append_normal_to_mtl(mtl_path, normal_png.name)
            except Exception as _e:
                print(f"[mv-unified] WARN: could not patch MTL "
                      f"`{mtl_path.name}` with normal map: {_e}")

        return normal_png
    except Exception as e:
        print(f"[mv-unified] WARN: normal-map embed failed: {e} - "
              f"continuing without one.")
        return None


@operation(ENGINE, MV_ENGINE)
def _do_mv_unified(f, l, b, r, name_, paint_enable,
                   shape_steps, shape_octree, shape_guidance, shape_chunks,
                   shape_mc_level, shape_seed, shape_faces, shape_bake,
                   paint_views, paint_res, paint_render, paint_texture,
                   paint_bake_exp, paint_merge, paint_remesh, paint_save_maps,
                   paint_low_vram,
                   normal_baker,
                   bms_enable, bms_share_textures, bms_num_lods,
                   bms_lod0, bms_lod1, bms_lod2, bms_lod3, bms_lod4, bms_lod5, bms_lod6,
                   # NOTE: track_tqdm=False on purpose - the Paint path
                   # triggers MANY tqdm bars (shape diffusion, volume
                   # decoding, paint diffusion, super-resolution, bake) that
                   # would otherwise stack in the UI as duplicate progress
                   # lines. We rely on the explicit StageTracker below;
                   # the terminal still shows tqdm bars for fine-grained progress.
                   progress=gr.Progress(track_tqdm=False)):
    views = {k: v for k, v in [("front", f), ("left", l), ("back", b), ("right", r)] if v is not None}
    if not views:
        raise gr.Error("Upload at least one view.")
    paint_enable = bool(paint_enable)
    normal_baker = (str(normal_baker) or "off").lower()

    if paint_enable and not rasterizer_ready():
        raise gr.Error("custom_rasterizer not compiled - Paint pipeline unavailable.")
    if (paint_enable or bms_enable) and not (name_ and name_.strip()):
        raise gr.Error("Asset name is required when Paint or BMS pipeline is enabled.")
    name = (name_ or "").strip()

    # Stage budget:
    #   shape:        1
    #   paint:        +2 (free VRAM, paint), +1 if normal-map embed runs
    #   bms:          +1
    stages = 1
    if paint_enable:
        stages += 2 + (1 if normal_baker != "off" else 0)
    if bms_enable:
        stages += 1
    tr = StageTracker(progress); tr.start(stages)

    # ---- Shape ---------------------------------------------------------
    tr.step(f"Shape: MV diffusion ({len(views)} views · "
            f"{int(shape_steps)} steps · octree {int(shape_octree)})")
    MV_ENGINE.load()
    mesh = MV_ENGINE.generate_multiview(
        views, seed=int(shape_seed), num_inference_steps=int(shape_steps),
        octree_resolution=int(shape_octree), guidance_scale=float(shape_guidance),
        num_chunks=int(shape_chunks), mc_level=float(shape_mc_level),
    )

    # Every Multi-view generation gets its own asset folder. The folder
    # name is the user-supplied asset name (or a timestamp fallback if
    # unnamed). All artifacts for one generation - white mesh, textured
    # GLB, editable OBJ + MTL + texture maps, normal map - live inside
    # this single folder so users do not have to hunt through outputs/.
    asset_name = name if name else f"mv_{int(time.time())}"
    asset_dir = fresh_asset_dir(OUT_DIR, asset_name)

    if not paint_enable:
        # Shape-only path (legacy MV behaviour).
        if int(shape_faces) > 0:
            mesh = decimate(mesh, int(shape_faces))
        if shape_bake != "none" and shape_bake in views:
            mesh = planar_project_front(mesh, views[shape_bake])
        elif shape_bake != "none":
            mesh = planar_project_front(mesh, next(iter(views.values())))
        out_path = asset_dir / f"{asset_name}.glb"
        mesh.export(str(out_path))
        msg = (f"✓ `{out_path}` · {mesh.faces.shape[0]:,}F\n"
               f"Asset folder: `{asset_dir}`")
        final_glb = out_path
    else:
        # Paint path: shape -> free VRAM -> PBR paint -> embed normal map.
        # All paint artifacts (OBJ + MTL + texture JPGs + final GLB +
        # baked normal PNG) land inside `asset_dir`. The user gets both
        # the binary GLB (good for viewers) and the editable Wavefront
        # OBJ (good for Blender / Maya / etc.) side by side.
        white_glb = asset_dir / f"{asset_name}_white.glb"
        mesh.export(str(white_glb))

        # CRITICAL: free shape model from VRAM before loading paint pipeline.
        tr.step("Paint: freeing shape VRAM")
        MV_ENGINE.unload()
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            print(f"[mv-unified] After unload: VRAM free="
                  f"{free/1024**3:.1f}/{total/1024**3:.1f} GB", flush=True)

        tr.step(f"Paint: PBR pipeline (texture {int(paint_texture)}²)")
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig
        painter = Hunyuan3DPainter(PaintConfig(
            max_num_view=int(paint_views), resolution=int(paint_res),
            use_remesh=bool(paint_remesh),
            render_size=int(paint_render), texture_size=int(paint_texture),
            bake_exp=int(paint_bake_exp), merge_method=str(paint_merge),
            save_separate_maps=bool(paint_save_maps),
            low_vram_mode=bool(paint_low_vram),
        ))
        painter.load()
        ref_image = views.get("front") or next(iter(views.values()))
        # `painter.paint()` writes the final .glb at `out_glb` AND keeps
        # the painter's native OBJ bundle (`<stem>_textured.obj` + .mtl +
        # albedo/metallic/roughness JPGs) in the same asset folder so
        # the user can open the OBJ in any 3D editor without GLB import.
        out_glb = asset_dir / f"{asset_name}.glb"
        painter.paint(str(white_glb), ref_image, str(out_glb))

        # Build the status block now that paint has finished. The mmgp
        # status line lets the user confirm what actually ran instead of
        # having to scrape the terminal for [paint] log lines.
        if bool(paint_low_vram):
            mmgp_line = ("Low-VRAM mode: mmgp offload used during paint (released)"
                         if painter.last_mmgp_applied
                         else "Low-VRAM mode: requested but NOT active (see warnings)")
        else:
            mmgp_line = "Low-VRAM mode: OFF (full-VRAM path)"

        msg = (f"✓ Textured GLB: `{out_glb}`\n"
               f"Editable OBJ: `{asset_dir / (asset_name + '_textured.obj')}`\n"
               f"White (untextured): `{white_glb}`\n"
               f"Asset folder: `{asset_dir}`\n"
               f"{mmgp_line}")
        for _w in painter.load_warnings:
            msg += f"\n⚠ {_w}"

        if normal_baker != "off":
            tr.step(f"Paint: normal map ({normal_baker})")
            normal_png = _embed_normal_map_in_glb(out_glb, normal_baker)
            if normal_png is not None:
                import json
                actual_baker = json.loads(out_glb.with_suffix(".normal_bake.json").read_text())["actual"]
                msg += f"\n→ Normal map (requested {normal_baker}; actual {actual_baker}): `{normal_png}`"
            else:
                msg += f"\n→ Normal map: skipped or failed (baker={normal_baker})."

        final_glb = out_glb

    MV_ENGINE.unload()
    # ---- BMS LOD set ----------------------------------------------------
    if bms_enable:
        lod_targets = _build_lod_targets(bms_num_lods, bms_lod0, bms_lod1, bms_lod2,
                                          bms_lod3, bms_lod4, bms_lod5, bms_lod6)
        if paint_enable:
            tr.step(f"BMS LOD set ({len(lod_targets)} LODs, "
                    f"{'shared' if bms_share_textures else 'per-LOD'} textures)")
            try:
                if bms_share_textures:
                    # `make_textured_lod_set` re-bakes a normal map only when
                    # the textured GLB doesn't already carry one; the embed
                    # above means we usually skip that redundant bake.
                    asset_dir = make_textured_lod_set(
                        final_glb, name, lod_targets, BMS_DIR,
                        normal_baker=normal_baker,
                    )
                    msg += (f"\n→ BMS LODs (shared textures, {len(lod_targets)} LODs, "
                            f"normal_baker={normal_baker}): `{asset_dir}`")
                else:
                    import trimesh
                    _scene = trimesh.load(str(final_glb), force="mesh", process=False)
                    asset_dir = make_lod_set(_scene, name, lod_targets, BMS_DIR)
                    msg += (f"\n→ BMS LODs (per-LOD GLB, {len(lod_targets)} "
                            f"LODs): `{asset_dir}`")
            except Exception as e:
                # #region agent log
                try:
                    import json as _json, time as _time, traceback as _tb
                    from pathlib import Path as _P
                    _entry = {
                        "sessionId": "c02a0e",
                        "id": f"log_{int(_time.time()*1000)}_mv_unified_bms_except",
                        "timestamp": int(_time.time() * 1000),
                        "location": "web_ui.py:_do_mv_unified:bms_except",
                        "message": "BMS LOD generation raised - caught and shown in status",
                        "hypothesisId": "H1",
                        "data": {
                            "exception_type": type(e).__name__,
                            "exception_msg": str(e),
                            "share_textures": bool(bms_share_textures),
                            "asset_name": name,
                            "lod_count": len(lod_targets),
                            "traceback": _tb.format_exc(),
                        },
                    }
                    _log_path = _P(__file__).resolve().parent.parent / "debug-c02a0e.log"
                    with open(_log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps(_entry) + "\n")
                except Exception:
                    pass
                # #endregion
                msg += f"\n[BMS LOD set FAILED]: {type(e).__name__}: {e}"
                import traceback as _traceback
                _traceback.print_exc()
        else:
            tr.step(f"BMS LOD set ({len(lod_targets)} LODs)")
            asset_dir = make_lod_set(mesh, name, lod_targets, BMS_DIR,
                                     normal_baker=normal_baker)
            msg += (f"\n→ BMS LODs ({len(lod_targets)}, "
                    f"normal={normal_baker}): `{asset_dir}`")

    tr.finish("Done")
    return str(final_glb), msg


# =============================================================================
# Tab 4: Paint PBR Texture (apply paint to an existing mesh)
# =============================================================================

@operation(ENGINE, MV_ENGINE)
def _do_paint(mesh_file, ref_img, preset, views_, res_, render_, texture_,
              bake_exp_, merge_, remesh_, save_maps_, low_vram_,
              # track_tqdm=False: see explanation on _do_single. Same
              # Gradio/Windows cp1252 + tqdm-block-chars crash applies
              # (also paint triggers many tqdm bars from sub-pipelines).
              progress=gr.Progress(track_tqdm=False)):
    if mesh_file is None: raise gr.Error("Upload a mesh file.")
    if ref_img is None: raise gr.Error("Upload a reference image.")
    if not rasterizer_ready(): raise gr.Error("custom_rasterizer not compiled.")
    from scripts.engine_paint import Hunyuan3DPainter, PaintConfig
    tr = StageTracker(progress); tr.start(3)
    tr.step("Loading Hunyuan3D-2.1 paint pipeline")
    painter = Hunyuan3DPainter(PaintConfig(
        max_num_view=int(views_), resolution=int(res_), use_remesh=bool(remesh_),
        render_size=int(render_), texture_size=int(texture_),
        bake_exp=int(bake_exp_), merge_method=str(merge_),
        save_separate_maps=bool(save_maps_),
        low_vram_mode=bool(low_vram_),
    ))
    painter.load()
    mesh_path = getattr(mesh_file, "name", mesh_file)
    # Per-asset folder: outputs/<input_stem>/  containing
    #   <stem>.glb                       (final textured GLB)
    #   <stem>_textured.obj + .mtl       (editable Wavefront for 3D editors)
    #   <stem>_textured.jpg              (albedo)
    #   <stem>_textured_metallic.jpg
    #   <stem>_textured_roughness.jpg
    asset_name = Path(mesh_path).stem
    asset_dir = fresh_asset_dir(OUT_DIR, asset_name)
    out_path = str(asset_dir / f"{asset_name}.glb")
    tr.step(f"Painting (texture {int(texture_)}² · {int(views_)} views)")
    painter.paint(mesh_path, ref_img, out_path)
    tr.finish("Done")
    if bool(low_vram_):
        mmgp_line = ("Low-VRAM mode: mmgp offload used during paint (released)"
                     if painter.last_mmgp_applied
                     else "Low-VRAM mode: requested but NOT active (see warnings)")
    else:
        mmgp_line = "Low-VRAM mode: OFF (full-VRAM path)"
    msg = (f"✓ Textured GLB: `{out_path}`\n"
           f"Editable OBJ: `{asset_dir / (asset_name + '_textured.obj')}`\n"
           f"Asset folder: `{asset_dir}`\n"
           f"{mmgp_line}")
    for _w in painter.load_warnings:
        msg += f"\n⚠ {_w}"
    return out_path, msg


# =============================================================================
# Compact UI
# =============================================================================

# ----- Tooltip JS (injected into <head> via gr.Blocks(head=...)) -------------
# Two Gradio quirks shaped this approach:
#
#   1. gr.HTML strips <script> tags. Its content goes through React's
#      dangerouslySetInnerHTML, which intentionally never executes scripts.
#      An earlier attempt that embedded the JS inside a gr.HTML block was
#      silently no-op'd: the icon rendered, but no handlers were attached.
#
#   2. gr.Blocks(js="() => { ... }") also did not fire in our Gradio
#      4.44 install. Runtime instrumentation showed zero JS-side log
#      events with that delivery channel, while the Python side correctly
#      emitted the icon HTML. The arrow-function-as-event-handler path
#      simply wasn't reaching the page.
#
# gr.Blocks(head=...) DOES work: Gradio injects the string verbatim into
# the page's <head>, and the browser parses + executes any <script> tags
# in the normal way. The script below uses a DOMContentLoaded guard
# because <head> is parsed BEFORE <body> exists, so document.body would
# be null if we tried to use it synchronously.
#
# What the script does once it runs:
#  - Creates ONE popup element appended to document.body. body has no
#    transform / filter / perspective parent, so its `position: fixed`
#    really IS fixed to the viewport - it is not trapped by any of the
#    overflow:auto / transform containers that Gradio places around its
#    own components (which would otherwise clip the popup to a column).
#  - Listens for mouseover / mouseout / focusin / focusout on `.tt-icon`
#    via event delegation on `document`, so it survives Gradio's later
#    re-renders and automatically picks up icons added by lazy-mounted
#    tabs.
#  - A `click` capture handler toggles a "pinned" state. Pinned = the
#    popup stays open even after the cursor leaves. Click anywhere not
#    inside the icon or the popup unpins. This makes the tooltip usable
#    on touch devices and lets mouse users lock it open while reading.
TOOLTIP_HEAD = r"""
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet" />
<script>
/* ---------------------------------------------------------------
   Settings panel cleanup.

   Gradio 6.17 renders its Settings panel as a Svelte component mounted
   at the document body (NOT inside .gradio-container, NOT a native
   <dialog>). The sections are <div class="banner-wrap svelte-1t60wb3">.
   The first section is the "Display Theme" block - it has NO <h2>
   heading, only theme buttons. Every other section has an <h2>.
   That structural difference is what we use to identify it (text
   matching by "Display Theme" string is locale-dependent; structure
   isn't).

   This script:
     1. Hides every .banner-wrap that has no <h2> child (= Display Theme).
     2. Walks up from the first .banner-wrap to find the outer panel
        container (the wrapper Gradio mounts the panel into) and
        constrains its inline width / position so it becomes a
        side-card instead of a full-screen sheet.
   --------------------------------------------------------------- */
(function () {
    /* From the Gradio 6.17 Settings source the layout is, in order:
         <div class="banner-wrap">  Display Theme  (NO h2)
         <Dropdown>                 Language
         <div class="banner-wrap"><h2>Progressive Web App</h2>...</div>
         <div class="banner-wrap"><h2>Screen Studio</h2>...</div>
       So the Display Theme block is either (a) the first .banner-wrap
       OR (b) any .banner-wrap with NO <h2> child. We hide both. */

    function hideDisplayTheme() {
        const banners = document.querySelectorAll('.banner-wrap');
        if (!banners.length) return false;
        banners.forEach((bw, idx) => {
            const hasHeading = !!bw.querySelector('h2');
            // First banner OR any banner without an h2 = Display Theme.
            if (idx === 0 || !hasHeading) {
                bw.style.setProperty('display', 'none', 'important');
                bw.setAttribute('data-hidden-by-theme', '1');
            }
        });
        return true;
    }

    function constrainPanel() {
        const firstBanner = document.querySelector('.banner-wrap:not([data-hidden-by-theme])')
                         || document.querySelector('.banner-wrap');
        if (!firstBanner) return;

        // Walk up to find the floating panel root (the wrapper that
        // covers the screen). We stop at the first ancestor that is
        // either position:fixed/absolute OR a direct child of <body>.
        let node = firstBanner.parentElement;
        let panelRoot = null;
        let safety = 14;
        while (node && safety-- > 0) {
            if (node === document.body) break;
            const cs = window.getComputedStyle(node);
            if (cs.position === 'fixed' || cs.position === 'absolute') {
                panelRoot = node;
            }
            if (node.parentElement === document.body) {
                panelRoot = panelRoot || node;
                break;
            }
            node = node.parentElement;
        }
        if (!panelRoot) return;

        // Apply layout + theme constraints inline (highest specificity).
        // Re-applying is idempotent so MutationObserver storms are safe.
        Object.assign(panelRoot.style, {
            maxWidth:    '560px',
            width:       'min(560px, 92vw)',
            maxHeight:   '85vh',
            height:      'auto',
            left:        'auto',
            right:       '24px',
            top:         '72px',
            bottom:      'auto',
            margin:      '0',
            borderRadius:'14px',
            border:      '1px solid rgba(255,255,255,0.14)',
            background:  'rgba(15, 20, 36, 0.97)',
            color:       '#f4f5fb',
            boxShadow:   '0 16px 48px rgba(0,0,0,0.50)',
            overflow:    'auto',
            zIndex:      '2147483646',
            backdropFilter: 'blur(20px) saturate(140%)',
            WebkitBackdropFilter: 'blur(20px) saturate(140%)',
        });

        // Also try to find and lighten the surrounding backdrop / overlay
        // so the rest of the app stays visible behind the panel. Any
        // sibling of panelRoot that covers the viewport is treated as
        // a backdrop and made semi-transparent.
        const siblings = Array.from(panelRoot.parentElement?.children || []);
        siblings.forEach((s) => {
            if (s === panelRoot) return;
            const r = s.getBoundingClientRect();
            if (r.width > window.innerWidth * 0.9 && r.height > window.innerHeight * 0.9) {
                Object.assign(s.style, {
                    background: 'rgba(7, 8, 15, 0.55)',
                    backdropFilter: 'blur(3px)',
                    WebkitBackdropFilter: 'blur(3px)',
                });
            }
        });
    }

    function cleanSettingsPanel() {
        const found = hideDisplayTheme();
        if (found) constrainPanel();
    }

    function initSettingsCleanup() {
        cleanSettingsPanel();
        const mo = new MutationObserver(() => cleanSettingsPanel());
        mo.observe(document.body, {
            childList: true, subtree: true,
            attributes: true, attributeFilter: ['class', 'style', 'open'],
        });
        // Belt-and-braces: also poll every 500 ms for the first 30 s after
        // load, in case the panel mounts via a code path the observer
        // doesn't catch (e.g. shadow DOM, deferred Svelte hydration).
        let polls = 0;
        const pollInterval = setInterval(() => {
            cleanSettingsPanel();
            polls += 1;
            if (polls > 60) clearInterval(pollInterval);
        }, 500);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSettingsCleanup);
    } else {
        initSettingsCleanup();
    }
})();
</script>
<script>
(function () {
    function setup() {
        if (window.__ttInit) return;
        window.__ttInit = true;

        const popup = document.createElement('div');
    popup.id = 'tt-singleton';
    Object.assign(popup.style, {
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%) scale(0.96)',
        width: 'min(560px, 92vw)',
        maxHeight: '80vh',
        overflowY: 'auto',
        padding: '20px 24px',
        background: 'rgba(17, 24, 39, 0.98)',
        color: '#f9fafb',
        border: '1px solid rgba(255, 255, 255, 0.10)',
        borderRadius: '10px',
        boxShadow: '0 20px 60px rgba(0, 0, 0, 0.45)',
        font: '13px/1.55 "Segoe UI", system-ui, sans-serif',
        textAlign: 'left',
        zIndex: '2147483647',
        whiteSpace: 'pre-wrap',
        pointerEvents: 'auto',
        opacity: '0',
        visibility: 'hidden',
        cursor: 'default',
        transition: 'opacity 0.15s ease-out, transform 0.15s ease-out'
    });
    document.body.appendChild(popup);

    let pinned = false;

    function show(icon) {
        const inner = icon.querySelector('.tt-popup');
        if (!inner) return;
        popup.textContent = inner.textContent;
        popup.style.visibility = 'visible';
        popup.style.opacity = '1';
        popup.style.transform = 'translate(-50%, -50%) scale(1)';
    }
    function hide(force) {
        if (pinned && !force) return;
        popup.style.opacity = '0';
        popup.style.transform = 'translate(-50%, -50%) scale(0.96)';
        setTimeout(() => {
            if (popup.style.opacity === '0') popup.style.visibility = 'hidden';
        }, 200);
    }

    document.addEventListener('mouseover', (e) => {
        const icon = e.target.closest && e.target.closest('.tt-icon');
        if (icon && !pinned) show(icon);
    });
    document.addEventListener('mouseout', (e) => {
        const icon = e.target.closest && e.target.closest('.tt-icon');
        if (icon && !icon.contains(e.relatedTarget)) hide(false);
    });
    document.addEventListener('focusin', (e) => {
        const icon = e.target.closest && e.target.closest('.tt-icon');
        if (icon && !pinned) show(icon);
    });
    document.addEventListener('focusout', (e) => {
        const icon = e.target.closest && e.target.closest('.tt-icon');
        if (icon) hide(false);
    });

    document.addEventListener('click', (e) => {
        const icon = e.target.closest && e.target.closest('.tt-icon');
        if (icon) {
            if (pinned) {
                pinned = false;
                hide(true);
            } else {
                pinned = true;
                show(icon);
            }
            e.stopPropagation();
            return;
        }
        if (pinned && !popup.contains(e.target)) {
            pinned = false;
            hide(true);
        }
    }, true);
    }
    // <head> scripts run before <body> exists, so defer setup() until
    // the DOM is ready (otherwise document.body would be null and the
    // appendChild call would throw).
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
})();
</script>
"""


CSS = """
/* =================================================================
   DESIGN TOKENS  -  change these to retheme the entire app.
   Brand: Modelunify - the palette mirrors the logo's teal-to-blue
   crystal gradient on a deep-navy surface so the wordmark in the
   header reads as part of the same visual family as the UI chrome.
   ================================================================= */
:root {
    /* surfaces - cooler navy than the previous near-black so the
       teal/blue accents have somewhere to breathe */
    --bg-0:        #06101A;                    /* page base (deep navy) */
    --bg-1:        #0E1A2E;                    /* card base */
    --bg-2:        #15243B;                    /* raised */
    --bg-glass:    rgba(21, 36, 59, 0.55);
    --border:      rgba(255, 255, 255, 0.08);
    --border-str:  rgba(255, 255, 255, 0.14);
    /* text */
    --text-hi:     #f4f8fb;
    --text-md:     #c5d0dd;
    --text-lo:     #8a96aa;
    --text-dim:    #5f6a7d;
    /* accent: Modelunify Teal -> Crystal Blue
       Teal  #2DD4BF  - matches the central "AI" badge in the logo.
       Blue  #3D8FE0  - matches the blue crystals on the logo's right side.
       Mid   #36B4D0  - geometric mid-point, used for shadows & glows so
                        a single colour can stand in for "the brand". */
    --acc-1:       #2DD4BF;
    --acc-2:       #3D8FE0;
    --acc-grad:    linear-gradient(135deg, #2DD4BF 0%, #3D8FE0 100%);
    --acc-glow:    0 0 0 3px rgba(54, 180, 208, 0.28);
    --acc-soft:    rgba(54, 180, 208, 0.14);
    /* feedback */
    --ok:          #10b981;
    --warn:        #f59e0b;
    --err:         #ef4444;
    /* geometry / motion */
    --radius-sm:   8px;
    --radius:      14px;
    --radius-lg:   20px;
    --shadow-soft: 0 8px 28px rgba(0, 0, 0, 0.35);
    --shadow-pop:  0 16px 48px rgba(0, 0, 0, 0.50);
    --t-fast:      120ms cubic-bezier(.2, .7, .2, 1);
    --t-base:      180ms cubic-bezier(.2, .7, .2, 1);
}

/* =================================================================
   GLOBAL
   ================================================================= */
html, body, .gradio-container, gradio-app {
    background:
        radial-gradient(1200px 600px at 10% -10%, rgba(45, 212, 191, 0.18), transparent 60%),
        radial-gradient(1000px 500px at 110% 10%,  rgba(61, 143, 224, 0.16), transparent 60%),
        var(--bg-0) !important;
    color: var(--text-hi) !important;
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
.gradio-container {
    max-width: 1500px !important;
    margin: 0 auto !important;
    padding: 18px 22px 64px !important;
}
.gradio-container * {
    font-family: inherit;
}

/* selection */
::selection { background: rgba(61, 143, 224, 0.35); color: #fff; }

/* scrollbars (WebKit) */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.08); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.16); }

/* =================================================================
   BLOCKS / CARDS  -  every gr.Column / gr.Group becomes a glass card
   ================================================================= */
.gradio-container .block,
.gradio-container .form,
.gradio-container .panel,
.gradio-container .gr-block,
.gradio-container .gr-form {
    background: var(--bg-glass) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow-soft) !important;
    -webkit-backdrop-filter: blur(14px) saturate(140%);
            backdrop-filter: blur(14px) saturate(140%);
    color: var(--text-hi) !important;
}
/* nested blocks: lose the second border so cards don't stack borders */
.gradio-container .block .block,
.gradio-container .form .block,
.gradio-container .gr-form .block,
.gradio-container .block .gr-form,
.gradio-container .form .form {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    -webkit-backdrop-filter: none;
            backdrop-filter: none;
}

/* rows / columns: just spacing */
.gradio-container .row, .gradio-container .gr-row { gap: 12px !important; }
.gradio-container .column, .gradio-container .gr-column { gap: 10px !important; }

/* =================================================================
   HEADER  -  topbar status banner + toolbar
   Lighter pill background + brighter base text (was reading too dark
   on the aurora background). Pills are allowed to wrap to a second
   line on narrow screens so long GPU names don't get clipped.
   ================================================================= */
.topbar {
    display: flex; align-items: center; gap: 10px;
    padding: 4px 0;
    font: 500 13px 'Inter', sans-serif;
    color: var(--text-hi);
    flex-wrap: wrap;
    overflow: visible;
}
.topbar .tb-pill {
    display: inline-flex; align-items: center; gap: 8px;
    height: 32px; padding: 0 14px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 999px;
    color: var(--text-hi);
    transition: background var(--t-fast), border-color var(--t-fast);
    white-space: nowrap;
    min-width: 0;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.20);
}
.topbar .tb-pill:hover { background: rgba(255, 255, 255, 0.10); border-color: rgba(255, 255, 255, 0.22); }
.topbar .tb-pill b { color: #ffffff; font-weight: 600; }
.topbar .tb-pill .label { color: var(--text-md); }
.topbar .dot {
    width: 9px; height: 9px; border-radius: 50%;
    box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
}
.topbar .dot.ok   { background: var(--ok);   box-shadow: 0 0 0 3px rgba(16,  185, 129, 0.25); }
.topbar .dot.warn { background: var(--warn); box-shadow: 0 0 0 3px rgba(245, 158,  11, 0.25); }
.topbar .dot.err  { background: var(--err);  box-shadow: 0 0 0 3px rgba(239,  68,  68, 0.25); }
.topbar .gpu-bar {
    width: 100px; height: 7px; border-radius: 999px;
    background: rgba(255, 255, 255, 0.10);
    overflow: hidden; position: relative;
    flex-shrink: 0;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.30);
}
.topbar .gpu-bar > span {
    position: absolute; inset: 0;
    background: var(--acc-grad);
    border-radius: 999px;
    box-shadow: 0 0 8px rgba(61, 143, 224, 0.45);
}

/* Title row: Modelunify logo mark + wordmark + tagline.
   The logo is the brand PNG/SVG itself, sized so the crystal motif
   and the central "AI" badge are actually readable at header size -
   any smaller and it just reads as a generic avatar. 72px matches the
   natural height of the status banner next to it (two stacked pill
   rows), so the row stays balanced without forcing the rest of the
   header to grow.
   A teal drop-shadow + thin glow tie the round mark into the page's
   accent system without needing a coloured tile behind it. */
.app-title { margin: 0 !important; padding: 0 !important; background: transparent !important;
             border: none !important; box-shadow: none !important; backdrop-filter: none !important; }
.app-title h3, .app-title p { margin: 0 !important; }
.app-title .title-inner {
    display: flex; align-items: center; gap: 18px;
    height: 100%;
}
.app-title .logo {
    width: 72px; height: 72px;
    flex-shrink: 0;
    display: grid; place-items: center;
    /* Glow scales with the larger mark; resting state stays subtle
       so the logo doesn't bloom on dark text behind it. */
    filter: drop-shadow(0 8px 24px rgba(54, 180, 208, 0.45));
    transition: filter var(--t-base);
}
.app-title .logo:hover {
    filter: drop-shadow(0 10px 32px rgba(54, 180, 208, 0.70));
}
.app-title .logo img,
.app-title .logo svg {
    width: 100%; height: 100%;
    border-radius: 50%;
    display: block;
}
/* The inline SVG fallback wants a dark fill so it reads on the navy
   background; the real PNG already includes its own light background
   ring so the rule is a no-op for the PNG case. */
.app-title .logo svg { background: var(--bg-1); }
.app-title .wordmark { display: flex; flex-direction: column; line-height: 1.1; }
.app-title .name-row { display: flex; align-items: baseline; gap: 10px; }
.app-title .name {
    font: 700 24px 'Inter', sans-serif;
    letter-spacing: 0.005em;
    background: linear-gradient(135deg, #f4f8fb 0%, #A8E0D5 60%, #3D8FE0 100%);
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
}
/* Small "v1.0" pill - sits next to the wordmark so the product
   version is always visible without needing an About dialog. Kept
   muted so it never competes with the brand name for attention. */
.app-title .version {
    display: inline-block;
    font: 600 10px 'JetBrains Mono', ui-monospace, monospace;
    line-height: 1;
    padding: 3px 7px;
    border-radius: 999px;
    color: var(--acc-1);
    background: var(--acc-soft);
    border: 1px solid rgba(54, 180, 208, 0.30);
    letter-spacing: 0.04em;
    transform: translateY(-1px);
}
.app-title .tagline {
    margin-top: 2px;
    font: 500 10px 'Inter', sans-serif;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--acc-1);
    opacity: 0.85;
}

/* The HTML banner block: strip Gradio's chrome so the topbar floats */
.topbar-host { background: transparent !important; border: none !important;
               box-shadow: none !important; padding: 0 !important; backdrop-filter: none !important; }

/* Toolbar buttons (refresh / outputs / bms_export): compact glass icons */
.toolbar-row { background: transparent !important; border: none !important;
               box-shadow: none !important; backdrop-filter: none !important; padding: 0 !important; }
.toolbar-row .gr-button,
.toolbar-row button {
    height: 32px !important;
    min-height: 32px !important;
    padding: 0 12px !important;
    font: 500 12px 'Inter', sans-serif !important;
    background: rgba(255, 255, 255, 0.03) !important;
    color: var(--text-md) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    transition: all var(--t-fast) !important;
}
.toolbar-row .gr-button:hover,
.toolbar-row button:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.07) !important;
    border-color: var(--border-str) !important;
}

/* =================================================================
   TABS  -  pill-shaped with circled step badges
   ================================================================= */
.tab-nav, .tabs > .tab-nav {
    display: flex !important; gap: 6px !important;
    padding: 6px !important;
    margin-bottom: 12px !important;
    background: var(--bg-glass) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow-soft);
    -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
    border-bottom: 1px solid var(--border) !important;
    overflow-x: auto;
}
.tab-nav button,
[role="tablist"] [role="tab"] {
    height: 38px !important;
    padding: 0 16px !important;
    font: 500 13.5px 'Inter', sans-serif !important;
    color: var(--text-md) !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: 10px !important;
    border-bottom: 1px solid transparent !important;
    transition: all var(--t-base) !important;
    position: relative;
    display: inline-flex !important; align-items: center !important; gap: 8px !important;
}
.tab-nav button:hover,
[role="tablist"] [role="tab"]:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.04) !important;
}
.tab-nav button.selected,
.tab-nav button[aria-selected="true"],
[role="tablist"] [role="tab"][aria-selected="true"] {
    color: #fff !important;
    background: linear-gradient(180deg, rgba(45, 212, 191, 0.22), rgba(61, 143, 224, 0.10)) !important;
    border-color: rgba(61, 143, 224, 0.40) !important;
    box-shadow: 0 6px 18px rgba(54, 180, 208, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}
.tab-nav button.selected::after,
[role="tablist"] [role="tab"][aria-selected="true"]::after {
    content: ''; position: absolute; left: 14px; right: 14px; bottom: -7px; height: 2px;
    background: var(--acc-grad); border-radius: 2px;
    box-shadow: 0 0 12px rgba(61, 143, 224, 0.6);
}

/* Step-number badges. Earlier we tried a CSS counter on .tab-nav, but
   Gradio 6.x's tab DOM resets it per-button (each tab ends up with "1").
   :nth-of-type() against the direct children is deterministic and
   completely sidesteps the counter-scope issue. */
.tab-nav > button::before,
[role="tablist"] > [role="tab"]::before {
    width: 22px; height: 22px; border-radius: 50%;
    display: inline-grid; place-items: center;
    font: 700 11.5px 'Inter', sans-serif;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    color: var(--text-md);
    margin-right: 4px;
    transition: all var(--t-fast);
}
.tab-nav > button:nth-of-type(1)::before,
[role="tablist"] > [role="tab"]:nth-of-type(1)::before { content: '1'; }
.tab-nav > button:nth-of-type(2)::before,
[role="tablist"] > [role="tab"]:nth-of-type(2)::before { content: '2'; }
.tab-nav > button:nth-of-type(3)::before,
[role="tablist"] > [role="tab"]:nth-of-type(3)::before { content: '3'; }
.tab-nav > button:nth-of-type(4)::before,
[role="tablist"] > [role="tab"]:nth-of-type(4)::before { content: '4'; }
.tab-nav > button:nth-of-type(5)::before,
[role="tablist"] > [role="tab"]:nth-of-type(5)::before { content: '5'; }

.tab-nav > button.selected::before,
.tab-nav > button[aria-selected="true"]::before,
[role="tablist"] > [role="tab"][aria-selected="true"]::before {
    background: var(--acc-grad);
    border-color: transparent;
    color: #fff;
    box-shadow: 0 2px 8px rgba(54, 180, 208, 0.5);
}

/* INNER tabs (Single / Folder under tab 1 and tab 2) shouldn't carry step
   numbers. Belt-and-braces: hide the ::before on any tab strip that
   itself sits inside a tab panel. */
[role="tabpanel"] .tab-nav > button::before,
[role="tabpanel"] [role="tablist"] > [role="tab"]::before,
.tab-nav .tab-nav > button::before,
.tab-nav .tab-nav > [role="tab"]::before {
    display: none !important;
    content: none !important;
}

/* =================================================================
   BUTTONS
   ================================================================= */
.gradio-container button.gr-button,
.gradio-container .gr-button {
    font: 600 13.5px 'Inter', sans-serif !important;
    border-radius: 10px !important;
    transition: transform var(--t-fast), box-shadow var(--t-fast), filter var(--t-fast) !important;
}
/* Primary action: the gradient */
.gradio-container .gr-button.primary,
.gradio-container button.primary,
.gradio-container .gr-button[variant="primary"],
.gradio-container button[variant="primary"] {
    background: var(--acc-grad) !important;
    color: #fff !important;
    border: none !important;
    box-shadow: 0 8px 22px rgba(54, 180, 208, 0.35),
                inset 0 1px 0 rgba(255, 255, 255, 0.20) !important;
}
.gradio-container .gr-button.primary:hover,
.gradio-container button.primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 12px 28px rgba(54, 180, 208, 0.50) !important;
    filter: brightness(1.05) !important;
}
.gradio-container .gr-button.primary:active,
.gradio-container button.primary:active { transform: translateY(0) !important; }

/* Secondary / ghost */
.gradio-container .gr-button.secondary,
.gradio-container button.secondary {
    background: transparent !important;
    color: var(--text-md) !important;
    border: 1px solid var(--border-str) !important;
}
.gradio-container .gr-button.secondary:hover,
.gradio-container button.secondary:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.05) !important;
}

/* Tall primary buttons get a touch more height */
.gradio-container .gr-button.lg.primary,
.gradio-container button.lg.primary { height: 44px !important; padding: 0 22px !important; }

/* =================================================================
   INPUTS (text / number / dropdown)
   ================================================================= */
.gradio-container input[type="text"],
.gradio-container input[type="number"],
.gradio-container input[type="search"],
.gradio-container input:not([type]),
.gradio-container textarea,
.gradio-container select {
    background: rgba(0, 0, 0, 0.25) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-hi) !important;
    font: 500 13px 'Inter', sans-serif !important;
    outline: none !important;
    transition: border-color var(--t-fast), box-shadow var(--t-fast) !important;
    padding: 8px 12px !important;
    box-shadow: none !important;
}
.gradio-container input[type="text"]::placeholder,
.gradio-container input[type="number"]::placeholder,
.gradio-container textarea::placeholder {
    color: var(--text-dim) !important;
}
.gradio-container input:hover,
.gradio-container textarea:hover,
.gradio-container select:hover { border-color: var(--border-str) !important; }
.gradio-container input:focus,
.gradio-container textarea:focus,
.gradio-container select:focus {
    border-color: var(--acc-2) !important;
    box-shadow: var(--acc-glow) !important;
}

/* Gradio's own Dropdown component is driven by its CSS variables
   (--input-background-fill, --background-fill-primary, --body-text-color,
   --border-color-primary, --border-color-accent, etc.) which we
   ALREADY override at :root above. Adding our own selectors here
   broke the popup (the .options.svelte-1ou0lab list is portalled
   outside .gradio-container so .gradio-container .options never
   matched, and our [class*="dropdown"] .wrap > div rule changed the
   layout the dropdown's positioning JS depends on, which is why the
   popup stopped appearing entirely). Trust the variables. */

/* Labels */
.gradio-container label,
.gradio-container label > span,
.gradio-container .label-wrap > span,
.gradio-container span[data-testid*="label"] {
    font: 500 12.5px 'Inter', sans-serif !important;
    color: var(--text-md) !important;
    letter-spacing: 0.005em;
}

/* `info=` text below a control */
.gradio-container .info,
.gradio-container [class*="info"]:not(input):not(svg):not(button):not(.gr-button) {
    color: var(--text-lo) !important;
    font-size: 11.5px !important;
    line-height: 1.45 !important;
}

/* =================================================================
   SLIDERS
   ================================================================= */
.gradio-container input[type="range"] {
    -webkit-appearance: none; appearance: none;
    background: rgba(255, 255, 255, 0.08) !important;
    height: 6px !important;
    border-radius: 999px !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    outline: none;
}
.gradio-container input[type="range"]::-webkit-slider-runnable-track {
    background: transparent;
    height: 6px;
    border-radius: 999px;
}
.gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px; height: 18px; border-radius: 50%;
    background: #fff;
    border: 3px solid var(--acc-2);
    box-shadow: 0 2px 8px rgba(61, 143, 224, 0.45);
    cursor: pointer;
    transition: transform var(--t-fast);
    margin-top: -6px;
}
.gradio-container input[type="range"]::-webkit-slider-thumb:hover { transform: scale(1.15); }
.gradio-container input[type="range"]::-moz-range-thumb {
    width: 16px; height: 16px; border-radius: 50%;
    background: #fff;
    border: 3px solid var(--acc-2);
    box-shadow: 0 2px 8px rgba(61, 143, 224, 0.45);
    cursor: pointer;
}
.gradio-container input[type="range"]::-moz-range-progress {
    background: var(--acc-grad);
    height: 6px;
    border-radius: 999px;
}

/* Gradio renders a "value display" bubble next to the slider track.
   Pick up the accent so it reads as the live readout. */
.gradio-container [data-testid*="slider"] [class*="value"],
.gradio-container .gr-slider [class*="value"] {
    font-family: 'JetBrains Mono', monospace !important;
    color: var(--text-hi) !important;
    background: var(--acc-grad) !important;
    padding: 2px 8px !important;
    border-radius: 999px !important;
    font-size: 11px !important;
    box-shadow: 0 2px 8px rgba(54, 180, 208, 0.40) !important;
}

/* =================================================================
   CHECKBOXES (and Gradio's "Checkbox" component)
   ================================================================= */
.gradio-container input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 18px !important; height: 18px !important;
    border-radius: 5px !important;
    background: rgba(0, 0, 0, 0.25) !important;
    border: 1.5px solid var(--border-str) !important;
    cursor: pointer;
    position: relative;
    transition: all var(--t-fast);
    box-shadow: none !important;
    padding: 0 !important;
}
.gradio-container input[type="checkbox"]:hover { border-color: var(--acc-2) !important; }
.gradio-container input[type="checkbox"]:checked {
    background: var(--acc-grad) !important;
    border-color: transparent !important;
    box-shadow: 0 2px 8px rgba(54, 180, 208, 0.40) !important;
}
.gradio-container input[type="checkbox"]:checked::after {
    content: '';
    position: absolute;
    left: 5px; top: 2px;
    width: 5px; height: 9px;
    border: solid #fff; border-width: 0 2px 2px 0;
    transform: rotate(45deg);
}
.gradio-container input[type="checkbox"]:focus { box-shadow: var(--acc-glow) !important; }

/* =================================================================
   RADIO BUTTONS  -  default styling + chip variant for Quality presets
   ================================================================= */
.gradio-container input[type="radio"] {
    appearance: none;
    -webkit-appearance: none;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.25);
    border: 1.5px solid var(--border-str);
    cursor: pointer;
    position: relative;
    transition: all var(--t-fast);
}
.gradio-container input[type="radio"]:checked {
    border-color: var(--acc-2);
}
.gradio-container input[type="radio"]:checked::after {
    content: '';
    position: absolute;
    left: 3px; top: 3px;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--acc-grad);
}

/* The "quality chips" elem_class: render gr.Radio as a pill segmented control */
.quality-chips {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    backdrop-filter: none !important;
}
.quality-chips .wrap,
.quality-chips fieldset,
.quality-chips [role="radiogroup"] {
    display: inline-flex !important;
    flex-wrap: wrap;
    gap: 4px !important;
    padding: 4px !important;
    background: rgba(0, 0, 0, 0.25) !important;
    border: 1px solid var(--border) !important;
    border-radius: 999px !important;
    width: auto !important;
}
.quality-chips label {
    margin: 0 !important;
    padding: 7px 14px !important;
    border-radius: 999px !important;
    font: 500 12.5px 'Inter', sans-serif !important;
    color: var(--text-md) !important;
    cursor: pointer !important;
    transition: all var(--t-fast) !important;
    user-select: none;
    display: inline-flex !important;
    align-items: center;
    gap: 0 !important;
    background: transparent !important;
    border: none !important;
}
.quality-chips label input[type="radio"] {
    display: none !important;
}
.quality-chips label:hover { color: var(--text-hi) !important; }
.quality-chips label.selected,
.quality-chips label:has(input:checked) {
    background: var(--acc-grad) !important;
    color: #fff !important;
    box-shadow: 0 4px 14px rgba(54, 180, 208, 0.40) !important;
}

/* =================================================================
   ACCORDIONS
   ================================================================= */
.gradio-container .accordion,
.gradio-container .gr-accordion {
    background: rgba(255, 255, 255, 0.02) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    margin: 10px 0 !important;
    overflow: hidden;
}
.gradio-container .accordion > button,
.gradio-container .gr-accordion > button,
.gradio-container .accordion > .label-wrap,
.gradio-container .gr-accordion > .label-wrap,
.gradio-container .accordion > [class*="header"],
.gradio-container .gr-accordion > [class*="header"] {
    font: 600 12.5px 'Inter', sans-serif !important;
    color: var(--text-md) !important;
    background: rgba(255, 255, 255, 0.03) !important;
    border: none !important;
    padding: 10px 14px !important;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    position: sticky !important;
    top: 0 !important;
    z-index: 6;
    transition: color var(--t-fast), background var(--t-fast);
}
.gradio-container .accordion > button:hover,
.gradio-container .gr-accordion > button:hover { color: var(--text-hi) !important; }

/* =================================================================
   IMAGE COMPONENT  -  styled drop zone.
   IMPORTANT: we ONLY apply visual decoration here (border, gradient
   background, focus state). We do NOT touch `display`, `overflow`,
   `position`, `height` etc on Gradio's internal children, because
   those overrides risk hiding the source-selection button row
   (upload / paste / clipboard / webcam) that Gradio renders below
   the drop area. The dashed outer border IS the drop affordance;
   everything inside it stays at Gradio's own layout.
   ================================================================= */
.gradio-container .image-container,
.gradio-container [data-testid*="image"],
.gradio-container .gr-image {
    border: 1.5px dashed var(--border-str) !important;
    border-radius: var(--radius) !important;
    background:
        repeating-linear-gradient(45deg, rgba(255, 255, 255, 0.012) 0 10px, transparent 10px 20px),
        rgba(0, 0, 0, 0.18) !important;
    transition: border-color var(--t-base), box-shadow var(--t-base);
    min-height: 200px !important;
}
.gradio-container .image-container:hover,
.gradio-container .gr-image:hover {
    border-color: var(--acc-2) !important;
    box-shadow: var(--acc-glow);
}

/* The bottom source-selection bar (upload / paste / clipboard /
   webcam buttons). COLOR-ONLY pass - no layout overrides, no
   display: flex, no min-height. We just darken its background and
   recolor the button glyphs so the row reads on the dark theme. */
.gradio-container .source-selection,
.gradio-container [class*="source-selection"] {
    background: rgba(7, 9, 22, 0.55) !important;
    border-top: 1px solid var(--border) !important;
    color: var(--text-md) !important;
}
.gradio-container .source-selection button,
.gradio-container [class*="source-selection"] button {
    background: transparent !important;
    color: var(--text-md) !important;
    border-radius: 8px !important;
    transition: color var(--t-fast), background var(--t-fast) !important;
    box-shadow: none !important;
}
.gradio-container .source-selection button:hover,
.gradio-container [class*="source-selection"] button:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.07) !important;
}
.gradio-container .source-selection svg,
.gradio-container [class*="source-selection"] svg {
    color: currentColor !important;
    stroke: currentColor !important;
}

/* Compact view slots for the 4-view multi-view tab.
   The component itself is sized via `height=210` on the Python side
   (enough room for: label + drop area + the source-selection button
   row below it). We DO NOT set max-height here - that clamp is what
   previously hid the upload / paste / clipboard buttons. The inner
   <img> still gets clamped so a tall photo doesn't blow the slot
   out, but everything else (action bar, drop zone) can grow naturally.

   IMPORTANT: no overflow: hidden, no max-height on the container.
   These two properties are the only things that hide the action bar. */
.compact-img .gr-image,
.compact-img .image-container,
.compact-img [data-testid*="image"] {
    margin-top: 14px !important;
}
.compact-img .gr-image img,
.compact-img [data-testid*="image"] img {
    object-fit: contain !important;
    max-height: 150px !important;
}

/* =================================================================
   FILE component
   ================================================================= */
.gradio-container .gr-file,
.gradio-container [data-testid*="file"] {
    border: 1.5px dashed var(--border-str) !important;
    border-radius: var(--radius) !important;
    background: rgba(0, 0, 0, 0.20) !important;
    color: var(--text-md) !important;
    transition: all var(--t-base);
}
.gradio-container .gr-file:hover,
.gradio-container [data-testid*="file"]:hover {
    border-color: var(--acc-2) !important;
    box-shadow: var(--acc-glow);
}

/* =================================================================
   3D viewer  (gr.Model3D)
   ================================================================= */
.gradio-container .gr-model3d,
.gradio-container [data-testid*="model3d"],
.gradio-container model-viewer {
    min-height: 300px !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    overflow: hidden;
    background:
        radial-gradient(ellipse at 50% 100%, rgba(61, 143, 224, 0.20), transparent 70%),
        radial-gradient(ellipse at 50% 0%,   rgba(99,  102, 241, 0.10), transparent 60%),
        #07091a !important;
    --poster-color: transparent;
}

/* =================================================================
   MARKDOWN (status messages under each tab)
   ================================================================= */
.gradio-container .prose,
.gradio-container .markdown {
    color: var(--text-md) !important;
    font-size: 12.5px !important;
}
.gradio-container .prose code,
.gradio-container .markdown code {
    background: rgba(255, 255, 255, 0.06) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 1px 6px !important;
    font: 500 11.5px 'JetBrains Mono', monospace !important;
}
.gradio-container .prose a,
.gradio-container .markdown a { color: var(--acc-2) !important; }

/* =================================================================
   PROGRESS OVERLAY (gr.Progress / StatusTracker)
   -----------------------------------------------------------------
   Gradio 6.17 renders the "generating ..." overlay as a nested
   tree (StreamingBar.svelte_svelte_type_style_lang-BttMSefY.css):

       .wrap.generating          - overlay backdrop covering host
         .eta-bar                - full-inset translucent fill
                                   that grows with predicted-ETA %
         .progress-level         - vertical stack
           .progress-level-inner - centered status text
           .progress-bar-wrap    - thin pill track (Gradio default
                                   is 55.5% × size-4, gray border)
             .progress-bar       - moving fill, driven by
                                   `transform: scaleX(<pct>)`
         .meta-text              - elapsed-time pill (bottom-right)
         .meta-text-center       - alt position for status text

   DESIGN GOALS (redesigned 2026-06):
     1. Status text on its OWN line, on a dark pill plate, so the
        long "[0s] Shape: MV diffusion (...) - 25.0%" string is
        legible regardless of bar fill.
     2. ONE clearly distinguished progress bar. The full-width
        `.eta-bar` was making the actual pill bar invisible, so we
        hide it entirely.
     3. Shimmer-animated fill gives a live "working" cue even when
        the underlying percentage is coarse (track_tqdm=False).
     4. "Generating overlay on every output" bug solved upstream by
        passing `show_progress_on=<Model3D>` to each click handler,
        so this CSS only has to look right on ONE component.
   ================================================================= */

/* Overlay backdrop: dark glass card over the still-loading viewer.
   Higher opacity than before so the bar/text never have to fight
   the host component for contrast. */
.gradio-container .wrap.generating,
.gradio-container [class*="generating"][class*="wrap"] {
    background: rgba(7, 9, 22, 0.78) !important;
    border-radius: var(--radius) !important;
    border: 1px solid rgba(61, 143, 224, 0.30) !important;
    box-shadow: inset 0 0 80px rgba(45, 212, 191, 0.08),
                0 10px 32px rgba(0, 0, 0, 0.45) !important;
    -webkit-backdrop-filter: blur(8px) saturate(140%);
            backdrop-filter: blur(8px) saturate(140%);
}

/* Hide the misleading full-width ETA prediction fill. It used to
   render as a wide violet stripe that the eye reads as "the bar",
   completely obscuring the actual `.progress-bar-wrap` pill below
   it (user-reported "double / weird loading bar"). The real bar
   carries enough information on its own. */
.gradio-container .eta-bar {
    display: none !important;
}

/* The vertical stack holding text + bar. NO background of its own -
   the .wrap above already provides the glass card. Generous gap
   so text and bar are visually distinct layers. */
.gradio-container .progress-level {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    gap: 16px !important;
    padding: 4px 16px !important;
    align-items: center !important;
}

/* Status text on its OWN dark pill plate, sitting cleanly above
   the bar. No overlap with any fill, always readable. */
.gradio-container .progress-level-inner,
.gradio-container .meta-text-center {
    background: rgba(0, 0, 0, 0.55) !important;
    border: 1px solid rgba(61, 143, 224, 0.22) !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45),
                inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
    color: var(--text-hi) !important;
    font: 600 12.5px 'JetBrains Mono', 'Cascadia Code', monospace !important;
    letter-spacing: 0.01em !important;
    text-shadow: none !important;
    padding: 7px 14px !important;
    margin: 0 auto !important;
    border-radius: 10px !important;
    max-width: 92% !important;
    text-align: center !important;
    -webkit-backdrop-filter: blur(4px);
            backdrop-filter: blur(4px);
}

/* Track: clean dark capsule, well separated from the text plate.
   Thinner than the text plate so the visual hierarchy is obvious:
   text = status, bar = progress. */
.gradio-container .progress-bar-wrap {
    background: rgba(0, 0, 0, 0.55) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 999px !important;
    width: 70% !important;
    min-width: 240px !important;
    max-width: 520px !important;
    height: 8px !important;
    overflow: hidden !important;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.6) !important;
    box-sizing: border-box !important;
    position: relative !important;
}

/* Moving fill. Animated linear-gradient gives a "shimmer" along
   the filled portion, signalling live work even when the discrete
   step counter sits at the same percent for many seconds. Gradio
   drives the FILL LENGTH via `transform: scaleX(<pct>)`. */
.gradio-container .progress-bar-wrap > .progress-bar {
    background: linear-gradient(90deg,
        #2DD4BF 0%,
        #3D8FE0 35%,
        #22D3EE 55%,
        #3D8FE0 75%,
        #2DD4BF 100%) !important;
    background-size: 220% 100% !important;
    background-color: transparent !important;
    animation: progress-shimmer 2.2s linear infinite !important;
    border-radius: 999px !important;
    box-shadow: 0 0 14px rgba(61, 143, 224, 0.65),
                inset 0 1px 0 rgba(255, 255, 255, 0.25) !important;
    height: 100% !important;
    width: 100% !important;
    border: none !important;
}

@keyframes progress-shimmer {
    0%   { background-position: 220% 0; }
    100% { background-position: 0 0; }
}

/* Elapsed-time pill anchored bottom-right ("13.5s" in the screenshot) */
.gradio-container .meta-text {
    background: rgba(15, 20, 36, 0.92) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--border) !important;
    border-radius: 999px !important;
    padding: 4px 11px !important;
    font: 500 11.5px 'JetBrains Mono', monospace !important;
    letter-spacing: 0.02em !important;
    bottom: 12px !important;
    right: 12px !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35) !important;
    -webkit-backdrop-filter: blur(8px) saturate(140%);
            backdrop-filter: blur(8px) saturate(140%);
}

/* Spinner SVG (some loading states show this) - pick up accent */
.gradio-container .loading svg path,
.gradio-container .wrap.generating svg path {
    fill: var(--acc-2) !important;
}

/* =================================================================
   TOASTS / Info messages
   ================================================================= */
.gradio-container .toast,
.gradio-container [class*="toast"] {
    background: var(--bg-glass) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    box-shadow: var(--shadow-pop) !important;
    color: var(--text-hi) !important;
    -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
}
.gradio-container [class*="toast"][class*="info"]    { border-left: 3px solid var(--ok)   !important; }
.gradio-container [class*="toast"][class*="warning"] { border-left: 3px solid var(--warn) !important; }
.gradio-container [class*="toast"][class*="error"]   { border-left: 3px solid var(--err)  !important; }

/* =================================================================
   TOOLTIP icons (existing .tt-icon / .tt-icon-sub) - re-skinned to
   outlined accent badges so they harmonise with the rest of the UI.
   The JS singleton popup in TOOLTIP_HEAD keeps working unchanged.
   ================================================================= */

/* The gr.HTML cell that hosts the icon: zero padding, no card chrome. */
.tt-host,
.tt-host > .form,
.tt-host > .gr-form,
.tt-host > .block,
.tt-host > .prose,
.tt-host.block,
.tt-host .form {
    flex: 0 0 36px !important;
    padding: 0 !important;
    margin: 0 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    min-width: 0 !important;
    -webkit-backdrop-filter: none !important;
            backdrop-filter: none !important;
}
.tt-host-sub,
.tt-host-sub > .form,
.tt-host-sub > .gr-form,
.tt-host-sub > .block,
.tt-host-sub > .prose,
.tt-host-sub.block { flex: 0 0 28px !important; }

.tt-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    margin-top: 22px;
}
.tt-wrap-sub { margin-top: 22px; }

/* MAIN tier  -  accent-soft fill, violet ring on hover */
.tt-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px; height: 22px;
    border-radius: 50%;
    background: var(--acc-soft);
    color: var(--acc-2);
    border: 1.5px solid var(--acc-2);
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    user-select: none;
    transition: all var(--t-fast);
    position: relative;
    z-index: 5;
    pointer-events: auto;
    box-shadow: none;
}
.tt-icon:hover,
.tt-icon:focus {
    background: var(--acc-grad);
    color: #fff;
    border-color: transparent;
    transform: scale(1.10);
    box-shadow: 0 0 0 3px rgba(61, 143, 224, 0.25),
                0 4px 14px rgba(54, 180, 208, 0.40);
    outline: none;
}
.tt-icon:active { transform: scale(0.96); }

/* SUB tier  -  thin outlined badge */
.tt-icon-sub {
    width: 16px; height: 16px;
    background: transparent;
    color: var(--text-lo);
    border: 1.5px solid var(--text-lo);
    font-size: 11px;
    box-shadow: none;
}
.tt-icon-sub:hover,
.tt-icon-sub:focus {
    background: var(--acc-soft);
    color: var(--acc-2);
    border-color: var(--acc-2);
    transform: scale(1.10);
    box-shadow: 0 0 0 3px rgba(61, 143, 224, 0.18);
}

/* The inline .tt-popup is a data carrier - JS reads textContent and
   shows a body-level singleton popup. Keep it hidden. */
.tt-popup { display: none !important; }

/* The body-level singleton popup created by TOOLTIP_HEAD JS picks up the
   inline styles set there, but we restyle it from the outside for the
   new dark theme (a single attribute selector targets the one element). */
#tt-singleton {
    background: rgba(15, 20, 36, 0.97) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--border-str) !important;
    box-shadow: var(--shadow-pop) !important;
    -webkit-backdrop-filter: blur(18px) saturate(140%);
            backdrop-filter: blur(18px) saturate(140%);
    border-radius: var(--radius) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    line-height: 1.55 !important;
}

/* =================================================================
   FLOATING COMPONENT LABELS  ("Image", "Mesh", "Result" pills that
   Gradio overlays at the top-left of Image, Model3D, File, etc.
   Default styling is a light pill that survives our dark theme and
   reads as "white on white" against our glass cards.)
   ================================================================= */
.gradio-container .block-label,
.gradio-container .image-label,
.gradio-container [class*="block-label"],
.gradio-container [class*="component-label"],
.gradio-container [data-testid="block-label"],
.gradio-container .gr-image > .label,
.gradio-container .gr-model3d > .label,
.gradio-container .gr-file > .label {
    background: rgba(15, 20, 36, 0.85) !important;
    color: var(--text-md) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    font: 500 11px 'Inter', sans-serif !important;
    letter-spacing: 0.02em;
    -webkit-backdrop-filter: blur(8px);
            backdrop-filter: blur(8px);
    box-shadow: var(--shadow-soft) !important;
    padding: 3px 9px !important;
}
.gradio-container .block-label svg,
.gradio-container [class*="block-label"] svg,
.gradio-container .image-label svg { stroke: var(--text-md) !important; color: var(--text-md) !important; }

/* The action toolbar (download / fullscreen / share buttons) that
   Gradio overlays on Image / Model3D. Default is also light. */
.gradio-container .icon-button-wrapper,
.gradio-container [class*="icon-button-wrapper"],
.gradio-container .gr-image .toolbar,
.gradio-container .gr-model3d .toolbar {
    background: rgba(15, 20, 36, 0.85) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    -webkit-backdrop-filter: blur(8px);
            backdrop-filter: blur(8px);
}
.gradio-container .icon-button-wrapper button,
.gradio-container .icon-button-wrapper svg,
.gradio-container [class*="icon-button-wrapper"] svg,
.gradio-container [class*="icon-button-wrapper"] button {
    background: transparent !important;
    color: var(--text-md) !important;
    fill: var(--text-md) !important;
    stroke: var(--text-md) !important;
}
.gradio-container .icon-button-wrapper button:hover,
.gradio-container [class*="icon-button-wrapper"] button:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.07) !important;
}

/* The big "Drop image here" placeholder inside an empty Image component */
.gradio-container .upload-text,
.gradio-container [class*="upload-text"],
.gradio-container .gr-image .empty,
.gradio-container [class*="empty"] {
    color: var(--text-lo) !important;
}
.gradio-container .upload-text svg,
.gradio-container [class*="upload"] svg { stroke: var(--acc-2) !important; color: var(--acc-2) !important; }

/* =================================================================
   NUMBER INPUT SPINNERS  (the up/down arrows on gr.Number)
   Default browser styling = white box with gray arrows = breaks the
   dark theme. Re-skin the inner spin buttons; if the browser doesn't
   support styling them, hide them entirely (users can still type +
   use the slider).
   ================================================================= */
.gradio-container input[type="number"]::-webkit-inner-spin-button,
.gradio-container input[type="number"]::-webkit-outer-spin-button {
    -webkit-appearance: none;
    appearance: none;
    background: rgba(61, 143, 224, 0.20);
    border-left: 1px solid var(--border);
    width: 18px;
    opacity: 1;
    color: var(--text-hi);
    cursor: pointer;
    margin: 0;
    border-radius: 0 8px 8px 0;
    background-image:
        linear-gradient(45deg,  transparent 38%, var(--text-hi) 38% 46%, transparent 46%),
        linear-gradient(-45deg, transparent 38%, var(--text-hi) 38% 46%, transparent 46%);
    background-size: 8px 4px, 8px 4px;
    background-position: center 7px, center calc(100% - 7px);
    background-repeat: no-repeat;
    transition: background-color var(--t-fast);
}
.gradio-container input[type="number"]::-webkit-inner-spin-button:hover {
    background-color: rgba(61, 143, 224, 0.40);
}
/* Firefox doesn't support spin-button styling. Hide them there - users
   can still type, scroll, or use the keyboard arrows. */
@-moz-document url-prefix() {
    .gradio-container input[type="number"] {
        -moz-appearance: textfield;
    }
}

/* =================================================================
   GRADIO INTERNAL CSS VARIABLES  -  global override.
   Gradio's own Svelte components (Settings panel, file picker, etc.)
   draw their colors from these CSS variables. We override them at the
   :root / html / body level so EVERY internal component picks up the
   dark palette automatically, even ones we don't have a selector for.
   This is the single most important change for the Settings panel.
   ================================================================= */
:root,
html,
body,
.gradio-container,
gradio-app {
    --background-fill-primary:   var(--bg-1) !important;
    --background-fill-secondary: var(--bg-2) !important;
    --block-background-fill:     var(--bg-glass) !important;
    --panel-background-fill:     var(--bg-glass) !important;
    --body-background-fill:      var(--bg-0) !important;
    --body-text-color:           var(--text-hi) !important;
    --body-text-color-subdued:   var(--text-lo) !important;
    --color-accent:              var(--acc-2) !important;
    --color-accent-soft:         var(--acc-soft) !important;
    --link-text-color:           var(--acc-2) !important;
    --border-color-primary:      var(--border) !important;
    --border-color-accent:       var(--acc-2) !important;
    --input-background-fill:     rgba(0, 0, 0, 0.30) !important;
    --input-border-color:        var(--border) !important;
    --input-border-color-focus:  var(--acc-2) !important;
    --button-secondary-background-fill:        rgba(255, 255, 255, 0.05) !important;
    --button-secondary-background-fill-hover:  rgba(255, 255, 255, 0.10) !important;
    --button-secondary-text-color:             var(--text-md) !important;
    --button-secondary-text-color-hover:       var(--text-hi) !important;
    --button-secondary-border-color:           var(--border-str) !important;
    --button-primary-background-fill:          var(--acc-1) !important;
    --button-primary-text-color:               #ffffff !important;
    --shadow-drop:               var(--shadow-soft) !important;
    --shadow-drop-lg:            var(--shadow-pop) !important;
}

/* =================================================================
   GRADIO SETTINGS PANEL  (gear icon top-right opens this)
   In Gradio 6.17 the panel is a Svelte component mounted at the
   document root with hashed class names:
     .banner-wrap.svelte-1t60wb3   - each section container
     .theme-buttons.svelte-1t60wb3 - the Light/Dark/System row
     .theme-button.svelte-1t60wb3  - one theme button
     .current-theme.svelte-1t60wb3 - the active one
     .record-button.svelte-1t60wb3 - "Start Recording"
     .url.svelte-xaoy31            - the URL text in the header
     button.svelte-xaoy31          - the close X
   We target those class names directly (NOT scoped to
   .gradio-container, which doesn't reach them).
   ================================================================= */

/* The first .banner-wrap in the panel is the Display Theme section.
   We're dark-only here, so the Light / Dark / System buttons would
   only re-theme Gradio's chrome (not our app) and are confusing.
   Hide that section. The CSS-only hide is "first-of-type" so it
   works even if Gradio reorders sections in a future build, BUT it
   only fires when the panel is rendered in a context where the
   .banner-wrap is the first child. The JS observer in TOOLTIP_HEAD
   also hides any .banner-wrap that has no <h2> heading - that's the
   reliable text-independent way to identify the Display Theme block
   (it's the only section without a heading). */
.banner-wrap.svelte-1t60wb3:not(:has(h2)),
.banner-wrap:not(:has(h2)) {
    display: none !important;
}

/* Section containers */
.banner-wrap.svelte-1t60wb3,
.banner-wrap {
    background: transparent !important;
    border-bottom: 1px solid var(--border) !important;
    color: var(--text-md) !important;
    padding: 18px 24px !important;
}
.banner-wrap.svelte-1t60wb3:last-child,
.banner-wrap:last-child { border-bottom: none !important; }

/* Section headings ("Language", "Progressive Web App", "Screen Studio") */
.banner-wrap h2,
h2.svelte-xaoy31,
h2.svelte-1t60wb3,
.title.svelte-xaoy31 {
    color: var(--text-hi) !important;
    font: 600 16px 'Inter', sans-serif !important;
    letter-spacing: -0.005em !important;
    margin-bottom: 8px !important;
}

/* Body text inside each section */
.banner-wrap p,
.padded.svelte-1t60wb3,
p.padded {
    color: var(--text-md) !important;
    font: 400 13px 'Inter', sans-serif !important;
    line-height: 1.55 !important;
}
.banner-wrap a,
a.svelte-1t60wb3 { color: var(--acc-2) !important; }
.banner-wrap code,
.banner-wrap b,
.banner-wrap strong { color: var(--text-hi) !important; }

/* The URL displayed in the header (".url" + the title row) */
.url.svelte-xaoy31,
.url { color: var(--acc-2) !important; font: 400 13px 'JetBrains Mono', monospace !important; }
.title.svelte-xaoy31,
.title { color: var(--text-hi) !important; }

/* Close X button in the header */
button.svelte-xaoy31 {
    color: var(--text-lo) !important;
    background: transparent !important;
    border: none !important;
    transition: color var(--t-fast) !important;
}
button.svelte-xaoy31:hover {
    color: var(--acc-2) !important;
    background: rgba(255, 255, 255, 0.06) !important;
    border-radius: 8px !important;
}

/* The Record button */
.record-button.svelte-1t60wb3,
.record-button {
    background: rgba(255, 255, 255, 0.05) !important;
    color: var(--text-md) !important;
    border: 1px solid var(--border-str) !important;
    border-radius: 10px !important;
    padding: 8px 14px !important;
    font: 500 13px 'Inter', sans-serif !important;
    cursor: pointer !important;
    transition: all var(--t-fast) !important;
}
.record-button.svelte-1t60wb3:hover,
.record-button:hover {
    color: var(--text-hi) !important;
    background: rgba(255, 255, 255, 0.10) !important;
    border-color: var(--acc-2) !important;
}

/* BETA tag on the Screen Studio heading */
.beta-tag.svelte-1t60wb3,
.beta-tag {
    background: var(--acc-grad) !important;
    color: #fff !important;
    font-weight: 600 !important;
}

/* =================================================================
   SETTINGS PANEL ROOT CONTAINER.
   Gradio mounts the panel inside an outer wrapper that doesn't have
   a stable class name; we can't target it with a single selector.
   Instead, the JS observer in TOOLTIP_HEAD finds the .banner-wrap's
   panel ancestor at runtime and applies width / position constraints
   inline (so the panel becomes a side card, not a full-screen sheet).
   The CSS rules below cover the fallback case where the panel happens
   to be a native <dialog>.
   ================================================================= */
html dialog,
html body > dialog,
html body > div[role="dialog"],
html body > div.modal {
    background: rgba(15, 20, 36, 0.97) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--border-str) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow-pop) !important;
    -webkit-backdrop-filter: blur(20px) saturate(140%);
            backdrop-filter: blur(20px) saturate(140%);
    max-width: 560px !important;
    width: min(560px, 92vw) !important;
    max-height: 85vh !important;
    margin: auto !important;
    padding: 0 !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}
html dialog::backdrop {
    background: rgba(7, 8, 15, 0.55) !important;
    -webkit-backdrop-filter: blur(4px);
            backdrop-filter: blur(4px);
}

/* =================================================================
   TOOLTIP SUB-ICON  -  bigger, more legible, properly clickable.
   User feedback (round 2): the 16px circle was too small to hit
   reliably. Going to 20px gives a real touch target while still
   reading as "smaller than the main blue 22px badge". Thicker
   outline + subtle fill make the `i` glyph solid instead of wispy.
   ================================================================= */
.tt-icon-sub {
    width: 20px; height: 20px;
    background: rgba(255, 255, 255, 0.06) !important;
    color: var(--text-md) !important;
    border: 2px solid var(--text-md) !important;
    font: 700 12px 'Inter', sans-serif !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.28) !important;
    /* Invisible-but-tappable padding around the visible circle so the
       hit box matches the visual click affordance the user wants. */
    outline-offset: 4px;
}
.tt-icon-sub:hover,
.tt-icon-sub:focus {
    background: var(--acc-soft) !important;
    color: var(--acc-2) !important;
    border-color: var(--acc-2) !important;
    transform: scale(1.10);
    box-shadow: 0 0 0 4px rgba(61, 143, 224, 0.22),
                0 2px 10px rgba(61, 143, 224, 0.40) !important;
}
.tt-host-sub,
.tt-host-sub > .form,
.tt-host-sub > .gr-form,
.tt-host-sub > .block,
.tt-host-sub > .prose,
.tt-host-sub.block { flex: 0 0 32px !important; }

/* =================================================================
   GRADIO 6 DROPDOWN  -  intentionally left empty.
   Gradio's own Dropdown stylesheet (Dropdown--Uz_kS2s.css) uses
   --input-background-fill, --border-color-primary,
   --border-color-accent, --background-fill-primary,
   --background-fill-secondary, --shadow-drop-lg, --body-text-color
   for all its colours. We override every one of those variables at
   :root, so the dropdown picks up the dark theme for free and the
   .options popup (a portalled <ul class="options svelte-1ou0lab">
   that lives outside .gradio-container) goes dark too.

   When we previously added our own .wrap / .secondary-wrap /
   .options overrides here, the popup stopped opening entirely:
     a) .gradio-container .options didn't match the portalled popup
     b) .wrap > div padding changes broke the position calculation
        the dropdown's own JS does to anchor the popup
   Lesson: only override the variables, don't fight the components.
   ================================================================= */

/* Just a tiny polish - the dropdown arrow icon should pick up the
   accent on focus so it visually echoes the focus ring. This is the
   one cosmetic thing CSS variables alone can't deliver. */
.icon-wrap.svelte-1xfsv4t,
.icon-wrap.svelte-1dv2vbb { color: var(--text-md) !important; transition: color var(--t-fast); }
.wrap.svelte-1xfsv4t:focus-within .icon-wrap,
.wrap.svelte-1dv2vbb:focus-within .icon-wrap { color: var(--acc-2) !important; }

/* Selected highlight in the .options popup uses background-fill-secondary
   by default. Map THAT to the soft accent so the highlighted option
   reads as "selected" in our accent colour instead of just another
   shade of dark grey. */
.options.svelte-1ou0lab .item.active,
.options.svelte-1ou0lab .item:hover {
    background: var(--acc-soft) !important;
    color: var(--text-hi) !important;
}

/* =================================================================
   NUMBER INPUT SPINNERS  (final fix)
   The previous attempt at re-skinning ::-webkit-inner-spin-button
   didn't take because Gradio's input ships with `appearance: auto`
   which restores the native control. We now hide the native spinner
   entirely and let users type / use the slider / scroll-wheel. This
   removes the gray-on-white box you were seeing.
   ================================================================= */
.gradio-container input[type="number"],
.gradio-container input[type="number"]:focus {
    -webkit-appearance: textfield !important;
       -moz-appearance: textfield !important;
            appearance: textfield !important;
}
.gradio-container input[type="number"]::-webkit-inner-spin-button,
.gradio-container input[type="number"]::-webkit-outer-spin-button {
    -webkit-appearance: none !important;
            appearance: none !important;
    display: none !important;
    margin: 0 !important;
}
"""


# Slim helpers to keep each tab body short ------------------------------------

def _btn_row(out_dir_btn=True, refresh_btn=True):
    """Return a row of compact utility buttons. Used inside per-tab Status row."""
    with gr.Row():
        if refresh_btn:
            r = gr.Button("↻", size="sm", scale=0, min_width=40)
        else:
            r = None
        if out_dir_btn:
            o = gr.Button("📂 outputs", size="sm", scale=0, min_width=110)
        else:
            o = None
    return r, o


_NORMAL_BAKER_TOOLTIP = (
    "How to produce normal.png for the textured output. "
    "The Hunyuan3D-2.1 painter does not emit a normal map, so we "
    "synthesise one. Higher tiers add more surface detail but cost more "
    "time / VRAM / disk:\n\n"
    "• Off — no normal map.\n\n"
    "• Low — mesh-derived (pure NumPy bake from the mesh's per-vertex "
    "normals). Free, ~3 s, no extra deps, no extra VRAM. Improves LOD "
    "shading consistency but does NOT add brick / panel / rivet detail.\n\n"
    "• Medium — Stable-X / StableNormal-turbo. AI predicts tangent-space "
    "normals from the painted albedo texture, so brick patterns and panel "
    "seams in the albedo become real surface relief. ~3 GB extra VRAM, "
    "~10-15 s, ~2 GB model download on first run (cached after).\n\n"
    "• High — prs-eth / Marigold-Normal v1-1. Same idea as Medium but "
    "higher fidelity. Best perceptual surface detail. ~5 GB extra VRAM, "
    "~30-60 s, ~3 GB model download on first run (cached after). On a "
    "12 GB GPU, run AFTER the painter has unloaded (the Multi-view tab with "
    "Paint enabled does this automatically between paint and embed steps)."
)


def _normal_baker_default() -> str:
    """Read the default from config.yaml; normalise legacy 'geometry' alias."""
    nb = (((CFG.get("bms") or {}).get("normal_baker")) or "low").lower()
    if nb == "geometry":
        nb = "low"
    if nb not in ("off", "low", "medium", "high"):
        nb = "low"
    return nb


# Shared by both the plain control (used on TripoSG tab today) and the
# ⓘ-tooltip version (used on Multi-view tab). Renaming labels here
# propagates everywhere.
#
# Labels are intentionally SHORT here ("Off / Low / Medium / High") so
# they render cleanly as pill chips on the Radio control. The full
# explanation of what each tier does lives in _NORMAL_BAKER_TOOLTIP
# and is shown by the ⓘ icon next to the control, so the short chip
# label + hover tooltip together carry the same information the old
# long label used to carry inline.
_NORMAL_BAKER_CHOICES = [
    ("Off",    "off"),
    ("Low",    "low"),
    ("Medium", "medium"),
    ("High",   "high"),
]


def _normal_map_dropdown_only(label: str = "Normal map"):
    """Plain Normal-map selector WITHOUT the help icon. Kept for callers
    that don't want the ⓘ tooltip cell.

    Rendered as a Radio with the `quality-chips` style instead of a
    Gradio Dropdown. The Dropdown component in Gradio 6.17 gets into
    a stuck state after a few interactions (typing into the filterable
    text input doesn't commit, the .options popup stops opening, the
    value silently reverts). Radio uses native HTML <input type=radio>
    under the hood - there is no popup, no filter input, no state
    machine to desync - so it just works.
    """
    return gr.Radio(
        choices=_NORMAL_BAKER_CHOICES,
        value=_normal_baker_default(),
        label=label,
        elem_classes="quality-chips",
    )


def _help_icon(tooltip_text: str):
    """Render the LARGE BLUE ⓘ-with-tooltip cell for MAIN / top-level
    controls (Quality presets, Build BMS LOD set, Normal map, etc.).

    Place inside an existing `gr.Row(equal_height=False)` next to the
    control it documents. The actual popup is rendered by the singleton
    JS in `TOOLTIP_HEAD` - this cell only carries the icon + a hidden
    `.tt-popup` span whose textContent the JS reads on hover/focus/click.

    The tooltip text is HTML-escaped before interpolation so characters
    like `<`, `>`, `&` (e.g., '<= depth', 'Performance & VRAM') don't
    break the surrounding <span> structure and silently kill the icon.
    """
    safe = html.escape(tooltip_text, quote=False)
    return gr.HTML(
        '<span class="tt-wrap">'
        '<span class="tt-icon" role="button" tabindex="0" '
        'aria-label="Show help" title="Click for help">i'
        f'<span class="tt-popup">{safe}</span>'
        '</span></span>',
        elem_classes=["tt-host"],
    )


def _help_icon_sub(tooltip_text: str):
    """Render the SMALL GREY ⓘ-with-tooltip cell for SUB / advanced
    controls (sliders inside Advanced accordions). Same behaviour as
    `_help_icon`, just visually smaller and outlined-grey instead of
    filled-blue, so it doesn't dominate the field row."""
    safe = html.escape(tooltip_text, quote=False)
    return gr.HTML(
        '<span class="tt-wrap tt-wrap-sub">'
        '<span class="tt-icon tt-icon-sub" role="button" tabindex="0" '
        'aria-label="Show help" title="Click for help">i'
        f'<span class="tt-popup">{safe}</span>'
        '</span></span>',
        elem_classes=["tt-host", "tt-host-sub"],
    )


# =============================================================================
# Tooltip TEXT for all control ⓘ icons. Kept here as named constants so the
# UI builder reads cleanly. Each tooltip follows the same 4-section structure:
#
#   What this does       - one-line purpose
#   Range and outputs    - what each value produces
#   Hardware tiers       - what works on low / mid / high-end GPUs +
#                          how to avoid OOM crashes
#   Default              - the "best of both worlds" recommendation
#
# Hardware tiers used throughout:
#   Low-VRAM  : 6 - 8  GB VRAM (entry-level / older laptop GPUs)
#   Mid-range : 10 - 14 GB VRAM (current laptop / mainstream desktop GPUs)
#   High-end  : 16+ GB VRAM (workstation / data-center GPUs)
#
# IMPORTANT: keep all tooltip text free of raw HTML metacharacters that the
# browser would treat as tag starts. Use "at or below" / "or less" instead
# of "<=", "and" instead of "&", "(approximately)" instead of "~" only if
# the text is interpolated unescaped. `_help_icon()` HTML-escapes the text
# before insertion, so plain `<`, `>`, `&` are now safe - but keeping the
# source readable in code is still nicer.
# =============================================================================

_HELP_TRIPOSG_QUALITY = (
    "What this does\n"
    "Quality preset for the TripoSG image-to-mesh diffusion. Each preset "
    "bundles Steps + Guidance + Octree + Face-count defaults; override "
    "in 'Advanced'.\n\n"
    "Modes\n"
    "• Fast — 25 steps, octree 7 (128³ voxels), 10k face cap. Coarsest, "
    "fastest. Visible voxel staircase on flat walls. Use for previews.\n"
    "• Balanced — 50 steps, octree 9 (512³), 20k face cap. Clean geometry, "
    "window mullions and roof seams readable.\n"
    "• HQ — 75 steps, octree 10 (1024³), 50k face cap. Picks up fine "
    "surface detail (vents, brick courses).\n\n"
    "Approximate VRAM\n"
    "Fast 6 GB · Balanced 8 GB · HQ 10 GB.\n\n"
    "Hardware tiers\n"
    "• Low-VRAM (6 – 8 GB): Fast only. Balanced may OOM during decode, HQ "
    "will. Drop Octree depth in 'Advanced' to 7 or 8 to be safe.\n"
    "• Mid-range (10 – 14 GB): Fast and Balanced safe. HQ is tight — close "
    "other GPU-accelerated apps (browser hardware acceleration, video "
    "editors) before running or the diffusion can OOM mid-sample.\n"
    "• High-end (16+ GB): all presets fine.\n\n"
    "If you hit 'CUDA out of memory'\n"
    "Drop Octree depth in 'Advanced' first — it dominates VRAM cost, more "
    "than Steps.\n\n"
    "Default\n"
    "Balanced. Reach for HQ only on hero buildings with VRAM headroom."
)

_HELP_TRIPOSG_STEPS = (
    "What this does\n"
    "Number of denoising steps in the TripoSG diffusion. Each step refines "
    "the predicted SDF used to extract the mesh.\n\n"
    "Range and outputs\n"
    "15 — fastest, noisy silhouettes.\n"
    "25 — usable for previews; light artifacts on flat surfaces.\n"
    "50 (default) — clean, no perceivable artifacts on buildings.\n"
    "75 — marginal gain on buildings; better for organic/curved shapes "
    "(vehicles, statues).\n\n"
    "Performance\n"
    "Roughly linear in step count — doubling steps doubles runtime.\n\n"
    "Hardware notes\n"
    "Steps do NOT affect VRAM. Safe to raise even on low-VRAM cards.\n\n"
    "Default\n"
    "50 (set by the Balanced preset)."
)

_HELP_TRIPOSG_GUIDANCE = (
    "What this does\n"
    "Classifier-free guidance: how strictly the diffusion follows your "
    "input image vs. drifting toward what the model thinks is plausible.\n\n"
    "Range\n"
    "1 – 4 — loose; model invents geometry not present in the image. "
    "Useful when the input is rough or partial.\n"
    "5 – 7 (default region) — strict but flexible. Best for clean photos "
    "of recognisable objects.\n"
    "8 – 15 — very strict; can produce overshoot artifacts (hard edges "
    "where there shouldn't be).\n\n"
    "Performance and VRAM\n"
    "No measurable impact. Pure quality knob.\n\n"
    "Default\n"
    "7. Lower (4 – 5) if the model is being too literal about lens "
    "distortion; raise (8 – 9) if it's inventing extra geometry."
)

_HELP_TRIPOSG_OCTREE = (
    "What this does\n"
    "Resolution of the hierarchical octree used to extract the mesh from "
    "the SDF. Each increment DOUBLES the voxel grid per axis (so 8x the "
    "cells in 3D).\n\n"
    "Range and approximate VRAM\n"
    "7 — 128³ voxels, 3 GB VRAM. Blocky, staircase artifacts.\n"
    "8 — 256³, 5 GB VRAM. Usable.\n"
    "9 (default) — 512³, 7 GB VRAM. Clean for buildings.\n"
    "10 — 1024³, 10 GB VRAM. Captures fine surface detail.\n\n"
    "Hardware tiers\n"
    "• Low-VRAM (6 – 8 GB): max depth 8. Depth 9 will OOM.\n"
    "• Mid-range (10 – 14 GB): 9 safe. 10 is tight — combining 10 with "
    "75 steps OOMs on 12 GB cards.\n"
    "• High-end (16+ GB): all values fine.\n\n"
    "If you hit 'CUDA out of memory'\n"
    "Octree depth is the #1 cause of OOM in TripoSG. Lower this BEFORE "
    "touching anything else.\n\n"
    "Default\n"
    "9."
)

_HELP_TRIPOSG_DENSE = (
    "What this does\n"
    "Resolution of the coarse SDF grid used BEFORE hierarchical refinement. "
    "The hierarchical decoder then refines this grid up to the final "
    "octree depth.\n\n"
    "Range\n"
    "6 to 9. Must be at or below the hierarchical octree depth (the field "
    "is auto-clamped).\n\n"
    "Performance and VRAM\n"
    "The dense grid has no sparsity, so its VRAM cost is steeper than the "
    "octree. Bumping this by 1 is roughly equivalent to bumping the "
    "hierarchical octree by 2 in VRAM terms.\n\n"
    "Hardware notes\n"
    "If you hit 'CUDA out of memory' specifically during the dense-grid "
    "stage, lower this before lowering hierarchical octree.\n\n"
    "Default\n"
    "octree depth minus 1 (set automatically). Leave alone unless tuning "
    "for sharper initial fits."
)

_HELP_TRIPOSG_BOUNDS = (
    "What this does\n"
    "Half-width of the SDF bounding cube the model decodes into. Acts as a "
    "zoom: smaller bounds put more voxels on the object itself.\n\n"
    "Range\n"
    "0.5 – 1.0 — tight zoom. More detail concentrated on the subject, but "
    "geometry can CLIP if the object extends outside the cube.\n"
    "1.0 – 1.5 (default region) — safe for square-cropped subjects.\n"
    "1.5 – 2.0 — loose. Use only if the subject is small in the frame "
    "(distant photo).\n\n"
    "Performance and VRAM\n"
    "No impact. Pure quality vs clipping trade-off.\n\n"
    "Default\n"
    "1.25. Tight-crop your input photo first; then leave this alone."
)

_HELP_TRIPOSG_FACES = (
    "What this does\n"
    "Post-decimation face count cap. The raw marching-cubes output has "
    "100k – 500k faces; this is the target after the pymeshlab quadric "
    "edge-collapse cleanup pass.\n\n"
    "Range\n"
    "-1 — no cap (keep raw mesh, can be hundreds of MB).\n"
    "5k – 15k — aggressive; suitable for LOD2 – LOD3 source.\n"
    "20k (default) — sweet spot for buildings; readable silhouette.\n"
    "50k+ — high-poly source for LOD0 of a hero asset.\n\n"
    "Performance\n"
    "Decimation runs on CPU and is fast (1 – 3 s for any target). Smaller "
    "mesh means smaller .glb file plus faster downstream LOD generation.\n\n"
    "Default\n"
    "20,000. Game engines (Unity, Unreal, BMS) prefer under 25k for LOD0."
)

_HELP_BG_REMOVER = (
    "What this does\n"
    "Background-removal model. Cleaner silhouette means cleaner generated "
    "mesh — background pixels become geometry if left in.\n\n"
    "Options\n"
    "• rmbg (default) — Briaai RMBG-1.4. Best on objects shot against "
    "studio / clean backgrounds.\n"
    "• rembg — u2net. Better on outdoor / cluttered backgrounds (satellite "
    "shots, ground-level photos with sky and foliage).\n"
    "• none — skip BG removal. Only safe if the input is already cut out.\n\n"
    "Performance\n"
    "Both run on GPU in under 1 s. Negligible cost.\n\n"
    "Default\n"
    "rmbg. Switch to rembg for outdoor / aerial shots of buildings."
)

_HELP_BAKE_PLANAR = (
    "What this does\n"
    "Projects the source image onto the mesh's front face as a planar "
    "texture. Gives you a colourful preview .glb out of the box.\n\n"
    "Effect on downstream steps\n"
    "When ON, the mesh carries UV coordinates plus a diffuse texture. The "
    "BMS LOD exporter can then share one texture across all LODs, and the "
    "AI normal-map bakers (Medium / High) can read an albedo from it.\n\n"
    "Performance and VRAM\n"
    "Free (under 100 ms). No VRAM impact.\n\n"
    "Default\n"
    "ON. Turn off only if you want a pure-geometry .glb."
)

_HELP_HUNYUAN_MV_QUALITY = (
    "What this does\n"
    "Quality preset for the Hunyuan3D-2mv multi-view shape model. Bundles "
    "Steps + Octree resolution + Guidance + Decoder chunks; override "
    "individually in 'Advanced'.\n\n"
    "Modes\n"
    "• Fast — 25 steps, 256³ octree resolution. Coarse mesh, identifiable "
    "silhouette.\n"
    "• Balanced — 50 steps, 380³ octree. Best speed / quality trade for "
    "buildings.\n"
    "• HQ — 75 steps, 512³ octree. Picks up fine facade detail; use HQ "
    "when you have orthogonal ground+aerial photos.\n\n"
    "Approximate VRAM\n"
    "Fast 5 GB · Balanced 7 GB · HQ 10 GB.\n\n"
    "Hardware tiers\n"
    "• Low-VRAM (6 – 8 GB): Fast only.\n"
    "• Mid-range (10 – 14 GB): Fast and Balanced safe; HQ leaves almost "
    "no slack — close GPU-accelerated apps first.\n"
    "• High-end (16+ GB): all presets fine.\n\n"
    "If you hit 'CUDA out of memory'\n"
    "Lower Octree resolution OR halve Decoder chunks in 'Advanced'.\n\n"
    "Default\n"
    "Balanced."
)

_HELP_HUNYUAN_MV_STEPS = (
    "What this does\n"
    "Diffusion step count for the multi-view shape model. Same purpose as "
    "TripoSG's Steps but on a different architecture (flow-matching DiT).\n\n"
    "Range and outputs\n"
    "15 – 25 — draft; wobbly silhouettes.\n"
    "50 (default) — clean.\n"
    "75 — marginal improvement, roughly 2x runtime.\n\n"
    "Performance and VRAM\n"
    "Linear in steps. VRAM is unaffected — safe to raise on any card.\n\n"
    "Default\n"
    "50."
)

_HELP_HUNYUAN_MV_OCTREE_RES = (
    "What this does\n"
    "Voxel resolution of the final octree used to extract the mesh from "
    "the diffusion output. Continuous number (unlike TripoSG's power-of-2 "
    "depth).\n\n"
    "Range and approximate VRAM\n"
    "256 — coarse mesh, 5 GB VRAM. Fast.\n"
    "380 (default) — balanced, 7 GB.\n"
    "512 — high detail, 10 GB.\n\n"
    "Hardware tiers\n"
    "• Low-VRAM (6 – 8 GB): max 320 to be safe.\n"
    "• Mid-range (10 – 14 GB): 380 safe; 512 tight.\n"
    "• High-end (16+ GB): 512 safe.\n\n"
    "If you hit 'CUDA out of memory'\n"
    "This is the dominant VRAM driver for Hunyuan-MV. Lower this first.\n\n"
    "Default\n"
    "380."
)

_HELP_HUNYUAN_MV_GUIDANCE = (
    "What this does\n"
    "Classifier-free guidance for the multi-view model.\n\n"
    "Range\n"
    "1 – 3 — loose, more creative.\n"
    "5 (default) — balanced; good for orthogonal photo sets.\n"
    "7 – 15 — very strict; risk of hard-edge artifacts.\n\n"
    "Performance and VRAM\n"
    "No impact.\n\n"
    "Default\n"
    "5. Slightly lower than TripoSG's default because multi-view input is "
    "already highly constraining."
)

_HELP_HUNYUAN_MV_CHUNKS = (
    "What this does\n"
    "Decoder chunk size. The volume decoder processes this many voxels at "
    "a time. Lower chunks = less peak VRAM, more overhead.\n\n"
    "Range\n"
    "5,000 — safest, slowest. Use if you keep OOM-ing.\n"
    "20,000 (default) — safe on mid-range cards at octree resolution 380.\n"
    "50,000 — faster, but risky on low-VRAM cards.\n\n"
    "If you hit 'CUDA out of memory' during 'decoding volume'\n"
    "(NOT the diffusion stage) — HALVE this number before anything else. "
    "Don't go below 5,000.\n\n"
    "Default\n"
    "20,000."
)

_HELP_HUNYUAN_MV_MCLEV = (
    "What this does\n"
    "Marching-cubes iso-surface level. Shifts the extracted surface in or "
    "out of the SDF by this offset.\n\n"
    "Range\n"
    "-0.5 — thicker geometry. Useful for thin walls that come out "
    "translucent or hole-y.\n"
    "0.0 (default) — canonical surface.\n"
    "+0.5 — thinner geometry. Risks puncturing thin features.\n\n"
    "Performance and VRAM\n"
    "No impact.\n\n"
    "Default\n"
    "0.0. Adjust only if walls have visible holes (try -0.1)."
)

_HELP_HUNYUAN_MV_BAKE_VIEW = (
    "What this does\n"
    "Which uploaded view to project as a placeholder planar texture on the "
    "output mesh (shape-only mode). The texture lands on the mesh's UV "
    "space so downstream LOD export can bake normal maps from real albedo "
    "data. Ignored when Paint is ON — the painter generates a real "
    "texture instead.\n\n"
    "Options\n"
    "• front (default) — the canonical 'face' of the object.\n"
    "• left / back / right — if your 'front' upload is actually a side view.\n"
    "• none — leave the mesh untextured; AI normal-map bakers will fall "
    "back to mesh-only mode.\n\n"
    "Performance\n"
    "Free. Pure texture-routing knob.\n\n"
    "Default\n"
    "front."
)

_HELP_HUNYUAN_MV_FACES = (
    "What this does\n"
    "Post-decimation face cap (shape-only output). Quadric edge collapse "
    "with topology preservation. Ignored when Paint is ON — the painter "
    "manages its own decimation.\n\n"
    "Range\n"
    "-1 — no cap (raw mesh, big).\n"
    "20,000 (default) — good for buildings.\n"
    "50,000+ — hero source for LOD0.\n\n"
    "Performance\n"
    "Decimation is fast (1 – 3 s on CPU). Smaller mesh = smaller GLB.\n\n"
    "Default\n"
    "20,000."
)

_HELP_PAINT_QUALITY = (
    "What this does\n"
    "Quality preset for the Hunyuan3D-2.1 PBR texture painter (albedo + "
    "metallic-roughness). Bundles Diffusion resolution + Render size + "
    "Texture size + Baking views.\n\n"
    "Modes\n"
    "• Speed — 1K texture, 4 views, 256² diffusion. Suitable for low-res "
    "previews / LOD3+ thumbnails.\n"
    "• Balanced — 2K texture, 6 views, 384² diffusion. Recommended.\n"
    "• HQ — 4K texture, 6 views, 512² diffusion. Use only on hero "
    "buildings — cv2.inpaint on a 4K UV map is CPU-only and slow.\n\n"
    "Approximate runtime (relative)\n"
    "Speed 1x · Balanced 3x · HQ 10x.\n\n"
    "Hardware tiers\n"
    "The painter is heavy. Base VRAM peak without offload is around 21 GB.\n"
    "• Without `paint.low_vram_mode` in config.yaml: needs a 24+ GB card "
    "(workstation / data-center class).\n"
    "• With `paint.low_vram_mode: true` (the project default) and the "
    "`mmgp` package installed: peak VRAM drops to about 10 – 12 GB, but "
    "you need 32+ GB SYSTEM RAM because weights are swapped in and out "
    "of GPU memory.\n"
    "• Low-VRAM (6 – 8 GB): not realistic for this painter even with "
    "offload; consider painting in Blender / Substance instead.\n\n"
    "Default\n"
    "Balanced."
)

_HELP_PAINT_RENDER_SIZE = (
    "What this does\n"
    "Internal render resolution per virtual baking view. The painter "
    "renders the untextured mesh from N angles at this resolution, then "
    "bakes the diffused texture back into UV space.\n\n"
    "Range\n"
    "512 — fastest, soft texture.\n"
    "1024 (default) — sweet spot for a 2K final texture.\n"
    "2048 — sharp; only useful with a 4K Texture size.\n"
    "4096 — overkill; almost no quality gain over 2048, and the texture-"
    "inpaint pass dominates wall-clock anyway.\n\n"
    "Performance\n"
    "Quadratic in this value. 2048² is 4x the work of 1024².\n\n"
    "Default\n"
    "1024."
)

_HELP_PAINT_TEXTURE_SIZE = (
    "What this does\n"
    "Final UV-space texture map size. Albedo, metallic-roughness, and the "
    "baked normal all use this resolution.\n\n"
    "Range and relative runtime\n"
    "1024² — fastest baseline. Sharp at distance, soft up-close.\n"
    "2048² (default) — about 3x baseline. Standard for game assets.\n"
    "4096² — about 10x baseline. Bottlenecked by the CPU-only cv2.inpaint "
    "pass that fills UV-seam gaps.\n"
    "8192² — about 30x baseline. Almost never worth it; UV mip-mapping "
    "discards this detail at typical viewing distances.\n\n"
    "Performance\n"
    "Texture size DOMINATES total painter runtime. If a paint job is "
    "taking longer than 2 minutes, this is almost certainly why.\n\n"
    "Default\n"
    "2048."
)

_HELP_PAINT_VIEWS = (
    "What this does\n"
    "Number of virtual camera angles the painter renders for view-baking. "
    "Each view contributes a slice of the final UV texture.\n\n"
    "Range\n"
    "4 — minimum coverage; visible seams on convex objects.\n"
    "6 (default) — good coverage for most objects.\n"
    "8 — max; useful only for objects with many concave features.\n\n"
    "Performance\n"
    "Linear in view count.\n\n"
    "Default\n"
    "6."
)

_HELP_PAINT_RES = (
    "What this does\n"
    "Diffusion resolution per view. The MaterialMVP UNet generates this "
    "many pixels per virtual camera angle.\n\n"
    "Range\n"
    "256 — fast, lower detail.\n"
    "384 — balanced.\n"
    "512 (default) — sharpest; capped at 512 by the model itself.\n\n"
    "Performance\n"
    "Quadratic in resolution.\n\n"
    "Default\n"
    "512."
)

_HELP_PAINT_BAKE_EXP = (
    "What this does\n"
    "Exponent controlling multi-view blending sharpness during the bake "
    "step. Higher means each view contributes only where it sees the "
    "surface most face-on; lower means more averaging across views.\n\n"
    "Range\n"
    "1 — heavy averaging; soft seams but soft texture.\n"
    "4 (default) — balanced.\n"
    "8 — per-view exclusive; sharper but more visible seams.\n\n"
    "Performance and VRAM\n"
    "Free.\n\n"
    "Default\n"
    "4."
)

_HELP_PAINT_MERGE = (
    "What this does\n"
    "How multi-view bakes are combined into the final UV texture.\n\n"
    "Options\n"
    "• fast (default) — weighted average per UV pixel. Fast, soft.\n"
    "• max — take the most face-on view per UV pixel. Sharper, slightly "
    "slower, slightly more visible seams.\n\n"
    "Performance\n"
    "Negligible difference (under 1 s).\n\n"
    "Default\n"
    "fast."
)

_HELP_PAINT_REMESH = (
    "What this does\n"
    "Remeshes the input mesh into a clean topology before painting. The "
    "Hunyuan painter assumes manifold, evenly-distributed triangles; "
    "meshes fresh out of TripoSG / Hunyuan-MV often aren't.\n\n"
    "Effect\n"
    "ON (default, strongly recommended) — prevents UV stretching, baking "
    "artifacts, and texture seams. Adds 5 – 10 s to paint time.\n"
    "OFF — faster but unreliable. Only safe if the input mesh was already "
    "remeshed in Blender / InstaMAT.\n\n"
    "Default\n"
    "ON."
)

_HELP_PAINT_SAVE_MAPS = (
    "What this does\n"
    "When ON, also writes individual texture PNGs (albedo, metallic, "
    "roughness, normal) into outputs/<name>_textured_maps/ alongside the "
    "GLB. The GLB already has them embedded; this gives you separate "
    "files to edit externally.\n\n"
    "Default\n"
    "OFF (the GLB carries everything embedded). Turn ON only if you plan "
    "to edit maps in Photoshop / Substance."
)

_HELP_PAINT_LOW_VRAM = (
    "What this does\n"
    "Wraps the Hunyuan3D-2.1 multi-view diffusion pipeline in mmgp's "
    "LowRAM_LowVRAM profile (profile 4). Weights live in system RAM and "
    "stream into VRAM only while the submodule that needs them is "
    "executing, then get evicted - so peak VRAM stays low.\n\n"
    "When to enable\n"
    "ON when the paint job OOMs without it, or pre-emptively on any "
    "card with < 16 GB VRAM. The painter normally peaks around 21 GB; "
    "with mmgp it fits in ~10–12 GB.\n\n"
    "Cost\n"
    "• Needs ≥ 32 GB system RAM (the resident copy of the weights).\n"
    "• Paint runs ~20–30% slower (PCIe transfer overhead).\n"
    "• Requires `pip install mmgp` - if missing, the run continues "
    "without offload and you'll see a warning in the status box.\n\n"
    "Default\n"
    "Auto-ticked when CUDA reports < 16 GB total VRAM, OR when "
    "config.yaml has `paint.low_vram_mode: true`. Untick per-run to "
    "force the full-VRAM path."
)

_HELP_BMS_ENABLE = (
    "What this does\n"
    "After mesh generation, decimate the result into N LODs and write a "
    "Parent.dat skeleton plus a shared texture set, ready for the BMS "
    "Blender plugin to export as .bml.\n\n"
    "Effect\n"
    "ON — generates bms_export/<asset_name>/ with Model_0.glb (highest "
    "poly) through Model_(N-1).glb (lowest), plus Materials.mtl and the "
    "baked normal map. Adds about 5 s overhead.\n"
    "OFF — skip the LOD pipeline; only the single textured GLB is produced.\n\n"
    "Default\n"
    "OFF. Turn ON when you've finalised a build and want a BMS-ready set."
)

_HELP_BMS_NUM_LODS = (
    "What this does\n"
    "How many LOD levels to generate. Each level is a decimated copy of "
    "the master mesh; targets default to a 4x-per-step falloff "
    "(20k → 8k → 3k → 1k → 400 → 150 → 60 faces).\n\n"
    "Range\n"
    "1 – 2 — tiny props (barrels, road signs).\n"
    "3 – 4 — simple buildings.\n"
    "5 – 6 — medium complexity (hangars, towers).\n"
    "7 (default) — hero / large structures viewed from a distance.\n\n"
    "Performance\n"
    "Each LOD is 1 – 3 s to generate. Cumulative cost is small.\n\n"
    "Default\n"
    "7."
)

_HELP_BMS_SHARE_TEXTURES = (
    "What this does\n"
    "Controls how textures are distributed across the LOD set.\n\n"
    "Modes\n"
    "ON (default, recommended) — ONE Materials.mtl plus ONE set of "
    "texture PNGs shared across all LODs. The BMS Blender plugin "
    "deduplicates this to a single DDS at game-bake time. UVs are "
    "preserved across decimation via texture-aware quadric edge collapse.\n"
    "OFF — each LOD is a self-contained GLB with embedded textures "
    "(about 3x more disk space, no BMS-side dedup benefit).\n\n"
    "Default\n"
    "ON."
)


def _normal_map_control():
    """Reusable Normal-map selector + hover-tooltip icon.

    Returns the Gradio component (the HTML icon is rendered next to
    it for its side-effect; it has no value for the handler input list).

    Implementation note: this used to be a gr.Dropdown but Gradio 6.17's
    Dropdown gets stuck after a handful of interactions on this app
    (typed text doesn't commit, popup stops opening, value silently
    reverts to the previous one). We now render it as a gr.Radio with
    the `quality-chips` pill style - same look-and-feel as the Quality
    selector, but with native <input type=radio> so it can't desync.
    """
    # `equal_height=False` + the `tt-host` styling on the right cell keeps
    # the row tight, so adding the icon doesn't make the accordion suddenly
    # ~50 px taller (which previously triggered the column scrollbar that
    # hid the accordion header).
    with gr.Row(equal_height=False):
        dd = gr.Radio(
            choices=_NORMAL_BAKER_CHOICES,
            value=_normal_baker_default(),
            label="Normal map",
            scale=10,
            min_width=160,
            elem_classes="quality-chips",
        )
        # Tooltip on hover. The JS singleton at the top of the UI reads
        # the .tt-popup text and renders it in a body-level fixed-position
        # popup that escapes Gradio's transform / overflow ancestors.
        _nb_safe = html.escape(_NORMAL_BAKER_TOOLTIP, quote=False)
        gr.HTML(
            '<span class="tt-wrap">'
            '<span class="tt-icon" role="button" tabindex="0" '
            'aria-label="Show help" title="Click for help">i'
            f'<span class="tt-popup">{_nb_safe}</span>'
            '</span></span>',
            elem_classes=["tt-host"],
        )
    return dd


def _bms_accordion(*, with_share_textures: bool = False, default_name: str = ""):
    """The 'Advanced - BMS pipeline' accordion, identical across generation tabs.

    Returns a dict of component handles so the caller can wire them into the
    handler's input list.

    Note: the Normal-map control is NOT part of this accordion - normal
    mapping is a general 3D-painting feature, not BMS-specific. It lives
    next to the painter's other texture controls. See `_normal_map_control`.
    """
    defaults = _bms_lod_targets()
    handles = {}
    with gr.Accordion("Advanced — BMS pipeline (build LOD set after generation)", open=False):
        with gr.Row(equal_height=False):
            handles["enable"] = gr.Checkbox(
                value=False, label="Build BMS LOD set", scale=10,
                info="Decimate the mesh into N LODs + a Parent.dat skeleton, ready "
                     "for the BMS Blender plugin to export as .bml.")
            _help_icon(_HELP_BMS_ENABLE)
        handles["name"] = gr.Textbox(
            value=default_name, label="Asset name",
            placeholder="e.g. hangar_01",
            info="Folder name under bms_export/. Required when 'Build BMS LOD set' is checked.")
        with gr.Row(equal_height=False):
            handles["num_lods"] = gr.Slider(
                1, 7, value=7, step=1, label="Number of LODs", scale=10,
                info="1-2 small props · 3-4 simple buildings · 5-6 medium · "
                     "7 hero / large structures.")
            _help_icon(_HELP_BMS_NUM_LODS)
        if with_share_textures:
            with gr.Row(equal_height=False):
                handles["share_textures"] = gr.Checkbox(
                    value=True, label="Share textures across LODs (recommended)",
                    scale=10,
                    info="ONE Materials.mtl + ONE texture set for all LODs "
                         "(BMS de-dupes to a single DDS at game-bake time).")
                _help_icon(_HELP_BMS_SHARE_TEXTURES)
        with gr.Accordion("LOD face counts (only the first N are used)", open=False):
            handles["lod0"] = gr.Number(value=defaults[0][1], label="LOD0", precision=0,
                info="Closest LOD - usually 15K-25K for a BMS building.", visible=True)
            handles["lod1"] = gr.Number(value=defaults[1][1], label="LOD1", precision=0, visible=True)
            handles["lod2"] = gr.Number(value=defaults[2][1], label="LOD2", precision=0, visible=True)
            handles["lod3"] = gr.Number(value=defaults[3][1], label="LOD3", precision=0, visible=True)
            handles["lod4"] = gr.Number(value=defaults[4][1], label="LOD4", precision=0, visible=True)
            handles["lod5"] = gr.Number(value=defaults[5][1], label="LOD5", precision=0, visible=True)
            handles["lod6"] = gr.Number(value=defaults[6][1], label="LOD6", precision=0,
                info="Furthest LOD / impostor - usually under 100 faces.", visible=True)

    # Show/hide LOD face-count fields based on the chosen LOD count.
    _lod_fields = [handles[f"lod{i}"] for i in range(7)]
    def _toggle_lod_visibility(n: int):
        n = int(n)
        return [gr.update(visible=(i < n)) for i in range(7)]
    handles["num_lods"].change(_toggle_lod_visibility,
                                inputs=[handles["num_lods"]],
                                outputs=_lod_fields)
    return handles


def _ui() -> gr.Blocks:
    with gr.Blocks(title="Modelunify",
                   analytics_enabled=False,
                   head=TOOLTIP_HEAD) as demo:

        # ---- header ---------------------------------------------------------
        # Row of 3 columns: title (Modelunify logo + wordmark + tagline) |
        # status banner (GPU pill + loaded + paint ext) | toolbar (refresh /
        # open outputs / open bms_export). Each cell carries an
        # elem_classes marker so the CSS can strip Gradio's default block
        # chrome from these specific cells (they're meant to look like
        # floating UI, not boxed panels).
        #
        # The logo prefers the real brand PNG (loaded once at module
        # import as a base64 data URL); if the asset can't be found we
        # drop in the inline SVG fallback so the header never renders
        # empty.
        _logo_mark = (
            f"<img src='{LOGO_DATA_URL}' alt='Modelunify' "
            "draggable='false'/>"
            if LOGO_DATA_URL is not None else _LOGO_SVG_FALLBACK
        )
        with gr.Row(equal_height=True):
            with gr.Column(scale=2, elem_classes="app-title"):
                gr.HTML(
                    "<div class='title-inner'>"
                    f"<div class='logo'>{_logo_mark}</div>"
                    "<div class='wordmark'>"
                    "<div class='name-row'>"
                    "<div class='name'>Modelunify</div>"
                    f"<span class='version'>v{MODELUNIFY_VERSION}</span>"
                    "</div>"
                    "<div class='tagline'>Integrated 3D AI Creation</div>"
                    "</div>"
                    "</div>"
                )
            with gr.Column(scale=5):
                banner = gr.HTML(_status_html(), elem_classes="topbar-host")
            with gr.Column(scale=2, elem_classes="toolbar-row"):
                with gr.Row():
                    top_refresh = gr.Button("↻", size="sm", scale=0, min_width=44)
                    top_outputs = gr.Button("📂 outputs", size="sm", scale=0, min_width=110)
                    top_bms     = gr.Button("📂 bms_export", size="sm", scale=0, min_width=130)
        top_refresh.click(lambda: _status_html(), outputs=[banner])
        top_outputs.click(lambda: _open(OUT_DIR))
        top_bms.click(lambda: _open(BMS_DIR))

        # =========================================================
        # Tab 1: Preprocess
        # =========================================================
        with gr.Tab("Preprocess"):
            with gr.Tab("Single"):
                with gr.Row():
                    with gr.Column(scale=1):
                        pp_img = gr.Image(type="pil", label="Image", height=240)
                    with gr.Column(scale=1):
                        pp_size = gr.Slider(256, 2048, value=1024, step=64, label="Size (px)",
                            info="Square output size. 1024 is best for both backends.")
                        pp_bg = gr.Radio(
                            ["u2net", "u2netp", "isnet-general-use", "silueta", "none"],
                            value="u2net", label="BG removal",
                            elem_classes="quality-chips",
                            info="u2net = general · u2netp = light · isnet = sharp · silueta = portraits · none = skip")
                        pp_fmt = gr.Radio(["PNG", "JPG", "WEBP"], value="PNG", label="Format",
                            elem_classes="quality-chips",
                            info="PNG keeps transparency. JPG smaller, no alpha.")
                        with gr.Accordion("Advanced", open=False):
                            pp_crop = gr.Textbox(label="Manual crop",
                                placeholder="left,top,right,bottom (px)",
                                info="Applied BEFORE square-padding.")
                        pp_go = gr.Button("Preprocess", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        pp_out = gr.Image(type="pil", label="Result", height=240)
                        pp_status = gr.Markdown()
                pp_go.click(_do_preprocess_single,
                            inputs=[pp_img, pp_size, pp_bg, pp_fmt, pp_crop],
                            outputs=[pp_out, pp_status],
                            show_progress_on=pp_out)
            with gr.Tab("Folder"):
                with gr.Row():
                    with gr.Column(scale=1):
                        ppb_folder = gr.Textbox(label="Source folder",
                            placeholder=r"e.g. inputs\raw", info="Full path on disk.")
                        ppb_pat = gr.Textbox(value="*.*", label="Pattern", info="Glob like *.png")
                        ppb_size = gr.Slider(256, 2048, value=1024, step=64, label="Size (px)")
                        ppb_bg = gr.Radio(
                            ["u2net", "u2netp", "isnet-general-use", "silueta", "none"],
                            value="u2net", label="BG removal",
                            elem_classes="quality-chips")
                        ppb_fmt = gr.Radio(["PNG", "JPG", "WEBP"], value="PNG", label="Format",
                            elem_classes="quality-chips")
                        ppb_go = gr.Button("Run", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        ppb_status = gr.Markdown()
                ppb_go.click(_do_preprocess_batch,
                             inputs=[ppb_folder, ppb_pat, ppb_size, ppb_bg, ppb_fmt],
                             outputs=[ppb_status])

        # =========================================================
        # Tab 2: TripoSG (Single image OR folder batch as inner sub-tabs)
        # =========================================================
        with gr.Tab("ComfyUI · TRELLIS.2 / Pixal3D"):
            gr.Markdown("### Native ComfyUI 3D in Mesh Workbench\n"
                "Launch **run_modelunify.bat** and select TRELLIS.2 or Pixal3D in **Generate**. "
                "The workbench provides model-specific inputs, advanced stage controls, PBR inspection, "
                "host management and saved workflow provenance.\n\n"
                "One-time setup: `.venv/Scripts/python.exe -m scripts.comfyui_host setup --model trellis` "
                "(or `pixal`, `pixal-mv`, `all`). Setup installs a separate Windows/NVIDIA CUDA runtime "
                "and multi-GB checkpoints; Generate never installs them. "
                "See docs/COMFYUI.md. AMD / Intel GPU inference is not validated.")
        with gr.Tab("TripoSG"):
            with gr.Tab("Single"):
                with gr.Row():
                    with gr.Column(scale=1):
                        s_img = gr.Image(type="pil", label="Image", height=240)
                    with gr.Column(scale=1):
                        s_name = gr.Textbox(
                            label="Asset name",
                            placeholder="e.g. car_1",
                            info="Output folder + filename. Required when "
                                 "BMS pipeline is enabled. If empty, a "
                                 "`webui_<timestamp>` folder is used.")
                        with gr.Row(equal_height=False):
                            s_preset = gr.Radio(list(TRIPOSG_PRESETS),
                                value="Balanced", label="Quality", scale=10,
                                elem_classes="quality-chips",
                                info="Fast / Balanced / HQ — speed vs detail trade-off. "
                                     "Click ⓘ for VRAM tiers.")
                            _help_icon(_HELP_TRIPOSG_QUALITY)
                        s_seed = gr.Number(value=42, label="Seed", precision=0)
                        with gr.Row(equal_height=False):
                            s_bake = gr.Checkbox(value=True,
                                label="Bake planar texture", scale=10,
                                info="Projects the source image onto the mesh as a "
                                     "placeholder texture. Needed for AI normal-map "
                                     "bakers.")
                            _help_icon(_HELP_BAKE_PLANAR)
                        with gr.Accordion("Advanced", open=False):
                            with gr.Row(equal_height=False):
                                s_steps = gr.Slider(15, 75, value=50, step=1,
                                    label="Steps", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_STEPS)
                            with gr.Row(equal_height=False):
                                s_guidance = gr.Slider(1.0, 15.0, value=7.0,
                                    step=0.5, label="Guidance", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_GUIDANCE)
                            with gr.Row(equal_height=False):
                                s_octree = gr.Slider(7, 10, value=9, step=1,
                                    label="Octree depth", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_OCTREE)
                            with gr.Row(equal_height=False):
                                s_dense = gr.Slider(6, 9, value=8, step=1,
                                    label="Dense octree depth", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_DENSE)
                            with gr.Row(equal_height=False):
                                s_bounds = gr.Slider(0.5, 2.0, value=1.25,
                                    step=0.05, label="SDF bounds", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_BOUNDS)
                            with gr.Row(equal_height=False):
                                s_rmbg = gr.Radio(["rmbg", "rembg", "none"],
                                    value="rmbg", label="BG remover", scale=10,
                                    elem_classes="quality-chips")
                                _help_icon_sub(_HELP_BG_REMOVER)
                            with gr.Row(equal_height=False):
                                s_faces = gr.Number(value=20000,
                                    label="Max faces", precision=0, scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_FACES)
                            # Note: there was a Normal-map dropdown here, but
                            # it was removed in 2026-06 because TripoSG's bare
                            # mesh has no UVs (and the planar-projection path
                            # only adds them when "Bake planar texture" is on).
                            # The bake_normal_map() call inside `make_lod_set`
                            # was the only consumer; it now falls back to its
                            # built-in "low" mesh-derived baker for the BMS
                            # LOD output. Users who want real AI-driven normal
                            # maps should use the Multi-view + Paint flow,
                            # where an albedo and UVs are both guaranteed.
                        s_bms = _bms_accordion()
                        s_go = gr.Button("Generate", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        s_out = gr.Model3D(label="Mesh", height=300)
                        s_status = gr.Markdown()

            with gr.Tab("Folder"):
                with gr.Row():
                    with gr.Column(scale=1):
                        bf_folder = gr.Textbox(label="Source folder",
                            placeholder=r"e.g. inputs\preprocessed",
                            info="Full path on disk.")
                        bf_pat = gr.Textbox(value="*.png", label="Pattern")
                        with gr.Row(equal_height=False):
                            bf_preset = gr.Radio(list(TRIPOSG_PRESETS),
                                value="Balanced", label="Quality", scale=10,
                                elem_classes="quality-chips",
                                info="Fast / Balanced / HQ — speed vs detail trade-off. "
                                     "Click ⓘ for VRAM tiers.")
                            _help_icon(_HELP_TRIPOSG_QUALITY)
                        bf_seed = gr.Number(value=42, label="Seed", precision=0)
                        bf_skip = gr.Checkbox(value=True, label="Skip if output exists")
                        with gr.Row(equal_height=False):
                            bf_bake = gr.Checkbox(value=True,
                                label="Bake planar texture", scale=10,
                                info="Projects the source image onto the mesh as a "
                                     "placeholder texture.")
                            _help_icon(_HELP_BAKE_PLANAR)
                        with gr.Accordion("Advanced", open=False):
                            with gr.Row(equal_height=False):
                                bf_steps = gr.Slider(15, 75, value=50, step=1,
                                    label="Steps", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_STEPS)
                            with gr.Row(equal_height=False):
                                bf_guidance = gr.Slider(1.0, 15.0, value=7.0,
                                    step=0.5, label="Guidance", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_GUIDANCE)
                            with gr.Row(equal_height=False):
                                bf_octree = gr.Slider(7, 10, value=9, step=1,
                                    label="Octree", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_OCTREE)
                            with gr.Row(equal_height=False):
                                bf_dense = gr.Slider(6, 9, value=8, step=1,
                                    label="Dense octree", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_DENSE)
                            with gr.Row(equal_height=False):
                                bf_bounds = gr.Slider(0.5, 2.0, value=1.25,
                                    step=0.05, label="Bounds", scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_BOUNDS)
                            with gr.Row(equal_height=False):
                                bf_rmbg = gr.Radio(["rmbg", "rembg", "none"],
                                    value="rmbg", label="BG", scale=10,
                                    elem_classes="quality-chips")
                                _help_icon_sub(_HELP_BG_REMOVER)
                            with gr.Row(equal_height=False):
                                bf_faces = gr.Number(value=20000,
                                    label="Max faces", precision=0, scale=10)
                                _help_icon_sub(_HELP_TRIPOSG_FACES)
                        bf_go = gr.Button("Run batch", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        bf_preview = gr.Model3D(label="Latest mesh", height=300)
                        bf_status = gr.Markdown()

            # Shared preset->fields mapping used by both Single + Folder.
            def _apply_triposg(p):
                d = TRIPOSG_PRESETS[p]
                return d["steps"], d["guidance"], d["octree"], max(6, d["octree"] - 1), d["faces"]
            s_preset.change(_apply_triposg, inputs=[s_preset],
                            outputs=[s_steps, s_guidance, s_octree, s_dense, s_faces])

            # Sync the top-level Asset name into the BMS-accordion's name
            # field so the user doesn't type it twice when BMS LOD set is on.
            # (Matches the mv_name -> mv_bms["name"] sync on Multi-view.)
            s_name.change(lambda v: gr.update(value=v),
                          inputs=[s_name], outputs=[s_bms["name"]])

            s_go.click(_do_single,
                       inputs=[s_img, s_name, s_preset, s_steps, s_guidance,
                               s_octree, s_dense,
                               s_bounds, s_rmbg, s_seed, s_faces, s_bake,
                               s_bms["enable"], s_bms["name"], s_bms["num_lods"],
                               s_bms["lod0"], s_bms["lod1"], s_bms["lod2"], s_bms["lod3"],
                               s_bms["lod4"], s_bms["lod5"], s_bms["lod6"]],
                       outputs=[s_out, s_status],
                       show_progress_on=s_out)
            bf_preset.change(_apply_triposg, inputs=[bf_preset],
                             outputs=[bf_steps, bf_guidance, bf_octree, bf_dense, bf_faces])
            bf_go.click(_do_batch,
                        inputs=[bf_folder, bf_pat, bf_preset, bf_steps, bf_guidance, bf_octree,
                                bf_dense, bf_bounds, bf_rmbg, bf_seed, bf_faces, bf_bake, bf_skip],
                        outputs=[bf_preview, bf_status],
                        show_progress_on=bf_preview)

        # =========================================================
        # Tab 3: Multi-view (shape + optional PBR Paint pipeline)
        # =========================================================
        # Single unified tab that replaces the old "3·Multi-view" + "4·MV+PBR"
        # pair. Toggle "Paint (PBR pipeline)" to switch between:
        #   OFF -> shape-only output (planar bake of one view, optional BMS LODs)
        #   ON  -> Hunyuan3D-2.1 PBR paint pipeline + embedded normal map,
        #          plus optional BMS LOD set with shared textures.
        with gr.Tab("Multi-view"):
            _rast_ok_mv = rasterizer_ready()
            with gr.Row():
                with gr.Column(scale=1, elem_classes="compact-img"):
                    mv_front = gr.Image(type="pil", label="Front (texture ref)", height=240)
                    mv_left  = gr.Image(type="pil", label="Left",  height=240)
                    mv_back  = gr.Image(type="pil", label="Back",  height=240)
                    mv_right = gr.Image(type="pil", label="Right", height=240)
                with gr.Column(scale=1):
                    mv_name = gr.Textbox(
                        label="Asset name",
                        placeholder="e.g. hangar_mv_01",
                        info="Required when Paint or BMS pipeline is enabled.")
                    mv_paint = gr.Checkbox(
                        value=False,
                        label="Paint (PBR pipeline)",
                        info=("Runs the Hunyuan3D-2.1 PBR paint pipeline after shape "
                              "generation. Bakes + embeds a tangent-space normal map "
                              "into the textured GLB. Requires custom_rasterizer."),
                        interactive=_rast_ok_mv,
                    )
                    with gr.Row(equal_height=False):
                        mv_preset_s = gr.Radio(
                            list(HUNYUAN_MV_PRESETS), value="Balanced",
                            label="Shape quality", scale=5,
                            elem_classes="quality-chips",
                            info="Fast / Balanced / HQ. Click ⓘ for VRAM tiers.")
                        _help_icon(_HELP_HUNYUAN_MV_QUALITY)
                        mv_preset_p = gr.Radio(
                            list(PAINT_PRESETS), value="Balanced",
                            label="Paint quality", scale=5,
                            elem_classes="quality-chips",
                            info="Speed / Balanced / HQ — texture size & runtime.",
                            visible=False)
                        _help_icon(_HELP_PAINT_QUALITY)
                    mv_seed = gr.Number(value=12345, label="Seed", precision=0)
                    with gr.Row(equal_height=False):
                        mv_bake = gr.Radio(
                            ["front", "left", "back", "right", "none"],
                            value="front", label="Bake view (shape-only)",
                            scale=10,
                            elem_classes="quality-chips",
                            info="Which uploaded view to project as a placeholder "
                                 "texture. Ignored when Paint is ON.")
                        _help_icon(_HELP_HUNYUAN_MV_BAKE_VIEW)
                    with gr.Accordion("Advanced — Shape", open=False):
                        with gr.Row(equal_height=False):
                            mv_steps = gr.Slider(15, 75, value=50, step=1,
                                label="Steps", scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_STEPS)
                        with gr.Row(equal_height=False):
                            mv_octree = gr.Slider(256, 512, value=380, step=4,
                                label="Octree resolution", scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_OCTREE_RES)
                        with gr.Row(equal_height=False):
                            mv_guide = gr.Slider(1.0, 15.0, value=5.0, step=0.5,
                                label="Guidance", scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_GUIDANCE)
                        with gr.Row(equal_height=False):
                            mv_chunks = gr.Number(value=20000,
                                label="Decoder chunks", precision=0, scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_CHUNKS)
                        with gr.Row(equal_height=False):
                            mv_mclev = gr.Slider(-0.5, 0.5, value=0.0, step=0.01,
                                label="MC level", scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_MCLEV)
                        with gr.Row(equal_height=False):
                            mv_faces = gr.Number(value=20000,
                                label="Max faces (shape-only)",
                                precision=0, scale=10)
                            _help_icon_sub(_HELP_HUNYUAN_MV_FACES)
                    mv_paint_adv = gr.Accordion("Advanced — Paint", open=False, visible=False)
                    with mv_paint_adv:
                        with gr.Row(equal_height=False):
                            mv_pviews = gr.Slider(4, 8, value=6, step=1,
                                label="Baking views", scale=10)
                            _help_icon_sub(_HELP_PAINT_VIEWS)
                        with gr.Row(equal_height=False):
                            mv_pres = gr.Slider(256, 512, value=512, step=64,
                                label="Diffusion resolution", scale=10)
                            _help_icon_sub(_HELP_PAINT_RES)
                        with gr.Row(equal_height=False):
                            mv_prnd = gr.Radio(["512", "1024", "2048", "4096"],
                                value="1024", label="Render size", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_RENDER_SIZE)
                        with gr.Row(equal_height=False):
                            mv_ptex = gr.Radio(["1024", "2048", "4096", "8192"],
                                value="2048", label="Texture size", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_TEXTURE_SIZE)
                        with gr.Row(equal_height=False):
                            mv_pbake = gr.Slider(1, 8, value=4, step=1,
                                label="Bake exponent", scale=10)
                            _help_icon_sub(_HELP_PAINT_BAKE_EXP)
                        with gr.Row(equal_height=False):
                            mv_pmerge = gr.Radio(["fast", "max"], value="fast",
                                label="Merge", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_MERGE)
                        with gr.Row(equal_height=False):
                            mv_premesh = gr.Checkbox(value=True,
                                label="Remesh before painting", scale=10)
                            _help_icon_sub(_HELP_PAINT_REMESH)
                        with gr.Row(equal_height=False):
                            mv_psave = gr.Checkbox(value=False,
                                label="Save individual PBR maps", scale=10)
                            _help_icon_sub(_HELP_PAINT_SAVE_MAPS)
                        with gr.Row(equal_height=False):
                            mv_plow = gr.Checkbox(
                                value=PAINT_LOW_VRAM_DEFAULT,
                                label="Low-VRAM mode (mmgp offload)",
                                scale=10,
                                info=("Swap weights CPU↔VRAM during paint. "
                                      "Needed on <16 GB cards; ~20-30% slower."))
                            _help_icon_sub(_HELP_PAINT_LOW_VRAM)
                    # Normal mapping is part of the PBR Pipeline output:
                    # when Paint is ON we bake a tangent-space normal map and
                    # embed it into the textured GLB. The same selector is
                    # reused for the BMS LOD pipeline in shape-only mode.
                    # Kept outside the Paint accordion so it's reachable in
                    # both modes without flipping the toggle first.
                    mv_normal_baker = _normal_map_control()
                    # Shared-texture LOD output (decimated OBJ + one Materials.mtl
                    # + one set of texture PNGs) is ideal for BMS - the engine
                    # loads textures once and reuses them across all LODs. The
                    # `Share textures` checkbox only applies when Paint is ON.
                    mv_bms = _bms_accordion(with_share_textures=True)
                    mv_go = gr.Button("Generate", variant="primary", size="lg")
                with gr.Column(scale=2):
                    mv_out = gr.Model3D(label="Mesh", height=300)
                    mv_status = gr.Markdown()

            def _apply_mv(p):
                d = HUNYUAN_MV_PRESETS[p]
                return d["steps"], d["octree"], d["guidance"], d["chunks"]
            mv_preset_s.change(_apply_mv, inputs=[mv_preset_s],
                               outputs=[mv_steps, mv_octree, mv_guide, mv_chunks])

            def _apply_paint(p):
                d = PAINT_PRESETS[p]
                return d["views"], d["resolution"], str(d["render_size"]), str(d["texture_size"])
            mv_preset_p.change(_apply_paint, inputs=[mv_preset_p],
                               outputs=[mv_pviews, mv_pres, mv_prnd, mv_ptex])

            # Toggle paint-only controls when the Paint checkbox flips.
            def _toggle_paint(enabled):
                vis = bool(enabled)
                return gr.update(visible=vis), gr.update(visible=vis)
            mv_paint.change(_toggle_paint, inputs=[mv_paint],
                            outputs=[mv_preset_p, mv_paint_adv])

            # Sync the BMS asset name with the top-level Asset name so the
            # user doesn't have to type it twice when BMS LOD set is on.
            mv_name.change(lambda v: gr.update(value=v),
                           inputs=[mv_name], outputs=[mv_bms["name"]])

            mv_go.click(
                _do_mv_unified,
                inputs=[mv_front, mv_left, mv_back, mv_right, mv_name, mv_paint,
                        mv_steps, mv_octree, mv_guide, mv_chunks, mv_mclev,
                        mv_seed, mv_faces, mv_bake,
                        mv_pviews, mv_pres, mv_prnd, mv_ptex,
                        mv_pbake, mv_pmerge, mv_premesh, mv_psave, mv_plow,
                        mv_normal_baker,
                        mv_bms["enable"], mv_bms["share_textures"], mv_bms["num_lods"],
                        mv_bms["lod0"], mv_bms["lod1"], mv_bms["lod2"], mv_bms["lod3"],
                        mv_bms["lod4"], mv_bms["lod5"], mv_bms["lod6"]],
                outputs=[mv_out, mv_status],
                show_progress_on=mv_out)

        # =========================================================
        # Tab 4: Paint PBR (paint an existing mesh)
        # =========================================================
        with gr.Tab("Paint PBR"):
            _rast_ok = rasterizer_ready()
            with gr.Row():
                with gr.Column(scale=1):
                    p_mesh = gr.File(label="Untextured mesh (.glb/.obj)",
                                     file_types=[".glb", ".obj"])
                    p_ref = gr.Image(type="pil", label="Front reference", height=200)
                with gr.Column(scale=1):
                    with gr.Row(equal_height=False):
                        p_preset = gr.Radio(list(PAINT_PRESETS),
                            value="Balanced", label="Quality", scale=10,
                            elem_classes="quality-chips",
                            info="Speed / Balanced / HQ — texture size dominates "
                                 "runtime. Click ⓘ for VRAM tiers.")
                        _help_icon(_HELP_PAINT_QUALITY)
                    with gr.Row(equal_height=False):
                        p_remesh = gr.Checkbox(value=True,
                            label="Remesh before painting", scale=10,
                            info="Strongly recommended — fixes UV stretching and "
                                 "texture seams on AI-generated meshes.")
                        _help_icon(_HELP_PAINT_REMESH)
                    with gr.Row(equal_height=False):
                        p_save = gr.Checkbox(value=False,
                            label="Save individual PBR maps", scale=10,
                            info="Also write albedo / MR / normal as separate PNGs "
                                 "for external editing.")
                        _help_icon(_HELP_PAINT_SAVE_MAPS)
                    with gr.Row(equal_height=False):
                        p_low = gr.Checkbox(
                            value=PAINT_LOW_VRAM_DEFAULT,
                            label="Low-VRAM mode (mmgp offload)", scale=10,
                            info=("Swap weights CPU↔VRAM during paint. "
                                  "Needed on <16 GB cards; ~20-30% slower."))
                        _help_icon(_HELP_PAINT_LOW_VRAM)
                    with gr.Accordion("Advanced", open=False):
                        with gr.Row(equal_height=False):
                            p_views = gr.Slider(4, 8, value=6, step=1,
                                label="Baking views", scale=10)
                            _help_icon_sub(_HELP_PAINT_VIEWS)
                        with gr.Row(equal_height=False):
                            p_res = gr.Slider(256, 512, value=512, step=64,
                                label="Diffusion resolution", scale=10)
                            _help_icon_sub(_HELP_PAINT_RES)
                        with gr.Row(equal_height=False):
                            p_rnd = gr.Radio(["512", "1024", "2048", "4096"],
                                value="1024", label="Render size", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_RENDER_SIZE)
                        with gr.Row(equal_height=False):
                            p_tex = gr.Radio(["1024", "2048", "4096", "8192"],
                                value="2048", label="Texture size", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_TEXTURE_SIZE)
                        with gr.Row(equal_height=False):
                            p_bake = gr.Slider(1, 8, value=4, step=1,
                                label="Bake exponent", scale=10)
                            _help_icon_sub(_HELP_PAINT_BAKE_EXP)
                        with gr.Row(equal_height=False):
                            p_merge = gr.Radio(["fast", "max"], value="fast",
                                label="Merge", scale=10,
                                elem_classes="quality-chips")
                            _help_icon_sub(_HELP_PAINT_MERGE)
                    p_go = gr.Button("Paint texture", variant="primary", size="lg",
                                     interactive=_rast_ok)
                with gr.Column(scale=2):
                    p_out = gr.Model3D(label="Textured mesh", height=300)
                    p_status = gr.Markdown()
            p_preset.change(_apply_paint, inputs=[p_preset],
                            outputs=[p_views, p_res, p_rnd, p_tex])
            p_go.click(_do_paint,
                       inputs=[p_mesh, p_ref, p_preset, p_views, p_res, p_rnd, p_tex,
                               p_bake, p_merge, p_remesh, p_save, p_low],
                       outputs=[p_out, p_status],
                       show_progress_on=p_out)

    return demo


if __name__ == "__main__":
    demo = _ui()
    # Base() (not Soft()) so our design-token CSS wins without fighting
    # the theme's own variable injections. The dark surfaces, accent
    # gradient, glass cards, pill tabs etc. all come from the CSS block
    # above; Base() just gives Gradio a neutral starting point.
    # `favicon_path` paints the Modelunify mark in the browser tab. We
    # only pass it when the file is on disk - Gradio raises on a missing
    # path instead of silently falling back. The data-URL embed in the
    # header keeps the in-page logo working independently of this.
    _favicon = str(LOGO_PATH) if LOGO_PATH.exists() else None
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                theme=gr.themes.Base(), css=CSS, show_error=True,
                favicon_path=_favicon,
                allowed_paths=[str(ASSETS_DIR)])
