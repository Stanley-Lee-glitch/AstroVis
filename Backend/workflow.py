"""
Backend/workflow.py

One-call export functions: snapshot directory -> Blender-ready files
(VDB / surface HDF5 / particle HDF5), for both grid/AMR and SPH-particle
simulation data.

Three shared building blocks, usable standalone or from any export_* below:

  - collect_snapshot_files(input_dir, ...)  -> discover + naturally sort snapshot files
  - resolve_slot(input_dir, ...)            -> build a gap-aware slot list from those files
  - interpolate_frame(good_data, field, ...) -> fill short gaps in a slot list by interpolation,
                                                 writing each filled frame via a caller-supplied write_fn

Every export_* function below is now a thin loop around these three calls:
resolve_slot() to get the slot list, a per-slot load/write loop, then
interpolate_frame() to patch the gaps. All other helpers (natural sort key,
run detection, hierarchy/grid-block interpolation, zig) live as private
helpers attached to whichever of the three they serve.
"""

import os
import re
import copy
import numpy as np
from collections import Counter
from dataclasses import replace as dataclass_replace
from typing import List, Dict, Optional, Union, Tuple, Callable
import zipfile


# ==================================================================
# 1. collect_snapshot_files
# ==================================================================

def _snapshot_sort_key(name: str):
    """Sort snapshot files naturally by their trailing integer, if present."""
    stem = os.path.splitext(os.path.basename(name))[0]
    match = re.search(r"(\d+)$", stem)
    if match:
        return (0, int(match.group(1)), name.lower())
    return (1, name.lower())


def collect_snapshot_files(
    input_dir: str,
    patterns: Optional[Union[str, List[str]]] = None,
    suffixes: Optional[Union[str, List[str]]] = None,
) -> List[str]:
    """
    Collect and sort snapshot files from a directory.

    Users may provide either glob patterns (e.g. "*.hdf5") or suffixes
    (e.g. [".hdf5", ".h5"]). If neither is given, the default supported set is
    used: .athdf, .hdf5, .h5.

    Returns a list of discovered snapshot file paths, sorted by their
    trailing integer (if present) or by filename otherwise.
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

    discovered = sorted(discovered, key=lambda path: _snapshot_sort_key(os.path.basename(path)))

    print(f"Discovered {len(discovered)} snapshot files in '{input_dir}':")
    print(f"  from {discovered[0]} to {discovered[-1]}")

    return discovered


# ==================================================================
# 2. resolve_slot
# ==================================================================

def _build_snapshot_slots(snapshot_files: List[str]) -> Dict[str, object]:
    """
    Map discovered snapshot files onto their true position in the numbered
    sequence, so a file that's simply missing from disk (e.g. snapshot 123
    was never written) shows up as a gap -- not just a failed yt.load.
    """
    numbered = []
    for path in snapshot_files:
        stem = os.path.splitext(os.path.basename(path))[0]
        match = re.search(r"(\d+)$", stem)
        num = int(match.group(1)) if match else None

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


def resolve_slot(
    input_dir: str,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    patterns: Optional[Union[str, List[str]]] = None,
    suffixes: Optional[Union[str, List[str]]] = None,
) -> Dict[str, object]:
    """
    Discover snapshot files (via collect_snapshot_files) and check for gaps.

    Returns a dict with:
      - 'slots': ordered list of (snapshot_number, filepath or None) tuples,
                 where None indicates a missing snapshot.
      - 'step': inferred spacing between snapshot numbers.
      - 'irregular_gaps': (num_before, num_after) pairs where the gap wasn't
                 a clean multiple of `step` -- ambiguous missing count, so
                 these are reported but not auto-filled.
      - 'numbered': False if filenames couldn't be parsed numerically at all
                 (falls back to plain positional slots, no gap detection).
    """
    snapshot_files = collect_snapshot_files(input_dir, patterns=patterns, suffixes=suffixes)
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
        slot_info["slots"] = slot_info["slots"][start:(end+1)]

    return slot_info


# ==================================================================
# 3. interpolate_frame
# ==================================================================

def _contiguous_runs(indices: List[int]) -> List[List[int]]:
    """Given a list of integers, return a list of contiguous runs."""
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


def _interpolate_grid_block(b0, b1, field: str, t: float):
    """
    Linear interpolation of `field` between two flat grid-like objects that
    expose `.fields: Dict[str, np.ndarray]` directly (no `.levels`) -- this
    is the shape assumed for whatever `sph_to_grid()` returns.
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

    return type(h_before)(unit=h_before.unit, field_units=h_before.field_units,
                           levels=new_levels, object_name=h_before.object_name)


def _interpolate_snapshot_data(obj_before, obj_after, field: str, t: float):
    """Dispatch to hierarchy- or flat-grid-block interpolation, based on shape of the object."""
    if hasattr(obj_before, "levels"):
        return _interpolate_field_hierarchy(obj_before, obj_after, field, t)
    return _interpolate_grid_block(obj_before, obj_after, field, t)


def interpolate_frame(
    good_data: Dict[int, object],
    field: str,
    write_fn: Callable[[object, int], None],
    slot_info: Optional[Dict[str, object]] = None,
    missing_snapshot_numbers: Optional[Dict[int, int]] = None,
    interpolate_missing: bool = True,
    max_interp_gap: int = 3,
) -> Tuple[List[int], List[int]]:
    """
    Given the successfully-loaded data keyed by frame index (`good_data`) and
    the frames that are missing/failed (`missing_snapshot_numbers`, or derived
    from `slot_info`), interpolate short contiguous gaps and call
    `write_fn(data, frame_num)` for each filled frame.

    If `interpolate_missing` is False, no interpolation is attempted and every
    missing frame is reported as unfilled (write_fn is never called here).

    Returns (interpolated_frames, unfilled_frames).
    """
    if missing_snapshot_numbers is None:
        if slot_info is not None:
            missing_snapshot_numbers = {num: path for num, path in slot_info["slots"] if path is None}
        else:
            print("  [WARN] No missing_snapshot_numbers or slot_info provided -- cannot report snapshot numbers for missing frames.")
            missing_snapshot_numbers = {}

    interpolated_frames: List[int] = []
    unfilled_frames: List[int] = []

    error_frames = list(missing_snapshot_numbers.keys())

    if not interpolate_missing:
        return interpolated_frames, error_frames

    for run in _contiguous_runs(error_frames):
        gap_len = len(run)
        before, after = run[0] - 1, run[-1] + 1

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


# ==================================================================
# Small shared helpers used by the export_* functions below
# ==================================================================

def zip_vdb(output_dir: str) -> str:
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


def _object_name_from_output_dir(output_dir: str) -> str:
    """Derive a stable object name from the output folder name."""
    name = output_dir.rstrip(os.sep).split(os.sep)[-1]
    if not name:
        raise ValueError(f"Could not derive an object name from output_dir: '{output_dir}'")
    return name


def _field_names(fields_spec: Union[str, List[str], Dict[str, Callable], None]) -> Optional[List[str]]:
    """
    Normalize a load_particles-style `fields` argument down to the list of
    resulting field NAMES, regardless of whether it was given as a string,
    a list, or a {name: callable} dict of derived fields.
    """
    if fields_spec is None:
        return None
    if isinstance(fields_spec, str):
        return [fields_spec]
    if isinstance(fields_spec, dict):
        return list(fields_spec.keys())
    return list(fields_spec)


# ==================================================================
# Volume (grid/AMR) exports
# ==================================================================

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
    scale: Optional[float] = 1.0,
    preview_every: Optional[int] = 10,
    preview_dir: Optional[str] = None,
    zip_output: bool = False,
    delete_unzipped: bool = False,
) -> Dict[str, object]:
    """
    Volume snapshot directory -> VDB sequence + preview output.
    """
    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir) if object_name is None else object_name

    import yt
    from .volume_data import load_volume
    from .grid_to_vdb import hierarchy_to_multiple_vdbs, hierarchy_to_vdb

    def _write_vdb(hierarchy, frame_num):
        if multi_vdb:
            frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
            os.makedirs(frame_dir, exist_ok=True)
            hierarchy_to_multiple_vdbs(hierarchy, field=field, 
                                        file_name_prefix=os.path.join(frame_dir, f"{object_name}_frame{frame_num}"), log=log, scale=scale)
        else:
            hierarchy_to_vdb(hierarchy, field=field,
                              file_path=os.path.join(output_dir, f"{object_name}_frame{frame_num}.vdb"), log=log, scale=scale)

    # 1. resolve_slot: check for missing snapshots and build a slot list
    slot_info = resolve_slot(input_dir, start_frame=start_frame, end_frame=end_frame)
    slots = slot_info["slots"]
    missing_snapshot_numbers = {num: num for num, path in slots if path is None}
    print(f"Loading snapshots {start_frame if start_frame is not None else 0} to "
          f"{end_frame if end_frame is not None else len(slots) - 1} from '{input_dir}' into '{output_dir}'...")
    print(f"Missing snapshot numbers detected: {list(missing_snapshot_numbers.values())}")

    preview_samples = []
    global_min, global_max = float("inf"), float("-inf")
    good_hierarchies: Dict[int, object] = {}

    def _track_range(hierarchy):
        nonlocal global_min, global_max
        current_range = hierarchy.get_field_value_ranges(fields=field, log=log)
        if field not in current_range:
            return
        field_min, field_max = current_range[field]
        global_min, global_max = min(global_min, field_min), max(global_max, field_max)

    def _write_and_track_range(hierarchy, frame_num):
        _track_range(hierarchy)
        _write_vdb(hierarchy, frame_num)
        # so an interpolated frame that happens to land on the preview cadence
        # still gets previewed, same as a directly-loaded one
        if preview_every is not None and preview_every > 0 and (frame_num % preview_every) == 0:
            preview_samples.append((frame_num, hierarchy))

    # 2. Load snapshots and write VDBs
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):
        frame_num = frame_num + (start_frame if start_frame is not None else 0)
        
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}'.")
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            hierarchy = load_volume(ds, vtype=vtype, fields=[field], object_name=object_name, verbose=verbose)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            continue

        good_hierarchies[frame_num] = hierarchy
        # use the same writer as interpolated frames so preview collection stays in one place
        _write_and_track_range(hierarchy, frame_num)

    # 3. interpolate_frame: fill any gaps between neighboring good frames.
    # Done BEFORE generating previews, so interpolated frames that land on the
    # preview cadence are included alongside directly-loaded ones.
    interpolated_frames, unfilled_frames = interpolate_frame(
        good_hierarchies, field, _write_and_track_range,
        missing_snapshot_numbers=missing_snapshot_numbers,
        interpolate_missing=interpolate_missing, max_interp_gap=max_interp_gap,
    )

    field_range = (global_min, global_max)

    # 4. Write preview images (now including interpolated frames) using the global field range
    preview_samples.sort(key=lambda item: item[0])
    print(f"\nGenerating preview for frames: {[frame_num for frame_num, _ in preview_samples]}")
    for frame_num, hierarchy in preview_samples:
        preview_path = (os.path.join(output_dir, f"preview_{frame_num:04d}.png") if preview_dir is None
                         else os.path.join(preview_dir, f"preview_{frame_num:04d}.png"))
        if preview_dir is not None:
            os.makedirs(preview_dir, exist_ok=True)
        hierarchy.analyze_field_data(fields=field, output_path=preview_path, log=log,
                                      value_ranges={field: field_range})

    # 5. Optionally zip the frame_NNNN/ tree into a single VDB export archive
    zip_path = None
    if zip_output:
        zip_path = zip_vdb(output_dir)
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
        "zip_path": zip_path,
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
    """
    import yt
    from .volume_data import load_volume
    from .grid_to_surface import grid_to_surface, grid_to_ridge_surface
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)

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
                return grid_to_ridge_surface(block, field=field_name, plot_check=False, **ridge_kwargs)
            except Exception as e:
                print(f"  [WARNING] Ridge extraction failed for a block: {e}")
                return None
        else:
            return grid_to_surface(block, threshold=fixed_threshold, field=field_name,
                                    center=False, scale=1.0, plot_surface=False)

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
            if surface.normals is not None:
                normals.append(np.asarray(surface.normals, dtype=float))
            faces.append(face_arr + vertex_offset)
            vertex_offset += verts.shape[0]

        if not vertices:
            raise ValueError("No valid surfaces remained after merge filtering.")

        merged_vertices = np.concatenate(vertices, axis=0)
        merged_faces = np.concatenate(faces, axis=0) if faces else np.empty((0, 3), dtype=int)
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

    # 1. resolve_slot
    slot_info = resolve_slot(input_dir, end_frame=num_snapshot)
    slots = slot_info["slots"]
    missing_snapshot_numbers = {num: num for num, path in slots if path is None}

    exports = []
    fixed_threshold = None if ridge_surface else threshold
    good_hierarchies: Dict[int, object] = {}

    def _write_surface_frame(hierarchy, frame_num, interpolated=False):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _build_surface_for_hierarchy(hierarchy, fixed_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        save(surface_path, {object_name: surface})
        exports.append({
            "frame": frame_num, "path": frame_dir, "surface_path": surface_path,
            "threshold": fixed_threshold, "mode": "ridge" if ridge_surface else "isosurface",
            "status": "immature_amr_merge_prototype" + (" (interpolated)" if interpolated else ""),
        })

    # 2. Load snapshots, extract + merge block surfaces, write one surface.h5 per frame
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            hierarchy = load_volume(ds, vtype=vtype, fields=field)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            continue

        good_hierarchies[frame_num] = hierarchy

        if not ridge_surface and fixed_threshold is None:
            field_range = hierarchy.get_field_value_ranges(fields=field_name, log=False).get(field_name, (0.0, 1.0))
            fixed_threshold = float((field_range[0] + field_range[1]) / 2.0)

        _write_surface_frame(hierarchy, frame_num)

    # 3. interpolate_frame
    interpolated_frames, unfilled_frames = interpolate_frame(
        good_hierarchies, field_name, lambda h, fn: _write_surface_frame(h, fn, interpolated=True),
        missing_snapshot_numbers=missing_snapshot_numbers,
        interpolate_missing=interpolate_missing, max_interp_gap=max_interp_gap,
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


# ==================================================================
# Particle (SPH) exports
# ==================================================================

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
    interpolation of a missing frame well-defined here.
    """
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_vdb import grid_to_vdb

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)

    def _write_vdb_grid(volume, frame_num):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        file_arg = (os.path.join(frame_dir, object_name) if multi_vdb
                    else os.path.join(frame_dir, f"{object_name}.vdb"))
        grid_to_vdb(volume, field=field, scale=scale, file_path=file_arg, log=log)

    # 1. resolve_slot
    slot_info = resolve_slot(input_dir, end_frame=num_snapshot)
    slots = slot_info["slots"]
    missing_snapshot_numbers = {num: num for num, path in slots if path is None}

    exports = []
    good_volumes: Dict[int, object] = {}

    # 2. Load snapshots, rasterize particles onto a grid, write VDBs
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
            volume = sph_to_grid(particles, fields=field if fields is None else fields,
                                  res=res, intensive=intensive, center=center)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
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

    # 3. interpolate_frame
    interpolated_frames, unfilled_frames = interpolate_frame(
        good_volumes, field, _write_and_record,
        missing_snapshot_numbers=missing_snapshot_numbers,
        interpolate_missing=interpolate_missing, max_interp_gap=max_interp_gap,
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
    """
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_surface import grid_to_surface
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)

    user_threshold = threshold  # what the caller actually asked for; never mutated below
    rasterize_fields = _field_names(fields) if fields is not None else field

    def _surface_for_volume(volume, frame_threshold):
        return grid_to_surface(volume, threshold=frame_threshold, field=field,
                                center=center, scale=scale, plot_surface=False)

    def _threshold_for(volume):
        if user_threshold is None:
            field_range = volume.get_field_value_ranges(fields=field, log=log).get(field, (0.0, 1.0))
            return float(np.mean(field_range))
        return user_threshold

    def _write_surface_frame(volume, frame_num, interpolated=False):
        frame_threshold = _threshold_for(volume)
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        surface = _surface_for_volume(volume, frame_threshold)
        surface_path = os.path.join(frame_dir, "surface.h5")
        if surface is not None:
            save(surface_path, {object_name: surface})
        entry = {"frame": frame_num, "path": frame_dir, "surface_path": surface_path,
                 "threshold": frame_threshold}
        if interpolated:
            entry["interpolated"] = True
        exports.append(entry)

    # 1. resolve_slot
    slot_info = resolve_slot(input_dir, end_frame=num_snapshot)
    slots = slot_info["slots"]
    missing_snapshot_numbers = {num: num for num, path in slots if path is None}

    exports = []
    good_volumes: Dict[int, object] = {}

    # 2. Load snapshots, rasterize + extract surface, write one surface.h5 per frame
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file.")
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
            volume = sph_to_grid(particles, fields=rasterize_fields, res=res, intensive=intensive, center=center)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            continue

        good_volumes[frame_num] = volume
        _write_surface_frame(volume, frame_num)

    # 3. interpolate_frame
    interpolated_frames, unfilled_frames = interpolate_frame(
        good_volumes, field, lambda v, fn: _write_surface_frame(v, fn, interpolated=True),
        missing_snapshot_numbers=missing_snapshot_numbers,
        interpolate_missing=interpolate_missing, max_interp_gap=max_interp_gap,
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
    matching. Uses resolve_slot only (interpolate_frame is skipped by
    passing interpolate_missing=False, so gaps are reported, not filled).
    """
    import yt
    from .particle_data import load_particles
    from .save_load_hdf5 import save

    os.makedirs(output_dir, exist_ok=True)
    object_name = _object_name_from_output_dir(output_dir)

    # 1. resolve_slot
    slot_info = resolve_slot(input_dir, end_frame=num_snapshot)
    slots = slot_info["slots"]
    missing_snapshot_numbers = {num: num for num, path in slots if path is None}

    exports = []
    good_particles: Dict[int, object] = {}

    def _write_particles(particles, frame_num):
        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        particle_file = os.path.join(frame_dir, "particles.h5")
        save(particle_file, {object_name: particles})
        exports.append({"frame": frame_num, "path": frame_dir, "particle_file": particle_file})

    # 2. Load snapshots and write one particles.h5 per frame (no interpolation -- see docstring)
    for frame_num, (snapshot_number, snapshot_path) in enumerate(slots):
        if snapshot_path is None:
            print(f"  [ERROR] Snapshot number {snapshot_number} is missing from '{input_dir}' -- no matching file "
                  f"(not interpolated -- see docstring).")
            continue

        snapshot_name = os.path.basename(snapshot_path)
        try:
            ds = yt.load(snapshot_path)
            particles = load_particles(ds, ptype=ptype, fields=fields)
        except Exception as e:
            print(f"  [ERROR] Failed to process snapshot '{snapshot_name}': {e}")
            continue

        good_particles[frame_num] = particles
        _write_particles(particles, frame_num)

    # 3. interpolate_frame, disabled -- just used to fold error/missing frames into 'unfilled_frames'
    _, unfilled_frames = interpolate_frame(
        good_particles, field=None, write_fn=_write_particles,
        missing_snapshot_numbers=missing_snapshot_numbers,
        interpolate_missing=False,
    )
    # frames whose yt.load/load_particles call itself failed (not "missing" slots) also count as unfilled
    unfilled_frames = sorted(set(unfilled_frames) | (set(range(len(slots))) - set(good_particles) - set(missing_snapshot_numbers)))

    return {
        "object_name": object_name,
        "output_dir": output_dir,
        "snapshot_count": len(slots),
        "exports": exports,
        "unfilled_frames": unfilled_frames,
        "missing_snapshot_numbers": missing_snapshot_numbers,
        "irregular_gaps": slot_info["irregular_gaps"],
    }