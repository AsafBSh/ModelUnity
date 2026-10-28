"""One authoritative preparation pass for both shape backends."""
from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image
from .schema import Preparation


def composite(image, background="white"):
    rgba = image.convert("RGBA")
    if background == "transparent":
        return rgba
    canvas = Image.new("RGBA", rgba.size, "white" if background == "white" else "black")
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def isolate(image, options: Preparation, root: Path, config: dict):
    if image is None:
        raise ValueError("Upload a reference image first.")
    image = image.convert("RGBA")
    from .mask_edit import image_digest
    manual = image_digest(image) in options.manual_alpha_digests
    if options.crop.strip():
        try:
            x1, y1, x2, y2 = map(int, options.crop.split(","))
        except ValueError as exc:
            raise ValueError("Crop requires four integers: left,top,right,bottom.") from exc
        if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
            raise ValueError("Crop must have positive area and stay inside the image.")
        image = image.crop((x1, y1, x2, y2))
    meaningful_alpha = image.getchannel("A").getextrema()[0] < 255
    actual = "manual corrected alpha" if manual else "preserved alpha" if meaningful_alpha and options.preserve_alpha else "unchanged input"
    if not (manual or meaningful_alpha and options.preserve_alpha):
        if options.provider == "rembg":
            import onnxruntime as ort
            from rembg import new_session, remove
            if options.execution not in ort.get_available_providers():
                raise ValueError(f"{options.execution} is unavailable; select an installed ONNX provider.")
            session = new_session(options.model, providers=[options.execution])
            image = remove(image, session=session, alpha_matting=options.alpha_matting,
                           alpha_matting_foreground_threshold=options.foreground,
                           alpha_matting_background_threshold=options.background_threshold,
                           alpha_matting_erode_size=options.erode,
                           post_process_mask=options.postprocess).convert("RGBA")
            actual = f"rembg/{options.model} · {session.inner_session.get_providers()}"
            del session
        elif options.provider == "rmbg":
            import sys
            import torch
            import torch.nn.functional as F
            vendor = str(root / "vendor" / "TripoSG" / "scripts")
            if vendor not in sys.path:
                sys.path.insert(0, vendor)
            from briarmbg import BriaRMBG
            path = root / config["model"]["triposg"]["rmbg_dir"]
            device = config["model"]["triposg"].get("device", "cuda")
            model = BriaRMBG.from_pretrained(str(path)).to(device).eval()
            try:
                rgb = np.asarray(image.convert("RGB").resize((1024, 1024)), dtype=np.float32) / 255
                tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(device) - .5
                with torch.inference_mode():
                    prediction = model(tensor)[0][0]
                    prediction = F.interpolate(prediction.unsqueeze(0) if prediction.ndim == 3 else prediction,
                                               size=(image.height, image.width), mode="bilinear", align_corners=False)
                    mask = prediction.squeeze().float().cpu().numpy()
                mask = (mask - mask.min()) / max(float(mask.max() - mask.min()), 1e-8)
                image.putalpha(Image.fromarray((mask * 255).astype("uint8")))
                actual = f"BRIA RMBG-1.4 · {device}"
            finally:
                del model
    return image, actual


def prepare(image, options: Preparation, root: Path, config: dict):
    image, actual = isolate(image, options, root, config)
    # Square padding retains the alpha master even when the display is composited.
    side = max(image.size)
    padded_side = max(side, round(side * (1 + 2 * options.margin)))
    canvas = Image.new("RGBA", (padded_side, padded_side), (255, 255, 255, 0))
    canvas.paste(image, ((padded_side-image.width)//2, (padded_side-image.height)//2))
    prepared = canvas.resize((options.size, options.size), Image.Resampling.LANCZOS)
    from .input_readiness import mask_metrics
    quality=mask_metrics(prepared)
    if quality["foreground_fraction"]==0:raise ValueError("Background preparation removed the entire foreground; inspect the mask before inference.")
    return prepared, prepared.getchannel("A"), {"requested": options.to_dict(), "actual": actual,
                                               "size": list(prepared.size),"mask_quality":quality}
