# Processing Volume Data

*Covers `Backend/volume_data.py`, `Backend/grid_to_surface.py`, and `Backend/grid_to_vdb.py`.*

Volume data refers to simulation snapshots produced by **grid-based** codes, often using an **Adaptive Mesh Refinement (AMR)** algorithm, which represent the fluid on a hierarchy of nested rectangular grid blocks — finer blocks are added on top of coarser ones wherever extra resolution is needed. [Athena++](https://www.athena-astro.app/) is one example of a grid-based (Godunov) hydrodynamics code, and is used as the running example throughout this page.

## Overview of Volume Data Pipeline

The recommended reading order is: start with the one-shot export example, then drill down into the lower-level API if you need finer control. The high-level export path is the simplest way to go from a snapshot directory to Blender-friendly VDB files, while the lower-level routines are still kept available for custom inspection and manual pipeline building.

### A high-level pipeline: `export_volume_sequence(...)`

This is the integrated workflow for turning a snapshot directory into VDB files for Blender animation.

```python
from AstroVis import export_volume_sequence

result = export_volume_sequence(
    input_dir="snapshots",
    output_dir="exports",
    field="density",
    vtype="gas",
    preview_every=10,
    log=True,
    multi_vdb=True,
)

print(result["field_range"])      # global (min, max) used for material scaling
print(result["preview_paths"])    # saved preview PNGs for sampled frames
```
Use this as the default entry point when you want the whole volume-export workflow; the lower-level tools below are there for custom inspection or specialized processing.

What it does internally:

1. loads each snapshot with `yt.load()`
2. calls `load_volume()` to build the AMR hierarchy
3. computes the field range and preview slice via `analyze_field_data()`
4. calls `hierarchy_to_multiple_vdbs()` to export each frame to VDB files (`frame_0000/`, `frame_0001/`, ...)
5. saves previews every `preview_every` frames using the final global range
6. prints the final global min/max so the Blender material can reuse the same scale

### A Lower-Level example: load + inspect + export

```python
import yt
from AstroVis.Backend.volume_data import load_volume
from AstroVis.Backend.grid_to_vdb import hierarchy_to_multiple_vdbs

# 1) load a single snapshot
snapshot = "snapshot_000.hdf5"
ds = yt.load(snapshot)
hierarchy = load_volume(ds, vtype="gas", fields=["density"])

# 2) inspect field statistics explicitly
analysis = hierarchy.analyze_field_data(fields="density", log=True)
print(analysis["ranges"]["density"])

# 3) optionally save a preview image with your chosen field range
hierarchy.analyze_field_data(
    fields="density",
    output_path="density_preview.png",
    log=True,
    axis=0,
    percentile=50,
    value_ranges={"density": analysis["ranges"]["density"]},
)

# 4) export the frame to VDB files
hierarchy_to_multiple_vdbs(
    hierarchy,
    field="density",
    file_name_prefix="frame_0000/density",
    log=True,
)
```

## Data Structures

### `GridBlock`
The basic unit of volume data — a single uniform rectangular grid.

| Attribute | Type | Meaning |
|---|---|---|
| `block_id` | `int` | Identifier, unique within a level |
| `left_edge`, `right_edge` | `(3,) ndarray` | Physical bounds of the block |
| `dims` | `(3,) ndarray` | Voxel resolution along each axis |
| `fields` | `dict[str, ndarray]` | Field name → 3D array |
| `field_ranges` | `dict[str, tuple[float, float]]` | Cached min/max for each field in this block |

### `GridLevel`
Groups all `GridBlock`s at one AMR refinement level (same `cell_size`, not necessarily spatially contiguous).

| Attribute | Type | Meaning |
|---|---|---|
| `level` | `int` | AMR refinement level |
| `cell_size` | `(3,) ndarray` | Physical spacing at this level |
| `blocks` | `list[GridBlock]` | Blocks that belong to the level |
| `field_ranges` | `dict[str, tuple[float, float]]` | Cached aggregated min/max for the whole level |

### `FieldHierarchy`
The full multi-level AMR volume.

| Attribute | Type | Meaning |
|---|---|---|
| `unit` | `dict` | Length/mass/time units |
| `field_units` | `dict` | Per-field units |
| `levels` | `dict[int, GridLevel]` | All levels, keyed by level index |
| `field_ranges` | `dict[str, tuple[float, float]]` | Cached global min/max across the hierarchy |

## Loading the Data

### ```load_volume(ds, vtype="gas", fields=None, levels=None, region=None, block_per_axis=None, verbose=None, force_non_remap=False) -> FieldHierarchy```

| Param | Default | Meaning |
|---|---|---|
| `vtype` | `"gas"` | yt field type. Available `(vtype, field)` combinations can be checked via `ds.derived_field_list` / `ds.field_list`. |
| `fields` | `None` → `['density']` | Field name(s) to load. |
| `levels` | `None` | Restrict to these AMR levels (direct path only). `None` = all. Valid range is `0` to `ds.max_level`. |
| `region` | `None` | yt data container (sphere, box, ...) to restrict loading to, instead of the full domain. |
| `block_per_axis` | `None` (auto) | Forces the remap path at this subdivision; must be a multiple of 4. |
| `verbose` | `None` (auto) | Print per-block load lines; auto-enabled on the remap path. |
| `force_non_remap` | `False` | Always use the direct path, ignoring detected overlaps. |

```python
ds = yt.load("dataset")
hierarchy = load_volume(ds, vtype="gas", fields=["density", "pressure"])
```
With region constraint:
```python
box = ds.box([-0.5, -0.5, -0.5], [0.5, 0.5, 0.5])
hierarchy = load_volume(ds, fields=["density"], region=box)
```

### Methodology

`load_volume` automatically decides between two loading strategies:

1. **Direct** — reads blocks straight from `ds.index.grids`. Used when the internal helper `analyze_grid_structure` finds no overlapping grids at any level, which is the common case.
2. **Remap** — used when grids overlap, or when `block_per_axis` is explicitly given to force it. Rebuilds the volume from scratch on a non-overlapping layout via `covering_grid`:
   - At the finest level, the domain is tiled into `block_per_axis³` blocks.
   - At every coarser level, the **center core** of that same `block_per_axis³` grid is skipped (since the next-finer level already covers it), and only the remaining shell blocks are built.
   - This only produces gap-free coverage when `block_per_axis` is a multiple of 4, which `load_volume` enforces. When not provided, the internal helper `_infer_block_per_axis` guesses it from `(number of grids at the finest level)^(1/3)`, rounded up to the nearest multiple of 4.
   - Region filtering on this path is a bounding-box approximation via the internal helper `_region_bbox` — blocks only *partially* overlapping `region` are still included in full. Non-box regions are supported if they provide `get_bbox()`.
   - The center-skip scheme assumes refinement is centered on the domain center.

Pass `force_non_remap=True` to always use the direct path regardless of detected overlaps (fast, but AMR blending artifacts may appear where blocks overlap).

### Known limitations of remapping

- Remap-path region filtering is a bounding-box approximation — blocks only *partially* overlapping the region are still included in full.
- The center-skip remap assumes refinement is centered on the domain center; off-center nested refinement is not handled.

## Accessing the Data

`GridBlock` fields are a plain dict and can be accessed by key.
`FieldHierarchy` blocks are reached by indexing into `.levels`.

Useful attributes and methods:

| Member | Meaning |
|---|---|
| `GridBlock.keys()` | Shortcut for `.fields.keys()` |
| `GridBlock.get_field_value_ranges(fields=None, log=False)` | Compute min/max for the block and cache them |
| `GridLevel.get_field_value_ranges(fields=None, log=False)` | Aggregate min/max across blocks on a level |
| `FieldHierarchy.get_field_value_ranges(fields=None, log=False)` | Aggregate min/max across the hierarchy |
| `FieldHierarchy.add_block(level, block, cell_size)` | Insert a `GridBlock` |

```python
density = block.fields["density"]     # raw field array
block.keys()                          # ['density', 'pressure']

finest_level = max(hierarchy.levels)
for block in hierarchy.levels[finest_level].blocks:
    print(block.block_id, block.dims)

print(hierarchy.get_field_value_ranges(fields="density", log=True)["density"])
```

### ```FieldHierarchy.analyze_field_data(fields=None, log=False, axis=0, percentile=50.0, slice_pos=None, levels=None, output_path=None, value_ranges=None) -> dict```

This is the central inspection method on the loaded hierarchy. It can:

- compute the global field range for one or more fields
- optionally build a slice preview image with `output_path`
- optionally reuse a fixed value range for consistent color scaling across frames

It is the single place where the volume inspection and preview logic are combined, so the export pipeline and the manual inspection path share the same behavior.

```python
analysis = hierarchy.analyze_field_data(fields="density", log=True)
print(analysis["ranges"]["density"])

hierarchy.analyze_field_data(
    fields="density",
    output_path="density_slice.png",
    log=True,
    axis=0,
    percentile=50,
)
```

### Field ranges stored on the hierarchy

`load_volume(...)` computes and caches the global `(min, max)` values directly on the returned `FieldHierarchy` as `hierarchy.field_ranges`.

This is the clean default for the volume API: once the hierarchy is loaded, the field range is attached to the object and can be reused for preview scaling, export, and Blender material setup.

```python
hierarchy = load_volume(ds, vtype="gas", fields=["density"])
print(hierarchy.field_ranges["density"])
```

### ```export_volume_sequence(input_dir, output_dir, field="density", vtype="gas", preview_every=10, log=True, multi_vdb=True) -> dict```

Loads a snapshot directory once, exports all frames to VDB folders, saves preview images every `preview_every` frames, and reports the final global field range for Blender.

This is the simplest pathway when you want:
- one backend pass over the snapshot files,
- periodic preview images,
- and one consistent `field_min` / `field_max` range for the Blender material.

```python
result = export_volume_sequence("snapshots", "exports", field="density", multi_vdb=True)
print(result["field_range"])
```

### ```analyze_grid_structure(ds) -> GridStructureReport```

Inspects `ds.index.grids`, grouping by level and checking pairwise for overlap. Returns a report with:
- levels present, grid counts per level, and `refine_by`
- whether overlaps exist, and the overlapping pairs
- a **suggested `block_per_axis`** for the remap path, inferred from the finest level's grid count by `_infer_block_per_axis`

It's useful for inspecting a dataset's grid layout in detail.

## Exporting to VDB

To bring a volume into Blender for volume rendering (rather than extracting a surface from it), export to [OpenVDB](https://www.openvdb.org/) (`.vdb`) — a hierarchical, sparse volumetric format used across VFX/rendering tools (Blender, Houdini, ...) that Blender imports natively.

### ```grid_to_vdb(grid_data, field="density", scale=1.0, file_path=None, log=True)```

Exports a single `GridBlock` field to one `.vdb` file. `log=True` applies `log10` (clipped away from zero) before export — suitable for density-like fields that span many orders of magnitude. If `file_path` is omitted, defaults to `Block_{block_id}.vdb`.

### Exporting a full `FieldHierarchy`

Two options, differing in whether the hierarchy becomes one Blender object or many:

#### ```hierarchy_to_vdb(hierarchy, field="density", file_name_prefix="volume", scale=1.0, log=True)```

Exports **all levels, all blocks** into a **single** `.vdb` file, one internal grid per block (named `density_l{level}_b{block_id}`). The whole `FieldHierarchy` becomes one Blender volume object made of nested internal grids.

```python
hierarchy_to_vdb(hierarchy, field="density", file_name_prefix="frame_0050")
```

#### ```hierarchy_to_multiple_vdbs(hierarchy, field="density", file_name_prefix="volume", scale=1.0, log=True)```

Writes **one `.vdb` file per block** (`{prefix}_l{level}_b{block_id}.vdb`) instead, and also tracks and prints the global min/max of the field across all blocks. Each `GridBlock` becomes an individually addressable Blender object.

### Single file vs. multiple files

| | `hierarchy_to_vdb` | `hierarchy_to_multiple_vdbs` |
|---|---|---|
| Blender result | One volume object, nested internal grids | One object per block |
| Per-block visibility/toggling | No | Yes |
| Required for animation via `volume_animation` | No — that module expects the multi-file (or `frame_*`-partitioned) layout | **Yes** |
| Applying one shader uniformly | Simpler — one material assignment | Needs `create_combined_grid_material` to merge blocks in-shader, or a shared field range (`hierarchy_to_multiple_vdbs`'s printed global min/max is for exactly this) |

Use `hierarchy_to_vdb` for a single static frame you want to treat as one cohesive object; use `hierarchy_to_multiple_vdbs` whenever you need per-block/per-level control, or whenever the output feeds into an animated sequence.

## Extracting Surfaces from a Volume

Once you have a `GridBlock` (or a single block pulled from a `FieldHierarchy`), you can extract a mesh surface from it directly — useful for rendering a shock front or density threshold as a solid, rather than as a volume.

### `SurfaceData`
The resulting container.

| Attribute | Type | Meaning |
|---|---|---|
| `vertices` | `(N,3) ndarray` | Mesh vertices |
| `faces` | `(M,3) ndarray` | Mesh faces |
| `normals` | `(N,3) ndarray`, optional | Per-vertex normals |

Also exposes `.N_vertices`, `.N_faces`.

There are two extraction methods.

### 1. Isosurface extraction 
### ```grid_to_surface(grid_data, threshold, field=None, build_obj=False, center=True, scale=1.0, plot_surface=True, axis=0, slice_idx=None) -> SurfaceData```

A marching-cubes isosurface at a given `threshold` value of `field` (via `skimage.measure.marching_cubes`).  
Vertices are rescaled by `scale` and optionally recentered. `plot_surface=True` saves a diagnostic 2D slice with the isosurface threshold contour overlaid, for a quick visual check before committing to a full 3D extraction.  
If `build_obj=True`, an `.obj` is also exported for direct import into Blender.

```python
block = hierarchy.levels[max(hierarchy.levels)].blocks[0]  # a single finest-level block
surface = grid_to_surface(block, threshold=1.5, field="density")
```

### ```grid_to_surfaces(grid_data, threshold, fields=None, **kwargs) -> dict[str, SurfaceData]```

Runs `grid_to_surface` across multiple fields (`str`, `list[str]`, or `None` for every field in the block), passing through any keyword arguments.

### 2. Ridge surface extraction ```grid_to_ridge_surface(grid_data, field=None, sigma=1.2, lambda_pct=10, min_cluster_size=250, normal_k=20, grid_sigma=1.5, isovalue_pct=50, plot_check=True, print_components=True, axis=0, slice_idx=None, center=True, scale=1.0, build_obj=False) -> SurfaceData```

For extracting **filament/ridge-like structures** (e.g. shocks, dense filaments) rather than a fixed-value isosurface — useful when there isn't a single threshold that cleanly separates structure from background.

#### Methodology

1. **Ridge detection** — Gaussian-smooths the field (`sigma`), computes the Hessian at every voxel, and finds voxels where the smallest eigenvalue `l3` is below a percentile threshold (`lambda_pct`) *and* less than the second eigenvalue `l2` (indicating a ridge rather than a blob or plane). Non-maximum suppression along the dominant eigenvector direction thins this into a 1-voxel-wide ridge.
2. **Component filtering** — connected-component labeling on the ridge voxels; components smaller than `min_cluster_size` are discarded as noise. Set `print_components=True` to see a size-ranked table of kept/discarded components.
3. **Poisson surface reconstruction** — estimates a normal vector at each ridge point via local PCA of its `normal_k` nearest neighbors (oriented outward from the point cloud centroid), splats the normal field onto the grid, smooths it (`grid_sigma`), and solves the Poisson equation for an implicit scalar field `chi` via FFT. The final surface is the `isovalue_pct` percentile isocontour of `chi`, extracted via marching cubes.

`plot_check=True` saves a 3-panel diagnostic (raw ridge, cleaned ridge, chi field + isocontour).  
It is worth checking on a new field/dataset since `sigma`, `lambda_pct`, and `min_cluster_size` are dataset-dependent. 

`build_obj=True` exports an `.obj`. 

### Saving the surface
You can save the surface into a .hdf5 file and prepare it for Blender.
### `save(file_path, data, mode="w", compression="gzip", compression_opts=4)`

`data` is `{object_name: instance_or_list_of_instances}` — a list represents animation frames, and must be a single consistent type per object.  
`mode="a"` appends/replaces named objects while leaving other objects in an existing file untouched while `mode="w"` overwrites the whole file.


```python
save("stromgren_sphere.hdf5", {
    "OI_surface":       [OI_frame_0, OI_frame_1, ...],
    "OII_surface":      [OII_frame_0, OII_frame_1, ...],
})
```
## See also
- [`Animation`](../Blender/Animation_setup.md) — importing a VDB sequence produced here as an animated Blender volume
- [`Particle_Data`](Particle_Data.md) — the SPH-native counterpart to this module
