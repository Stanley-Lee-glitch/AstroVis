"""
Backend/workflow.py

One-call export functions: snapshot directory -> Blender-ready files
(VDB / surface HDF5 / particle HDF5), for both grid/AMR and SPH-particle
simulation data.

Common utilities (snapshot discovery, gap detection, interpolation) live at
the top of this file and are shared across every export_* function below,
rather than each one re-implementing its own directory listing / sorting.
"""

import os
import re
import numpy as np
from collections import Counter
from dataclasses import replace as dataclass_replace
from typing import List, Dict, Optional, Union, Tuple, Callable
import zipfile

# Shared utility: snapshot discovery and gap detection (skipped/missing snapshot numbers)

def _snapshot_sort_key(name: str):
    """Sort snapshot files naturally by their trailing integer, if present."""
    stem = os.path.splitext(os.path.basename(name))[0]
    match = re.search(r"(\d+)$", stem)
    if match:
        return (0, int(match.group(1)), name.lower())
    return (1, name.lower())


def _collect_snapshot_files(
    input_dir: str,
    patterns: Optional[Union[str, List[str]]] = None,
    suffixes: Optional[Union[str, List[str]]] = None,
) -> List[str]:
    """
    Collect and sort snapshot files from a directory.

    Users may provide either glob patterns (e.g. "*.hdf5") or suffixes
    (e.g. [".hdf5", ".h5"]). If neither is given, the default supported set is
    used: .athdf, .hdf5, .h5.
    """
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Snapshot directory does not exist: {input_dir}")

    if patterns is None and suffixes is None:
        patterns = ["*.athdf", "*.hdf5", "*.h5"]

    if isinstance(patterns, str):
        patterns = [patterns]
    if isinstance(suffixes, str):
        suffixes = [suffixes]

    discovered = []
    seen = set()

    def add_match(path: str):
        if os.path.isfile(path) and path not in seen:
            discovered.append(path)
            seen.add(path)

    if patterns:
        import fnmatch
        for pattern in patterns:
            if pattern == "*":
                for name in sorted(os.listdir(input_dir)):
                    full_path = os.path.join(input_dir, name)
                    if os.path.isfile(full_path):
                        add_match(full_path)
            else:
                for name in sorted(os.listdir(input_dir)):
                    if fnmatch.fnmatch(name, pattern):
                        add_match(os.path.join(input_dir, name))

    if suffixes:
        normalized = []
        for suffix in suffixes:
            if suffix is None:
                continue
            suffix = str(suffix)
            if not suffix.startswith("."):
                suffix = "." + suffix
            normalized.append(suffix)

        for name in os.listdir(input_dir):
            full_path = os.path.join(input_dir, name)
            if not os.path.isfile(full_path):
                continue
            if any(name.endswith(suffix) for suffix in normalized):
                add_match(full_path)

    if not discovered:
        return []

    print(f"Discovered {len(discovered)} snapshot files in '{input_dir}':")
    print(f" from {discovered[0]} to {discovered[-1]}")

    return sorted(discovered, key=lambda path: _snapshot_sort_key(os.path.basename(path)))


def _extract_snapshot_number(name: str) -> Optional[int]:
    """Pull the trailing integer out of a snapshot filename, e.g. 'snapshot_00123.hdf5' -> 123."""
    stem = os.path.splitext(os.path.basename(name))[0]
    match = re.search(r"(\d+)$", stem)
    return int(match.group(1)) if match else None


def _build_snapshot_slots(snapshot_files: List[str]) -> Dict[str, object]:
    """
    Map discovered snapshot files onto their true position in the numbered
    sequence, so a file that's simply missing from disk (e.g. snapshot 123
    was never written) shows up as a gap -- not just a failed yt.load.

    Returns:
      - 'slots': ordered list of (snapshot_number, filepath_or_None) covering
                 every expected number from min to max, at the inferred step.
      - 'step': inferred spacing between snapshot numbers.
      - 'irregular_gaps': (num_before, num_after) pairs where the gap wasn't
                 a clean multiple of `step` -- ambiguous missing count, so
                 these are reported but not auto-filled.
      - 'numbered': False if filenames couldn't be parsed numerically at all
                 (falls back to plain positional slots, no gap detection).
    """
    numbered = []
    for path in snapshot_files:
        num = _extract_snapshot_number(path)
        if num is None:
            return {"slots": [(i, p) for i, p in enumerate(snapshot_files)],
                    "step": None, "irregular_gaps": [], "numbered": False}
        numbered.append((num, path))

    numbered.sort(key=lambda x: x[0])
    numbers = [n for n, _ in numbered]

    diffs = [b - a for a, b in zip(numbers, numbers[1:]) if b > a]
    step = Counter(diffs).most_common(1)[0][0] if diffs else 1

    slots = []
    irregular_gaps = []

    for i, (num, path) in enumerate(numbered):
        slots.append((num, path))
        if i + 1 < len(numbered):
            next_num = numbered[i + 1][0]
            gap = next_num - num
            if gap > step:
                if gap % step == 0:
                    missing_count = gap // step - 1
                    for k in range(1, missing_count + 1):
                        slots.append((num + k * step, None))
                else:
                    irregular_gaps.append((num, next_num))
                    print(f"  [WARN] Gap between snapshots {num} and {next_num} (diff={gap}) "
                          f"isn't a multiple of the inferred step ({step}) -- number of missing "
                          f"snapshots is ambiguous, not auto-filling this gap.")

    slots.sort(key=lambda x: x[0])
    return {"slots": slots, "step": step, "irregular_gaps": irregular_gaps, "numbered": True}


def _resolve_slots(input_dir: str, start_frame: Optional[int] = None, end_frame: Optional[int] = None) -> Dict[str, object]:
    """Discover snapshot files + compute their gap-aware slot list, in one call."""
    snapshot_files = _collect_snapshot_files(input_dir)
    if not snapshot_files:
        raise ValueError(f"No supported snapshot files found in: {input_dir}")

    slot_info = _build_snapshot_slots(snapshot_files)
    if not slot_info["numbered"]:
        print("  [WARN] Could not parse numeric snapshot IDs from filenames -- "
              "falling back to positional indexing; skipped/missing files won't be detected as gaps.")
    elif slot_info["irregular_gaps"]:
        print(f"  [WARN] {len(slot_info['irregular_gaps'])} irregular-sized gap(s) found "
              f"-- see warnings above; these were not auto-filled.")

    if start_frame is not None or end_frame is not None:
        start = start_frame if start_frame is not None else 0
        end = end_frame if end_frame is not None else len(slot_info["slots"])
        slot_info["slots"] = slot_info["slots"][start:end]
    return slot_info


def _contiguous_runs(indices: List[int]) -> List[List[int]]:
    indices = sorted(indices)
    runs, current = [], []
    for i in indices:
        if current and i != current[-1] + 1:
            runs.append(current)
            current = []
        current.append(i)
    if current:
        runs.append(current)
    return runs


def _object_name_from_output_dir(output_dir: str) -> str:
    """
    Derive a stable object name from the output folder name.
    """
    name = output_dir.rstrip(os.sep).split(os.sep)[-1]
    if not name:
        raise ValueError(f"Could not derive an object name from output_dir: '{output_dir}'")
    return name


# Interpolation

def _interpolate_grid_block(b0, b1, field: str, t: float):
    """
    Linear interpolation of `field` between two flat grid-like objects that
    expose `.fields: Dict[str, np.ndarray]` directly (no `.levels`) -- this
    is the shape assumed for whatever `sph_to_grid()` returns. If that
    assumption is wrong, this will raise/skip loudly rather than silently
    producing a bad array; verify against the real return type of
    sph_to_grid before relying on this in production.
    """
    if field not in b0.fields or field not in b1.fields:
        print(f"  [WARN] Field '{field}' missing on one side of the interpolation -- skipped.")
        return None
    if b0.fields[field].shape != b1.fields[field].shape:
        print(f"  [WARN] Shape mismatch {b0.fields[field].shape} vs {b1.fields[field].shape} -- skipped.")
        return None

    interp_array = (1 - t) * b0.fields[field] + t * b1.fields[field]
    new_fields = dict(b0.fields)
    new_fields[field] = interp_array
    try:
        return dataclass_replace(b0, fields=new_fields, field_ranges={})
    except TypeError:
        # not a dataclass / doesn't support replace -- fall back to shallow copy + mutate
        import copy
        new_obj = copy.copy(b0)
        new_obj.fields = new_fields
        if hasattr(new_obj, "field_ranges"):
            new_obj.field_ranges = {}
        return new_obj


def _interpolate_field_hierarchy(h_before, h_after, field: str, t: float):
    """
    Linear interpolation of `field` between two FieldHierarchy objects
    (AMR: levels -> blocks), matched by block_id per level. Blocks/levels
    present on only one side, or with mismatched field/shape, are skipped
    with a warning rather than crashing the whole interpolation.
    """
    new_levels = {}
    all_level_ids = set(h_before.levels) | set(h_after.levels)

    for lvl in sorted(all_level_ids):
        lvl_before = h_before.levels.get(lvl)
        lvl_after = h_after.levels.get(lvl)
        if lvl_before is None or lvl_after is None:
            print(f"  [WARN] Level {lvl} present in only one neighbor -- skipped.")
            continue

        blocks_before = {b.block_id: b for b in lvl_before.blocks}
        blocks_after = {b.block_id: b for b in lvl_after.blocks}
        common_ids = set(blocks_before) & set(blocks_after)
        missing = (set(blocks_before) | set(blocks_after)) - common_ids
        if missing:
            print(f"  [WARN] Level {lvl}: block_ids {sorted(missing)} not present in both neighbors -- skipped.")

        new_blocks = []
        for block_id in sorted(common_ids):
            new_block = _interpolate_grid_block(blocks_before[block_id], blocks_after[block_id], field, t)
            if new_block is not None:
                new_blocks.append(new_block)

        if new_blocks:
            new_levels[lvl] = type(lvl_before)(level=lvl, cell_size=lvl_before.cell_size, blocks=new_blocks)

    return type(h_before)(unit=h_before.unit, field_units=h_before.field_units, levels=new_levels, object_name=h_before.object_name)


def _interpolate_snapshot_data(obj_before, obj_after, field: str, t: float):
    """Dispatch to hierarchy- or flat-grid-block interpolation, based on shape of the object."""
    if hasattr(obj_before, "levels"):
        return _interpolate_field_hierarchy(obj_before, obj_after, field, t)
    return _interpolate_grid_block(obj_before, obj_after, field, t)


def _fill_gaps_by_interpolation(
    error_frames: List[int],
    good_data: Dict[int, object],
    field: str,
    interpolate_missing: bool,
    max_interp_gap: int,
    write_fn,
    missing_snapshot_numbers: Optional[Dict[int, int]] = None,
) -> Tuple[List[int], List[int]]:
    """
    Shared gap-filling pass: given frame indices that failed/are missing
    (`error_frames`) and the successfully-loaded data keyed by frame index
    (`good_data`), interpolate short contiguous gaps and call `write_fn(data,
    frame_num)` for each filled frame. Returns (interpolated_frames, unfilled_frames).
    """
    missing_snapshot_numbers = missing_snapshot_numbers or {}
    interpolated_frames: List[int] = []
    unfilled_frames: List[int] = []

    if not error_frames:
        return interpolated_frames, unfilled_frames

    for run in _contiguous_runs(error_frames):
        gap_len = len(run)
        before, after = run[0] - 1, run[-1] + 1

        if not interpolate_missing:
            unfilled_frames.extend(run)
            continue
        if before not in good_data or after not in good_data:
            print(f"  [WARN] Frames {run}: missing a valid neighbor on at least one side -- cannot interpolate.")
            unfilled_frames.extend(run)
            continue
        if gap_len > max_interp_gap:
            print(f"  [WARN] Frames {run}: gap of {gap_len} exceeds max_interp_gap={max_interp_gap} -- skipping.")
            unfilled_frames.extend(run)
            continue

        data_before, data_after = good_data[before], good_data[after]
        for step_i, frame_num in enumerate(run, start=1):
            t = step_i / (gap_len + 1)
            interp_data = _interpolate_snapshot_data(data_before, data_after, field, t)
            if interp_data is None:
                unfilled_frames.append(frame_num)
                continue

            write_fn(interp_data, frame_num)
            interpolated_frames.append(frame_num)
            label = (f"snapshot {missing_snapshot_numbers[frame_num]}"
                     if frame_num in missing_snapshot_numbers else f"frame {frame_num}")
            print(f"  [INFO] {label}: interpolated (t={t:.2f} between frames {before} and {after}).")

    return interpolated_frames, unfilled_frames


# Volume (grid/AMR) exports

def _zip_dir(output_dir: str) -> str:
    """Zip output_dir (preserving its frame_NNNN/ structure) into output_dir + '.zip'."""
    zip_path = output_dir.rstrip(os.sep) + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(output_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                arcname = os.path.relpath(full_path, start=os.path.dirname(output_dir))
                zf.write(full_path, arcname)
    print(f"Zipped '{output_dir}' -> '{zip_path}' ({os.path.getsize(zip_path) / 1e6:.1f} MB)")
    return zip_path


def export_volume_vdb_sequence(
    ## Folder configuration
    input_dir: str,
    output_dir: str,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    object_name: Optional[str] = None,
    ## Loading 
    vtype: str = "gas",
    field: str = "density",
    log: bool = True,
    verbose: bool = False,
    multi_vdb: bool = True,   
    ## Interpolation
    interpolate_missing: bool = True,
    max_interp_gap: int = 3,   
    ## Plotting and output
    preview_every: Optional[int] = 10,
    preview_dir: Optional[str] = None,
    zip_output: bool = False,
    delete_unzipped: bool = False,
) -> Dict[str, object]:
    """
    Volume snapshot directory -> VDB sequence + preview output.

    input_dir: directory containing volume snapshots (AMR or uniform grid)
    start_frame: optional first frame to process
    end_frame: optional last frame to process
    output_dir: directory to write frame_NNNN/ subfolders containing VDBs
    object_name: name of the object to use for VDB files (defaults to output folder name)
    vtype: volume type to load from yt (e.g. "gas", "dark_matter", etc.)
    field: field name to export (e.g. "density", "temperature", etc.)   
    log: whether to use log scaling for field range analysis 
    verbose: whether to print detailed progress messages
    multi_vdb: whether to export multiple VDBs per frame (if False, export a single VDB)
    interpolate_missing: whether to interpolate missing snapshots
    max_interp_gap: maximum gap length for interpolation
    preview_every: how often to generate preview images (None to skip)
    preview_dir: directory to write preview images (None to write alongside VDBs)
    zip_output: whether to zip the output_dir into a single archive
    delete_unzipped: whether to delete the raw output_dir after zipping
    
    """
    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir) if object_name is None else object_name

    import yt
    from .volume_data import load_volume
    from .grid_to_vdb import hierarchy_to_multiple_vdbs, hierarchy_to_vdb

    def _write_vdb(hierarchy, frame_num):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        if multi_vdb:
            hierarchy_to_multiple_vdbs(hierarchy, field=field,
                                        file_name_prefix=os.path.join(frame_dir, object_name), log=log)
        else:
            hierarchy_to_vdb(hierarchy, field=field,
                              file_path=os.path.join(frame_dir, f"{object_name}.vdb"), log=log)

    #1. Check for missing snapshots and build a slot list
    slot_info = _resolve_slots(input_dir, start_frame=start_frame, end_frame=end_frame)
    slots = slot_info["slots"]
    print(f"Loading snapshots {start_frame if start_frame is not None else 0} to {end_frame if end_frame is not None else len(slots)-1} from '{input_dir}' into '{output_dir}'...")
    print(f"Missing snapshot numbers detected: {[num for num, path in slots if path is None]}")

    preview_samples = []
    global_min, global_max = float("inf"), float("-inf")

    error_frames: List[int] = []
    good_hierarchies: Dict[int, object] = {}
    missing_snapshot_numbers: Dict[int, int] = {}

    #2. Load snapshots and write VDBs
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):

        ## Checking missing or error files
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}'.")
            error_frames.append(frame_num)
            missing_snapshot_numbers[frame_num] = snapshot_number
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            hierarchy = load_volume(ds, vtype=vtype, fields=[field], object_name=object_name, verbose = verbose)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            error_frames.append(frame_num)
            continue

        good_hierarchies[frame_num] = hierarchy

        ## Track ranges
        current_range = hierarchy.get_field_value_ranges(fields=field, log=log)
        if field not in current_range:
            raise ValueError(f"Field '{field}' was not found in snapshot '{snapshot_name}'.")
        field_min, field_max = current_range[field]
        global_min, global_max = min(global_min, field_min), max(global_max, field_max)

        ## Track preview
        if preview_every is not None and preview_every > 0 and (frame_num % preview_every) == 0:
            preview_samples.append((frame_num, hierarchy))

        _write_vdb(hierarchy, frame_num)

    def _write_and_track_range(hierarchy, frame_num):
        current_range = hierarchy.get_field_value_ranges(fields=field, log=log)
        if field in current_range:
            nonlocal_min, nonlocal_max = current_range[field]
            nonlocal global_min, global_max
            global_min, global_max = min(global_min, nonlocal_min), max(global_max, nonlocal_max)
        _write_vdb(hierarchy, frame_num)

    #3. Fill any gaps by interpolating between neighboring good frames
    interpolated_frames, unfilled_frames = _fill_gaps_by_interpolation(
        error_frames, good_hierarchies, field, interpolate_missing, max_interp_gap,
        _write_and_track_range, missing_snapshot_numbers,
    )

    field_range = (global_min, global_max)

    #4. Write preview images at the sampled frames, using the global field range
    print(f"\nGenerating preview for frames: {[frame_num for frame_num, _ in preview_samples]}")
    for frame_num, hierarchy in preview_samples:
        preview_path = (os.path.join(output_dir, f"preview_{frame_num:04d}.png") if preview_dir is None
                         else os.path.join(preview_dir, f"preview_{frame_num:04d}.png"))
        if preview_dir is not None:
            os.makedirs(preview_dir, exist_ok=True)            
        hierarchy.analyze_field_data(fields=field, output_path=preview_path, log=log,
                                      value_ranges={field: field_range})

    #5. Optionally zip the frame_NNNN/ tree into a single VDB export archive
    if zip_output:
        zip_path = _zip_dir(output_dir)
        print(f"Zipped output directory '{output_dir}' into '{zip_path}'")
        if delete_unzipped:
            import shutil
            shutil.rmtree(output_dir)
            print(f"Removed raw folder '{output_dir}' -- '{zip_path}' is now the only artifact.")

    result = {
        "field": field,
        "object_name": object_name,
        "field_range": field_range,
        "snapshot_count": len(slots),
        "interpolated_frames": interpolated_frames,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
        "output_dir": output_dir,
        "zip_path": zip_path if zip_output else None,
    }
    
    print(f"{'-'*50}")
    print("Summary of export_volume_vdb_sequence:")
    print(f"  Output directory: {output_dir}")
    print(f"  Field: {field}")
    print(f"  Object name: {object_name}")
    print(f"  Field range: {field_range}. Use it in blender.")
    print(f"  Snapshot count: {len(slots)}")
    print(f"  Interpolated frames: {interpolated_frames}")
    print(f"  Unfilled frames: {unfilled_frames}")
    print(f"  Missing snapshot numbers: {missing_snapshot_numbers}")
    print(f"  Irregular gaps: {slot_info['irregular_gaps']}")
    if zip_output:
        print(f"  Zipped output: {zip_path}")
    
    print(f"{'='*50}")
    
    return result


def export_volume_surface_sequence(
    input_dir: str,
    output_dir: str,
    num_snapshot: Optional[int] = None,
    field: Union[str, Dict[str, Callable[["GridBlock"], np.ndarray]]] = "density",
    vtype: str = "gas",
    ridge_surface: bool = False,
    threshold: Optional[float] = None,      # isosurface mode only; ignored when ridge_surface=True
    ridge_kwargs: Optional[dict] = None,     # e.g. {"sigma": 1.2, "lambda_pct": 10, "min_cluster_size": 250, ...}
    interpolate_missing: bool = True,
    max_interp_gap: int = 3,
    **kwargs,
):
    """
    Volume snapshot directory -> surface HDF5 sequence.

    Experimental AMR merge prototype: this assumes load_volume() already returns a
    non-overlapping hierarchy and then stitches the block-level surfaces together.

    ridge_surface=False (default): isosurface extraction via grid_to_surface
    (marching_cubes), thresholded at `threshold`.
    Note on `threshold`: intentional, not a bug -- if left as None, it is
    computed ONCE from the first available frame's field range, then reused
    unchanged for every subsequent frame, keeping the isosurface threshold
    consistent across the animation rather than drifting frame-to-frame.
    Pass an explicit `threshold` to fix it yourself from the start.

    ridge_surface=True: ridge-detection surface via grid_to_ridge_surface
    (Hessian eigen-analysis + Poisson reconstruction). `threshold` is not
    used in this mode -- pass ridge-specific tuning via `ridge_kwargs`
    (sigma, lambda_pct, min_cluster_size, normal_k, grid_sigma,
    isovalue_pct, ...). A failing block is skipped with a warning rather
    than crashing the whole export, matching isosurface's existing
    None-on-failure behavior.

    `field` also accepts a single {name: callable} dict for a derived field --
    this is passed straight through to load_volume, which now supports it.
    The callable must have signature (data_source, vtype) -> np.ndarray,
    matching that block's dims (see load_volume's docstring for why volume
    callables take the per-block data_source, unlike load_particles'
    no-argument callables).

    Every frame's surface is saved under the key `object_name`, derived from
    output_dir's folder name -- not a generic literal like "surface" -- so
    setup_animation() can recognize the per-frame files as one animated
    object instead of overwriting the same key each time.
    """
    import yt
    from .volume_data import load_volume
    from .grid_to_surface import grid_to_surface, grid_to_ridge_surface
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)  # use output folder name as object name

    ridge_kwargs = ridge_kwargs or {}

    if isinstance(field, dict):
        if len(field) != 1:
            raise ValueError("field as a dict must have exactly one {name: callable} entry.")
        field_name, field_fn = next(iter(field.items()))
    else:
        field_name, field_fn = field, None

    def _extract_one_block(block, fixed_threshold):
        if field_name not in block.fields:
            return None
        if ridge_surface:
            try:
                return grid_to_ridge_surface(
                    block, field=field_name, plot_check=False, **ridge_kwargs,
                )
            except Exception as e:
                print(f"  [WARNING] Ridge extraction failed for a block: {e}")
                return None
        else:
            return grid_to_surface(
                block, threshold=fixed_threshold, field=field_name,
                center=False, scale=1.0, plot_surface=False,
            )

    def _merge_surface_blocks(surfaces):
        if not surfaces:
            raise ValueError("No surfaces were provided to merge.")
        if len(surfaces) == 1:
            return surfaces[0]

        vertices, faces, normals = [], [], []
        vertex_offset = 0
        for surface in surfaces:
            if surface is None:
                continue
            verts = np.asarray(surface.vertices, dtype=float)
            face_arr = np.asarray(surface.faces, dtype=int)
            if verts.size == 0 or face_arr.size == 0:
                continue
            vertices.append(verts)
            if surface.normals is not None:   # SurfaceData.normals defaults to None -- safe for ridge mode
                normals.append(np.asarray(surface.normals, dtype=float))
            faces.append(face_arr + vertex_offset)
            vertex_offset += verts.shape[0]

        if not vertices:
            raise ValueError("No valid surfaces remained after merge filtering.")

        merged_vertices = np.concatenate(vertices, axis=0)
        merged_faces = np.concatenate(faces, axis=0) if faces else np.empty((0, 3), dtype=int)
        # only attach merged normals if EVERY contributing surface had them (isosurface-only mix);
        # a partial set would misalign vertex-to-normal correspondence after concatenation
        merged_normals = np.concatenate(normals, axis=0) if len(normals) == len(vertices) else None
        return type(surfaces[0])(vertices=merged_vertices, faces=merged_faces, normals=merged_normals)

    def _build_surface_for_hierarchy(hierarchy, fixed_threshold):
        block_surfaces = []
        for level in sorted(hierarchy.levels.keys()):
            for block in hierarchy.levels[level].blocks:
                block_surface = _extract_one_block(block, fixed_threshold)
                if block_surface is None:
                    continue
                block_surface.vertices = np.asarray(block_surface.vertices, dtype=float) + np.asarray(block.left_edge, dtype=float)
                block_surfaces.append(block_surface)
        if not block_surfaces:
            raise ValueError(f"No block surface could be extracted for field '{field_name}' from the volume hierarchy.")
        return _merge_surface_blocks(block_surfaces)

    #1. Check for missing snapshots and build a slot list
    slot_info = _resolve_slots(input_dir, num_snapshot)
    slots = slot_info["slots"]

    exports = []
    fixed_threshold = None if ridge_surface else threshold   # unused in ridge mode; None until locked in iso mode
    error_frames: List[int] = []
    good_hierarchies: Dict[int, object] = {}
    missing_snapshot_numbers: Dict[int, int] = {}

    #2. Load snapshots, extract + merge block surfaces, write one surface.h5 per frame
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):

        ## Checking missing or error files
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            error_frames.append(frame_num)
            missing_snapshot_numbers[frame_num] = snapshot_number
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            hierarchy = load_volume(ds, vtype=vtype, fields=field)  # `field` can be a str or a {name: callable} dict
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            error_frames.append(frame_num)
            continue

        good_hierarchies[frame_num] = hierarchy

        ## Lock the isosurface threshold once, from the first successful frame
        if not ridge_surface and fixed_threshold is None:
            field_range = hierarchy.get_field_value_ranges(fields=field_name, log=False).get(field_name, (0.0, 1.0))
            fixed_threshold = float((field_range[0] + field_range[1]) / 2.0)

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _build_surface_for_hierarchy(hierarchy, fixed_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        save(surface_path, {object_name: surface})   # keyed by object_name so frames merge into one animation

        exports.append({
            "frame": frame_num, "path": frame_dir, "surface_path": surface_path,
            "threshold": fixed_threshold, "mode": "ridge" if ridge_surface else "isosurface",
            "status": "immature_amr_merge_prototype",
        })

    def _write_surface_frame(hierarchy, frame_num):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _build_surface_for_hierarchy(hierarchy, fixed_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        save(surface_path, {object_name: surface})
        exports.append({
            "frame": frame_num, "path": frame_dir, "surface_path": surface_path,
            "threshold": fixed_threshold, "mode": "ridge" if ridge_surface else "isosurface",
            "status": "immature_amr_merge_prototype (interpolated)",
        })

    #3. Fill any gaps by interpolating between neighboring good frames
    interpolated_frames, unfilled_frames = _fill_gaps_by_interpolation(
        error_frames, good_hierarchies, field_name, interpolate_missing, max_interp_gap,
        _write_surface_frame, missing_snapshot_numbers,
    )

    return {
        "field": field_name,
        "object_name": object_name,
        "output_dir": output_dir,
        "snapshot_count": len(slots),
        "exports": exports,
        "interpolated_frames": interpolated_frames,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
        "status": "immature_amr_merge_prototype",
    }


def export_volume_particle_sequence(
    input_dir: str,
    output_dir: str,
    num_snapshot: Optional[int] = None,
    field: str = "density",
    vtype: str = "gas",
    **kwargs,
):
    """Volume snapshot directory -> particle HDF5 export sequence. To do."""
    raise NotImplementedError(
        "Volume-to-particle HDF5 sequence export is not implemented yet."
    )


# ============================================================
# Particle (SPH) exports
# ============================================================

def export_particle_vdb_sequence(
    input_dir: str,
    output_dir: str,
    num_snapshot: Optional[int] = None,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str]]] = None,
    res: int = 256,
    field: str = "density",
    log: bool = True,
    intensive: bool = True,
    center: bool = True,
    scale: float = 1.0,
    multi_vdb: bool = True,
    interpolate_missing: bool = True,
    max_interp_gap: int = 3,
) -> Dict[str, object]:
    """
    Particle snapshot directory -> VDB sequence export.

    Interpolation note: `sph_to_grid` is called with a fixed `res`, so the
    resulting grid shape is the same every frame -- that's what makes linear
    interpolation of a missing frame well-defined here (unlike raw particle
    export below, where particle count/order can vary frame to frame).

    Every frame's VDB is named from `object_name` (output_dir's folder name),
    matching export_volume_vdb_sequence's convention.
    """
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_vdb import grid_to_vdb

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)  # use output folder name as object name

    def _write_vdb_grid(volume, frame_num):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        file_arg = (os.path.join(frame_dir, object_name) if multi_vdb
                    else os.path.join(frame_dir, f"{object_name}.vdb"))
        grid_to_vdb(volume, field=field, scale=scale, file_path=file_arg, log=log)

    #1. Check for missing snapshots and build a slot list
    slot_info = _resolve_slots(input_dir, num_snapshot)
    slots = slot_info["slots"]

    exports = []
    error_frames: List[int] = []
    good_volumes: Dict[int, object] = {}
    missing_snapshot_numbers: Dict[int, int] = {}

    #2. Load snapshots, rasterize particles onto a grid, write VDBs
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):

        ## Checking missing or error files
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            error_frames.append(frame_num)
            missing_snapshot_numbers[frame_num] = snapshot_number
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
            volume = sph_to_grid(particles, fields=field if fields is None else fields,
                                  res=res, intensive=intensive, center=center)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            error_frames.append(frame_num)
            continue

        good_volumes[frame_num] = volume
        _write_vdb_grid(volume, frame_num)
        exports.append({"frame": frame_num, "path": os.path.join(output_dir, f"frame_{frame_num:04d}"),
                         "field_range": volume.get_field_value_ranges(fields=field, log=log)[field]})

    def _write_and_record(volume, frame_num):
        _write_vdb_grid(volume, frame_num)
        exports.append({"frame": frame_num, "path": os.path.join(output_dir, f"frame_{frame_num:04d}"),
                         "field_range": volume.get_field_value_ranges(fields=field, log=log).get(field),
                         "interpolated": True})

    #3. Fill any gaps by interpolating between neighboring good frames
    interpolated_frames, unfilled_frames = _fill_gaps_by_interpolation(
        error_frames, good_volumes, field, interpolate_missing, max_interp_gap,
        _write_and_record, missing_snapshot_numbers,
    )

    return {
        "field": field,
        "object_name": object_name,
        "output_dir": output_dir,
        "snapshot_count": len(slots),
        "exports": exports,
        "interpolated_frames": interpolated_frames,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
    }


def _field_names(fields_spec: Union[str, List[str], Dict[str, Callable], None]) -> Optional[List[str]]:
    """
    Normalize a load_particles-style `fields` argument down to the list of
    resulting field NAMES, regardless of whether it was given as a string,
    a list, or a {name: callable} dict of derived fields. Used to tell
    sph_to_grid which columns to rasterize -- sph_to_grid wants names, not
    the raw callables (which have already done their job inside
    load_particles by the time we get here).
    """
    if fields_spec is None:
        return None
    if isinstance(fields_spec, str):
        return [fields_spec]
    if isinstance(fields_spec, dict):
        return list(fields_spec.keys())
    return list(fields_spec)


def export_particle_surface_sequence(
    input_dir: str,
    output_dir: str,
    num_snapshot: Optional[int] = None,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str], Dict[str, Callable]]] = None,
    res: int = 256,
    field: str = "density",
    threshold: Optional[float] = None,
    log: bool = True,
    intensive: bool = True,
    center: bool = True,
    scale: float = 1.0,
    interpolate_missing: bool = True,
    max_interp_gap: int = 3,
    **kwargs,
):
    """
    Particle snapshot directory -> surface HDF5 sequence.

    Every frame's surface is saved under `object_name` (output_dir's folder
    name), matching export_volume_surface_sequence's convention.
    """
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_surface import grid_to_surface
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)  # use output folder name as object name

    user_threshold = threshold  # what the caller actually asked for; never mutated below
    rasterize_fields = _field_names(fields) if fields is not None else field

    def _surface_for_volume(volume, frame_threshold):
        return grid_to_surface(volume, threshold=frame_threshold, field=field,
                                center=center, scale=scale, plot_surface=False)

    #1. Check for missing snapshots and build a slot list
    slot_info = _resolve_slots(input_dir, num_snapshot)
    slots = slot_info["slots"]

    exports = []
    error_frames: List[int] = []
    good_volumes: Dict[int, object] = {}
    missing_snapshot_numbers: Dict[int, int] = {}

    #2. Load snapshots, rasterize + extract surface, write one surface.h5 per frame
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):

        ## Checking missing or error files
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            error_frames.append(frame_num)
            missing_snapshot_numbers[frame_num] = snapshot_number
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
            volume = sph_to_grid(particles, fields=rasterize_fields,
                                  res=res, intensive=intensive, center=center)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            error_frames.append(frame_num)
            continue

        good_volumes[frame_num] = volume

        ## Lock the threshold once (unless the caller fixed it) from each frame's own range
        if user_threshold is None:
            field_range = volume.get_field_value_ranges(fields=field, log=log).get(field, (0.0, 1.0))
            frame_threshold = float(np.mean(field_range))
        else:
            frame_threshold = user_threshold

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _surface_for_volume(volume, frame_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        if surface is not None:
            save(surface_path, {object_name: surface})   # keyed by object_name so frames merge into one animation

        exports.append({"frame": frame_num, "path": frame_dir, "surface_path": surface_path,
                         "threshold": frame_threshold})

    def _write_interp_surface(volume, frame_num):
        if user_threshold is None:
            field_range = volume.get_field_value_ranges(fields=field, log=log).get(field, (0.0, 1.0))
            frame_threshold = float(np.mean(field_range))
        else:
            frame_threshold = user_threshold

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _surface_for_volume(volume, frame_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        if surface is not None:
            save(surface_path, {object_name: surface})
        exports.append({"frame": frame_num, "path": frame_dir, "surface_path": surface_path,
                         "threshold": frame_threshold, "interpolated": True})

    #3. Fill any gaps by interpolating between neighboring good frames
    interpolated_frames, unfilled_frames = _fill_gaps_by_interpolation(
        error_frames, good_volumes, field, interpolate_missing, max_interp_gap,
        _write_interp_surface, missing_snapshot_numbers,
    )

    return {
        "field": field,
        "object_name": object_name,
        "output_dir": output_dir,
        "snapshot_count": len(slots),
        "exports": exports,
        "interpolated_frames": interpolated_frames,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
    }


def export_particle_particle_sequence(
    input_dir: str,
    output_dir: str,
    num_snapshot: Optional[int] = None,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str]]] = None,
):
    """
    Particle snapshot directory -> particle HDF5 sequence.

    No interpolation is performed for missing/failed frames here: particle
    count and ordering can differ between snapshots, so a linear blend
    between two particle sets isn't well-defined without per-particle ID
    matching (which this codebase doesn't appear to track). Missing/failed
    frames are detected and reported via 'unfilled_frames', not silently
    skipped -- but filling them is left to the caller.

    Each frame's particle set is saved under `object_name` (output_dir's
    folder name), matching the other export_* functions' convention -- even
    though frames aren't merged/interpolated here, keeping the key
    consistent avoids surprises if a downstream loader ever compares keys
    across export types.
    """
    import yt
    from .particle_data import load_particles
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)  # use output folder name as object name

    #1. Check for missing snapshots and build a slot list
    slot_info = _resolve_slots(input_dir, num_snapshot)
    slots = slot_info["slots"]

    exports = []
    unfilled_frames: List[int] = []
    missing_snapshot_numbers: Dict[int, int] = {}

    #2. Load snapshots and write one particles.h5 per frame (no interpolation -- see docstring)
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):

        ## Checking missing or error files
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file "
                  f"(not interpolated -- see docstring).")
            unfilled_frames.append(frame_num)
            missing_snapshot_numbers[frame_num] = snapshot_number
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            unfilled_frames.append(frame_num)
            continue

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        particle_file = os.path.join(frame_dir, "particles.h5")
        save(particle_file, {object_name: particles})

        exports.append({"frame": frame_num, "path": frame_dir, "particle_file": particle_file})

    return {
        "object_name": object_name,
        "output_dir": output_dir,
        "snapshot_count": len(slots),
        "exports": exports,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
    }