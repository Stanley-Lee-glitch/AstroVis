import bpy
import colorsys
import typing
import numpy as np

def create_volume_shaders(
    species_names: typing.List[str],
    species_colors: typing.Tuple = None,
    species_alpha: float = 1.0,
    emission_multiplier: float = 2.0,
    density_attribute: str = "density"
) -> typing.Dict[str, bpy.types.Material]:
    
    """
    Create and append volume shaders to the object. 
    Existing shaders with the same name will be overwritten.
    Other existing shaders of the object will be unlinked (but not removed). 
    Default using most extreme colors from a color ramp.

    Args:
        species_names: list of object/ species names
        color_ramp_values: (R, G, B) color ramp
        emission_multiplier: scaling for emission
        density_attribute: attribute controlling density

    Returns:
        dict: {species_name: bpy_material}
        
    """
    if isinstance(species_names, str):
        species_names = [species_names]

    shaders = {}
    N = len(species_names)

    if species_colors is None:
        species_colors = [colorsys.hsv_to_rgb(i/N, 0.6, 1) for i in range(N)]


    for i, name in enumerate(species_names):
        # Create unique material
        mat_name = f"{name}_volshader"
        
        if bpy.data.materials.get(mat_name) is not None:
            bpy.data.materials.remove(bpy.data.materials.get(mat_name)) # Delete shader with same name

        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        nt = mat.node_tree
        for node in nt.nodes:
            nt.nodes.remove(node)

        # Nodes
        output_node = nt.nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (400,0)

        volume_node = nt.nodes.new("ShaderNodeVolumePrincipled")
        volume_node.location = (100,0)
        volume_node.inputs['Density'].default_value = 0

        attr_node = nt.nodes.new("ShaderNodeAttribute")
        attr_node.attribute_name = density_attribute
        attr_node.location = (-400,0)

        # Color ramp with single extreme color
        ramp_node = nt.nodes.new("ShaderNodeValToRGB")
        ramp_node.location = (-200,200)
        ramp_node.color_ramp.interpolation = 'LINEAR'
        
        # Remove default extra elements
        while len(ramp_node.color_ramp.elements) > 1:
            ramp_node.color_ramp.elements.remove(ramp_node.color_ramp.elements[1])
        
        # Set first handle
        ramp_node.color_ramp.elements[0].position = 0.0
        ramp_node.color_ramp.elements[0].color = (*species_colors[i], species_alpha)

        # Add second handle at position 1.0, same color
        el = ramp_node.color_ramp.elements.new(1.0)
        el.color = (*species_colors[i], species_alpha)

        # Math node for emission strength
        math_node = nt.nodes.new("ShaderNodeMath")
        math_node.operation = 'MULTIPLY'
        math_node.inputs[1].default_value = emission_multiplier
        math_node.location = (-200,-200)

        # Links
        nt.links.new(attr_node.outputs['Fac'], math_node.inputs[0])
        nt.links.new(math_node.outputs[0], volume_node.inputs['Emission Strength'])
        nt.links.new(attr_node.outputs['Fac'], ramp_node.inputs['Fac'])
        nt.links.new(ramp_node.outputs['Color'], volume_node.inputs['Emission Color'])
        nt.links.new(volume_node.outputs['Volume'], output_node.inputs['Volume'])

        shaders[name] = mat
        
    for object in species_names:
        obj = bpy.data.objects[object]
        obj.data.materials.clear()  # Unlink all shader of the object
        obj.data.materials.append(shaders[object])
        print(object, shaders[object])

    return shaders


def create_mesh_shaders(
    species_names: typing.List[str],
    base_color: typing.Tuple = (0.54, 0.20, 0.0, 1.0),
    emission_color: typing.Tuple = (0.57, 0.15, 0.0, 1.0),
    emission_strength: float = 0.15,
) -> typing.Dict[str, bpy.types.Material]:


    if isinstance(species_names, str):
        species_names = [species_names]

    shaders = {}

    for name in species_names:
        mat_name = f"{name}_meshshader"

        # Remove existing material with the same name
        if mat_name in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials[mat_name])

        # Create new material
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        nt = mat.node_tree

        # Clear existing nodes
        for node in nt.nodes:
            nt.nodes.remove(node)

        # Create nodes 
        output_node = nt.nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (400, 0)

        principled_bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        principled_bsdf.location = (0, 0)

        principled_bsdf.inputs['Base Color'].default_value = base_color
        principled_bsdf.inputs['Metallic'].default_value = 0.0
        principled_bsdf.inputs['Roughness'].default_value = 1.0
        principled_bsdf.inputs['Emission Color'].default_value = emission_color
        principled_bsdf.inputs['Emission Strength'].default_value = emission_strength

        # --- Create links ---
        nt.links.new(principled_bsdf.outputs['BSDF'], output_node.inputs['Surface'])

        shaders[name] = mat

    return shaders