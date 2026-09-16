# Blender Object and Scene Utilities

*Covers `Blender_Effect/object.py` and `Blender_Effect/scene.py`.*

This page summarizes the practical Blender-side helpers that AstroVis uses after data has already been imported. These utilities are the small building blocks for:

- resolving Blender objects by name,
- assigning materials,
- creating or duplicating helper objects,
- managing modifier stacks,
- clearing scenes safely,
- configuring cameras, lights, world background, and render settings.

## When to use these helpers

Use `object.py` when you already know **which Blender object** you want to operate on.

Use `scene.py` when you want to manage the **whole scene state**: cleanup, light setup, camera framing, output path, and render defaults.

## Controlling the Objects

### `resolve_object(obj) -> bpy.types.Object`

Accepts either:

- a `bpy.types.Object`, or
- an object name string.

This is the standard entry point used by many AstroVis helpers.

```python
from AstroVis.api import resolve_object

gas_obj = resolve_object("Gas_density_l0_b0")
```

### `create_object(obj_name) -> bpy.types.Object`

Creates a fresh mesh object in the active collection. If an object or mesh of the same name already exists, it is removed first.

```python
from AstroVis.api import create_object

obj = create_object("DebugMesh")
```

### `duplicate_object(original_obj, new_name) -> bpy.types.Object`

Creates a new object linked to the original object's data block.

```python
from AstroVis.api import duplicate_object

dense_obj = duplicate_object("ImpactParticles", "ImpactParticles_copy")
```

### `set_object_shader(obj, shader_name=None)`

Assign a material to an object.

- if `shader_name` is a string, AstroVis looks up that material by name,
- if it is already a `bpy.types.Material`, AstroVis uses it directly,
- if it is omitted, AstroVis tries to find the first material whose name contains the object name.

```python
from AstroVis.api import set_object_shader

set_object_shader("Gas_density_l0_b0", "Gas_volmat")
```

### Modifier helpers

- `list_modifiers(obj)`
- `delete_modifier(obj, mod_name)`
- `move_modifier(obj, mod_name, direction="up")`
- `add_gn_modifer(obj, mod_name)`

These are useful when building Geometry Nodes workflows incrementally.

```python
from AstroVis.api import add_gn_modifer, list_modifiers

modifier, node_group = add_gn_modifer("ImpactParticles", "ImpactParticles_select")
list_modifiers("ImpactParticles")
```

## Controlling the Scene

### `SceneManager`

`SceneManager` is the high-level wrapper for scene-wide operations.

If you omit `export_dir`, AstroVis uses a user-writable default:

```text
~\AstroVis\output
```

```python
from AstroVis.api import SceneManager

scene = SceneManager(scene_name="ShockScene", export_dir=r"C:\renders")
```

## Scene cleanup

### `clear_scene(use_empty=True)`

Two cleanup modes are supported:

1. `use_empty=True` reloads Blender's empty startup scene.
2. `use_empty=False` performs structured cleanup through AstroVis helpers.

```python
scene.clear_scene(use_empty=False)
```

### Focused cleanup helpers

- `clear_all(...)`
- `clear_objects(object_types=None, exclude_names=None, clear_data=True)`
- `clear_mesh_objects()`
- `clear_volume_objects()`
- `clear_lights()`
- `clear_cameras()`
- `clear_collections()`
- `clear_materials()`
- `clear_node_groups()`
- `clear_images()`
- `clear_orphan_data()`

These are useful when you want to keep part of a scene while replacing only one layer of imported data.

```python
scene.clear_volume_objects()
scene.clear_lights()
```

## Camera setup

### `set_camera(...)`

Creates or reuses a camera, points it toward `look_at`, and assigns it to the active scene.

```python
scene.set_camera(
    location=(8, -8, 5),
    look_at=(0, 0, 0),
    lens=45,
)
```

## Lighting setup

### `set_light(...)` and `add_light(...)`

Use these for one light at a time. They support light type, energy, color, size, collection placement, and optional `look_at`.

```python
scene.set_light(
    name="SunKey",
    light_type="SUN",
    location=(6, -6, 8),
    energy=2.5,
    size=0.12,
)
```

### `set_lights(light_configs, clear_existing=False, collection_name="Lights")`

Use this when you want to define several lights in one call.

```python
scene.set_lights(
    [
        {"name": "Key", "light_type": "AREA", "location": (4, -4, 5), "energy": 2000.0, "size": 2.0},
        {"name": "Fill", "light_type": "POINT", "location": (0, 4, 2), "energy": 150.0, "size": 0.2},
        {"name": "Rim", "light_type": "POINT", "location": (-3, 2, 4), "energy": 300.0, "size": 0.2},
    ],
    clear_existing=True,
)
```

### `add_light_grid(...)`

This is useful for the exact case of “many small lights at once”.

```python
scene.add_light_grid(
    name_prefix="Fill",
    count_x=3,
    count_y=3,
    spacing=(2.5, 2.5),
    center=(0.0, 0.0, 0.0),
    height=3.0,
    light_type="POINT",
    energy=200.0,
    size=0.2,
)
```

## World and render settings

### `set_world_background(color=(0, 0, 0, 1), strength=1.0)`

Rebuilds the world node tree as a simple background shader.

```python
scene.set_world_background(color=(0.0, 0.0, 0.0, 1.0), strength=0.02)
```

### `set_render(...)`

Sets render engine, samples, resolution, transparency, output filepath, and optional FPS.

```python
scene.set_render(
    engine="CYCLES",
    samples=128,
    resolution=(1920, 1080),
    filepath="shock_render.png",
)
```

### `get_export_path(filename="output.png")`

Builds a path under the `export_dir` given to `SceneManager`.

```python
output_path = scene.get_export_path("frame_0100.png")
```

## Typical workflow

```python
from AstroVis.api import SceneManager, set_object_shader

scene = SceneManager(scene_name="VolumeScene", export_dir=r"C:\renders")
scene.clear_scene(use_empty=False)
scene.set_world_background(color=(0.0, 0.0, 0.0, 1.0), strength=0.02)
scene.set_camera(location=(8, -8, 5), look_at=(0, 0, 0), lens=45)
scene.set_light(name="SunKey", light_type="SUN", location=(6, -6, 8), energy=2.5, size=0.12)
scene.add_light_grid(name_prefix="Fill", count_x=3, count_y=3, spacing=(2.5, 2.5), height=3.0, light_type="POINT", energy=200.0, size=0.2)

set_object_shader("Gas_density_l0_b0", "Gas_volmat")
scene.set_render(engine="CYCLES", samples=128, resolution=(1920, 1080))
```

## See also

- [`Animation_setup.md`](Animation_setup.md)
- [`Node_and_shading.md`](Node_and_shading.md)
- [`../Overview.md`](../Overview.md)
