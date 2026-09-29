import os
import re
import zipfile
import bpy
from typing import List, Optional, Sequence, Union, Any, Dict
from pathlib import Path

from .mesh_animation import setup_mesh_animation
from .volume_animation import setup_volume_animation
from ..Backend.save_load_hdf5 import load, get_summary

def _infer_vdb_object_name(vdb_dir: str) -> Optional[str]:
    """
    Recover the `object_name` used at export time by parsing it back out of
    a .vdb filename, instead of trusting the containing folder's name (which
    may just be a generic output/zip folder unrelated to the object -- e.g.
    "Output" or "Output.zip" -> extracted "Output/").

    Handles both filename conventions grid_to_vdb produces:
      - "{object_name}_frame{frame_number}.vdb"                      (single-block / particle case)
      - "{object_name}_frame{frame_number}_l{level}_b{block_id}.vdb"  (AMR hierarchy case, from
                                                     hierarchy_to_multiple_vdbs)

    Searches the first directory level (flat layout, or the first frame_*/
    subfolder for partitioned layout) that actually contains .vdb files.
    Returns None if no .vdb files are found anywhere under vdb_dir.
    """
    candidates = []
    for root, dirs, files in os.walk(vdb_dir):
        candidates = [f for f in files if f.lower().endswith(".vdb")]
        if candidates:
            break  # first level with any .vdb files is enough -- naming is consistent per export

    if not candidates:
        return None

    stem = os.path.splitext(sorted(candidates)[0])[0]
    match = re.match(r"^(.*)_l\d+_b\d+$", stem)
    return match.group(1) if match else stem

def resolve_and_scan_dataset(data_path: str) -> Dict[str, Any]:
    def _extract_zip(zip_path: str) -> str:
        extract_dir = zip_path[:-4] if zip_path.lower().endswith(".zip") else zip_path
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    member_parts = member.filename.split('/', 1)
                    if len(member_parts) <= 1 or not member_parts[1]:
                        continue
                    member.filename = member_parts[1]
                    zip_ref.extract(member, extract_dir)
            print(f"Extracted contents of '{zip_path}' directly to '{extract_dir}'")
        return os.path.abspath(extract_dir)

    hdf5_files_path = []
    vdb_dirs_path = []
    scan_dir = None

    if os.path.isfile(data_path):
        if data_path.lower().endswith(".zip"):
            scan_dir = _extract_zip(data_path)
            vdb_dirs_path.append(scan_dir)          
            print(f"Found one VDB zip archive: {os.path.abspath(data_path)} -> extracted to {scan_dir}")
        elif data_path.lower().endswith((".h5", ".hdf5")):
            scan_dir = os.path.abspath(os.path.dirname(data_path))
            hdf5_files_path.append(os.path.abspath(data_path))
            print(f"Found one HDF5 file: {os.path.abspath(data_path)}")
        else:
            raise ValueError(f"Unsupported file type: {data_path}")

    elif os.path.isdir(data_path):
        scan_dir = os.path.abspath(data_path)
        for root, dirs, files in os.walk(scan_dir):
            if Path(root).name.startswith("frame_"):
                continue
            
            ## If root is one vdb object
            if any(d.lower().startswith("frame_") for d in dirs) or any(f.lower().endswith(".vdb") for f in files):
                vdb_dirs_path.append(os.path.abspath(root))
                print(f"Found one VDB dir: {os.path.abspath(root)}")
                continue
            
            ## If root contains .h5/.hdf5 files or .zip archives, add them to the list
            for file in files:
                if file.lower().endswith((".h5", ".hdf5")):
                    hdf5_files_path.append(os.path.abspath(os.path.join(root, file)))
                    print(f"Found one HDF5 file: {os.path.abspath(os.path.join(root, file))}")
                if file.lower().endswith(".zip"):
                    vdb_dirs_path.append(_extract_zip(os.path.join(root, file)))
                    print(f"Found one VDB zip archive: {os.path.abspath(os.path.join(root, file))} -> extracted to {vdb_dirs_path[-1]}")

            ## If root stored multiple vdb objects in subfolders, check subfolders for vdb files
            for d in dirs:
                if d.lower().startswith("frame_"):
                    continue  # skip frame_* subfolders, they are part of a vdb object already found
                dir_path = os.path.join(root, d)
                entries = os.listdir(dir_path)
                if any(f.lower().endswith(".vdb") for f in entries) or any(f.lower().startswith("frame_") for f in entries):
                    vdb_dirs_path.append(os.path.abspath(dir_path))
                    print(f"Found one VDB dir: {os.path.abspath(dir_path)}")

    else:
        raise ValueError(f"Path does not exist: {data_path}")

    return {
        "scan_dir": scan_dir,
        "hdf5_files_path": hdf5_files_path,
        "vdb_dirs_path": vdb_dirs_path,
    }


def setup_animation(
    data_path: str,
    object_material: Optional[Dict[str, Union[bpy.types.Material, None]]] = None,
    scale=None,
    target_size= 200,
    center=False,
    start_frame: int = 0,
    end_frame: int = None,
    suppress_vdb_warnings: bool = True,
):
    """
    Scan `data_path` for animation data and set it up in Blender.

    `data_path` accepts:
      - a single .zip file (a VDB export archive) 
      - a single .h5/.hdf5 file (from save()) -- loaded directly; its parent
        folder is still checked for a VDB sequence alongside it, since both
        commonly come from the same export run, but no other .hdf5 files in
        that folder are loaded
      - a folder that may contain any combination of 
        - one or more .h5/.hdf5 files 
        - VDB sequence (flat *.vdb files or frame_* subfolders of .vdb partitions)
        - .zip archives of a VDB export 


    Parameters
    ----------
    data_path : str
    object_material : dict, optional
        Mapping from object names to bpy.types.Material (or None). 
        Material is compulsory for VDB sequence, optional for HDF5.
    scale, target_size, center :
        [HDF5 only] Forwarded to `setup_mesh_animation` for every object.
    suppress_vdb_warnings : bool
        [VDB only] Hide Blender/OpenVDB terminal warnings during scripted import.
    Returns
    -------
    dict
        {
            "mesh": {object_name: bpy.types.Object, ...},
            "volume": {object_name: bpy.types.Object, ...}  
        }
    """
    all_object_names = object_material.keys() if object_material is not None else None
    
    scan_result = resolve_and_scan_dataset(data_path)
    hdf5_files = scan_result["hdf5_files_path"]
    vdb_folders = scan_result["vdb_dirs_path"]

    if not hdf5_files and not vdb_folders:
        raise ValueError(f"No .h5/.hdf5 files or .vdb sequence found under: {data_path}")

    print(f"\n{'='*50}")
    print(f"Scanning animation data: {data_path}")
    if hdf5_files:
        print(f"  HDF5 files found: {hdf5_files}")
        print(f"  HDF5 summary:")
        for hdf5_file in hdf5_files:
            summary = get_summary(hdf5_file)
            print(f"    {hdf5_file}:")
            for object_name, object_summary in summary.items():
                print(f"      {object_name}: {object_summary}")
    if vdb_folders:
        print(f"  VDB sequence found: {vdb_folders}")
    print(f"{'='*50}")

    results = {"mesh": {}, "volume": []}

    # --- HDF5 -> mesh/particle/surface animation ---
    for hdf5_file in hdf5_files:
        
        print(f"\nSetting up mesh animation from HDF5 file: {Path(hdf5_file).name}")
        data = load(hdf5_file, object_names=all_object_names)

        if scale is None and target_size is not None:
            max_size = max(
                max(frame.vertices.max(axis=0) - frame.vertices.min(axis=0))
                for frames in data.values()
                for frame in frames
            )
            scale = target_size / max_size if max_size > 0 else 1.0
            print(f"Auto-calculated scale factor: {scale} (target size: {target_size}, max object size after scale: {max_size*scale})")
        elif scale is not None:
            print(f"Using provided scale factor: {scale}")

        for object_name, frames_data in data.items():
            if object_name in results["mesh"]:
                print(f"  Warning: object '{object_name}' already set up from another HDF5 file; overwriting.")

            obj = setup_mesh_animation(
                frames_data,
                object=object_name,
                scale=scale,
                target_size=None,
                center=center,
                start_frame = start_frame,
                end_frame = end_frame,
                material=object_material.get(object_name) if object_material is not None else None,
            )
            results["mesh"][object_name] = obj

    # --- VDB -> volume animation ---
    if vdb_folders:
        for vdb_dir in vdb_folders:

            folder_name = Path(vdb_dir).name
            object_name = _infer_vdb_object_name(vdb_dir)
            if object_name is None:
                print(f"  [WARN] Could not parse an object_name from any .vdb filename in "
                      f"'{folder_name}' -- falling back to folder name.")
                object_name = folder_name

            print(f"Setting up volume animation from VDB sequence in: {folder_name} "
                  f"(resolved object_name='{object_name}')")
            setup_volume_animation(
                vdb_dir,
                object_name=object_name,
                material=object_material.get(object_name) if object_material is not None else None,
                suppress_vdb_warnings=suppress_vdb_warnings,
                start_frame=start_frame,
                end_frame=end_frame,
            )
            results["volume"].append(object_name)
            if scale is not None or target_size is not None or center:
                print(f"  [WARN] scale/target_size/center parameters are ignored for VDB sequence '{object_name}'")

    return results