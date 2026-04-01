from ..Blender_Effect.object import create_object
from ..Backend.particle_data import SPHParticleData

import numpy as np
import bpy


""" Animate mesh from preloaded particle/ surface data.
Parameters:
----------
    
frame_data : list of dict
    List of particle/ surface data per frame, each as output of load_particles() or grid_to_surface()
object_name : str
    Name of the Blender object to create. Duplicate names will be overwritten.
obj : bpy.types.Object or None
    Existing Blender object to use for mesh, or None to create new one
position_scale : float
    Scale factor for particle positions or surface vertices
center : bool
    Whether to subtract center-of-mass per frame
"""

## Helper functions for mesh animation
    
def remove_existing_handler(obj_name):
    handlers = bpy.app.handlers.frame_change_post
    to_remove = []

    for h in handlers:
        if hasattr(h, "_object_name") and h._object_name == obj_name:
            to_remove.append(h)

    for h in to_remove:
        handlers.remove(h)

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
    
def surface_frame_update(frame, mesh, position_scale=1.0, center=True):
    """
    Update surface mesh per frame.
    frame : dict with keys 'vertices' and 'faces'
    """
    verts = np.array(frame["vertices"], dtype=np.float32) * position_scale
    if center:
        verts -= verts.mean(axis=0)

    mesh.clear_geometry()
    mesh.from_pydata(verts.tolist(), [], frame["faces"])
    mesh.update()

## Main Function
def setup_mesh_animation(
    frames_data,
    object_name: str,
    obj: bpy.types.Object = None,
    position_scale=1.0,
    center=True
):
    """
    Generic mesh animation setup for Blender.

    Parameters
    ----------
    frames_data : list
        List of particle or surface data per frame.
    object_name : str
        Name of the Blender object.
    frame_update_fn : callable
        Function to update mesh each frame. Signature: (mesh, frame, index) -> None
    obj : bpy.types.Object or None
        Existing object or None to create new.
    position_scale : float
        Scale factor for positions.
    center : bool
        Whether to center vertices/particles per frame.
    """
    if isinstance(frames_data, dict):
        frames_data = [frames_data]

    num_frames = len(frames_data)

    # Resolve or create object
    if obj is None:
        obj = create_object(object_name)

    mesh = obj.data

    # Set scene frame range
    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = num_frames - 1

    # Inner handler function
    def handler(scene):
        f = scene.frame_current
        if f < 0 or f >= num_frames:
            return

        frame = frames_data[f]
        
        if isinstance(frame, SPHParticleData):
            particle_frame_update(frame, mesh, position_scale, center)
        
        else:
            surface_frame_update(frame, mesh, position_scale, center)

        # Tag handler for removal
        handler._object_name = obj.name

    # Remove any old handlers for this object
    remove_existing_handler(obj.name)
    bpy.app.handlers.frame_change_post.append(handler)

    # Link object to collection if not already
    if bpy.context.collection not in obj.users_collection:
        bpy.context.collection.objects.link(obj)

    print(f"{object_name} animation registered ({num_frames} frames).")
    return obj