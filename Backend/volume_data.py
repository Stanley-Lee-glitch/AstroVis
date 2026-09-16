import os
import numpy as np
from dataclasses import dataclass, field
from typing import Union, Dict, Tuple, List, Optional


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
    field_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    def keys(self):
        return list(self.fields.keys())

    def get_field_value_ranges(
        self,
        fields: Union[str, List[str]] = None,
        log: bool = False,
    ) -> Dict[str, Tuple[float, float]]:
        """Compute and cache min/max values for this block."""
        if fields is None:
            fields = list(self.fields.keys())
        elif isinstance(fields, str):
            fields = [fields]

        ranges = {}
        for field_name in fields:
            if field_name not in self.fields:
                continue
            values = self.fields[field_name].ravel()
            if log:
                values = np.log10(np.clip(values, a_min=1e-10, a_max=None))
            ranges[field_name] = (float(np.min(values)), float(np.max(values)))

        self.field_ranges = ranges
        return dict(ranges)


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
    field_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    @property
    def num_blocks(self) -> int:
        return len(self.blocks)

    def get_field_value_ranges(
        self,
        fields: Union[str, List[str]] = None,
        log: bool = False,
    ) -> Dict[str, Tuple[float, float]]:
        """Compute and cache min/max values aggregated over this level."""
        if not self.blocks:
            self.field_ranges = {}
            return {}

        if fields is None:
            fields = sorted({field_name for block in self.blocks for field_name in block.fields})
        elif isinstance(fields, str):
            fields = [fields]

        ranges = {}
        for field_name in fields:
            values = [
                block.get_field_value_ranges(fields=[field_name], log=log)[field_name]
                for block in self.blocks
                if field_name in block.fields
            ]
            if not values:
                continue
            mins = [v[0] for v in values]
            maxs = [v[1] for v in values]
            ranges[field_name] = (float(min(mins)), float(max(maxs)))

        self.field_ranges = ranges
        return dict(ranges)


@dataclass
class FieldHierarchy:
    """
    A hierarchical structure for organizing AMR volume data by level and
    block, with units.
    """
    unit: Dict[str, str]
    field_units: Dict[str, object] = field(default_factory=dict)
    levels: Dict[int, GridLevel] = field(default_factory=dict)
    field_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    def add_block(self, level: int, block: GridBlock, cell_size):
        if level not in self.levels:
            self.levels[level] = GridLevel(level=level, cell_size=cell_size)
        self.levels[level].blocks.append(block)

    @staticmethod
    def analyze_grid_structure(ds) -> "GridStructureReport":
        """
        Inspect a yt dataset's AMR grid hierarchy and check whether blocks overlap.
        This is the dataset-level structure analysis used by load_volume().
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

        if not grids_by_level:
            suggested_block_per_axis = 4
            block_per_axis_source = "no grid info available, default using block_per_axis=4"
        else:
            max_level = max(grids_by_level.keys())
            n_max = len(grids_by_level[max_level])
            raw_candidate = round(n_max ** (1 / 3))
            suggested_block_per_axis = max(4, int(np.ceil(raw_candidate / 4) * 4))

            if suggested_block_per_axis ** 3 == n_max:
                block_per_axis_source = f"inferred from level {max_level} having {n_max} = {suggested_block_per_axis}^3 grids"
            else:
                block_per_axis_source = (
                    f"approximated from level {max_level} having {n_max} grids, "
                    f"not a perfect cube -- rounded to block_per_axis={suggested_block_per_axis}"
                )

            expected_non_max = suggested_block_per_axis ** 3 - (suggested_block_per_axis // 2) ** 3
            for lvl, count in grids_by_level.items():
                if lvl == max_level:
                    continue
                if count != expected_non_max:
                    block_per_axis_source += (
                        f"; note: level {lvl} has {count} grids, expected {expected_non_max} "
                        f"for block_per_axis={suggested_block_per_axis}."
                    )
                    break

        return GridStructureReport(
            levels=sorted(grids_by_level.keys()),
            grids_per_level={lvl: len(g) for lvl, g in grids_by_level.items()},
            has_overlap=len(overlapping_pairs) > 0,
            overlapping_pairs=overlapping_pairs,
            refine_by=refine_by,
            suggested_block_per_axis=suggested_block_per_axis,
            block_per_axis_source=block_per_axis_source,
        )

    def get_field_value_ranges(
        self,
        fields: Union[str, List[str]] = None,
        log: bool = False,
    ) -> Dict[str, Tuple[float, float]]:
        """Compute and cache the global min/max range for this hierarchy."""
        if not self.levels:
            self.field_ranges = {}
            return {}

        if fields is None:
            fields = sorted({field_name for level in self.levels.values() for block in level.blocks for field_name in block.fields})
        elif isinstance(fields, str):
            fields = [fields]

        ranges = {}
        for field_name in fields:
            values = [
                level.get_field_value_ranges(fields=[field_name], log=log).get(field_name)
                for level in self.levels.values()
                if field_name in {b_name for block in level.blocks for b_name in block.fields}
            ]
            values = [v for v in values if v is not None]
            if not values:
                continue
            mins = [v[0] for v in values]
            maxs = [v[1] for v in values]
            ranges[field_name] = (float(min(mins)), float(max(maxs)))

        self.field_ranges = ranges
        return dict(ranges)

    def analyze_field_data(
        self,
        fields: Union[str, List[str]] = None,
        log: bool = False,
        axis: int = 0,
        percentile: float = 50.0,
        slice_pos: float = None,
        levels: List[int] = None,
        output_path: str = None,
        value_ranges: Optional[Union[Tuple[float, float], Dict[str, Tuple[float, float]]]] = None,
    ) -> Dict[str, object]:
        """High-level analysis for this hierarchy, including optional preview generation."""
        def _transform_values(values: np.ndarray) -> np.ndarray:
            if not log:
                return values
            return np.log10(np.clip(values, a_min=1e-10, a_max=None))

        def _collect_blocks():
            level_ids = sorted(self.levels.keys()) if levels is None else sorted(levels)
            blocks = [
                (lvl, block)
                for lvl in level_ids if lvl in self.levels
                for block in self.levels[lvl].blocks
            ]
            cell_size_map = {
                lvl: self.levels[lvl].cell_size for lvl in level_ids if lvl in self.levels
            }
            return blocks, cell_size_map

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

        all_blocks, cell_size_map = _collect_blocks()
        if not all_blocks:
            return {"fields": [], "ranges": {}, "preview": None}

        if fields is None:
            fields = sorted({field_name for _, block in all_blocks for field_name in block.fields})
        elif isinstance(fields, str):
            fields = [fields]

        valid_fields = [f for f in fields if any(f in block.fields for _, block in all_blocks)]
        for field_name in fields:
            if field_name not in valid_fields:
                print(f"  [WARNING] Field '{field_name}' not found in any block; skipping.")
        if not valid_fields:
            return {"fields": [], "ranges": {}, "preview": None}

        ranges = self.get_field_value_ranges(fields=valid_fields, log=log)

        preview = None
        if output_path is not None:
            import matplotlib.pyplot as plt
            all_left = np.min([block.left_edge for _, block in all_blocks], axis=0)
            all_right = np.max([block.right_edge for _, block in all_blocks], axis=0)
            if slice_pos is None:
                pct = min(max(percentile, 0.0), 100.0)
                slice_pos = all_left[axis] + (pct / 100.0) * (all_right[axis] - all_left[axis])

            remaining_axes = [a for a in (0, 1, 2) if a != axis]
            row_axis, col_axis = remaining_axes

            fig, axes_grid = plt.subplots(len(valid_fields), 2, figsize=(12, 5 * len(valid_fields)), squeeze=False)
            fig.suptitle(f"Field Preview  |  axis={axis}  |  slice_pos={slice_pos:.4g}")

            plot_ranges = {
                fname: _resolve_preview_range(fname) or ranges[fname]
                for fname in valid_fields
            }

            for row, field_name in enumerate(valid_fields):
                ax_img, ax_hist = axes_grid[row, 0], axes_grid[row, 1]
                hits = []
                for lvl, block in all_blocks:
                    if field_name not in block.fields:
                        continue
                    if not (block.left_edge[axis] <= slice_pos < block.right_edge[axis]):
                        continue
                    cell = cell_size_map[lvl]
                    idx = int((slice_pos - block.left_edge[axis]) / cell[axis])
                    idx = min(max(idx, 0), block.dims[axis] - 1)
                    slice_2d = np.take(block.fields[field_name], idx, axis=axis)
                    slice_2d = _transform_values(slice_2d)
                    hits.append((lvl, block, slice_2d))

                if not hits:
                    ax_img.set_title(f"'{field_name}'  |  no blocks intersect slice")
                    ax_hist.set_visible(False)
                    continue

                vmin, vmax = plot_ranges[field_name]
                for lvl, block, slice_2d in hits:
                    extent = [
                        block.left_edge[col_axis], block.right_edge[col_axis],
                        block.left_edge[row_axis], block.right_edge[row_axis],
                    ]
                    ax_img.imshow(
                        slice_2d, cmap='viridis', origin='lower',
                        extent=extent, vmin=vmin, vmax=vmax,
                    )
                ax_img.set_title(f"{field_name} | axis={axis}")
                ax_img.set_xlabel(['x', 'y', 'z'][col_axis])
                ax_img.set_ylabel(['x', 'y', 'z'][row_axis])

                combined = np.concatenate([v for _, _, v in hits])
                ax_hist.hist(combined.ravel(), bins=50, range=(vmin, vmax), color='C0')
                ax_hist.set_title("Value distribution")
                ax_hist.set_xlabel("value")
                ax_hist.set_ylabel("count")

            fig.tight_layout(rect=[0, 0, 1, 0.97])
            fig.savefig(output_path, dpi=180)
            plt.close(fig)
            preview = {"path": output_path, "axis": axis, "slice_pos": slice_pos}

        return {
            "fields": valid_fields,
            "ranges": ranges,
            "preview": preview,
        }



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
 
    report = FieldHierarchy.analyze_grid_structure(ds)
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

def _load_amr_volume(ds, vtype, fields, levels, region, verbose = False) -> FieldHierarchy:
    """Load blocks directly from ds.index.grids. """
    
    hierarchy = FieldHierarchy(
        unit={
            "length": ds.length_unit,
            "mass": ds.mass_unit,
            "time": ds.time_unit,
        },
        field_units={
            f: str(ds.field_info[(vtype, f)].units) for f in fields
        },
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


    hierarchy.get_field_value_ranges(fields=fields, log=False)
    print(f"  Cached field ranges: {hierarchy.field_ranges}")
    print(f"{'='*50}")
    return hierarchy

def _load_remap_amr_volume(
    ds, vtype, fields, report: GridStructureReport, block_per_axis: int,
    levels: Optional[List[int]] = None, region=None, verbose: bool = True
) -> FieldHierarchy:
    """
    Rebuild overlapping AMR data onto a non-overlapping block layout using
    `covering_grid`, while keeping the logic direct and local to this function.
    """

    def _center_core_range() -> Tuple[int, int]:
        core = block_per_axis // 2
        start = (block_per_axis - core) // 2
        return start, start + core - 1

    def _region_bbox() -> Optional[Tuple[np.ndarray, np.ndarray]]:
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

    def _resolve_internal_block_edges(block_id: int, current_level: int, max_level: int):
        is_max_level = (current_level == max_level)
        core_start, core_end = _center_core_range()

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

        domain_center = np.array([
            float(ds.domain_center[k].in_units("code_length").v) for k in range(3)
        ])
        level_edge = np.array([
            float(ds.domain_width[k].in_units("code_length").v) / 2 / (report.refine_by ** current_level)
            for k in range(3)
        ])
        block_width = (2 * level_edge) / block_per_axis
        left_edge = domain_center - level_edge + idx3 * block_width
        return left_edge, left_edge + block_width

    print(f"{'='*50}")
    print(f"Remapping dataset: {ds}")

    min_level = min(report.levels)
    max_level = max(report.levels)
    print(f"  Refinement levels: {min_level} to {max_level}")

    active_levels = [lvl for lvl in range(min_level, max_level + 1) if levels is None or lvl in levels]
    if levels is not None:
        print(f"  Restricting to requested levels: {active_levels}")

    bbox = _region_bbox()
    if region is not None and bbox is None:
        print("  [WARNING] `region` has no left_edge/right_edge or get_bbox(); ignoring region filter for remapping.")
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
        field_units={
            f: str(ds.field_info[(vtype, f)].units) for f in fields
        },
    )
    print(f"  Unit: length={ds.length_unit}, mass={ds.mass_unit}, time={ds.time_unit}")
    print(f"  Field units: {fh.field_units}")

    for level_idx in active_levels:
        num_blocks = (block_per_axis ** 3) if level_idx == max_level else block_per_non_max_level
        print(f"{'-'*50}")
        print(f"Processing Level {level_idx} with up to {num_blocks} blocks.")

        level_cell_size = np.array([
            float(ds.domain_width[k].in_units("code_length").v)
            / int(ds.domain_dimensions[k]) / (report.refine_by ** level_idx)
            for k in range(3)
        ])
        print(f"  Level {level_idx} cell size: {level_cell_size}")
        skipped = 0

        for b_id in range(num_blocks):
            left, right = _resolve_internal_block_edges(b_id, level_idx, max_level)

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
                print(f"  Added Block {b_id} at Level {level_idx}: Left Edge: {left}, Right Edge: {right}, Dims: {dims}")

        if region_left is not None and skipped:
            print(f"  Skipped {skipped} block(s) at Level {level_idx} outside region bbox.")

    fh.get_field_value_ranges(fields=fields, log=False)
    print(f"  Cached field ranges: {fh.field_ranges}")
    print(f"{'='*50}")
    print(f"Finished remapping volume dataset {ds}.")
    return fh
