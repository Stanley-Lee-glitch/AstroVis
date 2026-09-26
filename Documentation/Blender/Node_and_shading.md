# Blender Shading and Geometry Nodes

*Covers `Blender_Effect/material.py` and `Blender_Effect/node.py`. For object and scene helpers, see [`Object_and_scene.md`](Object_and_scene.md).*

These modules sit on top of imported AstroVis data and handle the Blender-side presentation layer:

- **`material.py`** builds shader node trees procedurally.
- **`node.py`** builds Geometry Nodes modifiers for particle-to-volume/mesh conversion and selection.

### Current API notes

The Blender helpers intentionally favor names and object handles over raw data arrays. In practice, the public functions accept either:

- a Blender object such as `bpy.types.Object`,
- an object name string, or
- a list mixing those forms for batch operations.

They normalize those inputs before creating or replacing materials and node groups so repeated calls overwrite old results instead of stacking duplicates. The naming pattern is consistent across the modules: generated object names, material names, and Geometry Nodes group names are all derived from the source species object name.

## Shader factories

All material factories accept `species_names` as a single name, a `bpy.types.Object`, or a list mixing either form. Internally they normalize this via `_normalize_species_names`, rebuild any same-named material from scratch, and optionally apply the result directly to matching scene objects.

### ```create_volume_materials(species_names, field_attribute="density", species_colors_map=None, emission_multiplier=0.1, apply=True) -> dict```

Creates one solid-color volume material per species. The field attribute drives **emission strength**, while color stays fixed per species.

| Param | Default | Meaning |
|---|---|---|
| `field_attribute` | `"density"` | Named volume attribute read by the shader. |
| `species_colors_map` | `None` | Optional `{species_name: (R, G, B, A)}` mapping; otherwise colors are auto-generated. |
| `emission_multiplier` | `0.1` | Scales emission strength from the input attribute. |
| `apply` | `True` | If true, assign each material to the matching object immediately. |

### ```create_mesh_materials(species_names, base_color=None, emission_color=None, emission_strength=0.15, apply=True) -> dict```

Creates a plain Principled BSDF material per species for mesh objects.

### ```create_field_volume_material(species_names, field="density", field_min=0.0, field_max=1.0, emission_multiplier=0.1, cmap_name="viridis", apply=True) -> dict```

Creates the main data-driven volume shader. The named attribute is remapped through `[field_min, field_max]`, sampled through a matplotlib colormap, then used for emission color, emission strength, and gradual volume density so lower values stay more transparent.

### ```create_combined_grid_material(species_names, field_min=0.0, field_max=1.0, emission_multiplier=0.1, cmap_name="viridis", apply=True) -> dict```

Builds one volume material for a **single Blender volume object containing many internal VDB grids**. Each internal grid gets its own attribute-driven sub-shader, and all sub-shaders are combined through an `AddShader` reduction tree.

Use this with single-object multi-grid volumes produced by `hierarchy_to_vdb`, not with per-block imported objects from `hierarchy_to_multiple_vdbs`.

### ```create_transparent_mesh_materials(species_names, refractive_index=1.1, constrast_index=(0.0, 1.0), base_color=None, emission_color=None, emission_strength=5, apply=True) -> dict```

Creates a Fresnel-driven transparent/emissive mesh shader. Head-on views remain more transparent while grazing angles become more visible and emissive.

### Methodology

Most shader factories are composed from the same internal helpers:

- `_add_attr_node` reads a named Blender attribute.
- `_add_map_range` normalizes raw field values into `[0, 1]`.
- `_add_color_ramp` turns normalized values into a colormap.
- `_add_emission_math` scales brightness.
- `_add_volume_principled` or `_add_principled_bsdf` emits the final shader branch.

`sample_matplotlib_cmap` provides the color stops, and `autogenerate_colors` provides fallback per-species colors when no explicit mapping is supplied.

```python
from AstroVis.api import create_field_volume_material

create_field_volume_material("Gas", field="density", field_min=-5, field_max=1, cmap_name="inferno")
```

## Geometry Nodes effects

### ```sph_point_to_volume(obj, attribute_name=None, material_name=None, voxel_size=0.02, density=0.2, math_multiplier=0.03) -> bpy.types.NodeTree```

Adds a Geometry Nodes modifier that converts a particle point cloud into a volume.

- `obj` can be an object name or a `bpy.types.Object`.
- If `attribute_name` is provided, that named particle attribute is multiplied by `math_multiplier` and used as the point radius input.
- `material_name` must already exist in `bpy.data.materials`.

### ```sph_point_to_mesh(obj, radius_attr=None, material_name=None, voxel_size=0.3, density=1.0, radius_multiplier=1.1)```

Adds a Geometry Nodes pipeline of **Points to Volume → Volume to Mesh → Set Shade Smooth → Set Material**, producing a renderable surface around the point cloud.

### ```select(obj, new_object_name, mode="attribute", attribute_name=None, compare_value=None, operation="GREATER", target_obj=None, target_element="POINTS", distance=1.0) -> bpy.types.Object```

Duplicates `obj` and adds a Geometry Nodes selection modifier to the duplicate.

Two selection modes are supported:

1. **`mode="attribute"`** — compare a named attribute against `compare_value` with `GREATER`, `LESS`, `EQUAL`, or `NOT_EQUAL`.
2. **`mode="proximity"`** — keep only points within `distance` of `target_obj`, measured against `POINTS`, `EDGES`, or `FACES`.

### Methodology

The Geometry Nodes helpers all rely on `object.resolve_object` and `object.add_gn_modifer` first, so repeated calls replace prior node groups/modifiers of the same generated name instead of stacking duplicates.

```python
from AstroVis.api import sph_point_to_mesh

sph_point_to_mesh("Dust", radius_attr="smoothing_length", material_name="Dust_meshmat")
```

## See also

- [`Animation_setup`](Animation_setup.md) — import animated HDF5 and VDB data before applying these effects
- [`Volume_Data`](../Backend/Volume_Data.md) — backend volume export paths that feed Blender volume materials
- [`Object_and_scene`](Object_and_scene.md) — practical usage guide for `object.py` and `scene.py`
