## This module provides functions to create volume and mesh materials in Blender, including
#  - create_volume_materials: Create individual volume materials for multiple species.
#  - create_mesh_materials: Create individual Principled BSDF mesh materials for multiple species.
#  - create_combined_grid_material: Create combined volume materials from multiple VDB grids via binary tree reduction.
#  - create_field_volume_material: Create continuous field-driven volume materials using a matplotlib colormap.
#  - create_transparent_mesh_materials: Create Principled BSDF mesh materials with Fresnel-driven transparency.


import bpy
import colorsys
from typing import Union
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
    stops: list[tuple],
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
    ior: float = 1.5,
    alpha: float = 1.0,
    location: tuple = (0, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeBsdfPrincipled")
    node.location = location
    node.inputs["Base Color"].default_value = base_color
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Roughness"].default_value = roughness
    node.inputs["IOR"].default_value = ior
    node.inputs["Alpha"].default_value = alpha
    node.inputs["Emission Color"].default_value = emission_color
    node.inputs["Emission Strength"].default_value = emission_strength
    return node

def _add_fresnel_node(
    nt: bpy.types.NodeTree,
    location: tuple = (0, 0),
    ior: float = 1.1
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeFresnel")
    node.location = location
    node.inputs["IOR"].default_value = ior
    return node

def _add_add_shader(
    nt: bpy.types.NodeTree,
    location: tuple = (0, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeAddShader")
    node.location = location
    return node

def _add_mix_shader(
    nt: bpy.types.NodeTree,
    location: tuple = (0, 0),
) -> bpy.types.Node:
    node = nt.nodes.new("ShaderNodeMixShader")
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


def _normalize_species_names(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]]
) -> list[str]:
    """
    Normalize any accepted species/object input shape into a flat list of name strings.

    Accepts: a single name string, a single bpy.types.Object, or a list mixing
    either of those, in any combination.
    """
    if isinstance(species_names, str):
        return [species_names]
    elif isinstance(species_names, bpy.types.Object):
        return [species_names.name]
    elif isinstance(species_names, list):
        return [obj.name if isinstance(obj, bpy.types.Object) else obj for obj in species_names]
    else:
        raise TypeError(
            f"species_names must be a str, bpy.types.Object, or list of either; got {type(species_names)}"
        )


def _apply_material_to_object(name: str, mat: bpy.types.Material) -> bool:
    """Apply `mat` to bpy.data.objects[name].data if the object exists. Returns success."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        print(f"  Warning: Object '{name}' not found in bpy.data.objects. Material '{mat.name}' not applied.")
        return False
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    print(f"  Applied '{mat.name}' to object '{obj.name}'.")
    return True


## Colour helpers

def sample_matplotlib_cmap(
    cmap_name: str = "viridis",
    n_stops: int = 8,
) -> list[tuple]:
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


def autogenerate_colors(n: int, alpha: float = 1.0) -> list[tuple]:
    """Generate N evenly-spaced HSV colors, returned as list of (R, G, B, A)."""
    return [colorsys.hsv_to_rgb(i / n, 0.6, 1) + (alpha,) for i in range(n)]


#  Public shader factories

def create_volume_materials(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]],
    field_attribute: str = "density",
    species_colors_map: dict[str, tuple] = None,
    emission_multiplier: float = 0.1,
    apply: bool = True,
) -> dict[str, tuple]:
    """
    Create volume materials for one or more species.
    Existing materials with the same name will be overwritten.

    Args:
        species_names:       (list of) object/species name(s), or bpy.types.Object(s)
        field_attribute:     attribute field to visualise for all species
        species_colors_map:  optional dict mapping species_name to (R, G, B, A) color tuple
        emission_multiplier: scaling for emission strength
        apply:                if True, apply each material directly to the matching object

    Returns:
        dict: {species_name: (bpy_material, applied)}
    """
    species_names = _normalize_species_names(species_names)
    N = len(species_names)

    if species_colors_map is None:
        colors = autogenerate_colors(N)
        species_colors_map = {name: colors[i] for i, name in enumerate(species_names)}

    print(f"\n{'='*50}")
    print(f"Creating volume materials for species: {species_names}")
    print("-" * 50)
    print(f"  Field attribute: {field_attribute}")
    print(f"  Colors: {species_colors_map}")
    print(f"  Emission multiplier: {emission_multiplier}")
    print("-" * 50)

    stops = {
        name: [(0.0, *species_colors_map[name]), (1.0, *species_colors_map[name])]
        for name in species_names
    }

    materials = {}

    for name in species_names:
        mat = _get_or_create_material(f"{name}_volmat")
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

        print(f"Created volume material '{mat.name}' for species '{name}'.")
        applied = _apply_material_to_object(name, mat) if apply else None
        materials[name] = (mat, applied)

    print("=" * 50)

    return materials


def create_mesh_materials(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]],
    base_color: dict[str, tuple] = None,
    emission_color: dict[str, tuple] = None,
    emission_strength: float = 0.15,
    apply: bool = True,
) -> dict[str, tuple]:
    """
    Create Principled BSDF mesh materials for one or more species.

    Args:
        species_names:      (list of) object/species name(s), or bpy.types.Object(s)
        base_color:         dict mapping species names to (R, G, B, A) base color tuples
        emission_color:     dict mapping species names to (R, G, B, A) emission color tuples
        emission_strength:  emission strength
        apply:                if True, apply each material directly to the matching object

    Returns:
        dict: {species_name: (bpy_material, applied)}
    """
    species_names = _normalize_species_names(species_names)

    if base_color is None:
        base_color = {name: (0.54, 0.20, 0.0, 1.0) for name in species_names}

    if emission_color is None:
        emission_color = {name: (0.57, 0.15, 0.0, 1.0) for name in species_names}

    print(f"\n{'='*50}")
    print(f"Creating mesh materials for species: {species_names}")
    print("-" * 50)
    print(f"  Base colors: {base_color}")
    print(f"  Emission colors: {emission_color}")
    print(f"  Emission strength: {emission_strength}")
    print("-" * 50)

    materials = {}

    for name in species_names:
        mat = _get_or_create_material(f"{name}_meshmat")
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

        print(f"Created mesh material '{mat.name}' for species '{name}'.")
        applied = _apply_material_to_object(name, mat) if apply else None
        materials[name] = (mat, applied)

    print("=" * 50)

    return materials


def create_combined_grid_material(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]],
    field_min: float = 0.0,
    field_max: float = 1.0,
    emission_multiplier: float = 0.1,
    cmap_name: str = "viridis",
    apply: bool = True,
) -> dict[str, tuple]:
    """
    Create combined volume materials, each merging all grids from one VDB volume
    using an AddShader binary tree reduction.

    Args:
        species_names:        (list of) volume object/species name(s) in bpy.data.volumes
        field_min:            minimum field value for Map Range node
        field_max:            maximum field value for Map Range node
        emission_multiplier:  scaling for emission strength
        cmap_name:            name of the matplotlib colormap
        apply:                 if True, apply each material directly to the matching object

    Returns:
        dict: {species_name: (bpy_material, applied)}
    """
    species_names = _normalize_species_names(species_names)

    print(f"\n{'='*50}")
    print(f"Creating combined grid materials for species: {species_names}")
    print("-" * 50)
    print(f"  Field range: [{field_min}, {field_max}]")
    print(f"  Emission multiplier: {emission_multiplier}")
    print(f"  Colormap: {cmap_name}")
    print("-" * 50)

    bpy.context.scene.render.engine = "CYCLES"

    colors = sample_matplotlib_cmap(cmap_name)
    stops = [(i / 7, *color) for i, color in enumerate(colors)]  ## Default 8 stops in colour map

    materials = {}

    for species_name in species_names:
        bpy.data.volumes[species_name].grids.load()
        grid_list = list(bpy.data.volumes[species_name].grids.keys())
        print(f"  '{species_name}': found {len(grid_list)} grids.")

        mat = _get_or_create_material(f"{species_name}_volmat")
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

        print(f"Created combined grid material '{mat.name}' for species '{species_name}'.")
        applied = _apply_material_to_object(species_name, mat) if apply else None
        materials[species_name] = (mat, applied)

    print("=" * 50)

    return materials


def create_field_volume_material(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]],
    field: str = "density",
    field_min: float = 0.0,
    field_max: float = 1.0,
    emission_multiplier: float = 0.1,
    cmap_name: str = "viridis",
    apply: bool = True,
) -> dict[str, tuple]:
    """
    Create volume material(s) driven by a field value using a matplotlib colormap.

    Args:
        species_names:        (list of) species name(s), or bpy.types.Object(s)
        field:                attribute field to visualise
        field_min:            minimum field value for Map Range node
        field_max:            maximum field value for Map Range node
        emission_multiplier:  scaling for emission strength
        cmap_name:            matplotlib colormap name e.g. 'viridis', 'inferno'
        apply:                 if True, apply each material directly to the matching object

    Returns:
        dict: {species_name: (bpy_material, applied)}
    """
    species_names = _normalize_species_names(species_names)

    print(f"\n{'='*50}")
    print(f"Creating field volume materials for species: {species_names}")
    print("-" * 50)
    print(f"  Field: {field}")
    print(f"  Field range: [{field_min}, {field_max}]")
    print(f"  Emission multiplier: {emission_multiplier}")
    print(f"  Colormap: {cmap_name}")
    print("-" * 50)

    colors = sample_matplotlib_cmap(cmap_name)
    stops = [(i / 7, *color) for i, color in enumerate(colors)]  ## Default 8 stops in colour map

    materials = {}

    for species_name in species_names:
        mat = _get_or_create_material(f"{species_name}_volmat")
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

        print(f"Created field volume material '{mat.name}' for species '{species_name}'.")
        applied = _apply_material_to_object(species_name, mat) if apply else None
        materials[species_name] = (mat, applied)

    print("=" * 50)

    return materials


def create_transparent_mesh_materials(
    species_names: Union[str, bpy.types.Object, list[str], list[bpy.types.Object]],
    refractive_index: float = 1.1,
    constrast_index: tuple = (0.0, 1.0),
    base_color: dict[str, tuple] = None,
    emission_color: dict[str, tuple] = None,
    emission_strength: float = 5,
    apply: bool = True,
) -> dict[str, tuple]:
    """
    Create Principled BSDF mesh materials for one or more species using a Fresnel node.

    Args:
        species_names:      (list of) object/species name(s), or bpy.types.Object(s)
        base_color:         dict mapping species names to (R, G, B, A) base color tuples
        emission_color:     dict mapping species names to (R, G, B, A) emission color tuples
        emission_strength:  emission strength
        apply:                if True, apply each material directly to the matching object

    Returns:
        dict: {species_name: (bpy_material, applied)}
    """
    species_names = _normalize_species_names(species_names)
    N = len(species_names)

    if base_color is None:
        base_color = {name: c for name, c in zip(species_names, autogenerate_colors(N))}

    if emission_color is None:
        emission_color = base_color

    print(f"\n{'='*50}")
    print(f"Creating transparent mesh materials for species: {species_names}")
    print("-" * 50)
    print(f"  Base colors: {base_color}")
    print(f"  Emission colors: {emission_color}")
    print(f"  Emission strength: {emission_strength}")
    print(f"  Refractive index: {refractive_index}")
    print(f"  Contrast index: {constrast_index}")
    print("-" * 50)

    materials = {}

    for name in species_names:
        mat = _get_or_create_material(f"{name}_tranmeshmat")
        nt = mat.node_tree
        _clear_node_tree(nt)

        # Nodes
        bsdf_node_trans = _add_principled_bsdf(
            nt,
            base_color=base_color[name],
            emission_color=emission_color[name],
            emission_strength=0.0,
            alpha=0.0,
            location=(-300, -100),
        )

        bsdf_node_col = _add_principled_bsdf(
            nt,
            base_color=base_color[name],
            emission_color=emission_color[name],
            emission_strength=emission_strength,
            location=(-300, -500),
        )

        fresnel_node = _add_fresnel_node(nt, location=(-400, 200), ior=refractive_index)
        color_ramp_node = _add_color_ramp(
            nt,
            [(constrast_index[0], 0.0, 0.0, 0.0, 1.0), (constrast_index[1], 1.0, 1.0, 1.0, 1.0)],
            location=(-200, 200),
        )
        mix_shader_node = _add_mix_shader(nt, location=(200, 0))
        output_node = _add_output_node(nt, location=(400, 0))

        # Links
        nt.links.new(bsdf_node_trans.outputs["BSDF"], mix_shader_node.inputs[1])
        nt.links.new(bsdf_node_col.outputs["BSDF"], mix_shader_node.inputs[2])
        nt.links.new(fresnel_node.outputs["Fac"], color_ramp_node.inputs[0])
        nt.links.new(color_ramp_node.outputs["Color"], mix_shader_node.inputs[0])
        nt.links.new(mix_shader_node.outputs["Shader"], output_node.inputs["Surface"])

        print(f"Created transparent mesh material '{mat.name}' for species '{name}'.")
        applied = _apply_material_to_object(name, mat) if apply else None
        materials[name] = (mat, applied)

    print("=" * 50)

    return materials