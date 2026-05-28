import os
import bpy
from ..Blender_Effect.object import set_object_shader

def setup_volume_animation(
    vdb_folder: str, 
    material: bpy.types.Material | None = None,
    multi_vdb_per_frame: bool = False,
):
    """
    Sets up volume animation in Blender by importing VDB files per frame and controlling their visibility.
    """
             
    frame_to_filepaths = {}

    ## Construct frame to filepaths mapping
    if multi_vdb_per_frame:
        subfolders = sorted([d for d in os.listdir(vdb_folder) 
                             if os.path.isdir(os.path.join(vdb_folder, d)) and d.startswith("frame_")])
        
        for frame_num, subfolder in enumerate(subfolders):
            current_frame_folder = os.path.join(vdb_folder, subfolder)
            vdb_files = sorted([f for f in os.listdir(current_frame_folder) if f.endswith(".vdb")])
            
            if vdb_files:
                frame_to_filepaths[frame_num] = [os.path.join(current_frame_folder, f) for f in vdb_files]
    else:
        vdb_files = sorted([f for f in os.listdir(vdb_folder) if f.endswith(".vdb")])
        for frame_num, vdb_file in enumerate(vdb_files):
            frame_to_filepaths[frame_num] = [os.path.join(vdb_folder, vdb_file)]

    if not frame_to_filepaths:
        print("Warning: No valid VDB sequence data detected. Exiting.")
        return

    for frame_num, filepaths in sorted(frame_to_filepaths.items()):
        print(f"Processing Frame {frame_num:03d}: Importing {len(filepaths)} VDB partitions...")
        
        ## Create collection for this frame
        col = bpy.data.collections.new(f"frame_{frame_num:03d}")
        bpy.context.scene.collection.children.link(col)
        
        ## Import VDB files for this frame
        for filepath in filepaths:
            filename = os.path.splitext(os.path.basename(filepath))[0]
            vol_data = bpy.data.volumes.new(name=filename)
            vol_data.filepath = filepath
            obj = bpy.data.objects.new(filename, vol_data)
            set_object_shader(obj, material)   
                     
            if obj.name in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.unlink(obj)
            col.objects.link(obj)

        ## Visibiltiy Control for the frame
        for obj in col.objects:
            obj.hide_viewport = True
            obj.hide_render = True
            obj.keyframe_insert(data_path="hide_viewport", frame=0)
            obj.keyframe_insert(data_path="hide_render", frame=0)
            
            obj.hide_viewport = False
            obj.hide_render = False
            obj.keyframe_insert(data_path="hide_viewport", frame=frame_num)
            obj.keyframe_insert(data_path="hide_render", frame=frame_num)
            
            obj.hide_viewport = True
            obj.hide_render = True
            obj.keyframe_insert(data_path="hide_viewport", frame=frame_num + 1)
            obj.keyframe_insert(data_path="hide_render", frame=frame_num + 1)


