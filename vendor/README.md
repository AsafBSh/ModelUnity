# Vendored inference source

These ordinary source snapshots preserve local Windows patches and upstream
licenses. Downloaded weights, nested Git histories, native builds and large
upstream demo/research media are excluded. They are not unpatched submodules.

- TripoSG: https://github.com/VAST-AI-Research/TripoSG
  at `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c`.
  Local patch: `triposg/inference_utils.py`.
- Hunyuan3D-2: https://github.com/Tencent/Hunyuan3D-2
  at `f8db63096c8282cb27354314d896feba5ba6ff8a`.
  Existing source checkout was clean at initial publication.
- Hunyuan3D-2.1: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
  at `82920d643c0dc2f7bfd7255f45f62d386edfe60c`.
  Local patches: paint pipeline; DifferentiableRenderer mesh utilities/inpaint C++
  and setup.py; rasterizer C++/CUDA/setup.py/build_ext.bat; simplification.

Keep the actual upstream licenses and notices with these files. This source
upload grants no replacement license for upstream models, assets or training data.
