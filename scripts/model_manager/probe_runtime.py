"""Read-only subprocess probes. Never load weights or perform inference."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=('comfy','paint'))
    parser.add_argument('report')
    args=parser.parse_args()
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    if not torch.cuda.is_available():raise RuntimeError('NVIDIA CUDA is unavailable in this environment. Check the driver and installed Torch runtime.')
    report={'kind':args.kind,'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'ready':True}
    if args.kind=='paint':
        from scripts.engine_paint import rasterizer_ready
        if not rasterizer_ready():raise RuntimeError('The native paint rasterizer cannot be imported. Build extensions with compatible MSVC/CUDA tools.')
        from textureGenPipeline import Hunyuan3DPaintPipeline
        from hunyuanpaintpbr import HunyuanPaint
        from realesrgan import RealESRGANer
        report['paint_modules']=True
    path=Path(args.report)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
