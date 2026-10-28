"""Manual alpha corrections bound to exact image pixels, never to a filename."""
import hashlib
import numpy as np
from PIL import Image


def image_digest(image):
    rgba = image.convert('RGBA')
    return hashlib.sha256(str(rgba.size).encode() + rgba.tobytes()).hexdigest()


def apply_strokes(editor):
    if not editor or editor.get('background') is None:
        raise ValueError('Load a reference into the mask editor first.')
    image = editor['background'].convert('RGBA').copy()
    alpha = np.array(image.getchannel('A'), dtype=np.float32)
    for layer in editor.get('layers', []):
        layer = layer.convert('RGBA')
        if layer.size != image.size:
            raise ValueError('Mask strokes must match the reference dimensions.')
        pixels = np.asarray(layer, dtype=np.float32)
        opacity = pixels[..., 3] / 255
        value = np.where(pixels[..., :3].mean(axis=2) >= 128, 255., 0.)
        alpha = alpha * (1-opacity) + value * opacity
    image.putalpha(Image.fromarray(np.rint(alpha).astype('uint8')))
    if image.getchannel('A').getextrema()[1] == 0:
        raise ValueError('The corrected mask is empty; restore some foreground.')
    return image
