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

import trimesh
import pymeshlab


def remesh_mesh(mesh_path, remesh_path):
    mesh = mesh_simplify_trimesh(mesh_path, remesh_path)


def mesh_simplify_trimesh(inputpath, outputpath, target_count=40000):
    # 1) Pre-cleanup via pymeshlab BEFORE decimation - removes floating
    #    marching-cubes droplets, duplicate / null faces, etc. Without this,
    #    fast_simplification produces "shredded" / chipped meshes (visible
    #    as little holes and triangular gaps all over the painted surface).
    ms = pymeshlab.MeshSet()
    if inputpath.endswith(".glb"):
        ms.load_new_mesh(inputpath, load_in_a_single_layer=True)
    else:
        ms.load_new_mesh(inputpath)
    # Drop tiny disconnected polygon islands (5% of bbox diagonal).
    try:
        ms.meshing_remove_connected_component_by_diameter(
            mincomponentdiag=pymeshlab.PercentageValue(5.0))
    except Exception:
        try:
            ms.meshing_remove_connected_component_by_diameter(
                mincomponentdiag=pymeshlab.Percentage(5.0))
        except Exception:
            pass
    for _filt in ("meshing_remove_duplicate_vertices",
                  "meshing_remove_duplicate_faces",
                  "meshing_remove_null_faces",
                  "meshing_remove_unreferenced_vertices",
                  "meshing_merge_close_vertices"):
        try: getattr(ms, _filt)()
        except Exception: pass
    ms.save_current_mesh(outputpath.replace(".glb", ".obj"), save_textures=False)

    # 2) Decimate with low aggression for cleaner topology.
    #    Default aggression=7 punches through thin walls and creates chips.
    #    aggression=3 is much more conservative; with the pre-cleanup above
    #    the painted surface comes out smooth.
    courent = trimesh.load(outputpath.replace(".glb", ".obj"), force="mesh")
    face_num = courent.faces.shape[0]

    if face_num > target_count:
        try:
            courent = courent.simplify_quadric_decimation(
                face_count=target_count, aggression=3)
        except TypeError:
            # Older trimesh: no aggression kwarg.
            try:
                courent = courent.simplify_quadric_decimation(face_count=target_count)
            except TypeError:
                courent = courent.simplify_quadric_decimation(target_count)
    courent.export(outputpath)
