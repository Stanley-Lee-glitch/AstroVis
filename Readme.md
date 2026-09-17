# AstroVis

**AstroVis** is a modular astrophysical visualization framework designed to transform simulation data into physically interpretable renders in Blender. It provides a bridge between scientific data libraries like `yt` and the powerful rendering capabilities of Blender, enabling automated and reproducible visualization workflows.

## Architecture

AstroVis is structured into three layers, separating scientific data processing from Blender-specific operations.

1.  **Backend**: Blender-independent scientific data manipulation.
    -   Store particle and grid data.
    -   Convert SPH particle data to a grid, and grid data to a surface (isosurface / ridge) or volume (VDB).
    -   Save/load a unified HDF5 exchange format for particles, surfaces, and volumes.
    -   `Backend/workflow.py` wraps a whole snapshot directory into one function call — this is the fastest way to get from simulation output to Blender-ready files (see Quickstart below).
    -   Can be run inside or outside of Blender (no `bpy` dependency).

2.  **Blender\_Import**: Imports processed data into Blender.
    -   Load particle animations.
    -   Load surface mesh animations.
    -   Load VDB volume animations.

3.  **Blender\_Effect**: Controls rendering and visual effects inside Blender.
    -   Procedurally generate geometry with Geometry Nodes.
    -   Create and assign physically-interpretable shaders.
    -   Manage scene settings, lighting, and object properties.

> **Note:** A `Blender_Export` layer (video rendering, Sketchfab export, etc.) is planned but not yet implemented in this repository.

### `backend.py` vs `api.py`

- **`backend.py`** — everything, including the VDB export functions. Requires the `openvdb` pip package. Use this in a normal Python environment for data processing.
- **`api.py`** — the Blender-side surface. Excludes the VDB export functions, since Blender's bundled Python environment typically doesn't have the standalone `openvdb` package installed. Use this inside Blender's script editor.

## Installation

1.  **Clone the Repository**
```bash
    git clone https://github.com/stanley-lee-glitch/AstroVis.git
```

2.  **Install Dependencies**
```bash
    pip install numpy h5py scipy scikit-image trimesh matplotlib numba yt
    conda install -c conda-forge openvdb
```
    *AstroVis targets Python 3.11. `openvdb` is only required for `backend.py`'s VDB export functions — `api.py` does not need it.*

3.  **Setup in Blender**
    Add the cloned repository's path to Blender's script paths:
    `Edit > Preferences > File Paths > Data > Scripts`.

## Quickstart

This is the fastest path from a snapshot directory to a Blender scene, using the one-call functions in `Backend/workflow.py`. For per-field, per-frame control and the full list of lower-level functions (`load_volume`, `sph_to_grid`, `grid_to_surface`, `grid_to_vdb`, ...), see [`Documentation/Overview.md`](Documentation/Overview.md).

### 1. Backend: export a snapshot directory (outside Blender)

Pick the export that matches your simulation type and target format.

**Grid/AMR data → VDB volume sequence**
```python
from AstroVis.backend import export_volume_vdb_sequence

result = export_volume_vdb_sequence(
    input_dir="snapshots",
    output_dir="exports",
    field="density",
    vtype="gas",
)
print(result["field_range"])   # global (min, max), reuse this for Blender material scaling
```

**Grid/AMR data → surface HDF5 sequence**
```python
from AstroVis.backend import export_volume_surface_sequence

export_volume_surface_sequence(
    input_dir="snapshots",
    output_dir="exports",
    field="density",
    vtype="gas",
)
```

**SPH particle data → VDB volume sequence**
```python
from AstroVis.backend import export_particle_vdb_sequence

export_particle_vdb_sequence(
    input_dir="snapshots",
    output_dir="exports",
    ptype="gas",
    field="density",
)
```

**SPH particle data → surface HDF5 sequence**
```python
from AstroVis.backend import export_particle_surface_sequence

export_particle_surface_sequence(
    input_dir="snapshots",
    output_dir="exports",
    ptype="gas",
    field="density",
)
```

**SPH particle data → particle HDF5 sequence** (animate the raw particles directly, no grid/surface conversion)
```python
from AstroVis.backend import export_particle_particle_sequence

export_particle_particle_sequence(
    input_dir="snapshots",
    output_dir="exports",
    ptype="stars",
)
```

### 2. Blender: import the export folder

`setup_animation` auto-detects whatever the export produced (HDF5 particles/surfaces, a VDB sequence, or both) and sets it up in one call.

```python
# Run inside Blender's script editor
from AstroVis.api import setup_animation

setup_animation("path/to/exports", target_size=200)
```

### 3. Blender: apply a material

```python
from AstroVis.api import create_field_volume_material

create_field_volume_material(
    "Volume",              # object name prefix used by setup_animation for VDB imports
    field="density",
    field_min=-8.0,
    field_max=0.0,
    cmap_name="inferno",
)
```

### 4. Blender: build the scene

```python
from AstroVis.api import SceneManager

scene = SceneManager(scene_name="AstroScene", export_dir=r"C:\Path\To\renders")
scene.set_world_background(color=(0.0, 0.0, 0.0, 1.0), strength=0.02)
scene.set_camera(location=(8, -8, 5), look_at=(0, 0, 0), lens=45)
scene.set_light(location=(5, -5, 8), light_type="SUN", energy=3.0, size=0.15)
scene.set_render(engine="CYCLES", samples=128, resolution=(1920, 1080))
```

## Next steps

The steps above cover the common path end-to-end. If you need to:
- convert between particle/grid/surface representations manually,
- control per-frame thresholds, materials, or Geometry Nodes effects individually,
- export data with combined pipeline

...the lower-level API for each of these is documented per-module:

- [`Documentation/Backend/Volume_Data.md`](Documentation/Backend/Volume_Data.md)
- [`Documentation/Backend/Particle_Data.md`](Documentation/Backend/Particle_Data.md)
- [`Documentation/Backend/Save_and_load.md`](Documentation/Backend/Save_and_load.md)
- [`Documentation/Blender/Animation_setup.md`](Documentation/Blender/Animation_setup.md)
- [`Documentation/Blender/Node_and_shading.md`](Documentation/Blender/Node_and_shading.md)
- [`Documentation/Blender/Object_and_scene.md`](Documentation/Blender/Object_and_scene.md)