## Import data from npz file to DataStructure

from .particle_data import SPHParticleData, SPHFields
from .volume_data import GridBlock, GridLevel, FieldHierarchy
from .surface_data import SurfaceData
import numpy as np
import json

def save(file_path: str, 
         data: dict):
    """
    Save FieldHierarchy, SPHParticleData, and SurfaceData into a single NPZ file.
    data = {
        "Planet_Surface": [SurfaceData, ...],
        "Emission_Gas": [FieldHierarchy, ...],
        "Dust": [SPHParticleData, ...],
    } 
    The key of dictionary is the name of the object, while the value stored the frame data.
    Each list only allowed to have one type of data, either FieldHierarchy, SPHParticleData, or SurfaceData.
    
    """
    
    npz_dict = {}
    
    object_registry = {object_name: {} for object_name in data.keys()}
    # {"Object name": {"Type": , "Frames": }}
    
    
    # Run per object
    for obj_name, frame_datas in data.items():
        if not isinstance(frame_datas, list):
            frame_datas = [frame_datas]
        
        ## Run per object frame
        for frame_idx, item in enumerate(frame_datas):
            prefix = f'{obj_name}_{frame_idx}'
            
            ### Save FieldHierarchy
            if isinstance(item, FieldHierarchy):
                object_registry[obj_name] = {"Type": "Volume", "Frames": len(frame_datas)}
                npz_dict[f'{prefix}_fh_unit'] = item.unit
                npz_dict[f'{prefix}_fh_field_units'] = item.field_units
                for level_id, gridlevel in item.levels.items():
                    npz_dict[f'{prefix}_level_{level_id}_cell_size'] = np.array(gridlevel.cell_size)
                    for block in gridlevel.blocks:  
                        blk_id = block.block_id
                        npz_dict[f'{prefix}_level_{level_id}_block_{blk_id}_left_edge'] = np.array(block.left_edge)
                        npz_dict[f'{prefix}_level_{level_id}_block_{blk_id}_right_edge'] = np.array(block.right_edge)
                        npz_dict[f'{prefix}_level_{level_id}_block_{blk_id}_dims'] = np.array(block.dims)
                        for field_name, arr in block.fields.items():
                            npz_dict[f'{prefix}_level_{level_id}_block_{blk_id}_field_{field_name}'] = arr                

            ### Save SPHParticleData
            elif isinstance(item, SPHParticleData):
                object_registry[obj_name] = {"Type": "Particles", "Frames": len(frame_datas)}
                npz_dict[f'{prefix}_particle_coordinates'] = item.coordinates
                npz_dict[f'{prefix}_particle_masses'] = item.masses
                npz_dict[f'{prefix}_particle_densities'] = item.densities
                npz_dict[f'{prefix}_particle_smoothing_lengths'] = item.smoothing_lengths
                npz_dict[f'{prefix}_particle_time'] = np.array([item.time])
                npz_dict[f'{prefix}_particle_units'] = item.units
                npz_dict[f'{prefix}_particle_boxsize'] = np.array(item.boxsize) if item.boxsize is not None else np.array([0.,0.,0.])
                # Save fields in SPHFields
                for field_name, arr in item.fields.items():
                    npz_dict[f'{prefix}_particle_field_{field_name}'] = arr

    # Save SurfaceData
            elif isinstance(item, SurfaceData):
                object_registry[obj_name] = {"Type": "Surface", "Frames": len(frame_datas)}
                npz_dict[f'{prefix}_surface_vertices'] = item.vertices
                npz_dict[f'{prefix}_surface_faces'] = item.faces
                if item.normals is not None:
                    npz_dict[f'{prefix}_surface_normals'] = item.normals
        
#        print(f"Saved {obj_name} with {len(frame_datas)} frame(s) as {object_registry[obj_name]['Type']}")
   
    #Storing object registry for reference
    npz_dict['Object_registry'] = np.bytes_(json.dumps(object_registry))
    
     # Save everything
    np.savez(file_path, **npz_dict)
    print(f"Saved to {file_path}")


def load(file_path: str):
    """
    Load FieldHierarchy, SPHParticleData, and SurfaceData from NPZ file.
    Returns: field_hierarchy, particle_data, surface_data
    """
    data = np.load(file_path, allow_pickle=True)

    object_registry = json.loads(data['Object_registry'].tobytes())
    
    result = {
        "Particles": {}, # object name: [SPHParticleData, ...]
        "Volume": {}, # object name: [FieldHierarchy, ...]
        "Surface": {} # object name: [SurfaceData, ...]
    }
    # --- Load FieldHierarchy ---
    
    particles_list = {
        object_name: meta['Frames']
        for object_name, meta in object_registry.items()
        if meta['Type'] == 'Particles'
    }    
    volume_list = {
        object_name: meta['Frames']
        for object_name, meta in object_registry.items()
        if meta['Type'] == 'Volume'
    }
    surface_list = {
        object_name: meta['Frames']
        for object_name, meta in object_registry.items()
        if meta['Type'] == 'Surface'
    }
    
    
    for name, num_frames in volume_list.items():
        result["Volume"][name] = []
        
        for i in range(num_frames):
            prefix = f'{name}_{i}'
            fh = FieldHierarchy(
                unit=data[f'{prefix}_fh_unit'].item(), 
                field_units=data[f'{prefix}_fh_field_units'].item()
            )
            
            # Temporary dict to safely gather blocks before instantiation
            temp_levels = {}
            
            for k in data.files:
                if not k.startswith(f'{prefix}_level_'):
                    continue
                    
                key_core = k[len(f'{prefix}_'):] 
                parts = key_core.split('_') 
                # key_core = 'level_1_block_0_left_edge' -> parts = ['level', '1', 'block', '0', 'left', 'edge']
                
                level_id = int(parts[1])
                if level_id not in temp_levels:
                    temp_levels[level_id] = {'cell_size': None, 'blocks': {}}
                
                if 'cell_size' in k:
                    temp_levels[level_id]['cell_size'] = tuple(data[k])
                    continue

                if 'block' in key_core:
                    block_idx = int(parts[3])
                    if block_idx not in temp_levels[level_id]['blocks']:
                        temp_levels[level_id]['blocks'][block_idx] = {'fields': {}}
                    
                    block_dict = temp_levels[level_id]['blocks'][block_idx]
                    
                    if 'left_edge' in key_core:
                        block_dict['left_edge'] = tuple(data[k])
                    elif 'right_edge' in key_core:
                        block_dict['right_edge'] = tuple(data[k])
                    elif 'dims' in key_core:
                        block_dict['dims'] = tuple(data[k])
                    elif 'field' in key_core:
                        # Everything after 'field' is the field name
                        field_name = '_'.join(parts[5:]) 
                        block_dict['fields'][field_name] = data[k]

            for level_id, level_data in temp_levels.items():
                fh.levels[level_id] = GridLevel(level=level_id, cell_size=level_data['cell_size'])
                
                for blk_id in sorted(level_data['blocks'].keys()):
                    blk_data = level_data['blocks'][blk_id]
                    block = GridBlock(
                        block_id=blk_id,
                        left_edge=blk_data['left_edge'],
                        right_edge=blk_data['right_edge'],
                        dims=blk_data['dims'],
                        fields=blk_data['fields']
                    )
                    fh.levels[level_id].blocks.append(block)

            result["Volume"][name].append(fh)

    # --- Load SPHParticleData ---
    for name, num_frames in particles_list.items():
        result["Particles"][name] = []
        
        for i in range(num_frames):
            prefix = f'{name}_{i}'
            fields_dict = {}
            for k in data.files:
                if k.startswith(f'{prefix}_particle_field_'):
                    fname = k[len(f'{prefix}_particle_field_'):]
                    fields_dict[fname] = data[k]
            particle_fields = SPHFields(fields_dict)
            particle_data = SPHParticleData(
                coordinates=data[f'{prefix}_particle_coordinates'],
                masses=data[f'{prefix}_particle_masses'],
                densities=data[f'{prefix}_particle_densities'],
                smoothing_lengths=data[f'{prefix}_particle_smoothing_lengths'],
                time=float(data[f'{prefix}_particle_time'][0]),
                fields=particle_fields,
                units=data[f'{prefix}_particle_units'].item(),
                boxsize=tuple(data[f'{prefix}_particle_boxsize'])
            )
            result["Particles"][name].append(particle_data)

    # --- Load SurfaceData ---
    for name, num_frames in surface_list.items():
        result["Surface"][name] = []
        for i in range(num_frames):
            prefix = f'{name}_{i}'
            verts = data[f'{prefix}_surface_vertices']
            faces = data[f'{prefix}_surface_faces']
            normals = data[f'{prefix}_surface_normals'] if f'{prefix}_surface_normals' in data else None        
            surface_data = SurfaceData(vertices=verts, 
                                       faces=faces, 
                                       normals=normals)
            result["Surface"][name].append(surface_data)

    return result
