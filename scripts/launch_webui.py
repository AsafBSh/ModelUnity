"""
Web UI launcher with a CLI progress bar.

Same end result as `python scripts/web_ui.py`, but shows a Rich progress bar
in the terminal as each heavy module imports — so you know the system isn't
hung during the ~20-30 s startup. After bootstrap, the actual server launches
in-browser as usual.

Usage:
    python scripts/launch_webui.py            # foreground, default port 7860
    python scripts/launch_webui.py --no-open  # don't auto-open browser
    python scripts/launch_webui.py --port 8000
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Force stdout/stderr to UTF-8 BEFORE any imports that might write to
# them. The launcher uses Rich (em-dash, checkmarks) and the downstream
# pipelines use tqdm (block-drawing chars ▏▎▍▌▋▊▉█), all of which crash
# Windows's default cp1252 console encoder with UnicodeEncodeError.
# Reconfiguring the existing TextIOWrapper avoids the crash and keeps
# any handler that already captured a reference to sys.stdout valid.
# (Same guard duplicated at the top of scripts/web_ui.py for users that
# launch it directly without going through this launcher.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _preflight() -> None:
    """Cheap pre-import checks. Prints clear messages BEFORE the 20 s
    import storm so the user doesn't stare at a frozen progress bar
    while the real error is hiding 200 lines down in a stack trace.

    Two checks:
      1. nvcuda.dll loadable -> NVIDIA driver is installed and recent
         enough to expose the CUDA runtime to PyTorch.
      2. Any AI-model weights already present locally -> if not, warn
         the user that the first run will download ~8 GB.
    """
    # --- 1. NVIDIA driver / CUDA runtime ---
    # Only meaningful on Windows; ctypes.WinDLL is a no-op on other OSes.
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.WinDLL("nvcuda.dll")
        except OSError:
            print(
                "\n[WARN] nvcuda.dll could not be loaded.\n"
                "       Modelunify needs an NVIDIA GPU + recent driver\n"
                "       (>= 555.x) to run TripoSG / Hunyuan3D-2mv.\n"
                "       Continuing anyway in case you set device: cpu\n"
                "       in config.yaml, but expect a CUDA error otherwise.\n",
                file=sys.stderr, flush=True,
            )

    # --- 2. First-run model-weight notice ---
    # Two backends, two cache locations. Warn ONCE up-front so the user
    # understands the 8 GB download isn't a hang.
    hf_home = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    triposg_dir = ROOT / "pretrained_weights" / "TripoSG"
    hf_cache_present = Path(hf_home).exists() and any(Path(hf_home).rglob("*.safetensors"))
    triposg_present = triposg_dir.exists() and any(triposg_dir.rglob("*.safetensors"))
    if not (hf_cache_present or triposg_present):
        print(
            "\n[INFO] First-run model download required (~8 GB total).\n"
            "       TripoSG (~3 GB) downloads to pretrained_weights\\.\n"
            "       Hunyuan3D-2mv (~5 GB) downloads to the HF cache:\n"
            f"         {hf_home}\n"
            "       This happens the first time you click Generate in the\n"
            "       web UI; the progress bar lives in this console window.\n",
            flush=True,
        )


# Each tuple is (description shown in bar, percentage of total bar to advance).
# Total of the 'advance' column should be 100.
_STAGES = [
    ("Importing Rich + applying CLI styling",                 3),
    ("Importing Gradio + applying compat patches",           10),
    ("Importing PyTorch + CUDA bindings",                    25),
    ("Importing TripoSG engine (diffusers, transformers)",   12),
    ("Importing Hunyuan3D-2mv engine (hy3dgen.shapegen)",    14),
    ("Importing Hunyuan3D-2.1 paint engine + torchvision shim", 14),
    ("Importing LOD exporter + texture helpers",              4),
    ("Initializing engine configs (no model weights yet)",    5),
    ("Building Gradio UI tabs",                               8),
    ("Starting HTTP server",                                  5),
]


def _plain_run():
    """Fallback when Rich isn't installed: just print stage lines."""
    n = len(_STAGES)
    for i, (desc, _adv) in enumerate(_STAGES, start=1):
        print(f"[{i}/{n}] {desc} ...", flush=True)
        _run_stage(i - 1)
    print("\n[OK] Ready. Launching server...\n")


def _check_torch_stack() -> None:
    """Catch the torch/torchvision ABI-mismatch regression with a clear msg.

    Background: some transitive pip installs (e.g. mmgp, basicsr, realesrgan)
    pull plain `torch` from PyPI, which OVERWRITES the project's CUDA wheel
    (`torch==2.5.1+cu124`) with a CPU-only build. torchvision, still pinned
    to the +cu124 build, can no longer find the ops it was compiled against
    and the launcher dies with a 200-line `torchvision::nms does not exist`
    stack trace deep inside transformers/diffusers. This guard surfaces
    the real cause + exact fix command before that mess happens.
    """
    try:
        import torch
        import torchvision
    except Exception:
        # Let downstream stage raise its own ImportError; nothing to check.
        return

    tv_has_cuda = "+cu" in torchvision.__version__
    torch_has_cuda = "+cu" in torch.__version__
    if tv_has_cuda and not torch_has_cuda:
        msg = (
            "\n[FATAL] PyTorch / torchvision build mismatch detected.\n"
            f"  torch       = {torch.__version__}   (CPU-only build)\n"
            f"  torchvision = {torchvision.__version__}  (CUDA build)\n"
            "\n"
            "A recent `pip install` overwrote your CUDA PyTorch wheel with the\n"
            "vanilla CPU wheel from PyPI. torchvision's compiled ops no longer\n"
            "match torch's ABI, which would crash the launcher inside\n"
            "transformers with the misleading error\n"
            "    `RuntimeError: operator torchvision::nms does not exist`.\n"
            "\n"
            "Fix (run from a fresh shell, takes ~2 min and ~2.5 GB download):\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install --force-reinstall \\\n"
            "    --no-deps torch==2.5.1+cu124 torchvision==0.20.1+cu124 \\\n"
            "    torchaudio==2.5.1+cu124 \\\n"
            "    --index-url https://download.pytorch.org/whl/cu124\n"
        )
        print(msg, file=sys.stderr, flush=True)
        sys.exit(2)


def _run_stage(idx: int) -> None:
    """Execute the work for a given stage index."""
    if idx == 0:
        # Rich just imported; nothing else
        pass
    elif idx == 1:
        import gradio  # noqa: F401
    elif idx == 2:
        import torch  # noqa: F401
        _check_torch_stack()
    elif idx == 3:
        from scripts import engine  # noqa: F401
    elif idx == 4:
        from scripts import engine_hunyuan  # noqa: F401
    elif idx == 5:
        from scripts import engine_paint  # noqa: F401
    elif idx == 6:
        from scripts import lod_export  # noqa: F401
        from scripts import texture     # noqa: F401
    elif idx == 7:
        # Importing web_ui triggers CFG load + engine init (no weights yet)
        from scripts import web_ui  # noqa: F401
    elif idx == 8:
        from scripts import web_ui
        # Build the Blocks tree
        web_ui._launcher_demo = web_ui._ui()
    elif idx == 9:
        # Server launch happens AFTER the progress bar closes - here just
        # a small pause so the bar reaches 100% visually before the next print.
        time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7860,
                    help="HTTP port (default 7860)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind address (default 127.0.0.1 - localhost only)")
    ap.add_argument("--no-open", action="store_true",
                    help="Don't auto-open the browser")
    ap.add_argument("--share", action="store_true",
                    help="Create a public Gradio sharing link (tunneled)")
    args = ap.parse_args()

    _preflight()

    # Try Rich; fall back to plain output if unavailable.
    try:
        from rich.console import Console
        from rich.progress import (
            Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn,
            TimeElapsedColumn,
        )
    except Exception:
        print("(rich not available - falling back to plain output)\n")
        _plain_run()
        from scripts import web_ui as _w
        import gradio as _gr
        demo = _w._launcher_demo if hasattr(_w, "_launcher_demo") else _w._ui()
        _favicon = str(_w.LOGO_PATH) if _w.LOGO_PATH.exists() else None
        demo.launch(server_name=args.host, server_port=args.port,
                    inbrowser=not args.no_open, share=args.share,
                    theme=_gr.themes.Base(), css=_w.CSS, show_error=True,
                    favicon_path=_favicon,
                    allowed_paths=[str(_w.ASSETS_DIR)])
        return

    # Read the version from the dedicated tiny module so we DON'T trigger
    # the full `web_ui` import (torch, diffusers, gradio, all engines)
    # just to render the banner. Keeps the first paint snappy.
    try:
        from scripts._version import MODELUNIFY_VERSION as _v
    except Exception:
        _v = "?"

    console = Console()
    console.print()
    console.rule(f"[bold cyan]Modelunify v{_v} — starting up", style="cyan")
    console.print()

    t0 = time.time()
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold blue]{task.description}", justify="left"),
        BarColumn(bar_width=40, style="dim", complete_style="green",
                  finished_style="bold green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(_STAGES[0][0], total=100)
        for i, (desc, adv) in enumerate(_STAGES):
            progress.update(task, description=desc)
            _run_stage(i)
            progress.update(task, advance=adv)

    dt = time.time() - t0
    console.print()
    console.print(f"[bold green]✓ Bootstrap complete[/bold green] in {dt:.1f}s. "
                  f"Launching server at [bold cyan]http://{args.host}:{args.port}[/bold cyan]...")
    console.print("[dim]Press Ctrl+C in this window to stop the server.[/dim]")
    console.print()

    from scripts import web_ui as _w
    import gradio as _gr
    demo = _w._launcher_demo if hasattr(_w, "_launcher_demo") else _w._ui()
    # Base() (not Soft()) so the design-token CSS in web_ui.CSS wins
    # without fighting the theme's own CSS variable injections. The dark
    # surfaces, accent gradient, glass cards and pill tabs all come from
    # the stylesheet; Base() just gives Gradio a neutral starting point.
    _favicon = str(_w.LOGO_PATH) if _w.LOGO_PATH.exists() else None
    demo.launch(server_name=args.host, server_port=args.port,
                inbrowser=not args.no_open, share=args.share,
                theme=_gr.themes.Base(), css=_w.CSS, show_error=True,
                favicon_path=_favicon,
                allowed_paths=[str(_w.ASSETS_DIR)])


if __name__ == "__main__":
    main()
