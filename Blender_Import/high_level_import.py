import os
import bpy
from typing import List, Optional

from .mesh_animation import setup_mesh_animation
from .volume_animation import setup_volume_animation
from ..Backend.save_load_hdf5 import load, get_summary


def _find_hdf5_files(data_path: str) -> List[str]:
    return sorted(
        f for f in os.listdir(data_path)
        if os.path.isfile(os.path.join(data_path, f)) and f.lower().endswith((".h5", ".hdf5"))
    )


def _has_vdb_sequence(data_path: str) -> bool:
    """True if `data_path` contains a flat .vdb sequence or frame_* subfolders of .vdb files."""
    if any(f.endswith(".vdb") for f in os.listdir(data_path)):
        return True

    for d in os.listdir(data_path):
        sub = os.path.join(data_path, d)
        if os.path.isdir(sub) and d.startswith("frame_"):
            if any(f.endswith(".vdb") for f in os.listdir(sub)):
                return True

    return False


def setup_animation(
    data_path: str,
    object: Optional[List[str]] = None,
    material: Optional[bpy.types.Material] = None,
    scale=None,
    target_size= 200,
    center=False,
):
    """
    Scan `data_path` for animation data and set it up in Blender.

    `data_path` is a folder that may contain any combination of:
      - one or more .h5/.hdf5 files (mesh/particle/surface animation), each of
        which may itself contain multiple objects
      - a VDB sequence: either .vdb files directly in the folder, or frame_*
        subfolders each containing one or more .vdb partitions per frame
        (volume animation) -- layout is auto-detected, no flag needed

    Everything found is set up; HDF5 objects and the VDB sequence (if present)
    are independent and both get processed in the same call.

    Parameters
    ----------
    data_path : str
        Folder containing the animation data described above.
    object : list of str, optional
        [HDF5] Restrict loading to these object names, applied across
        every HDF5 file found. Default: load every object in every file.
        [VDB] Used as a prefix for every created volume object.
    material : bpy.types.Material, optional
        Applied to every created object. Compulsory for VDB sequence, optional for HDF5.
    scale, target_size, center :
        [HDF5 only] Forwarded to `setup_mesh_animation` for every object.

    Returns
    -------
    dict
        {
            "mesh": {object_name: bpy.types.Object, ...},
            "volume": bool,   # True if a VDB sequence was found and set up
        }
    """
    if not os.path.isdir(data_path):
        raise FileNotFoundError(f"Path does not exist or is not a folder: {data_path}")

    hdf5_files = _find_hdf5_files(data_path)
    has_vdb = _has_vdb_sequence(data_path)

    if not hdf5_files and not has_vdb:
        raise ValueError(f"No .h5/.hdf5 files or .vdb sequence found under: {data_path}")

    print(f"\n{'='*50}")
    print(f"Scanning animation data: {data_path}")
    if hdf5_files:
        print(f"  HDF5 files found: {hdf5_files}")
        print(f"  HDF5 summary:")
        for hdf5_file in hdf5_files:
            file_path = os.path.join(data_path, hdf5_file)
            summary = get_summary(file_path)
            print(f"    {hdf5_file}:")
            for object_name, object_summary in summary.items():
                print(f"      {object_name}: {object_summary}")
    if has_vdb:
        print(f"  VDB sequence found: {has_vdb}")
    print(f"{'='*50}")

    results = {"mesh": {}, "volume": False}

    # --- HDF5 -> mesh/particle/surface animation ---
    for hdf5_file in hdf5_files:
        file_path = os.path.join(data_path, hdf5_file)
        data = load(file_path, object_names=object)

        if scale is None and target_size is not None:
            max_size = max(
                max(frame.vertices.max(axis=0) - frame.vertices.min(axis=0))
                for frames in data.values()
                for frame in frames
            )
            scale = target_size / max_size if max_size > 0 else 1.0
            print(f"Auto-calculated scale factor: {scale} (target size: {target_size}, max object size after scale: {max_size*scale})")
        
        elif scale is not None:
            print(f"Using provided scale factor: {scale}")  ## Ignore target_size if scale is provided to ensure same scale for different object
        
        
        for object_name, frames_data in data.items():
            if object_name in results["mesh"]:
                print(f"  Warning: object '{object_name}' already set up from another HDF5 file; overwriting.")

            obj = setup_mesh_animation(
                frames_data,
                object=object_name,
                scale=scale,
                target_size=None,  # Already applied to scale above
                center=center,
                material=material,
            )
            results["mesh"][object_name] = obj

    # --- VDB -> volume animation ---
    if has_vdb:
        setup_volume_animation(
            data_path,
            object = object_name[0] if object_name else "Volume",
            material=material,
        )
        results["volume"] = True

    return results