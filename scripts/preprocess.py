"""
preprocess — prep satellite / aerial / ground photos before TripoSG.

TripoSG works best with:
- A square (1:1) image
- A single, well-lit object
- Background already removed (or removable by RMBG)

For *satellite* shots of buildings you usually want to:
1. Manually crop tight around the building
2. Square-pad (transparent or white)
3. Optionally remove non-building pixels with rembg (u2net works better on aerial than RMBG-1.4)
"""
from __future__ import annotations

import os
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
from PIL import Image
from rich import print

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Preprocess images for TripoSG.")


def _square_pad(img: Image.Image, color=(255, 255, 255)) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    mode = img.mode if img.mode in ("RGB", "RGBA") else "RGB"
    bg = Image.new(mode, (s, s), color if mode == "RGB" else (*color, 0))
    bg.paste(img, ((s - w) // 2, (s - h) // 2), img if img.mode == "RGBA" else None)
    return bg


@app.command()
def prep(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    size: int = typer.Option(1024, "--size", help="Output square size (px)"),
    remove_bg: bool = typer.Option(False, "--remove-bg", help="Run rembg (u2net) for background removal"),
    crop: Optional[str] = typer.Option(None, "--crop",
                                       help="Crop box 'left,top,right,bottom' in pixels (pre-resize)"),
):
    """Square-pad + resize + (optional) bg-remove a single image."""
    img = Image.open(input_path).convert("RGBA")

    if crop:
        try:
            l, t, r, b = [int(x) for x in crop.split(",")]
        except ValueError:
            print("[red]--crop must be 'left,top,right,bottom'[/red]")
            raise typer.Exit(2)
        img = img.crop((l, t, r, b))

    if remove_bg:
        from rembg import remove
        img = remove(img)

    img = _square_pad(img)
    img = img.resize((size, size), Image.LANCZOS)

    out = output or input_path.with_name(f"{input_path.stem}_prep.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"[green]✓ Wrote[/green] {out}  ({size}x{size})")


@app.command()
def batch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False),
    pattern: str = typer.Option("*.*", "--pattern"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    size: int = typer.Option(1024, "--size"),
    remove_bg: bool = typer.Option(False, "--remove-bg"),
):
    """Square-pad + resize every image in folder."""
    out_dir = output_dir or folder.parent / f"{folder.name}_prep"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(folder.glob(pattern)):
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
            continue
        try:
            img = Image.open(p).convert("RGBA")
            if remove_bg:
                from rembg import remove
                img = remove(img)
            img = _square_pad(img).resize((size, size), Image.LANCZOS)
            out = out_dir / f"{p.stem}.png"
            img.save(out, "PNG")
            print(f"  [green]✓[/green] {p.name} -> {out.name}")
            n += 1
        except Exception as e:
            print(f"  [red]✗[/red] {p.name}: {e}")
    print(f"[bold]Done.[/bold] {n} images written to {out_dir}")


if __name__ == "__main__":
    app()
