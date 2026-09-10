import os
import numpy as np
from dataclasses import dataclass, field
from typing import Union, Dict, Tuple, List, Optional


def _require_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for preview plotting. Install matplotlib to use "
            "preview_field_slice() or preview-enabled export_volume_sequence()."
        ) from exc
    return plt

@dataclass
class GridBlock:
    """
    A uniform rectangular grid, containing field data and metadata.
    This is the basic unit of volume data that will be converted to VDB
    and imported into Blender.
    """
    block_id: int
    left_edge: np.ndarray   # (3,) array of floats
    right_edge: np.ndarray  # (3,) array of floats
    dims: np.ndarray        # (3,) array of ints
    fields: Dict[str, np.ndarray]

    def keys(self):
        return list(self.fields.keys())


@dataclass
class GridLevel:
    """
    For AMR datasets, we group blocks by their refinement level. Each
    level contains multiple blocks of the same cell size. It may or may
    not be contiguous in space.
    """
    level: int
    cell_size: np.ndarray  # (3,) array of floats
    blocks: List[GridBlock] = field(default_factory=list)

    @property
    def num_blocks(self) -> int:
        return len(self.blocks)


@dataclass
class FieldHierarchy:
    """
    A hierarchical structure for organizing AMR volume data by level and
    block, with units.
    """
    unit: Dict[str, str]
    field_units: Dict[str, object] = field(default_factory=dict)
    levels: Dict[int, GridLevel] = field(default_factory=dict)

    def add_block(self, level: int, block: GridBlock, cell_size):
        if level not in self.levels:
            self.levels[level] = GridLevel(level=level, cell_size=cell_size)
        self.levels[level].blocks.append(block)

    def get_info(self):
        info = {}
        for level, lvl_data in self.levels.items():
            info[level] = {
                "num_blocks": lvl_data.num_blocks,
                "cell_size": lvl_data.cell_size,
            }
        return info


@dataclass
class GridStructureReport:
    """
    Result of analyze_grid_structure().
    """
    levels: List[int]
    grids_per_level: Dict[int, int]
    has_overlap: bool
    overlapping_pairs: List[Tuple[int, int, int]]  # (level, grid_id_1, grid_id_2)
    refine_by: int
    suggested_block_per_axis: int
    block_per_axis_source: str


def analyze_grid_structure(ds) -> GridStructureReport:
    """
    Inspect a yt dataset's AMR grid hierarchy and check whether block are overlapping.
    """
    grids_by_level: Dict[int, List] = {}
    for g in ds.index.grids:
        grids_by_level.setdefault(int(g.Level), []).append(g)
 
    overlapping_pairs: List[Tuple[int, int, int]] = []
    for lvl, grids in grids_by_level.items():
        if len(grids) <= 1:
            continue
        for i in range(len(grids)):
            for j in range(i + 1, len(grids)):
                g1_left, g1_right = grids[i].LeftEdge.v, grids[i].RightEdge.v
                g2_left, g2_right = grids[j].LeftEdge.v, grids[j].RightEdge.v
                if np.all(g1_left < g2_right) and np.all(g1_right > g2_left):
                    overlapping_pairs.append((lvl, int(grids[i].id), int(grids[j].id)))
 
    refine_by = int(np.atleast_1d(getattr(ds, "refine_by", 2))[0])
    suggested_block_per_axis, block_per_axis_source = _infer_block_per_axis(grids_by_level)
 
    return GridStructureReport(
        levels=sorted(grids_by_level.keys()),
        grids_per_level={lvl: len(g) for lvl, g in grids_by_level.items()},
        has_overlap=len(overlapping_pairs) > 0,
        overlapping_pairs=overlapping_pairs,
        refine_by=refine_by,
        suggested_block_per_axis=suggested_block_per_axis,
        block_per_axis_source=block_per_axis_source,
    )

def load_volume(
    ds,
    vtype: str = "gas",
    fields: Optional[List[str]] = None,
    levels: Optional[List[int]] = None,
    region=None,
    block_per_axis: Optional[int] = None,
    verbose: bool = None,
    force_non_remap: bool = False
) -> FieldHierarchy:
    """
    Load AMR volume data from a yt dataset, grouped by level.

    Grid structure is inspected by analyze_grid_structure and load 
    directly from ds.index.grids or remapping via covering_grid if overlapping or upon requested.

    Parameters
    ----------
    ds : yt.Dataset
        The yt dataset object.
    vtype : str
        yt field type (default: "gas")
    fields : list of str or None
        Field names, e.g. ["density", "temperature"]. Default: ["density"]
    levels : list or None
        AMR levels to include (native path only); None = all
    region : yt data container or None
        Optional region selector.
    block_per_axis : int or None
        Blocks-per-dimension to use if remapping is needed. If None
        (default), this is auto-detected from `ds` via
        `analyze_grid_structure`.

    Returns
    -------
    FieldHierarchy
        A structured hierarchy of grid blocks organized by AMR level,
        containing field data and units.
    """
    fields = list(fields) if fields is not None else ["density"]
 
    print(f"\n{'='*50}")
    print(f"Loading volume data from dataset: {ds}. Inspecting grid structure...")
    print(f"{'-'*50}")
 
    report = analyze_grid_structure(ds)
    print(f"  Levels found: {report.levels}")
    print(f"  Grids per level: {report.grids_per_level}")
    
    if force_non_remap:
        print("  force_non_remap=True: loading directly from ds.index.grids, ignoring overlaps.")
        if verbose is None:
            verbose = True
        return _load_amr_volume(ds, vtype=vtype, fields=fields, levels=levels, region=region, verbose=verbose)
    
    if report.has_overlap or block_per_axis is not None:
        chosen_bpa = block_per_axis if block_per_axis is not None else report.suggested_block_per_axis
        if chosen_bpa < 4 or chosen_bpa % 4 != 0:
            raise ValueError(
                f"block_per_axis={chosen_bpa} is invalid: the center-skip remap logic "
                "only produces gap-free coverage when block_per_axis is a multiple of 4 "
            )
        source = "user-specified, rebuilding at a different subdivision" if block_per_axis is not None else report.block_per_axis_source
        print(f"  Overlapping grids detected ({len(report.overlapping_pairs)} pair(s)).")
        print(f"  Block_per_axis={chosen_bpa} ({source}).")
        if verbose is None:
            verbose = True
        return _load_remap_amr_volume(
            ds, vtype=vtype, fields=fields, report=report,
            block_per_axis=chosen_bpa, levels=levels, region=region, verbose=verbose
        )

    print("  No overlapping grids detected.")
    if verbose is None:
        verbose = False
    return _load_amr_volume(ds, vtype=vtype, fields=fields, levels=levels, region=region, verbose = verbose)

def _get_field_units(ds, vtype: str, fields: List[str]) -> Dict[str, str]:
    """Shared helper: resolve field units once, used by both loading paths."""
    return {f: str(ds.field_info[(vtype, f)].units) for f in fields}


def _load_amr_volume(ds, vtype, fields, levels, region, verbose = False) -> FieldHierarchy:
    """Load blocks directly from ds.index.grids. """
    
    hierarchy = FieldHierarchy(
        unit={
            "length": ds.length_unit,
            "mass": ds.mass_unit,
            "time": ds.time_unit,
        },
        field_units=_get_field_units(ds, vtype, fields),
    )
    
    print(f"{'='*50}")
    print(f"Loading volume data directly...")
    print(f"  Unit: length={ds.length_unit}, mass={ds.mass_unit}, time={ds.time_unit}")
    print(f"  Field units: {hierarchy.field_units}")

    for grid in ds.index.grids:
        level = int(grid.Level)
        if levels is not None and level not in levels:
            continue

        if region is not None:
            selector = region & grid
            if selector is None:
                continue
            data_source = selector
        else:
            data_source = grid

        dims = np.array([int(d) for d in data_source.ActiveDimensions])
        left_edge = np.array([float(d) for d in data_source.LeftEdge.to_value()])
        right_edge = np.array([float(d) for d in data_source.RightEdge.to_value()])
        cell_size = np.array([float(d) for d in data_source.dds.to("code_length").value])

        field_dict = {f: data_source[(vtype, f)].in_base("code").v for f in fields}

        block = GridBlock(
            block_id=grid.id,
            left_edge=left_edge,
            right_edge=right_edge,
            dims=dims,
            fields=field_dict,
        )
        hierarchy.add_block(level=level, block=block, cell_size=cell_size)
        
        if verbose:
            print(f"  Added Block {grid.id} at Level {level}: Left Edge: {left_edge}, Right Edge: {right_edge}, Dims: {dims}")


    print(f"{'='*50}")
    return hierarchy

def _center_core_range(block_per_axis: int) -> Tuple[int, int]:
    """
    Return the region that gets skipped at non-max levels
    because the next-finer level's covering_grid will fully fills it.
    """
    
    core = block_per_axis // 2
    start = (block_per_axis - core) // 2
    return start, start + core - 1
 
 
def _infer_block_per_axis(grids_by_level: Dict[int, List]) -> Tuple[int, str]:
    """
    Recover `block_per_axis` from the dataset's own native grid layout,
    assuming the max level's grids tile a cubic block_per_axis**3 arrangement, 
    and non-max levels tile the same arrangement minus the centered core.
    Rounded up to the nearest multiple of 4 if needed. 

    Returns (block_per_axis, human-readable source description).
    """
    
    if not grids_by_level:
        return 4, "no grid info available, default using block_per_axis=4"
 
    max_level = max(grids_by_level.keys())
    n_max = len(grids_by_level[max_level])
 
    raw_candidate = round(n_max ** (1 / 3))
    candidate = max(4, int(np.ceil(raw_candidate / 4) * 4))
 
    if candidate ** 3 == n_max:
        source = f"inferred from level {max_level} having {n_max} = {candidate}^3 grids"
    else:
        source = (f"approximated from level {max_level} having {n_max} grids, "
                   f"not a perfect cube -- rounded to block_per_axis={candidate})")
 
    # Check against non-max levels
    expected_non_max = candidate ** 3 - (candidate // 2) ** 3
    for lvl, grids in grids_by_level.items():
        if lvl == max_level:
            continue
        if len(grids) != expected_non_max:
            source += (f"; note: level {lvl} has {len(grids)} grids, expected {expected_non_max} "
                        f"for block_per_axis={candidate}.")
            break
 
    return candidate, source
 
 
def _resolve_internal_block_edges(ds, block_id, current_level, max_level, block_per_axis, block_per_non_max_level, refine_by):
    """
    Map a linear block_id at `current_level` to physical (left_edge,
    right_edge). Non-max levels skip the center core of the
    block_per_axis**3 grid.
    Assumes the nested refinement is centered on the dataset's
    domain center.
    """
    
    is_max_level = (current_level == max_level)
    core_start, core_end = _center_core_range(block_per_axis)

    if not is_max_level:
        relative_id = block_id % block_per_non_max_level
        actual_grid_id = 0
        valid_count = 0
        for i in range(block_per_axis ** 3):
            ix = i % block_per_axis
            iy = (i // block_per_axis) % block_per_axis
            iz = (i // (block_per_axis ** 2)) % block_per_axis
            is_center = all(core_start <= idx <= core_end for idx in (ix, iy, iz))
            if not is_center:
                if valid_count == relative_id:
                    actual_grid_id = i
                    break
                valid_count += 1
    else:
        actual_grid_id = block_id % (block_per_axis ** 3)

    ix = actual_grid_id % block_per_axis
    iy = (actual_grid_id // block_per_axis) % block_per_axis
    iz = (actual_grid_id // (block_per_axis ** 2)) % block_per_axis
    idx3 = np.array([ix, iy, iz])

    domain_center = np.array([float(ds.domain_center[k].in_units("code_length").v) for k in range(3)])
    level_edge = np.array([
        float(ds.domain_width[k].in_units("code_length").v) / 2 / (refine_by ** current_level)
        for k in range(3)
    ])
    block_width = (2 * level_edge) / block_per_axis

    left_edge = domain_center - level_edge + idx3 * block_width
    return left_edge, left_edge + block_width
 
 
def _region_bbox(region) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Extraction of a (left_edge, right_edge) bounding box from
    a yt data container, for the remap path's block-level filtering.
    Non-box like (spheres, disks, ...) are handled via get_bbox() if
    available. If neither is available, include everything and warn.
    """
    
    if region is None:
        return None
    if hasattr(region, "left_edge") and hasattr(region, "right_edge"):
        left = np.array([float(x) for x in region.left_edge.to_value()])
        right = np.array([float(x) for x in region.right_edge.to_value()])
        return left, right
    if hasattr(region, "get_bbox"):
        left, right = region.get_bbox()
        return np.array([float(x) for x in left]), np.array([float(x) for x in right])
    return None
 
 
def _load_remap_amr_volume(
    ds, vtype, fields, report: GridStructureReport, block_per_axis: int,
    levels: Optional[List[int]] = None, region=None, verbose: bool = True
) -> FieldHierarchy:
    """
    Rebuild the volume onto a non-overlapping block layout via
    `covering_grid`.
    `levels` restricts which levels are rebuilt at all (max_level for the
    "skip the center core" logic is still the dataset's true max_level) 
    `region` is an approximation here. Remapped blocksare kept only if 
    its bounding box overlaps the region's bounding box (via `_region_bbox`).
    This may include blokcs that only partially overlap the region.
    If `region` doesn't expose a usable bounding box, filtering is skipped (with a warning).
    """
    
    print(f"{'='*50}")
    print(f"Remapping dataset: {ds}")
 
    min_level = min(report.levels)
    max_level = max(report.levels)
    print(f"  Refinement levels: {min_level} to {max_level}")
 
    active_levels = [lvl for lvl in range(min_level, max_level + 1) if levels is None or lvl in levels]
    if levels is not None:
        print(f"  Restricting to requested levels: {active_levels}")
 
    bbox = _region_bbox(region)
    if region is not None and bbox is None:
        print("  [WARNING] `region` has no left_edge/right_edge or get_bbox(); "
              "ignoring region filter for remapping.")
    region_left, region_right = bbox if bbox is not None else (None, None)
 
    block_per_non_max_level = block_per_axis ** 3 - (block_per_axis // 2) ** 3
    print(f"  Blocks per non-maximum level: {block_per_non_max_level}")
    print(f"  Blocks per maximum level: {block_per_axis ** 3}")
 
    fh = FieldHierarchy(
        unit={
            "length": ds.length_unit,
            "mass": ds.mass_unit,
            "time": ds.time_unit,
        },
        field_units=_get_field_units(ds, vtype, fields),
    )
    print(f"  Unit: length={ds.length_unit}, mass={ds.mass_unit}, time={ds.time_unit}")
    print(f"  Field units: {fh.field_units}")
    
    for level_idx in active_levels:
        num_blocks = (block_per_axis ** 3) if level_idx == max_level else block_per_non_max_level
        print(f"{'-'*50}")
        print(f"Processing Level {level_idx} with up to {num_blocks} blocks.")
 
        # Native cell size at this level, derived from the domain grid
        # itself rather than from a raw ds.index.grids read (those grids
        # are the ones that overlap, so we can't trust their .dds here).
        level_cell_size = np.array([
            float(ds.domain_width[k].in_units("code_length").v)
            / int(ds.domain_dimensions[k]) / (report.refine_by ** level_idx)
            for k in range(3)
        ])
        print(f"  Level {level_idx} cell size: {level_cell_size}")
        skipped = 0
        for b_id in range(num_blocks):
            left, right = _resolve_internal_block_edges(
                ds, b_id, level_idx, max_level, block_per_axis, block_per_non_max_level, report.refine_by
            )
 
            if region_left is not None:
                overlaps = np.all(left < region_right) and np.all(right > region_left)
                if not overlaps:
                    skipped += 1
                    continue
 
            dims = tuple(
                int(round((right[k] - left[k]) / level_cell_size[k])) for k in range(3)
            )
 
            grid = ds.covering_grid(level=level_idx, left_edge=left, dims=dims)
            data = {f: grid[(vtype, f)].in_base("code").v for f in fields}
 
            block = GridBlock(
                block_id=b_id,
                left_edge=left,
                right_edge=right,
                dims=np.array(dims),
                fields=data,
            )
            fh.add_block(level=level_idx, block=block, cell_size=level_cell_size)
            if verbose:
                print(f"  Added Block {b_id} at Level {level_idx}: "
                  f"Left Edge: {left}, Right Edge: {right}, Dims: {dims}")
 
        if region_left is not None and skipped:
            print(f"  Skipped {skipped} block(s) at Level {level_idx} outside region bbox.")
 
    print(f"{'='*50}")
    print(f"Finished remapping volume dataset {ds}.")
    return fh


def get_field_value_ranges(
    data: Union[GridBlock, FieldHierarchy],
    fields: Union[str, List[str]] = None,
    log: bool = False,
) -> Dict[str, Tuple[float, float]]:
    """
    Return global min/max ranges for one or more fields from a GridBlock or
    FieldHierarchy.
    """
    def _transform_values(values: np.ndarray) -> np.ndarray:
        if not log:
            return values
        return np.log10(np.clip(values, a_min=1e-10, a_max=None))

    if isinstance(data, GridBlock):
        all_blocks = [data]
    elif isinstance(data, FieldHierarchy):
        all_blocks = [
            block
            for level in data.levels.values()
            for block in level.blocks
        ]
    else:
        raise TypeError(f"Expected GridBlock or FieldHierarchy, got {type(data).__name__}")

    if not all_blocks:
        return {}

    if fields is None:
        fields = sorted({field_name for block in all_blocks for field_name in block.fields})
    elif isinstance(fields, str):
        fields = [fields]

    ranges = {}
    for field_name in fields:
        values = [
            _transform_values(block.fields[field_name].ravel())
            for block in all_blocks
            if field_name in block.fields
        ]
        if not values:
            print(f"  [WARNING] Field '{field_name}' not found in any block; skipping range summary.")
            continue

        merged = np.concatenate(values)
        ranges[field_name] = (float(merged.min()), float(merged.max()))

    return ranges


def export_volume_sequence(
    input_dir: str,
    output_dir: str,
    field: str = "density",
    vtype: str = "gas",
    preview_every: Optional[int] = 10,
    log: bool = True,
) -> Dict[str, object]:
    """
    Load a snapshot directory once, export each frame to VDB immediately,
    cache periodic preview frames, and then save previews using the final
    global range so Blender can reuse the same field_min/field_max.
    """
    import yt
    from .grid_to_vdb import hierarchy_to_multiple_vdbs

    snapshot_names = sorted(
        name for name in os.listdir(input_dir)
        if name.endswith((".athdf", ".hdf5", ".h5"))
    )
    if not snapshot_names:
        raise ValueError(f"No supported snapshot files found in: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    preview_samples = []
    global_min = float("inf")
    global_max = float("-inf")

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        hierarchy = load_volume(ds, vtype=vtype, fields=[field])

        current_range = get_field_value_ranges(hierarchy, fields=field, log=log)
        if field not in current_range:
            raise ValueError(f"Field '{field}' was not found in snapshot '{snapshot_name}'.")

        field_min, field_max = current_range[field]
        global_min = min(global_min, field_min)
        global_max = max(global_max, field_max)

        if preview_every is not None and preview_every > 0 and (frame_num % preview_every) == 0:
            preview_samples.append((frame_num, hierarchy))

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)
        hierarchy_to_multiple_vdbs(
            hierarchy,
            field=field,
            file_name_prefix=os.path.join(frame_dir, field),
            log=log,
        )

    field_range = (global_min, global_max)
    preview_paths = []
    for frame_num, hierarchy in preview_samples:
        preview_path = os.path.join(output_dir, f"preview_{frame_num:04d}.png")
        preview_field_slice(
            hierarchy,
            fields=field,
            output_path=preview_path,
            log=log,
            value_ranges={field: field_range},
        )
        preview_paths.append(preview_path)

    range_label = "log10" if log else "linear"
    print(f"Final global {range_label} range for '{field}': {field_range}")
    print(f"Use field_min={field_range[0]:.6g} and field_max={field_range[1]:.6g} in Blender.")

    return {
        "field": field,
        "field_range": field_range,
        "preview_paths": preview_paths,
        "snapshot_count": len(snapshot_names),
    }


def preview_field_slice(
    data: Union[GridBlock, FieldHierarchy],
    fields: Union[str, List[str]] = None,
    axis: int = 0,
    percentile: float = 50.0,
    slice_pos: float = None,
    levels: List[int] = None,
    output_path: str = "preview.png",
    log: bool = False,
    value_ranges: Optional[Union[Tuple[float, float], Dict[str, Tuple[float, float]]]] = None,
):
    """
    Preview field slices from either a single GridBlock or a full AMR
    FieldHierarchy. For a hierarchy, all blocks across levels that
    intersect the slice plane are composited onto ONE set of axes per
    field, positioned by their own left_edge/right_edge, with finer
    levels drawn on top of coarser ones.

    Parameters
    ----------
    data       : GridBlock or FieldHierarchy
    fields     : str or list[str] or None
        Field name(s) to preview. If None, previews every field found.
    axis       : int   0='z', 1='y', 2='x' (matches load_volume convention)
    percentile : float
        Auto-detect the slice position as this percentile (0-100) of the
        domain extent along `axis`. Default 50 = middle. Ignored if
        `slice_pos` is given explicitly.
    slice_pos  : float or None
        Explicit physical coordinate along `axis` to slice at. Overrides
        `percentile` when given.
    levels     : list[int] or None
        AMR levels to include (FieldHierarchy only); None = all levels.
    output_path : str
        Path to save the preview figure.
    log : bool
        If True, apply log10 scaling (with clipping at 1e-10) to both the
        slice image values and histogram values before plotting.
    value_ranges : (min, max) tuple, dict[str, (min, max)], or None
        Fixed plotting range to reuse across calls. Use a single tuple for
        every field, or a dict keyed by field name for per-field ranges.
    """
    def _transform_preview_values(values: np.ndarray) -> np.ndarray:
        if not log:
            return values
        return np.log10(np.clip(values, a_min=1e-10, a_max=None))

    def _resolve_preview_range(field_name: str):
        if value_ranges is None:
            return None

        if isinstance(value_ranges, dict):
            if field_name not in value_ranges:
                return None
            range_values = value_ranges[field_name]
        else:
            range_values = value_ranges

        if len(range_values) != 2:
            raise ValueError("value_ranges entries must be (min, max) pairs.")

        range_min, range_max = float(range_values[0]), float(range_values[1])
        if range_min >= range_max:
            raise ValueError("value_ranges entries must satisfy min < max.")

        return range_min, range_max

    if isinstance(data, GridBlock):
        plt = _require_matplotlib()
        all_blocks = [(0, data)]
        cell_size_map = {0: (data.right_edge - data.left_edge) / data.dims}
    elif isinstance(data, FieldHierarchy):
        plt = _require_matplotlib()
        level_ids = sorted(data.levels.keys()) if levels is None else sorted(levels)
        all_blocks = [
            (lvl, block)
            for lvl in level_ids if lvl in data.levels
            for block in data.levels[lvl].blocks
        ]
        cell_size_map = {lvl: data.levels[lvl].cell_size for lvl in level_ids if lvl in data.levels}
    else:
        raise TypeError(f"Expected GridBlock or FieldHierarchy, got {type(data).__name__}")

    if not all_blocks:
        print("  [WARNING] No blocks found for requested levels.")
        return

    if fields is None:
        fields = sorted({f for _, b in all_blocks for f in b.fields})
    elif isinstance(fields, str):
        fields = [fields]

    valid_fields = [f for f in fields if any(f in b.fields for _, b in all_blocks)]
    for f in fields:
        if f not in valid_fields:
            print(f"  [WARNING] Field '{f}' not found in any block; skipping.")
    if not valid_fields:
        print("  [WARNING] No valid fields to preview.")
        return

    all_left = np.min([b.left_edge for _, b in all_blocks], axis=0)
    all_right = np.max([b.right_edge for _, b in all_blocks], axis=0)
    if slice_pos is None:
        pct = min(max(percentile, 0.0), 100.0)
        slice_pos = all_left[axis] + (pct / 100.0) * (all_right[axis] - all_left[axis])

    remaining_axes = [a for a in (0, 1, 2) if a != axis]
    row_axis, col_axis = remaining_axes

    n = len(valid_fields)
    fig, axes_grid = plt.subplots(n, 2, figsize=(12, 5 * n), squeeze=False)
    fig.suptitle(f"Field Preview  |  axis={axis}  |  slice_pos={slice_pos:.4g}")

    transformed_values = {
        fname: np.concatenate([
            _transform_preview_values(b.fields[fname].ravel())
            for _, b in all_blocks if fname in b.fields
        ])
        for fname in valid_fields
    }
    auto_ranges = get_field_value_ranges(data, fields=valid_fields, log=log)
    plot_ranges = {
        fname: _resolve_preview_range(fname) or auto_ranges[fname]
        for fname in valid_fields
    }

    scale_label = "log10" if log else "linear"
    for fname in valid_fields:
        print(
            f"Preview field '{fname}': using {scale_label} range "
            f"[{plot_ranges[fname][0]:.4g}, {plot_ranges[fname][1]:.4g}]"
        )

    for row, fname in enumerate(valid_fields):
        ax_img, ax_hist = axes_grid[row, 0], axes_grid[row, 1]

        hits = []
        for lvl, block in all_blocks:
            if fname not in block.fields:
                continue
            if not (block.left_edge[axis] <= slice_pos < block.right_edge[axis]):
                continue
            cell = cell_size_map[lvl]
            idx = int((slice_pos - block.left_edge[axis]) / cell[axis])
            idx = min(max(idx, 0), block.dims[axis] - 1)
            slice_2d = np.take(block.fields[fname], idx, axis=axis)
            slice_2d = _transform_preview_values(slice_2d)
            hits.append((lvl, block, slice_2d))

        field_label = f"log10({fname})" if log else fname
        vmin, vmax = plot_ranges[fname]
        if not hits:
            ax_img.set_title(f"'{fname}'  |  no blocks intersect slice")
        else:
            im = None
            for lvl, block, slice_2d in hits:
                extent = [
                    block.left_edge[col_axis], block.right_edge[col_axis],
                    block.left_edge[row_axis], block.right_edge[row_axis],
                ]
                im = ax_img.imshow(
                    slice_2d, cmap='viridis', origin='lower',
                    extent=extent, vmin=vmin, vmax=vmax,
                    zorder=lvl,
                )
            ax_img.set_xlim(all_left[col_axis], all_right[col_axis])
            ax_img.set_ylim(all_left[row_axis], all_right[row_axis])
            ax_img.set_title(f"'{fname}'  |  {len(hits)} blocks, levels {sorted({l for l, _, _ in hits})}")
            cbar = plt.colorbar(im, ax=ax_img)
            cbar.set_label(field_label)

        vals = transformed_values[fname]
        ax_hist.hist(vals, bins=100, range=(vmin, vmax), color='steelblue')
        ax_hist.set_yscale('log')
        ax_hist.set_title(f"'{fname}' value distribution")
        ax_hist.set_xlabel(field_label)
        ax_hist.set_ylabel("Voxel count (log)")

    plt.tight_layout()
    plt.savefig(f"{output_path}", dpi=150)
    plt.show()
    print(f"Saved: {output_path}")
