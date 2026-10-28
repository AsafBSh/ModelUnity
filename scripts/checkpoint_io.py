"""Scoped Windows workaround for large DINO safetensors Torch-storage mappings."""
from contextlib import contextmanager
import sys

def numpy_checkpoint(filename):
    """Read unchanged F16/F32 tensors through the supported NumPy backend."""
    import torch
    from safetensors import safe_open
    with safe_open(filename,framework="numpy") as stream:
        return {key:torch.from_numpy(stream.get_tensor(key)) for key in stream.keys()}

@contextmanager
def windows_dino_checkpoint_io(enabled=True):
    if not enabled or sys.platform!="win32":
        yield
        return
    import transformers.modeling_utils as module
    original=module.safe_load_file
    def load(filename,device="cpu",**kwargs):
        if "dinov2" in str(filename).lower() and str(device)=="cpu":
            print("[checkpoint] Reading DINO weights through NumPy (Windows mmap workaround)",flush=True)
            return numpy_checkpoint(filename)
        return original(filename,device=device,**kwargs)
    module.safe_load_file=load
    try:yield
    finally:module.safe_load_file=original
