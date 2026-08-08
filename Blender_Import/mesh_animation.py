from ..Blender_Effect.object import create_object, set_object_shader
from ..Backend.particle_data import SPHParticleData
from ..Backend.surface_data import SurfaceData

from typing import Union, List, Optional
import numpy as np
import bpy


## Helper functions for mesh animation
    
_registered_handlers = {}

def remove_existing_handler(obj_name):
    old = _registered_handlers.pop(obj_name, None)
    if old is not None and old in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(old)

def particle_frame_update(frame, mesh, position_scale=1.0, center=True):
    """
    Update particle mesh per frame.
    frame : SPHParticleData
    """
    num_particles = frame.coordinates.shape[0]

    # Ensure vertices exist
    if len(mesh.vertices) != num_particles:
        mesh.clear_geometry()
        mesh.from_pydata([(0.0, 0.0, 0.0)] * num_particles, [], [])
        mesh.update()

    # Create attributes if missing
    for name in frame.fields.keys():
        if name not in mesh.attributes:
            mesh.attributes.new(name=name, type='FLOAT', domain='POINT')

    # Update vertex positions
    pos = frame.coordinates.astype(np.float32) * position_scale
    if center:
        pos -= pos.mean(axis=0)
    mesh.vertices.foreach_set("co", pos.ravel())

    # Update attributes
    for name, values in frame.fields.items():
        mesh.attributes[name].data.foreach_set("value", np.ravel(values, order='C'))

    mesh.update()
    
def surface_frame_update(frame, mesh, scale=1.0, center=True):
    """
    Update surface mesh per frame.
    frame : dict with keys 'vertices' and 'faces'
    """
    verts = np.array(frame.vertices, dtype=np.float32) * scale
    if center:
        verts -= verts.mean(axis=0)

    mesh.clear_geometry()
    mesh.from_pydata(verts.tolist(), [], frame.faces.tolist())
    mesh.update()

## Main Function
def setup_mesh_animation(
    frames_data: Union[SPHParticleData, SurfaceData, List[Union[SPHParticleData, SurfaceData]]],
    object: Union[str | bpy.types.Object] = None,
    scale = None,
    target_size = 200,
    center=False,
    material: Optional[bpy.types.Material] = None,
):
    """
    Generic mesh animation setup for Blender.

    Parameters
    ----------
    frames_data : list
        List of SPHParticleData or SurfaceData per frame.
    object_name : str
        Name of the Blender object.
    obj : bpy.types.Object or None
        Existing object or None to create new.
    scale : float
        Scale factor for positions.
    center : bool
        Whether to center vertices/particles per frame.
    material : bpy.types.Material, optional
        Material to assign to the created/resolved object.
    """
    
    print(f'\n{"="*50}')
    if isinstance(object, bpy.types.Object):
        obj = object
        object = obj.name
    print(f"Setting up mesh animation for object: {object}")
    print(f"{'-'*50}")
    
    ## Resolve or create object
    if isinstance(object, str):
        if object in bpy.data.objects:
            obj = bpy.data.objects[object]
            print(f"  Apply animination on existing object: {object}")
        else:
            obj = create_object(object)
            print(f"  Created new object: {object}")

    mesh = obj.data
    
    if isinstance(frames_data, SPHParticleData) or isinstance(frames_data, SurfaceData):
        frames_data = [frames_data]
    elif isinstance(frames_data, list):
        if not all(isinstance(f, (SPHParticleData, SurfaceData)) for f in frames_data):
            raise TypeError("All elements in frames_data must be SPHParticleData or SurfaceData.")
    else:
        raise TypeError("frames_data must be (a list of) SPHParticleData or SurfaceData.")
    
    num_frames = len(frames_data)
    print(f"  Number of frames: {num_frames}")

    if material is not None:
        set_object_shader(object, material)

    if scale is None and target_size is not None:
        if isinstance(frames_data[0], SPHParticleData):
            scale = target_size / max(np.ptp(frames_data[0].coordinates, axis=0))
            print(f"Auto-calculated scale factor: {scale} (target size: {target_size})")
        elif isinstance(frames_data[0], SurfaceData):
            scale = target_size / max(np.ptp(frames_data[0].vertices, axis=0))
            print(f"Auto-calculated scale factor: {scale} (target size: {target_size})")
        else:
            raise TypeError("Unsupported frame data type for scaling.")
    
    elif scale is not None:
        print(f"  Using provided scale factor: {scale}")
        
    else:
        scale = 1.0
        print(f"  Using default scale factor: {scale}")
       
    # Set scene frame range
    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = num_frames - 1

    print(f"  Frame range: {scene.frame_start} to {scene.frame_end}")
    print(f"  Material: {material.name if material else 'none'}")
    print(f"{'-'*50}")
        
    # Inner handler function
    def handler(scene):
        f = scene.frame_current
        if f < 0 or f >= num_frames:
            return

        frame = frames_data[f]

        if isinstance(frame, SPHParticleData):
            particle_frame_update(frame, mesh, scale, center)
        elif isinstance(frame, SurfaceData):
            surface_frame_update(frame, mesh, scale, center)

    # Remove any old handler for this object, then register the new one
    remove_existing_handler(obj.name)
    bpy.app.handlers.frame_change_post.append(handler)
    _registered_handlers[obj.name] = handler

    # Link object to collection if not already
    if bpy.context.collection not in obj.users_collection:
        bpy.context.collection.objects.link(obj)

    print(f"{object} animation registered ({num_frames} frames).")
    print(f"{'='*50}")
    return obj