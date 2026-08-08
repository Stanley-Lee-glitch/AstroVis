import os
import bpy
from ..Blender_Effect.object import set_object_shader


def setup_volume_animation(
    vdb_folder: str,
    object: str = "Volume",
    material: bpy.types.Material = None,
    scale: float = None,
    target_size: float = None,
    ):
    """
    Sets up volume animation in Blender by importing VDB files per frame and
    controlling their visibility.

    Layout is auto-detected from `vdb_folder`:
      - flat layout: one .vdb file directly in `vdb_folder` per frame
      - partitioned layout: frame_* subfolders, each containing one or more
        .vdb partitions for that frame
    """

    frame_to_filepaths = {}

    ## Auto-detect layout: frame_* subfolders containing .vdb files means
    ## each frame is split across multiple VDB partitions.
    subfolders = sorted([
        d for d in os.listdir(vdb_folder)
        if os.path.isdir(os.path.join(vdb_folder, d)) and d.startswith("frame_")
    ])
    multi_vdb_per_frame = any(
        any(f.endswith(".vdb") for f in os.listdir(os.path.join(vdb_folder, d)))
        for d in subfolders
    )

    ## Construct frame to filepaths mapping
    if multi_vdb_per_frame:
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

    print(f"\n{'='*50}")
    print(f"Setting up volume animation from: {vdb_folder}")
    print(f"{'-'*50}")
    print(f"  Layout: {'partitioned (frame_*/*.vdb)' if multi_vdb_per_frame else 'flat (*.vdb)'}")
    print(f"  Frames detected: {len(frame_to_filepaths)}")
    print(f"  VDB files detected: {sum(len(files) for files in frame_to_filepaths.values())}")
    print(f"  Material: {material.name if material else 'none'}")
    print(f"{'-'*50}")

    for frame_num, filepaths in sorted(frame_to_filepaths.items()):
        print(f"Processing Frame {frame_num:03d}: Importing {len(filepaths)} VDB partitions...")
        
        ## Create collection for this frame
        col = bpy.data.collections.new(f"frame_{frame_num:03d}")
        bpy.context.scene.collection.children.link(col)
        
        ## Import VDB files for this frame
        for filepath in filepaths:
            filename = os.path.splitext(os.path.basename(filepath))[0]
            name = f"{object}_{filename}" if object else filename
            vol_data = bpy.data.volumes.new(name=name)
            vol_data.filepath = filepath
            obj = bpy.data.objects.new(name=name, data=vol_data)
            set_object_shader(obj, material)
            
            if scale is not None:
                obj.scale = (scale, scale, scale)
                print(f"  Applied scale factor: {scale} to object: {obj.name}")
            elif target_size is not None:
                # Assuming the VDB volume has a bounding box, we can scale it to fit target_size
                # This is a placeholder; actual bounding box calculation may be needed
                bbox_size = max(vol_data.dimensions)
                if bbox_size > 0:
                    scale_factor = target_size / bbox_size
                    obj.scale = (scale_factor, scale_factor, scale_factor)
                    print(f"  Applied scale factor: {scale_factor} to object: {obj.name} for target size: {target_size}")
            else:
                obj.scale = (1.0, 1.0, 1.0)
                     
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

    print(f"Volume animation registered ({len(frame_to_filepaths)} frames).")
    print(f"{'='*50}")