import os
from setuptools import setup
from torch.utils.cpp_extension import BuildExtension, CppExtension

if os.name == "nt":
    extra_compile_args = [
        "/O2", "/std:c++14", "/EHsc", "/MP", "/bigobj",
        "/wd4838", "/wd4244", "/wd4267", "/wd4996",
        "/D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH",
    ]
    cmdclass = {"build_ext": BuildExtension.with_options(use_ninja=False)}
else:
    extra_compile_args = ["-O3", "-std=c++14", "-fPIC", "-pthread"]
    cmdclass = {"build_ext": BuildExtension}

setup(
    name="mesh_inpaint_processor",
    version="0.0.0",
    ext_modules=[
        CppExtension(
            "mesh_inpaint_processor",
            sources=["mesh_inpaint_processor.cpp"],
            extra_compile_args=extra_compile_args,
        )
    ],
    cmdclass=cmdclass,
)
