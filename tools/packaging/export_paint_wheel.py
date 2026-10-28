"""Package the installed, validated Windows rasterizer without recompiling it.

This is a local binary-reuse shortcut, not a reproducible CUDA source build.
Run with the validated Python 3.11 / torch 2.5.1+cu124 environment. The wheel
records binary hashes and keeps the upstream license. No weights are included.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata as metadata
import io
import json
from pathlib import Path
import platform
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def write_wheel(target: Path, files: dict[str, bytes]) -> None:
    """Write a wheel exclusively, with hashes for every payload in RECORD."""
    records = io.StringIO(newline="")
    writer = csv.writer(records, lineterminator="\n")
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow(("custom_rasterizer-0.1.dist-info/RECORD", "", ""))
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)
        wheel.writestr("custom_rasterizer-0.1.dist-info/RECORD", records.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Directory for a new wheel; existing wheels are refused")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or platform.machine().upper() != "AMD64":
        parser.error("Requires Windows x64 with CPython 3.11.")
    import torch

    if torch.__version__ != "2.5.1+cu124" or torch.version.cuda != "12.4":
        parser.error("Requires the validated torch 2.5.1+cu124 ABI.")
    # Loading both modules establishes that the existing binary is usable here.
    import custom_rasterizer
    import custom_rasterizer_kernel

    package = Path(custom_rasterizer.__file__).resolve().parent
    kernel = Path(custom_rasterizer_kernel.__file__).resolve()
    if kernel.name != "custom_rasterizer_kernel.cp311-win_amd64.pyd":
        parser.error("Unexpected native extension ABI/name.")
    files = {"custom_rasterizer/" + path.name: path.read_bytes() for path in sorted(package.glob("*.py"))}
    if "custom_rasterizer/__init__.py" not in files or "custom_rasterizer/render.py" not in files:
        parser.error("The installed package is incomplete.")
    files[kernel.name] = kernel.read_bytes()
    dist = "custom_rasterizer-0.1.dist-info/"
    files[dist + "METADATA"] = (
        "Metadata-Version: 2.1\nName: custom-rasterizer\nVersion: 0.1\n"
        "Summary: Locally repackaged Hunyuan rasterizer binary\n"
        "Requires-Python: >=3.11,<3.12\nRequires-Dist: torch (==2.5.1+cu124)\n\n"
        "Existing validated native binary; not recompiled by this tool.\n"
    ).encode()
    files[dist + "WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: ModelUnify local binary export\n"
        "Root-Is-Purelib: false\nTag: cp311-cp311-win_amd64\n"
    ).encode()
    files[dist + "LICENSE"] = (ROOT / "vendor/Hunyuan3D-2.1/LICENSE").read_bytes()
    files[dist + "MODELUNIFY_BUILD.json"] = json.dumps({
        "method": "reuse installed validated binary; no CUDA compilation",
        "python": sys.version, "torch": torch.__version__, "cuda": torch.version.cuda,
        "source_distribution": metadata.version("custom-rasterizer"),
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()
                   if not name.startswith(dist)},
    }, indent=2).encode()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "custom_rasterizer-0.1-cp311-cp311-win_amd64.whl"
    write_wheel(target, files)
    print(json.dumps({"wheel": str(target.resolve()), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "native_source": str(kernel), "recompiled": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
