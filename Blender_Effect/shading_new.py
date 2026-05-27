import bpy
import colorsys
import typing
import numpy as np

## Node creation helpers

def _add_output_node(
    nt: bpy.types.NodeTree,
    location: tuple = (400, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeOutputMaterial")
    node.location = location
    return node


def _add_volume_principled(
    nt: bpy.types.NodeTree,
    density: float = 0.0,
    location: tuple = (100, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeVolumePrincipled")
    node.location = location
    node.inputs["Density"].default_value = density
    return node


def _add_attr_node(
    nt: bpy.types.NodeTree,
    attribute_name: str,
    location: tuple = (-400, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeAttribute")
    node.attribute_name = attribute_name
    node.location = location
    return node


def _add_map_range(
    nt: bpy.types.NodeTree,
    from_min: float = 0.0,
    from_max: float = 1.0,
    to_min: float = 0.0,
    to_max: float = 1.0,
    clamp: bool = True,
    location: tuple = (-550, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeMapRange")
    node.location = location
    node.clamp = clamp
    node.inputs["From Min"].default_value = from_min
    node.inputs["From Max"].default_value = from_max
    node.inputs["To Min"].default_value = to_min
    node.inputs["To Max"].default_value = to_max
    return node


def _add_color_ramp(
    nt: bpy.types.NodeTree,
    stops: typing.List[typing.Tuple],
    interpolation: str = "LINEAR",
    location: tuple = (-200, 200),
) -> bpy.types.Node:
    """
    Create a ColorRamp node from a list of stops.

    Args:
        stops: list of (position, R, G, B, A) tuples, at least 2 entries.
               Use `sample_matplotlib_cmap` to build this.
        interpolation: ColorRamp interpolation mode.

    Returns:
        The ColorRamp node.
    """
    node = nt.nodes.new("ShaderNodeValToRGB")
    node.location = location
    node.color_ramp.interpolation = interpolation

    # Remove all but the first element (Blender always keeps at least one)
    while len(node.color_ramp.elements) > 1:
        node.color_ramp.elements.remove(node.color_ramp.elements[1])

    # Set the first stop
    node.color_ramp.elements[0].position = stops[0][0]
    node.color_ramp.elements[0].color = stops[0][1:]

    # Add remaining stops
    for pos, r, g, b, a in stops[1:]:
        el = node.color_ramp.elements.new(pos)
        el.color = (r, g, b, a)

    return node


def _add_emission_math(
    nt: bpy.types.NodeTree,
    multiplier: float = 0.1,
    location: tuple = (-200, -200),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeMath")
    node.operation = "MULTIPLY"
    node.inputs[1].default_value = multiplier
    node.location = location
    return node


def _add_principled_bsdf(
    nt: bpy.types.NodeTree,
    base_color: tuple = (0.54, 0.20, 0.0, 1.0),
    emission_color: tuple = (0.57, 0.15, 0.0, 1.0),
    emission_strength: float = 0.15,
    metallic: float = 0.0,
    roughness: float = 1.0,
    location: tuple = (0, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeBsdfPrincipled")
    node.location = location
    node.inputs["Base Color"].default_value = base_color
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Emission Color"].default_value = emission_color
    node.inputs["Emission Strength"].default_value = emission_strength
    return node


def _add_add_shader(
    nt: bpy.types.NodeTree,
    location: tuple = (0, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeAddShader")
    node.location = location
    return node


##  Utility helpers

def _clear_node_tree(nt: bpy.types.NodeTree) -> None:
    """Remove all nodes from a node tree."""
    for node in nt.nodes:
        nt.nodes.remove(node)


def _get_or_create_material(mat_name: str) -> bpy.types.Material:
    """Remove any existing material with this name, then create a fresh one."""
    existing = bpy.data.materials.get(mat_name)
    if existing is not None:
        bpy.data.materials.remove(existing)
    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    return mat

## Coloour helpers

def sample_matplotlib_cmap(
    cmap_name: str = "viridis",
    n_stops: int = 8,
) -> typing.List[tuple]:
    """
    Sample a matplotlib colormap to produce ColorRamp stops.

    Args:
        cmap_name: matplotlib colormap name e.g. 'viridis', 'inferno', 'magma'
        n_stops:   number of stops to sample

    Returns:
        List of (R, G, B, A) tuples with values in [0, 1].
    """
    import matplotlib.pyplot as plt
    cmap = plt.get_cmap(cmap_name)
    return [cmap(t) for t in np.linspace(0, 1, n_stops)]


def autogenerate_colors(n: int, alpha: float = 1.0) -> typing.List[tuple]:
    """Generate N evenly-spaced HSV colors, returned as (R, G, B, A)."""
    return [colorsys.hsv_to_rgb(i / n, 0.6, 1) + (alpha,) for i in range(n)] 


# ─────────────────────────────────────────────
#  Public shader factories
# ─────────────────────────────────────────────

def create_volume_shaders(
    species_names: typing.List[str],
    field_attribute: str = "density",
    species_colors_map: typing.Dict[str, tuple] = None,  
    emission_multiplier: float = 0.1,
) -> typing.Dict[str, bpy.types.Material]:
    """
    Create volume shaders for one or more species.
    Existing shaders with the same name will be overwritten.

    Args:
        species_names:       list of object/species names
        field_attribute:     attribute field to visualise for all species
        species_colors_map:  optional dict mapping species_name to (R, G, B, A) color tuple
        emission_multiplier: scaling for emission strength
        
    Returns:
        dict: {species_name: bpy_material}
    """
    if isinstance(species_names, str):
        species_names = [species_names]

    N = len(species_names)
    
    ## Create stop for colour ramp
    ## If no color map provided, generate one with evenly spaced hues in HSV space
    for i, name in enumerate(species_names):
        if species_colors_map is None:
            colors = autogenerate_colors(N)
            species_colors_map = {name: colors[i] for i, name in enumerate(species_names)}

        stops = {
            name: [(0.0, *species_colors_map[name]), (1.0, *species_colors_map[name])]
            for name in species_names
        }
 
    
    shaders = {}

    for name in species_names:
        mat = _get_or_create_material(f"{name}_volshader")
        nt = mat.node_tree
        _clear_node_tree(nt)

        # Nodes
        output_node  = _add_output_node(nt, location=(400, 0))
        volume_node  = _add_volume_principled(nt, location=(100, 0))
        attr_node    = _add_attr_node(nt, field_attribute, location=(-400, 0))
        ramp_node    = _add_color_ramp(nt, stops[name], location=(-200, 200))
        math_node    = _add_emission_math(nt, emission_multiplier, location=(-200, -200))

        # Links
        nt.links.new(attr_node.outputs["Fac"],   math_node.inputs[0])
        nt.links.new(attr_node.outputs["Fac"],   ramp_node.inputs["Fac"])
        nt.links.new(math_node.outputs[0],       volume_node.inputs["Emission Strength"])
        nt.links.new(ramp_node.outputs["Color"], volume_node.inputs["Emission Color"])
        nt.links.new(volume_node.outputs["Volume"], output_node.inputs["Volume"])

        shaders[name] = mat

    return shaders


def create_mesh_shaders(
    species_names: typing.List[str],
    base_color: typing.Dict[str, tuple] = None,
    emission_color: typing.Dict[str, tuple] = None,
    emission_strength: float = 0.15,
) -> typing.Dict[str, bpy.types.Material]:
    """
    Create Principled BSDF mesh shaders for one or more species.

    Args:
        species_names:    list of object/species names
        base_color:       dict mapping species names to (R, G, B, A) base color tuples
        emission_color:   dict mapping species names to (R, G, B, A) emission color tuples
        emission_strength: emission strength

    Returns:
        dict: {species_name: bpy_material}
    """
    if isinstance(species_names, str):
        species_names = [species_names]

    if base_color is None:
        base_color = {name: (0.54, 0.20, 0.0, 1.0) for name in species_names}
        
    if emission_color is None:
        emission_color = {name: (0.57, 0.15, 0.0, 1.0) for name in species_names}

    shaders = {}

    for name in species_names:
        mat = _get_or_create_material(f"{name}_meshshader")
        nt = mat.node_tree
        _clear_node_tree(nt)

        # Nodes
        output_node = _add_output_node(nt, location=(400, 0))
        bsdf_node   = _add_principled_bsdf(
            nt,
            base_color=base_color.get(name),
            emission_color=emission_color.get(name),
            emission_strength=emission_strength,
            location=(0, 0),
        )

        # Links
        nt.links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

        shaders[name] = mat

    return shaders


def create_combined_volume_shader(
    species_name: str,
    field_min: float = 0.0,
    field_max: float = 1.0,
    emission_multiplier: float = 0.1,
    cmap_name: str = "viridis",
) -> bpy.types.Material:
    """
    Create a single volume shader that combines multiple grids from one VDB
    using an AddShader binary tree reduction.

    Args:
        species_name:        name of the volume object in bpy.data.volumes
        field_min:           minimum field value for Map Range node
        field_max:           maximum field value for Map Range node
        emission_multiplier: scaling for emission strength
        cmap_name:           name of the matplotlib colormap

    Returns:
        bpy.types.Material
    """
    bpy.context.scene.render.engine = "CYCLES"
    bpy.data.volumes[species_name].grids.load()
    grid_list = list(bpy.data.volumes[species_name].grids.keys())
    print(f"Found {len(grid_list)} grids.")

    colors = sample_matplotlib_cmap(cmap_name)
    stops = [(i / 7, *color) for i, color in enumerate(colors)]  ## Default 8 stops in colour map

    mat = _get_or_create_material(f"{species_name}_volshader")
    nt = mat.node_tree
    _clear_node_tree(nt)

    output_node   = _add_output_node(nt, location=(1000, 0))
    volume_outputs = []

    for i, grid_name in enumerate(grid_list):
        y = i * -300

        attr_node    = _add_attr_node(nt, grid_name, location=(-800, y))
        map_node     = _add_map_range(nt, field_min, field_max, location=(-550, y))
        ramp_node    = _add_color_ramp(nt, stops, location=(-300, y))
        math_node    = _add_emission_math(nt, emission_multiplier, location=(-300, y - 150))
        volume_node  = _add_volume_principled(nt, location=(0, y))

        nt.links.new(attr_node.outputs["Fac"],    map_node.inputs["Value"])
        nt.links.new(map_node.outputs["Result"],  ramp_node.inputs["Fac"])
        nt.links.new(map_node.outputs["Result"],  math_node.inputs[0])
        nt.links.new(ramp_node.outputs["Color"],  volume_node.inputs["Emission Color"])
        nt.links.new(math_node.outputs[0],        volume_node.inputs["Emission Strength"])

        volume_outputs.append(volume_node.outputs["Volume"])

    # Binary tree reduction using AddShader nodes
    add_x = 350
    level_counter = 0
    nodes_in_current_level = len(volume_outputs)

    while len(volume_outputs) > 1:
        out1 = volume_outputs.pop(0)
        out2 = volume_outputs.pop(0)

        add_shader = _add_add_shader(nt, location=(add_x, -level_counter * 80))
        level_counter += 1

        nt.links.new(out1, add_shader.inputs[0])
        nt.links.new(out2, add_shader.inputs[1])

        volume_outputs.append(add_shader.outputs["Shader"])

        nodes_in_current_level -= 2
        if nodes_in_current_level <= 1:
            add_x += 220
            nodes_in_current_level = len(volume_outputs)

    if volume_outputs:
        nt.links.new(volume_outputs[0], output_node.inputs["Volume"])

    return mat


def create_volume_field_shader(
    species_name: str,
    field: str = "density",
    field_min: float = 0.0,
    field_max: float = 1.0,
    emission_multiplier: float = 0.1,
    cmap_name: str = "viridis",
) -> bpy.types.Material:
    """
    Create a volume shader according to field values using a matplotlib colormap.

    Args:
        species_name:        name of the species
        field:               attribute field to visualise
        field_min:           minimum field value for Map Range node
        field_max:           maximum field value for Map Range node
        emission_multiplier: scaling for emission strength
        cmap_name:           matplotlib colormap name e.g. 'viridis', 'inferno'

    Returns:
        bpy.types.Material
    """
    colors = sample_matplotlib_cmap(cmap_name)
    stops = [(i / 7, *color) for i, color in enumerate(colors)] ## Default 8 stops in colour map
    
    mat = _get_or_create_material(f"{species_name}_volshader")
    nt = mat.node_tree
    _clear_node_tree(nt)

    # Nodes
    output_node    = _add_output_node(nt, location=(600, 0))
    volume_node    = _add_volume_principled(nt, location=(300, 0))
    attr_node      = _add_attr_node(nt, field, location=(-600, 0))
    map_range_node = _add_map_range(nt, field_min, field_max, location=(-350, 0))
    ramp_node      = _add_color_ramp(nt, stops, location=(-100, 200))
    math_node      = _add_emission_math(nt, emission_multiplier, location=(-100, -200))

    # Links
    nt.links.new(attr_node.outputs["Fac"],    map_range_node.inputs["Value"])
    nt.links.new(map_range_node.outputs["Result"], ramp_node.inputs["Fac"])
    nt.links.new(map_range_node.outputs["Result"], math_node.inputs[0])
    nt.links.new(math_node.outputs[0],        volume_node.inputs["Emission Strength"])
    nt.links.new(ramp_node.outputs["Color"],  volume_node.inputs["Emission Color"])
    nt.links.new(volume_node.outputs["Volume"], output_node.inputs["Volume"])

    return mat