import numpy as np
import pyopenvdb as vdb
from .volume_data import GridBlock

def convert_vdb(
    grid_data: GridBlock,
    output_path: str,
    scale: float = 1.0,
):
    density_grid = grid_data.fields["density"]
    output = output_path
    dx, dy, dz = grid_data.cell_size
    (x_min, y_min, z_min) = grid_data.left_edge
    
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
    vdb.write(f"Block_{grid_data.block_id}.vdb", grids=[density])