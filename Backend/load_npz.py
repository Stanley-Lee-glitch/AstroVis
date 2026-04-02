## Import data from npz file to DataStructure

from .particle_data import SPHParticleData, SPHFields
from .volume_data import GridBlock, GridLevel, FieldHierarchy
from .grid_to_surface import SurfaceData
import numpy as np


def load(file_path: str):
    """
    Load FieldHierarchy, SPHParticleData, and SurfaceData from NPZ file.
    Returns: field_hierarchy, particle_data, surface_data
    """
    data = np.load(file_path, allow_pickle=True)

    # --- Load FieldHierarchy ---
    fh = None
    if 'fh_unit' in data:
        fh = FieldHierarchy(unit=data['fh_unit'].item(), field_units=data['fh_field_units'].item())
        # detect levels
        level_keys = [k for k in data.files if k.startswith('level_') and '_cell_size' in k]
        for lk in level_keys:
            level_id = int(lk.split('_')[1])
            cell_size = tuple(data[lk])
            fh.levels[level_id] = GridLevel(level=level_id, cell_size=cell_size)
        # detect blocks and fields
        for k in data.files:
            if k.startswith('level_') and 'block' in k and 'field' not in k:
                parts = k.split('_')
                level_id = int(parts[1])
                block_idx = int(parts[3])
                if 'left_edge' in k:
                    left = tuple(data[k])
                    right = tuple(data[f'level_{level_id}_block_{block_idx}_right_edge'])
                    dims = tuple(data[f'level_{level_id}_block_{block_idx}_dims'])
                    block = GridBlock(block_id=block_idx, left_edge=left, right_edge=right, dims=dims, fields={})
                    fh.levels[level_id].blocks.append(block)
            elif k.startswith('level_') and 'field' in k:
                parts = k.split('_')
                level_id = int(parts[1])
                block_idx = int(parts[3])
                field_name = '_'.join(parts[5:])
                block = fh.levels[level_id].blocks[block_idx]
                block.fields[field_name] = data[k]

    # --- Load SPHParticleData ---
    particle_data = None
    if 'particle_coordinates' in data:
        fields_dict = {}
        for k in data.files:
            if k.startswith('particle_field_'):
                fname = k[len('particle_field_'):]
                fields_dict[fname] = data[k]
        particle_fields = SPHFields(fields_dict)
        particle_data = SPHParticleData(
            coordinates=data['particle_coordinates'],
            masses=data['particle_masses'],
            densities=data['particle_densities'],
            smoothing_lengths=data['particle_smoothing_lengths'],
            time=float(data['particle_time'][0]),
            fields=particle_fields,
            units=data['particle_units'].item(),
            boxsize=tuple(data['particle_boxsize'])
        )

    # --- Load SurfaceData ---
    surface_data = None
    if 'surface_vertices' in data and 'surface_faces' in data:
        verts = data['surface_vertices']
        faces = data['surface_faces']
        normals = data.get('surface_normals', None)
        surface_data = SurfaceData(vertices=verts, faces=faces, normals=normals)

    if fh:
        return fh
    elif particle_data:
        return particle_data
    elif surface_data:
        return surface_data
    else:
        raise ValueError("No recognizable data found in NPZ file.")