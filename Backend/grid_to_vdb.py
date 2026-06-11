import numpy as np
import pyopenvdb as vdb
from .volume_data import FieldHierarchy, GridLevel, GridBlock

def convert_vdb(
    grid_data: GridBlock,
    field: str = "density",
    scale: float = 1.0,
    file_path: str = None,
    log: bool = True
):
    density_grid = np.array(grid_data.fields[field].astype(np.float32))  # Ensure data is in float32 format for VDB
    
    if log:
        density_grid = np.log10(np.clip(density_grid, a_min=1e-10, a_max=None))  # Log scale and clip to avoid -inf
    
    dim = np.array(grid_data.dims) - np.array([1, 1, 1])  
    dx, dy, dz = (np.array(grid_data.right_edge) -np.array(grid_data.left_edge)) / dim
    (x_min, y_min, z_min) = np.array(grid_data.left_edge)
    
    print(f"Block {grid_data.block_id}: dx={dx:.4f}, dy={dy:.4f}, dz={dz:.4f}, x_min={x_min:.4f}, y_min={y_min:.4f}, z_min={z_min:.4f}")

    
    density = vdb.FloatGrid()
    density.gridClass = vdb.GridClass.FOG_VOLUME
    density.name = 'density'
  
    matrix = np.array([
        [scale * dx, 0.0, 0.0, 0],
        [0.0, scale * dy, 0.0, 0],
        [0.0, 0.0, scale * dz, 0],
        [x_min*scale, y_min*scale, z_min*scale, 1.0]
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
    
## One vdb with all grids for each frame
def volume_to_vdb(
    hierarchy: FieldHierarchy,
    field: str = 'density',
    file_name_prefix: str = "volume",
    scale: float = 1.0,
    log: bool = True
):

    grids_to_save = []

    for level_id, level in hierarchy.levels.items():
        
        for block_data in level.blocks:
            
            if field not in block_data.fields.keys():
                print(f"Warning: Block {block_data.block_id} does not have field '{field}'. Skipping.")
                continue
            
            if log:
                block_data.fields[field] = np.log10(np.clip(block_data.fields[field], a_min=1e-10, a_max=None))  # Log scale and clip to avoid -inf
                
            density_grid = block_data.fields[field]
    
            dim = np.array(block_data.dims) - np.array([1, 1, 1])  
            dx, dy, dz = (block_data.right_edge - block_data.left_edge) / dim
            (x_min, y_min, z_min) = block_data.left_edge
            
            density = vdb.FloatGrid()
            density.gridClass = vdb.GridClass.FOG_VOLUME
            density.name = f'density_l{level_id}_b{block_data.block_id}'       
    
            matrix = np.array([
                [scale * dx, 0.0, 0.0, 0],
                [0.0, scale * dy, 0.0, 0],
                [0.0, 0.0, scale * dz, 0],
                [x_min*scale, y_min*scale, z_min*scale, 1.0]
            ], dtype=np.float64)

            # Create transform from matrix
            density.transform = vdb.createLinearTransform(matrix)
            density.copyFromArray(density_grid)
            
            grids_to_save.append(density)
            
    file_name = f"{file_name_prefix}.vdb"
    vdb.write(file_name, grids=grids_to_save)

## Multiple VDBs for each frame
def volume_to_multiple_vdbs(
    hierarchy: FieldHierarchy,
    field: str = 'density',
    file_name_prefix: str = "volume",
    scale: float = 1.0,
    log: bool = True
):
    
    if log:
        print("Applying log scale to the data.")
    
    global_min = float('inf')
    global_max = float('-inf')
    
    for level_id, level in hierarchy.levels.items():
        for block_data in level.blocks:
            if field not in block_data.fields.keys():
                print(f"Warning: Block {block_data.block_id} does not have field '{field}'. Skipping.")
                continue
            
            if log:
                block_data.fields[field] = np.log10(np.clip(block_data.fields[field], a_min=1e-10, a_max=None))  # Log scale and clip to avoid -inf
                
            global_min = min(global_min, block_data.fields[field].min())
            global_max = max(global_max, block_data.fields[field].max())
            
            file_name = f"{file_name_prefix}_l{level_id}_b{block_data.block_id}"
            convert_vdb(block_data, field=field, scale=scale, file_path=file_name, log=False)
    
    print(f"GLOBAL RANGE: Min: {global_min:.4f}, Max: {global_max:.4f}")
    print(f"Finished exporting {len(hierarchy.levels)} levels with a total of {sum(len(level.blocks) for level in hierarchy.levels.values())} blocks to VDB files.")
    
    