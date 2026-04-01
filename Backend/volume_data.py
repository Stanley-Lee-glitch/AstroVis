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
    left_edge: Tuple[float, float, float]
    right_edge: Tuple[float, float, float]
    dims: Tuple[int, int, int]
    fields: Dict[str, np.ndarray]

@dataclass
class GridLevel:
    """
    For AMR datasets, we group blocks by their refinement level. Each level contains multiple blocks of the same cell size.
    It may or may not be contiguous in space.
    """
    level: int
    cell_size: Tuple[float, float, float]
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
        
        dims = tuple(int(d) for d in data_source.ActiveDimensions)
        left_edge = tuple(float(d) for d in data_source.LeftEdge.to_value())
        right_edge = tuple(float(d) for d in data_source.RightEdge.to_value())
        
        cell_size = tuple(float(d) for d in data_source.dds.to("code_length").value)
        
        field_dict = {}
        
        for f in fields:
            if f not in hierarchy.field_units:
                hierarchy.field_units[f] = data_source.ds.field_info[(vtype, f)].units
            
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


