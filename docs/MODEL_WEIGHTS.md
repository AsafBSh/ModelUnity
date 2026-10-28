# Optional model weights

Version 1.11.2 keeps the integrations but excludes AI checkpoints from Git. The
2026-10-28 cleanup removed project weights, including named shared Hugging Face
cache folders. Code, runtimes, native modules and user assets remain installed.
Other applications sharing those cache folders must download the same weights
again. Unrelated Faster Whisper data was retained.

Without weights, launch the GUI and use existing-mesh inspection, manual alpha
correction, CPU optimization, UV rebaking of existing maps, scaling and export.
Generation, painting, learned background removal and AI normals need restoration.
A fresh Git clone additionally needs [DEVELOPMENT.md](DEVELOPMENT.md).

Run only the downloads you need, from the root in PowerShell with the main venv
installed. Review upstream licenses. These commands require network access and
disk space; cleanup did not run them.

## TripoSG

About 7.40 GiB logical including its VAE and image encoder:

```powershell
.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('VAST-AI/TripoSG', local_dir='pretrained_weights/TripoSG')"
```

## Hunyuan3D 2mv

The configured wrapper uses FP16 safetensors, about 4.59 GiB. The removed cache
also had a 4.59 GiB .ckpt copy; do not download both for this configuration.

```powershell
.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('tencent/Hunyuan3D-2mv', allow_patterns=['hunyuan3d-dit-v2-mv/config.yaml','hunyuan3d-dit-v2-mv/model.fp16.safetensors'])"
```

If config.yaml changes, use its actual model repository/subfolder/variant.

## Hunyuan Paint

The old Paint folder was about 6.41 GiB logical; DINOv2 giant adds 4.23 GiB.
RealESRGAN adds about 64 MiB. NVIDIA CUDA and native paint extensions are separate
requirements. Keep low-VRAM mode on for the 12 GB validation GPU.

```powershell
.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('tencent/Hunyuan3D-2.1', allow_patterns=['hunyuan3d-paintpbr-v2-1/*']); snapshot_download('facebook/dinov2-giant', allow_patterns=['config.json','preprocessor_config.json','model.safetensors'])"
New-Item -ItemType Directory -Force vendor/Hunyuan3D-2.1/hy3dpaint/ckpt
Invoke-WebRequest -Uri 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth' -OutFile 'vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth'
```

On a fresh machine build the native extensions with compatible MSVC/CUDA tools;
Git excludes machine-specific binaries. See [DEVELOPMENT.md](DEVELOPMENT.md).

## Background removal

Keep alpha and manual correction need no learned remover. Restore BRIA RMBG:

```powershell
.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('briaai/RMBG-1.4', local_dir='pretrained_weights/RMBG-1.4')"
```

Download rembg U2Net without processing an image:

```powershell
.venv/Scripts/python.exe -c "from rembg import new_session; new_session('u2net', providers=['CPUExecutionProvider'])"
```

Other GUI rembg choices have separate downloads. The main environment currently
has CPU onnxruntime; selecting CUDA does not install a GPU ONNX provider.

## TRELLIS 2 and Pixal3D

For the retained isolated runtime:

```powershell
.venv/Scripts/python.exe -m scripts.comfyui_host download --model trellis
# Alternatives: pixal, pixal-mv, all
```

For a fresh clone use `setup --model trellis` instead. Shared VAEs and vision
models are downloaded once. Automatic Pixal FOV adds MoGe. Previous logical sizes
were about 7.93 GiB for TRELLIS/common models, or 18.95 GiB for all variants/support
models, plus the separate runtime and installation working space.

```powershell
.venv/Scripts/python.exe -m scripts.comfyui_host plan --model trellis
.venv/Scripts/python.exe -m scripts.comfyui_host start
.venv/Scripts/python.exe -m scripts.comfyui_host status --model trellis
```

`plan` is read-only. Status checks the running host's nodes and exact checkpoints;
a stopped host alone does not establish whether weights exist. The GUI Check
model action serves the selected workflow. Keep this runtime separate from the
main venv. Original research stacks are Linux-first; this Windows integration
uses ComfyUI native nodes and NVIDIA CUDA. See [COMFYUI.md](COMFYUI.md).

## Normal maps

Low geometry normals need no weights. High Marigold previously used about 2.40 GiB:

```powershell
.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('prs-eth/marigold-normals-v1-1', allow_patterns=['model_index.json','scheduler/*','tokenizer/*','text_encoder/config.json','text_encoder/model.fp16.safetensors','unet/config.json','unet/diffusion_pytorch_model.fp16.safetensors','vae/config.json','vae/diffusion_pytorch_model.fp16.safetensors'])"
```

Medium StableNormal downloads code/weights via torch.hub on first actual use;
it was not present in the default cache. AI normal jobs can fall back to Low;
inspect the actual-baker report.

## Offline checks

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
.venv/Scripts/python.exe -m scripts.launch_workbench --check
.venv/Scripts/python.exe -m scripts.workbench_preview --check
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
```

Unset those environment variables before deliberate model downloads. These checks
verify the app and CPU tools, not inference without checkpoints. The environment
check with `--require-paint` should report the deliberately absent RealESRGAN file
until restored. Native backends may download on first use; Comfy never installs
models implicitly during Generate.
