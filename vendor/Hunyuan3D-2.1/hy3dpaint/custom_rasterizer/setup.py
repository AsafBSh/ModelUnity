# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

# For avoidance of doubts, Hunyuan 3D means the large language models and
# their software and algorithms, including trained model weights, parameters (including
# optimizer states), machine-learning model code, inference-enabling code, training-enabling code,
# fine-tuning enabling code and other elements of the foregoing made publicly available
# by Tencent in accordance with TENCENT HUNYUAN COMMUNITY LICENSE AGREEMENT.

import os
from setuptools import setup, find_packages
import torch
from torch.utils.cpp_extension import BuildExtension, CUDAExtension

# Windows MSVC + CUDA 12.x compatibility fixes (lzz19980125 / PR#79)
if os.name == "nt":
    extra_compile_args = {
        "cxx": [
            "/wd4838",
            "/wd4244",
            "/wd4267",
            "/wd4996",
            "/D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH",
            "/std:c++17",
        ],
        "nvcc": [
            "-allow-unsupported-compiler",
            "-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH",
        ],
    }
    cmdclass = {"build_ext": BuildExtension.with_options(use_ninja=False)}
else:
    extra_compile_args = {"cxx": ["-O3", "-std=c++17"], "nvcc": []}
    cmdclass = {"build_ext": BuildExtension}

custom_rasterizer_module = CUDAExtension(
    "custom_rasterizer_kernel",
    [
        "lib/custom_rasterizer_kernel/rasterizer.cpp",
        "lib/custom_rasterizer_kernel/grid_neighbor.cpp",
        "lib/custom_rasterizer_kernel/rasterizer_gpu.cu",
    ],
    extra_compile_args=extra_compile_args,
)

setup(
    packages=find_packages(),
    version="0.1",
    name="custom_rasterizer",
    include_package_data=True,
    package_dir={"": "."},
    ext_modules=[custom_rasterizer_module],
    cmdclass=cmdclass,
)
