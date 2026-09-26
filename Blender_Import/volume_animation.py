import os
import sys
import tempfile

import bpy
from ..Blender_Effect.object import set_object_shader


def _filter_suppressed_vdb_stderr(stderr_text: str) -> str:
    visible_lines = []
    for line in stderr_text.splitlines(True):
        if "unsupported VDB file format" in line and "got version" in line:
            continue
        visible_lines.append(line)
    return "".join(visible_lines)


def _run_volume_import(filepath: str, suppress_vdb_warnings: bool):
    if not suppress_vdb_warnings:
        return bpy.ops.object.volume_import(
            filepath=filepath,
            use_sequence_detection=False,
        ), ""

    saved_stderr_fd = None
    try:
        stderr_fd = sys.stderr.fileno()
        saved_stderr_fd = os.dup(stderr_fd)
        captured_stderr_file = tempfile.TemporaryFile(mode="w+t")
    except (AttributeError, OSError, ValueError):
        if saved_stderr_fd is not None:
            os.close(saved_stderr_fd)
        return bpy.ops.object.volume_import(
            filepath=filepath,
            use_sequence_detection=False,
        ), ""

    with captured_stderr_file as captured_stderr:
        sys.stderr.flush()
        os.dup2(captured_stderr.fileno(), stderr_fd)
        try:
            result = bpy.ops.object.volume_import(
                filepath=filepath,
                use_sequence_detection=False,
            )
        finally:
            sys.stderr.flush()
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stderr_fd)

        captured_stderr.seek(0)
        return result, captured_stderr.read()


def _create_volume_object_from_filepath(filepath: str, name: str):
    vol_data = bpy.data.volumes.new(name=name)
    vol_data.filepath = filepath
    return bpy.data.objects.new(name=name, object_data=vol_data)


def _reset_imported_volume_transform(obj):
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)


def _cleanup_imported_objects(imported_objects):
    for imported_object in imported_objects:
        volume_data = imported_object.data
        bpy.data.objects.remove(imported_object, do_unlink=True)
        if volume_data is not None and volume_data.users == 0:
            bpy.data.volumes.remove(volume_data)


def _import_volume_object(filepath: str, name: str, suppress_vdb_warnings: bool):
    existing_object_ids = {existing.as_pointer() for existing in bpy.data.objects}
    result, captured_stderr = _run_volume_import(filepath, suppress_vdb_warnings)

    imported_objects = [
        existing for existing in bpy.data.objects
        if existing.as_pointer() not in existing_object_ids and existing.type == 'VOLUME'
    ]

    if 'FINISHED' in result and len(imported_objects) == 1:
        obj = imported_objects[0]
        obj.name = name
        obj.data.name = name
        _reset_imported_volume_transform(obj)
        if captured_stderr:
            visible_stderr = _filter_suppressed_vdb_stderr(captured_stderr)
            if visible_stderr:
                sys.stderr.write(visible_stderr)
        return obj

    if captured_stderr:
        sys.stderr.write(captured_stderr)

    if imported_objects:
        _cleanup_imported_objects(imported_objects)

    return _create_volume_object_from_filepath(filepath, name)


def setup_volume_animation(
    vdb_folder: str,
    object: str = "Volume",
    material: bpy.types.Material = None,
    scale: float = None,
    target_size: float = None,
    suppress_vdb_warnings: bool = True,
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

            obj = _import_volume_object(filepath, name, suppress_vdb_warnings)
            set_object_shader(obj, material)
             
            if scale is not None:
                obj.scale = (scale, scale, scale)
                print(f"  Applied scale factor: {scale} to object: {obj.name}")
            elif target_size is not None:
                bbox_size = max(obj.dimensions)
                if bbox_size > 0:
                    scale_factor = target_size / bbox_size
                    obj.scale = (scale_factor, scale_factor, scale_factor)
                    print(f"  Applied scale factor: {scale_factor} to object: {obj.name} for target size: {target_size}")
            else:
                obj.scale = (1.0, 1.0, 1.0)
                      
            for existing_collection in list(obj.users_collection):
                existing_collection.objects.unlink(obj)
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
