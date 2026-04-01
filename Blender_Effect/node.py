import bpy
import typing

from .object import (
    resolve_object,
    duplicate_object,
    add_gn_modifer
)

def sph_point_to_volume(obj: typing.Union[str, bpy.types.Object],
                        attribute_name: str | None = None,
                        material_name: str | None = None,
                        voxel_size: float = 0.02,
                        density: float = 0.2,
                        math_multiplier: float = 0.03):

    obj = resolve_object(obj)
    species_name = obj.name
    group_name = species_name + "_volnode"
      
    if material_name is None:   
        material_name = species_name + "_volshader"  
        
    gn_mod, sph_group = add_gn_modifer(obj, group_name) 

    # Interface
    geometry_socket = sph_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    geometry_socket.attribute_domain = 'POINT'

    geometry_socket_1 = sph_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    geometry_socket_1.attribute_domain = 'POINT'

    # Nodes
    group_input = sph_group.nodes.new("NodeGroupInput")
    group_input.name = "Group Input"

    group_output = sph_group.nodes.new("NodeGroupOutput")
    group_output.name = "Group Output"
    group_output.is_active_output = True

    points_to_volume = sph_group.nodes.new("GeometryNodePointsToVolume")
    points_to_volume.resolution_mode = 'VOXEL_SIZE'
    points_to_volume.inputs[1].default_value = density  # Density
    points_to_volume.inputs[2].default_value = voxel_size  # Voxel Size

    set_material = sph_group.nodes.new("GeometryNodeSetMaterial")
    set_material.name = "Set Material"
    set_material.inputs[1].default_value = True  # Selection
    
    if material_name in bpy.data.materials:
        set_material.inputs[2].default_value = bpy.data.materials[material_name]
    else:
        raise ValueError(f"Material '{material_name}' not found in bpy.data.materials.")


    # Set locations
    sph_group.nodes["Group Input"].location = (-350.0, 50.0)
    sph_group.nodes["Group Output"].location = (450.0, 100.0)
    sph_group.nodes["Points to Volume"].location = (-100.0, 100.0)
    sph_group.nodes["Set Material"].location = (200.0, 100.0)

    # Links
    sph_group.links.new(sph_group.nodes["Group Input"].outputs[0], sph_group.nodes["Points to Volume"].inputs[0])
    sph_group.links.new(sph_group.nodes["Set Material"].outputs[0], sph_group.nodes["Group Output"].inputs[0])
    sph_group.links.new(sph_group.nodes["Points to Volume"].outputs[0], sph_group.nodes["Set Material"].inputs[0])

    if attribute_name is not None:
        named_attr_radius = sph_group.nodes.new("GeometryNodeInputNamedAttribute")
        named_attr_radius.name = "Radius Attribute"
        named_attr_radius.data_type = 'FLOAT'
        named_attr_radius.inputs[0].default_value = attribute_name  # Name

        math_radius = sph_group.nodes.new("ShaderNodeMath")
        math_radius.name = "Math Radius"
        math_radius.operation = 'MULTIPLY'
        math_radius.use_clamp = False
        math_radius.inputs[1].default_value = math_multiplier

        sph_group.links.new(named_attr_radius.outputs[0], math_radius.inputs[0])
        sph_group.links.new(math_radius.outputs[0], points_to_volume.inputs[4])

        named_attr_radius.location = (-500.0, -100.0)
        math_radius.location = (-300.0, -50.0)
    
    
    
    return sph_group


def sph_point_to_mesh(obj, 
                      radius_attr: str = None, 
                      material_name: str = None, 
                      voxel_size: float = 0.3, 
                      density: float = 1.0, 
                      radius_multiplier: float = 1.1):
    """ 
    Create a modifer with GN node group that converts point to mesh with material. 

    Args: 
        group_name: Name of node group
        radius_attr: Named attribute used for radius scaling
        material_name: Name of material to assign
        voxel_size: Voxel size for Points to Volume and Volume to Mesh
        density: Density input for Points to Volume
        radius_multiplier: Multiply radius by this factor

    Returns: 
        bpy.types.NodeTree: The created node group
    """ 
    obj = resolve_object(obj) 
    species_name = obj.name 
    group_name = species_name + '_meshnode' 


    if material_name is None: 
        material_name = species_name + '_meshshader' 

    gn_mod, gn_group = add_gn_modifer(obj, group_name) 

    # Interface 
    geometry_socket = gn_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry') 
    geometry_socket.attribute_domain = 'POINT' 
    geometry_socket_1 = gn_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry') 
    geometry_socket_1.attribute_domain = 'POINT' 

    # Nodes 
    group_input = gn_group.nodes.new("NodeGroupInput") 
    group_input.name = "Group Input" 
    group_output = gn_group.nodes.new("NodeGroupOutput") 
    group_output.name = "Group Output" 
    group_output.is_active_output = True 

    points_to_volume = gn_group.nodes.new("GeometryNodePointsToVolume") 
    points_to_volume.name = "Points to Volume" 
    points_to_volume.resolution_mode = 'VOXEL_SIZE' 
    points_to_volume.inputs[1].default_value = density 
    points_to_volume.inputs[2].default_value = voxel_size 

    volume_to_mesh = gn_group.nodes.new("GeometryNodeVolumeToMesh") 
    volume_to_mesh.name = "Volume to Mesh" 
    volume_to_mesh.resolution_mode = 'VOXEL_SIZE' 
    volume_to_mesh.inputs[1].default_value = voxel_size 
    volume_to_mesh.inputs[3].default_value = 0.01 
    volume_to_mesh.inputs[4].default_value = 0.0267 

    set_shade = gn_group.nodes.new("GeometryNodeSetShadeSmooth") 
    set_shade.name = "Set Shade Smooth" 
    set_shade.domain = 'FACE' 
    set_shade.inputs[1].default_value = True 
    set_shade.inputs[2].default_value = True 

    set_material = gn_group.nodes.new("GeometryNodeSetMaterial") 
    set_material.name = "Set Material" 
    set_material.inputs[1].default_value = True 
    if material_name and material_name in bpy.data.materials: 
        set_material.inputs[2].default_value = bpy.data.materials[material_name] 

    # Links 
    gn_group.links.new(group_input.outputs[0], points_to_volume.inputs[0]) 
    gn_group.links.new(points_to_volume.outputs[0], volume_to_mesh.inputs[0]) 
    gn_group.links.new(volume_to_mesh.outputs[0], set_shade.inputs[0]) 
    gn_group.links.new(set_shade.outputs[0], set_material.inputs[0]) 
    gn_group.links.new(set_material.outputs[0], group_output.inputs[0]) 

    # Locations 
    group_input.location = (-600, 0) 
    group_output.location = (600, 0) 
    points_to_volume.location = (-300, 0) 
    volume_to_mesh.location = (0, 0) 
    set_shade.location = (300, 0) 
    set_material.location = (450, 0) 

    if radius_attr is not None: 
        named_attr = gn_group.nodes.new("GeometryNodeInputNamedAttribute") 
        named_attr.name = "Radius Attribute" 
        named_attr.data_type = 'FLOAT' 
        named_attr.inputs[0].default_value = radius_attr 

        math_node = gn_group.nodes.new("ShaderNodeMath") 
        math_node.name = "Math Multiply" 
        math_node.operation = 'MULTIPLY' 
        math_node.inputs[1].default_value = radius_multiplier 

        gn_group.links.new(named_attr.outputs[0], math_node.inputs[0]) 
        gn_group.links.new(math_node.outputs[0], points_to_volume.inputs[4]) 

        named_attr.location = (-450, -100) 
        math_node.location = (-150, -100)



def select(
    obj,
    new_object_name: str,
    mode: str = "attribute",  # "attribute" or "proximity"
    attribute_name: str = None,
    compare_value: float = None,
    operation: str = "GREATER",  # GREATER, LESS, EQUAL, NOT_EQUAL
    target_obj = None,
    target_element: str = 'POINTS',  # 'POINTS', 'EDGES', 'FACES' for mesh
    distance: float = 1.0,
):
    """ 
    Add a Geometry Nodes modifier that selects points based on attribute or proximity. 
    """
    obj = resolve_object(obj)
    new_obj = duplicate_obj(obj, new_object_name)
    mod_name = new_object_name

    gn_mod, gn_group = add_gn_modifer(new_obj, mod_name)

    # Group Input / Output
    group_input = gn_group.nodes.new("NodeGroupInput")
    group_input.name = "Group Input"
    group_output = gn_group.nodes.new("NodeGroupOutput")
    group_output.name = "Group Output"

    # Add input/output sockets
    geo_in = gn_group.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    geo_out = gn_group.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # Seperate Geometry node (selection gate)
    separate_geo = gn_group.nodes.new("GeometryNodeSeparateGeometry")
    separate_geo.domain = 'POINT'

    # Link
    gn_group.links.new(group_input.outputs[0], separate_geo.inputs[0])
    gn_group.links.new(separate_geo.outputs[0], group_output.inputs[0])

    # --- Simple attribute selection ---
    if mode == "attribute":
        if attribute_name is None or compare_value is None:
            raise ValueError("attribute_name and compare_value required for 'attribute' mode")

        attr_node = gn_group.nodes.new("GeometryNodeInputNamedAttribute")
        attr_node.name = "Attribute Input"
        attr_node.data_type = 'FLOAT'
        attr_node.inputs[0].default_value = attribute_name

        compare_node = gn_group.nodes.new("ShaderNodeMath")
        compare_node.name = "Compare"
        compare_node.inputs[1].default_value = compare_value
        op_map = {
            "GREATER": 'GREATER_THAN',
            "LESS": 'LESS_THAN',
            "EQUAL": 'EQUAL',
            "NOT_EQUAL": 'NOT_EQUAL'
        }
        compare_node.operation = op_map.get(operation.upper(), 'GREATER_THAN')

        # Link attribute → compare → selection
        gn_group.links.new(attr_node.outputs[0], compare_node.inputs[0])
        gn_group.links.new(compare_node.outputs[0], separate_geo.inputs[1])

        # Layout
        group_input.location = (-400, 0)
        attr_node.location = (-200, 0)
        compare_node.location = (0, 0)
        separate_geo.location = (200, 0)
        group_output.location = (400, 0)

    # --- Advanced proximity selection ---
    elif mode == "proximity":
        if target_obj is None:
            raise ValueError("target_obj required for 'proximity' mode")
        target_obj = resolve_object(target_obj)

        # Object info node
        object_info_node = gn_group.nodes.new("GeometryNodeObjectInfo")
        object_info_node.name = "Object Info"
        object_info_node.transform_space = 'RELATIVE'
        object_info_node.inputs[0].default_value = target_obj

        # Proximity node
        proximity_node = gn_group.nodes.new("GeometryNodeProximity")
        proximity_node.name = "Proximity"

        if target_element not in ('POINTS', 'EDGES', 'FACES'):
            raise ValueError("target_element must be 'POINTS', 'EDGES', 'FACES'")

        proximity_node.target_element = target_element

        compare_node = gn_group.nodes.new("ShaderNodeMath")
        compare_node.name = "Distance Compare"
        compare_node.operation = 'LESS_THAN'
        compare_node.inputs[1].default_value = distance

        # Link proximity → compare → delete
        gn_group.links.new(object_info_node.outputs[4], proximity_node.inputs[0])
        gn_group.links.new(proximity_node.outputs[1], compare_node.inputs[0])
        gn_group.links.new(compare_node.outputs[0], separate_geo.inputs[1])

        # Layout
        group_input.location = (-400, 0)
        object_info_node.location = (-400, -200)
        proximity_node.location = (-200, -100)
        compare_node.location = (0, -100)
        separate_geo.location = (200, 0)
        group_output.location = (400, 0)

    else:
        raise ValueError("mode must be 'attribute' or 'proximity'")

    return new_obj



