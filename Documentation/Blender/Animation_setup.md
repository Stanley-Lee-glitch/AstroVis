# Setting up Animation

*Covers `Blender_Import/high_level_import.py`, `Blender_Import/mesh_animation.py`, and `Blender_Import/volume_animation.py`.*

Once backend data has been exported, the `Blender_Import` layer turns it into animated Blender objects.

- **HDF5** (`.h5` / `.hdf5`) is used for particle and surface animations.
- **OpenVDB** (`.vdb`) is used for volume animations.
- `setup_animation` is the high-level entry point that can import both in one call.

## High-level import

### ```setup_animation(data_path, object=None, material=None, scale=None, target_size=200, center=False, suppress_vdb_warnings=True) -> dict```

Scans a folder for any combination of HDF5 animation files and VDB volume sequences, then sets up everything it finds.

| Param | Default | Meaning |
|---|---|---|
| `data_path` | — | Folder containing exported animation data. |
| `object` | `None` | For HDF5, restricts loading to these object names. For VDB, a string is used directly as the created object-name prefix, and a list uses its first entry. |
| `material` | `None` | Material applied to created objects. Required in practice for volume rendering; optional for mesh objects. |
| `scale` | `None` | Fixed scale forwarded to mesh animation. |
| `target_size` | `200` | If `scale` is not given, mesh data is auto-scaled toward this size. |
| `center` | `False` | Forwarded to mesh animation to optionally recenter mesh/particle positions per frame. |
| `suppress_vdb_warnings` | `True` | Hides repeated OpenVDB version warnings from the terminal during scripted VDB import. |

Returns:

```python
{
    "mesh": {object_name: bpy.types.Object, ...},
    "volume": bool,
}
```

```python
from AstroVis.api import setup_animation

setup_animation("path/to/exported_frames/", material=my_material)
```

### Methodology

`setup_animation` performs two independent import passes:

1. **HDF5 pass** — every discovered file is read with `save_load_hdf5.load`, then every object inside it is registered through `setup_mesh_animation`.
2. **VDB pass** — if the folder also contains a valid VDB sequence, it is registered through `setup_volume_animation`.

For the HDF5 path, `scale=None` with a non-`None` `target_size` triggers a single auto-computed scale factor based on the largest loaded object's extent, so all imported mesh objects from that call share one consistent size convention.

## Mesh animation

### ```setup_mesh_animation(frames_data, object=None, scale=None, target_size=200, center=False, material=None) -> bpy.types.Object```

Registers a frame-change handler that rebuilds one Blender mesh object from a time series of particle or surface frames.

| Param | Default | Meaning |
|---|---|---|
| `frames_data` | — | One `SPHParticleData`, one `SurfaceData`, or a list of either type. |
| `object` | `None` | Existing `bpy.types.Object` or object name string. If a name is given and no object exists yet, a new mesh object is created. |
| `scale` | `None` | Fixed coordinate scale applied on every frame. |
| `target_size` | `200` | Used only when `scale` is `None`; auto-computes a scale from the first frame's extent. |
| `center` | `False` | Recenter coordinates/vertices around their mean on each frame update. |
| `material` | `None` | Optional material assigned to the object. |

### Methodology

- If `frames_data` contains **particles**, the mesh's vertex count is resized as needed, point positions are rewritten every frame, and every field in `frame.fields` is exposed as a Blender `FLOAT` / `POINT` attribute.
- If `frames_data` contains a **surface**, the mesh is fully rebuilt every frame from `vertices` and `faces`.
- Animation is driven by a `bpy.app.handlers.frame_change_post` callback rather than baked keyframes.
- Re-registering animation for the same object replaces the old handler via `remove_existing_handler`, so repeated calls do not stack duplicate callbacks.

```python
from AstroVis.api import setup_mesh_animation

setup_mesh_animation(surface_frames, object="ShockSurface", target_size=150)
```

### Known limitations

- Auto-scaling uses the **first frame only**. If the object's physical extent changes significantly later, the rendered size will drift relative to the original target.
- `center=True` recenters each frame independently, which is useful for inspection but removes absolute motion through the scene.

## Volume animation

### ```setup_volume_animation(vdb_folder, object="Volume", material=None, scale=None, target_size=None, suppress_vdb_warnings=True)```

Imports a VDB time series as one collection per frame, with per-frame visibility keyframes.

| Param | Default | Meaning |
|---|---|---|
| `vdb_folder` | — | Folder containing either a flat VDB sequence or `frame_*` subfolders. |
| `object` | `"Volume"` | Prefix for each created Blender volume object name. |
| `material` | `None` | Material assigned through `Blender_Effect.object.set_object_shader`. |
| `scale` | `None` | Fixed object scale applied to every imported VDB object. |
| `target_size` | `None` | If `scale` is omitted, approximate per-object scaling target based on the imported object bounds. |
| `suppress_vdb_warnings` | `True` | Temporarily silences terminal warnings emitted by Blender/OpenVDB while each VDB file is imported. |

### Layouts

Two folder layouts are supported:

1. **Flat sequence** — `.vdb` files directly under `vdb_folder`, one file per frame.
2. **Partitioned sequence** — `frame_*/` subfolders, each containing one or more `.vdb` files for that frame.

The partitioned layout is the one produced by `grid_to_vdb.hierarchy_to_multiple_vdbs` when a volume frame has been split into many blocks.

### Methodology

For each detected frame:

1. A Blender collection named `frame_{NNN}` is created.
2. Every `.vdb` file for that frame is imported through Blender's native `bpy.ops.object.volume_import` path, then moved into the frame collection.
3. A material and scale are assigned.
4. Visibility is keyframed so those objects are hidden before the frame, visible on their frame, then hidden again immediately after.

This means the full sequence exists in the scene at once, with playback driven purely by hide/unhide keyframes.

When `suppress_vdb_warnings=True`, AstroVis temporarily captures terminal stderr during the operator call, suppresses only the repeated warning `unsupported VDB file format ... got version 225`, and replays any other diagnostics. If stderr capture is unavailable in the current Blender environment, AstroVis falls back to the normal unsuppressed operator call.

AstroVis also resets imported VDB objects back to zero location and zero rotation after the operator import so the result does not depend on the current 3D cursor or add-object orientation settings. If Blender's native operator does not return exactly one new volume object, AstroVis falls back to direct `bpy.data.volumes` creation for compatibility.

```python
from AstroVis.api import setup_volume_animation

setup_volume_animation("path/to/vdb_frames/", object="Gas", material=gas_material)
```

### Known limitations

- All frame objects remain loaded simultaneously, so memory usage scales with the total frame count and number of partitions.
- `target_size` is computed per imported VDB object independently from the imported object bounds, so partitions or frames with different bounds do not automatically preserve a global relative size convention.

## See also

- [`Volume_Data`](../Backend/Volume_Data.md) — how grid data is loaded and exported to VDB
- [`Node_and_shading`](Node_and_shading.md) — assigning materials and adding Geometry Nodes effects after import
