from .mesh_animation import setup_mesh_animation
from ..Backend.particle_data import load_particles
from ..Backend.save_load_npz import load
import glob
import os
import bpy
import yt

def resolve_file_paths(file_paths, folder_path, pattern, max_files):
    if folder_path is not None and pattern is not None:
        file_paths = sorted(glob.glob(os.path.join(folder_path, pattern)))
    elif folder_path is not None and pattern is None:
        file_paths = sorted(glob.glob(os.path.join(folder_path, "*")))
    elif file_paths is not None:
        if isinstance(file_paths, str):
            file_paths = [file_paths]
    else:
        raise ValueError("Either input file paths or folder_path + pattern or folder_path alone.")
      
    if not file_paths:
        raise ValueError("No files found with the given input")
    
    if max_files is not None:
        file_paths = file_paths[:max_files]
    
    return file_paths

def load_particles_into_blender(
    ptype: str,
    fields=None, 
    region=None,
    
    object_name: str = 'Star',
    file_paths: str = None,
    folder_path: str = None,
    pattern: str = None,
    max_files: int = None,
    
    obj: bpy.types.Object = None,
    position_scale=1.0,
    center=True
    ):
    """
    A high level function to load particle data from yt datasets and create animated particle object in Blender.
    Parameters
    ----------
    ptype : str
        Particle type name (e.g., 'stars', 'dark_matter', 'PartType0')
    fields : list of str
        Fields to extract (e.g., ['mass', 'temperature'])
    region : yt object or None
        A region (sphere, box) to subset particles
    object_name : str
        Name of the Blender object to create
    file_paths : list of str or str or None
        List of yt dataset file paths to load
    folder_path : str or None  
        Folder path to search for dataset files
    pattern : str or None
        Filename pattern to match within folder_path (e.g., "*.h5")
    max_files : int or None
        Maximum number of files to load
    obj : bpy.types.Object or None
        Existing Blender object to use for particle mesh
    position_scale : float
        Scale factor for particle positions
    center : bool
        Whether to subtract center-of-mass per frame
    
    Returns
    -------
    frames_data : list of dict
        List of particle data per frame, each as output of particle_data:
        particle_data = dict
        {
            "positions": np.ndarray (N,3),
            "fields": {field_name: np.ndarray},
            "time": dataset time in code units
            "units": {"length": (numerical value, unit), "mass": ..., "time": ...}
        }
    """

    file_paths = resolve_file_paths(file_paths, folder_path, pattern, max_files)
    
    frames_data = []
    for fpath in file_paths:
        data = yt.load(fpath)
        frames_data.append(load_particles(data, ptype=ptype, fields = fields, region=region))
        
    setup_mesh_animation(frames_data = frames_data, object_name = object_name, obj= obj, position_scale = position_scale, center = center)
    
    return frames_data

def load_npz_into_blender(
    file_path: str,
    position_scale=1.0,
    center = True
):
    data = load(file_path)
    for obj_name, frames_data in {**data["Particles"], **data["Surface"]}.items():
        setup_mesh_animation(frames_data=frames_data, object_name=obj_name, position_scale=position_scale, center=center)
    for obj_name, frames_data in data["Volume"].items():
        continue 
    


        