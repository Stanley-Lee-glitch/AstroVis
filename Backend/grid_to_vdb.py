import numpy as np
import pyopenvdb as vdb
from .volume_data import FieldHierarchy, GridLevel, GridBlock

def convert_vdb(
    grid_data: GridBlock,
    field: str = "density",
    scale: float = 1.0,
    file_path: str = None
):
    density_grid = grid_data.fields[field]
    (x_min, y_min, z_min) = grid_data.left_edge
    (x_max, y_max, z_max) = grid_data.right_edge
    dim = grid_data.dims
    dx, dy, dz = (x_max - x_min)/dim[0], (y_max - y_min)/dim[1], (z_max - z_min)/dim[2]   
    
    density = vdb.FloatGrid()
    density.gridClass = vdb.GridClass.FOG_VOLUME
    density.name = 'density'
  
    matrix = np.array([
        [scale * dx, 0.0, 0.0, 0],
        [0.0, scale * dy, 0.0, 0],
        [0.0, 0.0, scale * dz, 0],
        [x_min, y_min, z_min, 1.0]
    ], dtype=np.float64)

    # Create transform from matrix
    density.transform = vdb.createLinearTransform(matrix)
    density.copyFromArray(density_grid)

    # 4. Export to VDB file
    if file_path is not None:
        file_name = f"{file_path}.vdb"
    else:
        file_name = f"Block_{grid_data.block_id}.vdb"
        
    vdb.write(file_name, grids=[density])
    

def fieldhierarchy_to_vdb(
    hierarchy: FieldHierarchy,
    field_name: str = 'density'):
  
    for level_id, level in hierarchy.levels.items():
        
        for block in level.blocks:
            if field_name not in block.fields.keys():
                print(f"Warning: Block {block.block_id} does not have field '{field_name}'. Skipping.")
                continue
            
            convert_vdb(block, field=field_name)

