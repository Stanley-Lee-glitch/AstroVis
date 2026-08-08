import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple, List

@dataclass
class GridBlock:
    """
    A uniform rectangular grid, containing field data and metadata. 
    This is the basic unit of volume data that will be converted to VDB and imported into Blender.
    """
    block_id: int
    left_edge: np.ndarray  # (3,) array of floats
    right_edge: np.ndarray  # (3,) array of floats
    dims: np.ndarray  # (3,) array of ints
    fields: Dict[str, np.ndarray]
    
    def keys(self):
        return list(self.fields.keys())

@dataclass
class GridLevel:
    """
    For AMR datasets, we group blocks by their refinement level. Each level contains multiple blocks of the same cell size.
    It may or may not be contiguous in space.
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
    A hierarchical structure for organizing AMR volume data by level and block with units.
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


def load_volume(ds, vtype = "gas", fields=["density"], levels=None, region=None):
    """
    Load AMR volume data from a yt dataset, grouped by level.

    Parameters
    ----------
    ds : yt.Dataset
        The yt dataset object.
    fields : list of str or None
        Field names, e.g. ["density", "temperature"]
        Default: ["density"]
    levels : list or None
        AMR levels to include; None = all
    region : yt data container or None
        Optional region selector
    field_type : str
        yt field type (default: "gas")

    Returns
    -------
    FieldHierarchy
         A structured hierarchy of grid blocks organized by AMR level, containing field data and units.
        }
    """
    # Initialize unit and output structure
    
    hierarchy = FieldHierarchy(
        unit = {
            "length": ds.length_unit,
            "mass": ds.mass_unit,
            "time": ds.time_unit,
        }
    )
    
    # Loop over block in the grids and group by level
    for grid in ds.index.grids:

        # Level restriction
        level = int(grid.Level)
        if levels is not None and level not in levels:
            continue

        # Region restriction
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
        
        field_dict = {}
        
        for f in fields:
            if f not in hierarchy.field_units:
                hierarchy.field_units[f] = str(data_source.ds.field_info[(vtype, f)].units)
            
            field_dict[f] = data_source[(vtype, f)].in_base("code").v
        
        block = GridBlock(
            block_id=grid.id,
            left_edge=left_edge,
            right_edge=right_edge,
            dims=dims,
            fields=field_dict
        )
        
        hierarchy.add_block(level=level, block=block, cell_size=cell_size)


    return hierarchy

def preview_field_slice(
    grid_data : GridBlock,
    fields    : Union[str, List[str]] = None,
    axis      : int = 0,
    slice_idx : int = None,
):
    """
    Quick look at one or more fields before choosing an extraction method.

    - A field with a clean, single-mode threshold in its histogram and a
      blob-like slice -> grid_to_surface (isosurface) is usually enough.
    - A field with filamentary / ridge-like structure and no clean single
      threshold -> grid_to_ridge_surface is usually better.

    Parameters
    ----------
    grid_data : GridBlock
    fields    : str or list[str] or None
        Field name(s) to preview. If None, previews every field in grid_data.fields.
    axis      : int   axis_map = {'z': 0, 'y': 1, 'x': 2} (default: 'z')
    slice_idx : int   Index along `axis` for plot (default: middle of that axis)
    """
    if fields is None:
        fields = list(grid_data.fields.keys())
    elif isinstance(fields, str):
        fields = [fields]

    valid_fields = [f for f in fields if f in grid_data.fields]
    for f in fields:
        if f not in grid_data.fields:
            print(f"  [WARNING] Field '{f}' not found in grid_data.fields; skipping.")

    if not valid_fields:
        print("  [WARNING] No valid fields to preview.")
        return

    n = len(valid_fields)
    fig, axes = plt.subplots(n, 2, figsize=(12, 5 * n), squeeze=False)
    fig.suptitle(f"Field Preview  |  axis={axis}")

    for row, field in enumerate(valid_fields):
        volume = grid_data.fields[field]
        s_idx = slice_idx if slice_idx is not None else volume.shape[axis] // 2
        slice_2d = np.take(volume, s_idx, axis=axis)

        im = axes[row, 0].imshow(slice_2d, cmap='viridis', origin='lower')
        axes[row, 0].set_title(f"'{field}'  |  index={s_idx}")
        plt.colorbar(im, ax=axes[row, 0])

        axes[row, 1].hist(volume.ravel(), bins=100, color='steelblue')
        axes[row, 1].set_yscale('log')
        axes[row, 1].set_title(f"'{field}' value distribution")
        axes[row, 1].set_xlabel(field)
        axes[row, 1].set_ylabel("Voxel count (log)")

    plt.tight_layout()
    plt.savefig(f"preview.png", dpi=150)
    plt.show()
    print(f"  Saved: preview.png")


