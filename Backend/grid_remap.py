## This script remaps the overlapping grid data by ds.covering_grid from yt.
## New block id will be the relative id of eaach level. 
from .volume_data import load_volume, GridBlock, GridLevel, FieldHierarchy

import numpy as np

## Only one fields is allowed for remapping function

def load_remap_amr_volume(ds, vtype = "gas", fields=["density"], block_per_layer: int = 4):
    
    volume = load_volume(ds, vtype=vtype, fields=fields)
    
    min_level = min(volume.levels.keys())
    max_level = max(volume.levels.keys())
    
    
    # 56 blocks for lower levels (excluding center) when block_per_layer is 4, 64 for max level
    block_per_level_internal = block_per_layer ** 3 - (block_per_layer // 2) ** 3
    

    def get_block_metadata(block_id, current_level):
        # Determine if we are at max level or an internal level
        is_max_level = (current_level == max_level)
        
        if not is_max_level:
            # Logic to skip the center 2x2x2 core of blocks
            relative_id = block_id % block_per_level_internal
            actual_grid_id = 0
            valid_count = 0
            for i in range(block_per_layer ** 3):
                ix, iy, iz = i % block_per_layer, (i // block_per_layer) % block_per_layer, (i // (block_per_layer ** 2)) % block_per_layer
                is_center = all(1 <= idx <= block_per_layer / 2 for idx in (ix, iy, iz))
                if not is_center:
                    if valid_count == relative_id:
                        actual_grid_id = i
                        break
                    valid_count += 1
        else:
            # Max level fills the whole 4x4x4 (64 blocks)
            actual_grid_id = block_id % (block_per_layer ** 3)

        ix = actual_grid_id % block_per_layer
        iy = (actual_grid_id // block_per_layer) % block_per_layer
        iz = (actual_grid_id // (block_per_layer ** 2)) % block_per_layer
        
        level_edge = float(ds.domain_width[0] / 2) / (2**current_level)  ## Restricted to e.g. [-0.5, 0.5] for level 0
        block_width = (2 * level_edge) / block_per_layer ## Block width = 0.25 for level 0 and block_per_layer 4
              
        left_edge = np.array([
            -level_edge + (ix * block_width),
            -level_edge + (iy * block_width),
            -level_edge + (iz * block_width)
        ], dtype="float64")
         
        return left_edge, left_edge + block_width

    # 1. First Pass: Collect metadata and identify global min/max
    print("Remapping grids...")
    
    fh = FieldHierarchy(
        unit=volume.unit,
        field_units=volume.field_units
    )
    
    for level_idx in range(min_level, max_level + 1):
        
        num_blocks = (block_per_layer**3) if level_idx == max_level else block_per_level_internal
        
        for b_id in range(num_blocks):
            left, right = get_block_metadata(b_id, level_idx)            
            # Use original cell size to determine dims for covering_grid, which will be used for VDB conversion
            dims = (
                int(ds.domain_width[0].v / (2**level_idx) / block_per_layer / volume.levels[level_idx].cell_size[0]),
                int(ds.domain_width[1].v / (2**level_idx) / block_per_layer / volume.levels[level_idx].cell_size[1]),
                int(ds.domain_width[2].v / (2**level_idx) / block_per_layer / volume.levels[level_idx].cell_size[2])
            )
            
            grid = ds.covering_grid(level=level_idx, left_edge=left, dims=dims)
            data = {field: grid[field].v for field in fields}
            
            # Create block object
            block = GridBlock(
                block_id=b_id, 
                left_edge=left, 
                right_edge=right, 
                dims=dims, 
                fields=data
            )
            
            fh.add_block(level=level_idx, block=block, cell_size=volume.levels[level_idx].cell_size)
    
    return fh

          

