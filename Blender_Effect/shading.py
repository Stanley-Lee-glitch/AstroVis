import bpy
import colorsys
import typing
import numpy as np

def create_volume_shaders(
    species_names: typing.List[str],
    species_colors: typing.Tuple = None,
    color_low: typing.Tuple = (1.0, 0.7, 0.0, 1.0),
    color_high: typing.Tuple = (1.0, 0.1, 0.0, 1.0),
    emission_multiplier: float = 0.1,
    density_attribute: str = "density",
) -> typing.Dict[str, bpy.types.Material]:
    
    """
    Create volume shaders to the object. 
    Existing shaders with the same name will be overwritten.
    Other existing shaders of the object will be unlinked (but not removed). 
    Default using most extreme colors from a color ramp.

    Args:
        species_names: list of object/ species names
        color_low: (R, G, B, A) color for low density
        color_high: (R, G, B, A) color for high density
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

        ramp_node = nt.nodes.new("ShaderNodeValToRGB")
        ramp_node.location = (-200, 200)
        ramp_node.color_ramp.interpolation = 'LINEAR'
        while len(ramp_node.color_ramp.elements) > 1:
            ramp_node.color_ramp.elements.remove(ramp_node.color_ramp.elements[1])

        # Low density color (e.g. dark blue)
        ramp_node.color_ramp.elements[0].position = 0.0
        ramp_node.color_ramp.elements[0].color = color_low

        # High density color (e.g. bright orange)
        el = ramp_node.color_ramp.elements.new(1.0)
        el.color = color_high

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

## For multiple grids in a single volume
def create_combined_volume_shader(
    species_name: str,  
    color_low: tuple = (1.0, 0.7, 0.0, 1.0),
    color_high: tuple = (1.0, 0.1, 0.0, 1.0), 
    emission_multiplier: float = 0.001,
    density_min: float = -2.0,   # your global log10 min
    density_max: float = 2.0,    # your global log10 max
) -> bpy.types.Material:
    
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.data.volumes[species_name].grids.load()
    grid_list = list(bpy.data.volumes[species_name].grids.keys())
    print(f"Found {len(grid_list)} grids.")
    
    mat_name = f"{species_name}_volshader"
    if bpy.data.materials.get(mat_name):
        bpy.data.materials.remove(bpy.data.materials.get(mat_name))
    
    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    for node in nt.nodes:
        nt.nodes.remove(node)

    output_node = nt.nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (1000, 0)

    volume_outputs = []

    for i, grid_name in enumerate(grid_list):
        y_offset = i * -300

        attr_node = nt.nodes.new("ShaderNodeAttribute")
        attr_node.attribute_name = grid_name
        attr_node.location = (-800, y_offset)

        # Map Range: absolute density_min/max → 0..1
        map_node = nt.nodes.new("ShaderNodeMapRange")
        map_node.location = (-550, y_offset)
        map_node.inputs['From Min'].default_value = density_min
        map_node.inputs['From Max'].default_value = density_max
        map_node.inputs['To Min'].default_value = 0.0
        map_node.inputs['To Max'].default_value = 1.0
        map_node.clamp = True  # clamp so out-of-range values don't break color ramp

        ramp_node = nt.nodes.new("ShaderNodeValToRGB")
        ramp_node.location = (-300, y_offset)
        ramp_node.color_ramp.interpolation = 'LINEAR'
        while len(ramp_node.color_ramp.elements) > 1:
            ramp_node.color_ramp.elements.remove(ramp_node.color_ramp.elements[1])

        # Low density color (e.g. dark blue)
        ramp_node.color_ramp.elements[0].position = 0.0
        ramp_node.color_ramp.elements[0].color = color_low

        # High density color (e.g. bright orange)
        el = ramp_node.color_ramp.elements.new(1.0)
        el.color = color_high
        
        math_node = nt.nodes.new("ShaderNodeMath")
        math_node.operation = 'MULTIPLY'
        math_node.inputs[1].default_value = emission_multiplier
        math_node.location = (-300, y_offset - 150)

        volume_node = nt.nodes.new("ShaderNodeVolumePrincipled")
        volume_node.location = (0, y_offset)
        volume_node.inputs['Density'].default_value = 0

        # Attribute → Map Range → Color Ramp + Emission
        nt.links.new(attr_node.outputs['Fac'], map_node.inputs['Value'])
        nt.links.new(map_node.outputs['Result'], ramp_node.inputs['Fac'])
        nt.links.new(map_node.outputs['Result'], math_node.inputs[0])
        nt.links.new(ramp_node.outputs['Color'], volume_node.inputs['Emission Color'])
        nt.links.new(math_node.outputs[0], volume_node.inputs['Emission Strength'])

        volume_outputs.append(volume_node.outputs['Volume'])

    # Binary tree reduction
    add_x = 350
    level_counter = 0
    nodes_in_current_level = len(volume_outputs)

    while len(volume_outputs) > 1:
        out1 = volume_outputs.pop(0)
        out2 = volume_outputs.pop(0)

        add_shader = nt.nodes.new("ShaderNodeAddShader")
        
        add_shader.location = (add_x, -level_counter * 80)
        level_counter += 1

        nt.links.new(out1, add_shader.inputs[0])
        nt.links.new(out2, add_shader.inputs[1])

        volume_outputs.append(add_shader.outputs['Shader'])

        nodes_in_current_level -= 2
        if nodes_in_current_level <= 1:
            add_x += 220
            nodes_in_current_level = len(volume_outputs)

    if volume_outputs:
        nt.links.new(volume_outputs[0], output_node.inputs['Volume'])

    return mat

def create_plt_colourmap(
    cmap_name: str = "viridis",
    n_stops: int = 8,
) -> typing.List[tuple]:
    """
    Sample a matplotlib colormap to get RGBA stops for Blender's ColorRamp.

    Args:
        cmap_name: name of the matplotlib colormap (e.g. 'viridis', 'inferno', 'magma')
        n_stops: number of stops to sample from the colormap
    
    Returns:
        List of tuples: [(position, R, G, B, A), ...] where position is in [0, 1] and RGBA are in [0, 1]
    """
    
    import matplotlib.pyplot as plt
    cmap = plt.get_cmap(cmap_name)
    cmap_stops = [(float(t), *cmap(t)) for t in np.linspace(0, 1, n_stops)]
    
    
    
)
def create_plt_shader(
    species_name: str,
    # --- Field Parameters ---
    field: str = "density",
    field_min: float = 0.0,
    field_max: float = 1.0,
    # --- Colormap Parameters ---
    emission_multiplier: float = 0.1,
    cmap_name: str = "viridis",
    cmap_n_stops: int = 8,
) -> bpy.types.Material:
    """
    Create volume shaders using a matplotlib colormap.
    ColorRamp stops are automatically sampled from the colormap.

    Args:
        species_name:        name of the species
        field:               field to visualize 
        field_min:           minimum field value for Map Range node
        field_max:           maximum field value for Map Range node
        emission_multiplier: scaling for emission strength
        cmap_name:           matplotlib colormap name e.g. 'viridis', 'inferno', 'magma'
        cmap_n_stops:        number of ColorRamp stops to sample from the colormap

    Returns:
        bpy.types.Material: The created material
    """
    
    import numpy as np
    import matplotlib.pyplot as plt

    # --- Sample colormap stops ---
    cmap = plt.get_cmap(cmap_name)
    cmap_stops = [(float(t), *cmap(t)) for t in np.linspace(0, 1, cmap_n_stops)]

    mat_name = f"{species_name}_volshader"

    if bpy.data.materials.get(mat_name) is not None:
        bpy.data.materials.remove(bpy.data.materials.get(mat_name))

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    for node in nt.nodes:
        nt.nodes.remove(node)

    # --- Nodes ---
    output_node = nt.nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (600, 0)

    volume_node = nt.nodes.new("ShaderNodeVolumePrincipled")
    volume_node.location = (300, 0)
    volume_node.inputs['Density'].default_value = 0

    attr_node = nt.nodes.new("ShaderNodeAttribute")
    attr_node.attribute_name = field
    attr_node.location = (-600, 0)

    map_range_node = nt.nodes.new("ShaderNodeMapRange")
    map_range_node.location = (-350, 0)
    map_range_node.inputs['From Min'].default_value = field_min
    map_range_node.inputs['From Max'].default_value = field_max
    map_range_node.inputs['To Min'].default_value = 0.0
    map_range_node.inputs['To Max'].default_value = 1.0

    ramp_node = nt.nodes.new("ShaderNodeValToRGB")
    ramp_node.location = (-100, 200)
    ramp_node.color_ramp.interpolation = 'LINEAR'

    while len(ramp_node.color_ramp.elements) > 1:
        ramp_node.color_ramp.elements.remove(ramp_node.color_ramp.elements[1])

    # Populate stops directly from cmap — no manual color input
    ramp_node.color_ramp.elements[0].position = cmap_stops[0][0]
    ramp_node.color_ramp.elements[0].color = cmap_stops[0][1:]
    for pos, r, g, b, a in cmap_stops[1:]:
        el = ramp_node.color_ramp.elements.new(pos)
        el.color = (r, g, b, a)

    math_node = nt.nodes.new("ShaderNodeMath")
    math_node.operation = 'MULTIPLY'
    math_node.inputs[1].default_value = emission_multiplier
    math_node.location = (-100, -200)

    # --- Links ---
    nt.links.new(attr_node.outputs['Fac'], map_range_node.inputs['Value'])
    nt.links.new(map_range_node.outputs['Result'], ramp_node.inputs['Fac'])
    nt.links.new(map_range_node.outputs['Result'], math_node.inputs[0])
    nt.links.new(math_node.outputs[0], volume_node.inputs['Emission Strength'])
    nt.links.new(ramp_node.outputs['Color'], volume_node.inputs['Emission Color'])
    nt.links.new(volume_node.outputs['Volume'], output_node.inputs['Volume'])

    return mat