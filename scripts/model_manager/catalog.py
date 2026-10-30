"""The application model catalog. Importing this module never contacts a server."""
from dataclasses import dataclass
from fnmatch import fnmatchcase


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    group: str
    description: str
    repo: str = ''
    patterns: tuple = ('*',)
    required: tuple = ()
    dependencies: tuple = ()
    estimated_bytes: int = 0
    runtime: str = 'shape'
    revision: str = 'main'
    url: str = ''
    filename: str = ''
    checksum: str = ''
    source: str = 'hf'
    download_bytes: int | None = None

    @property
    def license_url(self):
        if self.source == 'hf':
            return 'https://huggingface.co/' + self.repo
        if self.key.startswith('rembg-'):
            return 'https://github.com/danielgatis/rembg#models'
        if self.key == 'realesrgan':
            return 'https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE'
        return 'https://github.com/' + self.repo

    def includes(self, name):
        return any(fnmatchcase(name, pattern) for pattern in self.patterns)


def catalog(config):
    hunyuan = config.get('model', {}).get('hunyuan', {})
    sub = hunyuan.get('subfolder', 'hunyuan3d-dit-v2-mv')
    variant = '.' + hunyuan.get('variant','fp16') if hunyuan.get('variant','fp16') else ''
    models = [
        Model('triposg', 'TripoSG 1.5B', 'Generate', 'Single image to static geometry; optional planar projection.',
              'VAST-AI/TripoSG', required=('model_index.json', 'transformer/*.safetensors', 'vae/*.safetensors', 'image_encoder_dinov2/*.safetensors'),
              estimated_bytes=7945689498),
        Model('hunyuan', 'Hunyuan3D-2mv', 'Generate', 'One to four named directions to geometry. PBR painting is separate.',
              hunyuan.get('model_repo', 'tencent/Hunyuan3D-2mv'),
              patterns=(f'{sub}/config.yaml', f'{sub}/model{variant}.safetensors'),
              required=(f'{sub}/config.yaml', f'{sub}/model{variant}.safetensors'), estimated_bytes=4928474972),
        Model('paint', 'Hunyuan3D-2.1 Paint', 'Texture', 'Mesh plus reference image to PBR. Requires NVIDIA CUDA and native paint extensions.',
              'tencent/Hunyuan3D-2.1', patterns=('hunyuan3d-paintpbr-v2-1/*',),
              required=('hunyuan3d-paintpbr-v2-1/model_index.json', 'hunyuan3d-paintpbr-v2-1/unet/*.bin', 'hunyuan3d-paintpbr-v2-1/vae/*.bin'),
              dependencies=('dinov2', 'realesrgan'), estimated_bytes=6882689024, runtime='paint'),
        Model('dinov2', 'DINOv2 giant · Paint support', 'Support', 'Shared image encoder used by the paint pipeline.',
              'facebook/dinov2-giant', patterns=('config.json', 'preprocessor_config.json', 'model.safetensors'),
              required=('config.json', 'preprocessor_config.json', 'model.safetensors'), estimated_bytes=4541927916, runtime='none'),
        Model('rmbg', 'BRIA RMBG-1.4', 'Prepare', 'Learned background removal. Review the upstream model terms.',
              'briaai/RMBG-1.4', patterns=('config.json', 'model.safetensors'), required=('config.json', 'model.safetensors'),
              estimated_bytes=176000000, runtime='shape'),
        Model('marigold', 'Marigold normals · High', 'Normals', 'Image-based normal estimation; geometry normals need no model.',
              'prs-eth/marigold-normals-v1-1', patterns=('model_index.json', 'scheduler/*', 'tokenizer/*', '*/config.json', '*/*.fp16.safetensors'),
              required=('model_index.json', 'unet/*.fp16.safetensors', 'vae/*.fp16.safetensors', 'text_encoder/*.fp16.safetensors'),
              estimated_bytes=2576980378, runtime='shape'),
        Model('stablenormal', 'StableNormal turbo · Medium', 'Normals', 'Image-based normals with explicitly installed, pinned upstream Python code.',
              'Stable-X/yoso-normal-v0-3', required=('model_index.json', 'unet/*.fp16.safetensors', 'vae/*.fp16.safetensors', 'controlnet/*.fp16.safetensors'),
              dependencies=('stablenormal-code',), estimated_bytes=3000000000, runtime='shape'),
        Model('stablenormal-code', 'StableNormal · source code', 'Support', 'Upstream Python code executed only when the normal estimator runs.',
              'Stable-X/StableNormal', required=('hubconf.py',), runtime='none', source='github',
              revision='594b934630ab3bc71f35c77d14ec7feb98480cd0', estimated_bytes=12000000),
        Model('realesrgan', 'RealESRGAN x4plus · Paint support', 'Support', 'Image upscaler checkpoint used by Hunyuan Paint.',
              url='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
              filename='RealESRGAN_x4plus.pth', required=('RealESRGAN_x4plus.pth',), source='url', runtime='none',
              revision='v0.1.0',estimated_bytes=67040989,download_bytes=67040989),
    ]
    rembg = [('u2net', '60024c5c889badc19c04ad937298a77b', 176000000),
             ('u2netp', '8e83ca70e441ab06c318d82300c84806', 5000000),
             ('isnet-general-use', 'fc16ebd8b0c10d971d3513d564d01e29', 179000000),
             ('silueta', '55e59e0d8062d2f5d013f4725ee84782', 44000000)]
    for name, md5, size in rembg:
        models.append(Model('rembg-' + name, 'rembg · ' + name, 'Prepare', 'ONNX background removal; CPU provider works without NVIDIA.',
            url=f'https://github.com/danielgatis/rembg/releases/download/v0.0.0/{name}.onnx', filename=name + '.onnx',
            required=(name + '.onnx',), checksum='md5:' + md5, source='url', runtime='onnx', revision='v0.0.0', estimated_bytes=size))
    from scripts.comfyui_workflows import WEIGHTS
    from scripts.comfyui_install import SIZES
    # Default names also feed the Comfy node selectors; custom names stay explicit.
    common = ('comfy-shape_vae', 'comfy-vision')
    for key in ('trellis', 'pixal', 'pixal_mv', 'shape_vae', 'texture_vae', 'vision', 'moge'):
        group = 'Generate' if key in ('trellis', 'pixal', 'pixal_mv') else 'Support'
        folder = 'diffusion_models' if group == 'Generate' else 'clip_vision' if key == 'vision' else 'geometry_estimation' if key == 'moge' else 'vae'
        repo = 'Comfy-Org/TRELLIS.2' if key == 'trellis' else 'Comfy-Org/MoGe' if key == 'moge' else 'Comfy-Org/Pixal3D'
        filename = config.get('model', {}).get('comfyui', {}).get('weights', {}).get(key, WEIGHTS[key])
        label = {'trellis': 'TRELLIS.2 · ComfyUI', 'pixal': 'Pixal3D · single view', 'pixal_mv': 'Pixal3D · fixed-orbit multiview'}.get(key, 'ComfyUI · ' + key.replace('_', ' '))
        models.append(Model('comfy-' + key, label, group,
            'Windows / NVIDIA native ComfyUI integration. Original research stacks are Linux-first. Multiview uses separate fixed-orbit weights.' if group == 'Generate' else 'Shared ComfyUI support checkpoint.',
            repo, patterns=(folder + '/' + filename,), required=(folder + '/' + filename,),
            dependencies=common if group == 'Generate' else (), runtime='comfy' if group == 'Generate' else 'none', estimated_bytes=SIZES[key]))
    return {m.key: m for m in models}


def required_models(stage, settings, images=None):
    """Exact selected workflow dependencies, without adding unused removers."""
    keys = []
    if stage == 'Generate':
        backend = settings.get('backend', 'Hunyuan3D-2mv')
        keys.append({'TripoSG 1.5B': 'triposg', 'Hunyuan3D-2mv': 'hunyuan',
                     'TRELLIS.2 · ComfyUI': 'comfy-trellis', 'Pixal3D · ComfyUI': 'comfy-pixal_mv' if settings.get('c_multiview') else 'comfy-pixal'}[backend])
        if backend == 'Pixal3D · ComfyUI' and not settings.get('c_multiview') and settings.get('c_auto_fov', True):
            keys.append('comfy-moge')
        if backend in ('TRELLIS.2 · ComfyUI','Pixal3D · ComfyUI') and settings.get('c_texture',True):
            keys.append('comfy-texture_vae')
        if backend == 'Hunyuan3D-2mv' and settings.get('m_paint'):
            keys.append('paint')
    if stage in ('Generate', 'Prepare'):
        prep = settings.get('preparation', {})
        provider = prep.get('provider', 'none')
        if images is not None:
            from PIL import Image
            selected = list(images.values())
            if stage == 'Generate' and (settings.get('backend') in ('TripoSG 1.5B','TRELLIS.2 · ComfyUI') or
                    settings.get('backend') == 'Pixal3D · ComfyUI' and not settings.get('c_multiview')):
                selected = [images.get('front')]
            elif stage == 'Generate': selected = [images.get(k) for k in ('front','left','back','right')]
            elif stage == 'Prepare': selected = [images.get(settings.get('prep_view','Front').lower())]
            def preserved(value):
                if value is None: return True
                image=value.copy() if isinstance(value,Image.Image) else Image.open(value)
                try:
                    if prep.get('manual_alpha_digests'):
                        from scripts.workbench.mask_edit import image_digest
                        if image_digest(image) in prep['manual_alpha_digests']:return True
                    if not prep.get('preserve_alpha',True):return False
                    if prep.get('crop','').strip():image=image.crop(tuple(map(int,prep['crop'].split(','))))
                    return image.convert('RGBA').getchannel('A').getextrema()[0] < 255
                finally:image.close()
            if all(preserved(value) for value in selected): provider = 'none'
        if provider == 'rmbg': keys.append('rmbg')
        if provider == 'rembg': keys.append('rembg-' + prep.get('model', 'u2net'))
    if stage == 'Texture': keys.append('paint')
    normal = settings.get('surface', {}).get('normal', 'low') if stage == 'Surface' else settings.get('normal', 'off')
    needs_normal = stage in ('Texture', 'Export', 'Surface') or (stage == 'Generate' and settings.get('m_paint'))
    if needs_normal and normal in ('medium', 'high'):
        keys.append('stablenormal' if normal == 'medium' else 'marigold')
    return list(dict.fromkeys(keys))
