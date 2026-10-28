"""Enhance an existing textured master mesh for general use and Falcon BMS."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pymeshlab
import trimesh
from PIL import Image
from trimesh.visual.material import PBRMaterial


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lod_export import bake_normal_map, _decimate_keep_uv  # noqa: E402


def mesh_stats(mesh: trimesh.Trimesh) -> dict[str, object]:
    faces = np.asarray(mesh.faces)
    duplicate = len(faces) - len(np.unique(np.sort(faces, axis=1), axis=0))
    uv = getattr(mesh.visual, "uv", None)
    return {
        "vertices": len(mesh.vertices),
        "faces": len(faces),
        "uv_vertices": 0 if uv is None else len(uv),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "components": len(mesh.split(only_watertight=False)),
        "degenerate_faces": int(np.count_nonzero(mesh.area_faces < 1e-12)),
        "duplicate_faces": duplicate,
        "bounds": np.asarray(mesh.bounds).round(6).tolist(),
    }


def safe_cleanup(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, list[str]]:
    """Remove only provably invalid faces; preserve components and topology."""
    notes: list[str] = []
    faces = np.asarray(mesh.faces)
    nondegenerate = np.asarray(mesh.area_faces >= 1e-12)
    if np.count_nonzero(~nondegenerate):
        notes.append(
            f"removed {int(np.count_nonzero(~nondegenerate))} zero-area faces"
        )

    remaining = faces[nondegenerate]
    _, unique_index = np.unique(
        np.sort(remaining, axis=1), axis=0, return_index=True
    )
    unique = np.zeros(len(remaining), dtype=bool)
    unique[unique_index] = True
    if np.count_nonzero(~unique):
        notes.append(f"removed {int(np.count_nonzero(~unique))} duplicate faces")

    keep = np.zeros(len(faces), dtype=bool)
    keep[np.flatnonzero(nondegenerate)[unique]] = True
    if not np.all(keep):
        mesh.update_faces(keep)
        mesh.remove_unreferenced_vertices()
    else:
        notes.append("no invalid faces found; geometry preserved unchanged")
    return mesh, notes


def resize(image: Image.Image, size: int, mode: str) -> Image.Image:
    return image.convert(mode).resize((size, size), Image.Resampling.LANCZOS)


def delight_light(image: Image.Image, strength: float = 0.18) -> Image.Image:
    """Conservatively flatten broad illumination while retaining local color."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    linear = np.power(np.clip(rgb, 0.0, 1.0), 2.2)
    luminance = (
        0.2126 * linear[..., 0]
        + 0.7152 * linear[..., 1]
        + 0.0722 * linear[..., 2]
    )
    sigma = max(image.size) / 24.0
    illumination = cv2.GaussianBlur(
        luminance,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )
    positive = illumination[illumination > 1e-4]
    target = float(np.median(positive)) if positive.size else 0.5
    correction = np.power(
        np.clip(target / np.maximum(illumination, 0.02), 0.55, 1.8),
        strength,
    )
    corrected = np.clip(linear * correction[..., None], 0.0, 1.0)
    srgb = np.power(corrected, 1.0 / 2.2)
    return Image.fromarray((srgb * 255.0 + 0.5).astype(np.uint8), "RGB")


def rasterize_vertex_scalar(
    mesh: trimesh.Trimesh,
    values: np.ndarray,
    size: int,
    outside: int,
) -> Image.Image:
    uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) != len(mesh.vertices):
        raise ValueError("Mesh needs one UV coordinate per vertex")

    uv = np.asarray(uv, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    values = np.asarray(values, dtype=np.float32)
    pixels = np.column_stack((uv[:, 0] * size, (1.0 - uv[:, 1]) * size))
    accum = np.zeros((size, size), dtype=np.float32)
    weight = np.zeros((size, size), dtype=np.float32)

    for face in faces:
        p0, p1, p2 = pixels[face]
        v0, v1, v2 = values[face]
        xmin = max(0, int(np.floor(min(p0[0], p1[0], p2[0]))))
        xmax = min(size - 1, int(np.ceil(max(p0[0], p1[0], p2[0]))))
        ymin = max(0, int(np.floor(min(p0[1], p1[1], p2[1]))))
        ymax = min(size - 1, int(np.ceil(max(p0[1], p1[1], p2[1]))))
        if xmin > xmax or ymin > ymax:
            continue
        denominator = (
            (p1[1] - p2[1]) * (p0[0] - p2[0])
            + (p2[0] - p1[0]) * (p0[1] - p2[1])
        )
        if abs(float(denominator)) < 1e-9:
            continue
        xs = np.arange(xmin, xmax + 1, dtype=np.float32) + 0.5
        ys = np.arange(ymin, ymax + 1, dtype=np.float32) + 0.5
        xgrid, ygrid = np.meshgrid(xs, ys)
        a = (
            (p1[1] - p2[1]) * (xgrid - p2[0])
            + (p2[0] - p1[0]) * (ygrid - p2[1])
        ) / denominator
        b = (
            (p2[1] - p0[1]) * (xgrid - p2[0])
            + (p0[0] - p2[0]) * (ygrid - p2[1])
        ) / denominator
        c = 1.0 - a - b
        inside = (a >= 0.0) & (b >= 0.0) & (c >= 0.0)
        if not np.any(inside):
            continue
        yi, xi = np.nonzero(inside)
        yi = yi + ymin
        xi = xi + xmin
        interpolated = (a * v0 + b * v1 + c * v2)[inside]
        accum[yi, xi] += interpolated
        weight[yi, xi] += 1.0

    covered = weight > 0.0
    result = np.full((size, size), outside / 255.0, dtype=np.float32)
    result[covered] = accum[covered] / weight[covered]
    return Image.fromarray(
        (np.clip(result, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), "L"
    )


def bake_ao(mesh: trimesh.Trimesh, size: int, rays: int = 64) -> Image.Image:
    mesh_set = pymeshlab.MeshSet()
    mesh_set.add_mesh(pymeshlab.Mesh(mesh.vertices, mesh.faces), "master")
    mesh_set.apply_filter("compute_scalar_ambient_occlusion", rays=rays)
    raw = np.asarray(
        mesh_set.current_mesh().vertex_scalar_array(), dtype=np.float32
    )
    low, high = np.percentile(raw, (2.0, 98.0))
    if high <= low + 1e-8:
        normalized = np.ones_like(raw)
    else:
        normalized = np.clip((raw - low) / (high - low), 0.0, 1.0)
        normalized = np.power(normalized, 0.8)
    return rasterize_vertex_scalar(mesh, normalized, size, outside=255)


def bake_wetness(
    mesh: trimesh.Trimesh,
    ao: Image.Image,
    size: int,
    up_axis: str,
) -> Image.Image:
    axis_index = {"x": 0, "y": 1, "z": 2}[up_axis]
    upward = np.asarray(mesh.vertex_normals)[:, axis_index]
    exposure = np.clip((upward - 0.10) / 0.70, 0.0, 1.0)
    slope = rasterize_vertex_scalar(mesh, exposure, size, outside=0)
    slope_array = np.asarray(slope, dtype=np.float32) / 255.0
    ao_array = np.asarray(ao.resize((size, size)), dtype=np.float32) / 255.0
    wet = slope_array * (0.25 + 0.75 * ao_array)
    return Image.fromarray(
        (np.clip(wet, 0.0, 1.0) * 255.0).astype(np.uint8), "L"
    )


def pack_armw(
    ao: Image.Image,
    roughness: Image.Image,
    metallic: Image.Image,
    wetness: Image.Image,
) -> Image.Image:
    return Image.merge(
        "RGBA",
        (
            ao.convert("L"),
            roughness.convert("L"),
            metallic.convert("L"),
            wetness.convert("L"),
        ),
    )


def report_lines(title: str, values: dict[str, object]) -> list[str]:
    lines = [title]
    lines.extend(f"  {key}: {value}" for key, value in values.items())
    return lines


def enhance(args: argparse.Namespace) -> Path:
    started = time.time()
    source = args.input.resolve()
    asset_dir = source.parent
    output = (args.output or (asset_dir / "enhanced")).resolve()
    if output == asset_dir or output == source or (output.exists() and any(output.iterdir())):
        raise FileExistsError(f"Enhancement needs a fresh output folder, separate from the master: {output}")

    albedo_path = asset_dir / "albedo.png"
    mr_path = asset_dir / "metallic_roughness.png"
    for required in (source, albedo_path, mr_path):
        if not required.exists():
            raise FileNotFoundError(required)

    loaded = trimesh.load(str(source), force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"Could not load {source} as one mesh")
    mesh = loaded.copy()
    before = mesh_stats(mesh)
    print(f"[enhance] Source: {source}; static mesh export; hierarchy/animation are not retained.")
    print(f"[enhance] Mesh: {before}; output: {output}; supplied master is preserved.")
    if before["uv_vertices"] == 0:
        raise ValueError("Input mesh has no UV coordinates")
    output.mkdir(parents=True, exist_ok=True)

    mesh, cleanup_notes = safe_cleanup(mesh)
    if args.mesh_mode == "optimize":
        before_opt = len(mesh.faces)
        target = args.target_faces
        if target > 0 and before_opt > target:
            print(
                f"[enhance] UV-preserving optimize {before_opt} -> {target} faces"
            )
            mesh = _decimate_keep_uv(mesh, target)
            cleanup_notes.append(
                f"UV-preserving optimize {before_opt} -> {len(mesh.faces)} faces"
            )
        else:
            cleanup_notes.append(
                f"optimize skipped (faces={before_opt}, target={target})"
            )
    after = mesh_stats(mesh)

    albedo_original = resize(Image.open(albedo_path), args.resolution, "RGB")
    albedo = (
        delight_light(albedo_original, args.delight_strength)
        if args.delight_strength > 0.0
        else albedo_original
    )
    mr = resize(Image.open(mr_path), args.resolution, "RGB")
    mr_array = np.asarray(mr)
    roughness = Image.fromarray(mr_array[..., 1], "L")
    metallic = Image.fromarray(mr_array[..., 2], "L")

    print(
        f"[enhance] Baking AO at {args.resolution} "
        f"with {args.ao_rays} rays"
    )
    ao = bake_ao(mesh, args.resolution, args.ao_rays)
    wetness = bake_wetness(mesh, ao, args.resolution, args.up_axis)

    print(f"[enhance] Baking normal map: requested={args.normal}")
    normal = bake_normal_map(
        mesh, albedo, baker=args.normal, uv_size=args.resolution
    )
    if normal is None:
        raise RuntimeError("Normal baker returned no image")
    normal = normal.convert("RGB")

    albedo.save(output / "albedo.png")
    mr.save(output / "metallic_roughness.png")
    normal.save(output / "normal.png")

    wrote: list[str] = [
        "albedo.png",
        "metallic_roughness.png",
        "normal.png",
    ]
    if args.armw in ("separate", "both"):
        ao.save(output / "ao.png")
        roughness.save(output / "roughness.png")
        metallic.save(output / "metallic.png")
        wetness.save(output / "wetness.png")
        wrote.extend(
            ["ao.png", "roughness.png", "metallic.png", "wetness.png"]
        )
    if args.armw in ("packed", "both"):
        pack_armw(ao, roughness, metallic, wetness).save(output / "armw.png")
        wrote.append("armw.png (R=AO, G=roughness, B=metallic, A=wetness)")
    leftover = output / "armw.png"
    if args.armw == "separate" and leftover.exists():
        leftover.unlink()

    mesh.visual.material = PBRMaterial(
        name=args.material_name,
        baseColorTexture=albedo,
        metallicRoughnessTexture=mr,
        normalTexture=normal,
        occlusionTexture=ao,
        doubleSided=True,
    )
    mesh.export(output / "Model_0.glb")

    report: list[str] = [
        "ModelUnify BMS enhancement report",
        "=================================",
        f"input: {source}",
        f"output: {output}",
        "target: BMS + general 3D",
        f"mesh_mode: {args.mesh_mode}",
        f"target_faces: {args.target_faces}",
        f"resolution: {args.resolution}",
        f"delight_strength: {args.delight_strength}",
        f"normal_requested: {args.normal}",
        f"ao_rays: {args.ao_rays}",
        f"wetness: automatic, up_axis={args.up_axis}",
        f"ARMW: {args.armw}",
        "format: GLB only",
        "",
    ]
    report.extend(report_lines("Before", before))
    report.append("")
    report.extend(report_lines("After", after))
    report.append("")
    report.append("Cleanup")
    report.extend(f"  - {note}" for note in cleanup_notes)
    report.extend([
        "",
        "Outputs",
        "  Model_0.glb (embedded albedo, MR, normal, AO)",
        *[f"  {name}" for name in wrote],
        "",
        "Warnings",
        "  - DDS export is not implemented by this processor; convert with the external exporter/texconv.",
        *(
            [
                "  - Separate maps only: BMS still needs a packed ARMW DDS before in-game export."
            ]
            if args.armw == "separate"
            else []
        ),
        "  - BMS Materials.mtl and BML require the BMS Blender/3ds Max exporter.",
        "  - The mesh remains non-watertight when safe cleanup cannot repair it",
        "    without changing component structure.",
        f"elapsed_seconds: {time.time() - started:.1f}",
    ])
    (output / "enhance_report.txt").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enhance an existing textured Model_0 for BMS/general use"
    )
    parser.add_argument("input", type=Path, help="Textured Model_0 OBJ or GLB")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--resolution",
        type=int,
        choices=(1024, 2048, 4096),
        default=2048,
    )
    parser.add_argument(
        "--normal", choices=("low", "medium", "high"), default="high"
    )
    parser.add_argument("--delight-strength", type=float, default=0.18)
    parser.add_argument("--ao-rays", type=int, default=64)
    parser.add_argument(
        "--up-axis", choices=("x", "y", "z"), default="y"
    )
    parser.add_argument("--material-name", default="modelunify_asset")
    parser.add_argument(
        "--armw",
        choices=("separate", "packed", "both"),
        default="both",
        help="separate = AO/roughness/metallic/wetness only; "
        "packed = armw.png only; both = packed plus sources",
    )
    parser.add_argument(
        "--mesh-mode",
        choices=("safe", "optimize"),
        default="safe",
    )
    parser.add_argument(
        "--target-faces",
        type=int,
        default=20000,
        help="Used with --mesh-mode optimize",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = enhance(args)
    except Exception as exc:
        print(f"[enhance] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[enhance] Complete: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
