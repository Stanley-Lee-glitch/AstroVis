# AstroVis

**A Python package for moving astrophysical simulation data into Blender for 3D rendering and animation.**

AstroVis turns hydrodynamic simulation outputs into Blender-ready particles, surfaces, and volumes. It separates the workflow into a **backend data-processing layer** and a **Blender presentation layer**, so heavy scientific processing can happen in a normal Python environment while rendering and scene assembly happen inside Blender.

## Table of contents

- [Why AstroVis exists](#why-astrovis-exists)
- [General pipeline overview](#general-pipeline-overview)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Example notebooks](#example-notebooks)
- [Main modules](#main-modules)

## Why AstroVis exists

Standard simulation inspection tools are excellent for fast analysis, but they are not designed around physically rich 3D presentation. AstroVis bridges that gap so you can:

- render **volumetric fields** such as density or temperature with Blender volume shaders,
- extract **surfaces** from SPH or AMR data and animate them as meshes,
- keep **time series** data synchronized as Blender animation,
- build **repeatable scenes** with scripted materials, lights, and camera setup.

## General pipeline overview

```text
Simulation snapshots
    |
    | yt.load(...)
    v
Backend/
    particle_data.py          -> SPHParticleData
    volume_data.py            -> FieldHierarchy / GridBlock
    sph_particle_to_grid.py   -> SPH -> grid
    grid_to_surface.py        -> grid -> SurfaceData
    grid_to_vdb.py            -> grid / hierarchy -> .vdb
    save_load_hdf5.py         -> unified .h5/.hdf5 exchange format
    |
    +--> HDF5 animation payloads (.h5/.hdf5) for particles / surfaces
    |
    +--> OpenVDB sequences (.vdb) for volumes
    v
Blender_Import/
    setup_animation()         -> high-level HDF5 + VDB import
    setup_mesh_animation()    -> particle / surface animation
    setup_volume_animation()  -> volume sequence import
    v
Blender_Effect/
    material.py               -> data-driven materials
    node.py                   -> Geometry Nodes effects
    object.py                 -> object / modifier helpers
    scene.py                  -> scene, camera, lights, render helpers
```

## Installation

Core backend dependencies:

```bash
pip install numpy h5py scipy scikit-image trimesh matplotlib numba yt
conda install -c conda-forge openvdb
```

AstroVis now targets **Python 3.11** with **`openvdb`** as the supported VDB backend.

The `Blender_Import` and `Blender_Effect` modules must run inside Blender's Python environment because they depend on `bpy`.

## Quickstart

### 1. Export a backend volume

Run this in a normal Python environment:

```python
from AstroVis.backend import export_volume_sequence

result = export_volume_sequence("snapshots", "exports", field="density")
print(result["field_range"])
```

### 2. Import the VDB sequence in Blender

Run this inside Blender:

```python
from AstroVis.api import create_field_volume_material, setup_volume_animation

material, _ = create_field_volume_material(
    "Gas",
    field="density",
    field_min=-8.0,
    field_max=0.0,
    cmap_name="inferno",
    apply=False,
)["Gas"]

setup_volume_animation(
    r"C:\Path\To\exports",
    object="Gas",
    material=material,
    suppress_vdb_warnings=True,
)
```

`setup_volume_animation()` uses Blender's native VDB import operator. When `suppress_vdb_warnings=True`, AstroVis hides the repeated forward-compatibility warning lines that some Blender/OpenVDB builds print even when import succeeds.

### 3. Build the Blender scene

```python
from AstroVis.api import SceneManager

scene = SceneManager(scene_name="AstroScene", export_dir=r"C:\Path\To\renders")
scene.set_world_background(color=(0.0, 0.0, 0.0, 1.0), strength=0.02)
scene.set_camera(location=(8, -8, 5), look_at=(0, 0, 0), lens=45)
scene.set_light(location=(5, -5, 8), light_type="SUN", energy=3.0, size=0.15)
scene.add_light_grid(
    name_prefix="Fill",
    count_x=3,
    count_y=3,
    spacing=(2.5, 2.5),
    center=(0.0, 0.0, 0.0),
    height=3.5,
    light_type="POINT",
    energy=200.0,
    size=0.2,
)
scene.set_render(engine="CYCLES", samples=128, resolution=(1920, 1080))
```

## Example notebooks

The `Example/` folder contains end-to-end notebooks that mirror the documented workflows:

- `Rendering Particle Mesh.ipynb` - animate SPH particles directly in Blender
- `Rendering Surface.ipynb` - extract SPH-derived surfaces and import them as animated meshes
- `Rendering Volume Snapshots.ipynb` - export AMR volumes to OpenVDB and import them into Blender

These notebooks are intended as working templates rather than exhaustive tutorials.

## Main modules

| Area | Purpose |
|---|---|
| `Backend/particle_data.py` | Load and store SPH particle data from `yt`. |
| `Backend/volume_data.py` | Load AMR/grid data into `FieldHierarchy`. |
| `Backend/grid_to_surface.py` | Convert scalar grids into surface meshes. |
| `Backend/grid_to_vdb.py` | Convert scalar grids into OpenVDB output. |
| `Backend/save_load_hdf5.py` | Save/load unified AstroVis animation payloads. |
| `Blender_Import/mesh_animation.py` | Animate particles or surfaces in Blender. |
| `Blender_Import/volume_animation.py` | Import VDB sequences frame-by-frame. |
| `Blender_Effect/material.py` | Build procedural mesh and volume materials. |
| `Blender_Effect/node.py` | Add Geometry Nodes effects and selections. |
| `Blender_Effect/scene.py` | Manage camera, lights, cleanup, world, and render settings. |

## Related documentation

- [`Backend/Volume_Data.md`](Backend/Volume_Data.md)
- [`Backend/Particle_Data.md`](Backend/Particle_Data.md)
- [`Backend/Save_and_load.md`](Backend/Save_and_load.md)
- [`Blender/Animation_setup.md`](Blender/Animation_setup.md)
- [`Blender/Node_and_shading.md`](Blender/Node_and_shading.md)
- [`Blender/Object_and_scene.md`](Blender/Object_and_scene.md)
