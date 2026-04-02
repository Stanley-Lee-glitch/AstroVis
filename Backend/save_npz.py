## Exporting Data structure to .npz file

from .particle_data import SPHParticleData, SPHFields
from .volume_data import GridBlock, GridLevel, FieldHierarchy
from .grid_to_surface import SurfaceData

import numpy as np
from typing import Dict

def save(file_path: str,
        data: FieldHierarchy | SPHParticleData | SurfaceData):
    """
    Save FieldHierarchy, SPHParticleData, and SurfaceData into a single NPZ file.
    """
    npz_dict = {}

    # Save FieldHierarchy
    if isinstance(data, FieldHierarchy):
        npz_dict['fh_unit'] = data.unit
        npz_dict['fh_field_units'] = data.field_units
        for level_id, gridlevel in data.levels.items():
            npz_dict[f'level_{level_id}_cell_size'] = np.array(gridlevel.cell_size)
            for block in gridlevel.blocks:  
                blk_id = block.block_id
                npz_dict[f'level_{level_id}_block_{blk_id}_left_edge'] = np.array(block.left_edge)
                npz_dict[f'level_{level_id}_block_{blk_id}_right_edge'] = np.array(block.right_edge)
                npz_dict[f'level_{level_id}_block_{blk_id}_dims'] = np.array(block.dims)
                for field_name, arr in block.fields.items():
                    npz_dict[f'level_{level_id}_block_{blk_id}_field_{field_name}'] = arr

    # Save SPHParticleData
    if isinstance(data, SPHParticleData):
        npz_dict['particle_coordinates'] = data.coordinates
        npz_dict['particle_masses'] = data.masses
        npz_dict['particle_densities'] = data.densities
        npz_dict['particle_smoothing_lengths'] = data.smoothing_lengths
        npz_dict['particle_time'] = np.array([data.time])
        npz_dict['particle_units'] = data.units
        npz_dict['particle_boxsize'] = np.array(data.boxsize) if data.boxsize is not None else np.array([0.,0.,0.])
        # Save fields in SPHFields
        for field_name, arr in data.fields.items():
            npz_dict[f'particle_field_{field_name}'] = arr

    # Save SurfaceData
    if isinstance(data, SurfaceData):
        npz_dict[f'surface_vertices'] = data.vertices
        npz_dict[f'surface_faces'] = data.faces
        if data.normals is not None:
            npz_dict[f'surface_normals'] = data.normals

    # Save everything
    np.savez(file_path, **npz_dict)
    print(f"Saved data to {file_path}")
