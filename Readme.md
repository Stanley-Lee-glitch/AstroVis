# AstroVis

**AstroVis** is a modular astrophysical visualization framework that turns simulation data into physically interpretable renders in Blender. It bridges scientific data libraries like `yt` with Blender's rendering engine, enabling automated, reproducible visualization workflows.

Comparison with other visualization tools:

| Capability | AstroVis | `yt` | ParaView / VisIt | AstroBlend | Houdini-astro | SciBlend | 3D Slicer |
|---|---|---|---|---|---|---|---|
| Particle-based snapshot input | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Grid-based (AMR) snapshot input | ✓ | ✓ | ~ | ~ | ✓ | ~ | ~ |
| Volume rendering | ✓ | ✓ | ✓ | — | ✓ | — | ✓ |
| Feature extraction (isosurface/ridge) | ✓ | ✓ | ✓ | ~ | ~ | ~ | ~ |
| Physically-based ray-traced rendering | ✓ | — | ~ | ✓ | ✓ | ✓ | — |
| Field-driven color/opacity mapping | ✓ | ✓ | ✓ | ~ | ~ | ✓ | ✓ |
| Multi-frame 3D animation | ✓ | ~ | ~ | ~ | ✓ | ✓ | ~ |
| Open-source | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ |

See more in the documentation:
https://stanley-lee-glitch.github.io/AstroVis/

## Architecture

AstroVis has three layers, separating scientific data processing from Blender-specific operations.

1. **Backend** (`AstroVis/backend.py`) — Blender-independent scientific data manipulation.
   - Store particle and grid data.
   - Convert SPH particle data to a grid, and grid data to a surface (isosurface/ridge) or volume (VDB).
   - Save/load a unified HDF5 exchange format for particles, surfaces, and volumes.
   - `Backend/workflow.py` wraps a whole snapshot directory into one function call — the fastest path from simulation output to Blender-ready files (see Quickstart below).
   - Runs standalone in a normal Python environment — no `bpy` (Blender's Python module) required.

2. **Blender_Import** — imports processed data into Blender.
   - Load particle animations.
   - Load surface mesh animations.
   - Load VDB volume animations.

3. **Blender_Effect** — controls rendering and visual effects inside Blender.
   - Procedurally generate geometry with Geometry Nodes.
   - Create and assign physically-interpretable shaders.
   - Manage scene settings, lighting, and object properties.

> **Note:** A `Blender_Export` layer (video rendering, Sketchfab export, etc.) is planned but not yet implemented in this repository.

### `backend.py` vs `api.py` — which file do I import from?


| | `AstroVis.backend` | `AstroVis.api` |
|---|---|---|
| Where you run it | **Normal Python** (terminal, VS Code, Jupyter) | **Inside Blender's Script Editor** |
| Needs `openvdb` installed? | Only if you call a `*_vdb_sequence` function | No — VDB export functions are excluded |
| Needs `bpy`? | No | Yes (comes bundled with Blender) |
| What it's for | Step 1: turning simulation snapshots into exported files | Step 2 onward: importing those files into a Blender scene, building materials, building the scene |

In short: **export from `backend`, outside Blender. Import and build the scene from `api`, inside Blender.**

## Installation

### Step 1: Install Python dependencies (for the Backend step)

AstroVis targets **Python 3.11**. This is the Python you use for the export step (Step 1 of the Quickstart below).

```bash
pip install -r requirements.txt
```

This installs the core dependencies: `numpy`, `h5py`, `scipy`, `scikit-image`, `trimesh`, `matplotlib`, `numba`, `yt`..

It does **not** install `openvdb` If you only ever use the surface/particle export functions (not the `*_vdb_sequence` ones), you can skip that entirely.

#### Optional: VDB export support

Only needed if you plan to call `export_volume_vdb_sequence`, `export_particle_vdb_sequence`, or any other `*_vdb_sequence` function. 

```bash
conda install -c conda-forge openvdb
```


### Step 2: Clone the repository

```bash
git clone https://github.com/stanley-lee-glitch/AstroVis.git
```

### Step 3: Set up Blender's Python interface

 **Blender does not use your system Python**  and has its own bundled Python interpreter. There are two things to set up: (A) pointing Blender at the AstroVis code, and (B) Install dependency with Blender Python.

#### (A) Add AstroVis to Blender's script search path

Open Blender's **Scripting** tab, and in the Python console type:
```python
import sys
sys.path.append(r"C:\path\to\your\cloned\AstroVis")
```
And you can check by
```python
import AstroVis
```
If that succeeds with no error, the path is set correctly.

#### (B) Install dependencies into Blender's own Python

Blender's Script Editor runs on **Blender's own bundled Python**, the api.py still relies on packages like `numpy`, `numba` and `h5py`.

1. Find Blender's bundled Python executable. Typical locations:
   - **Windows:** `C:\Program Files\Blender Foundation\Blender <version>\<version>\python\bin\python.exe`
   - **macOS:** `/Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x`
   - **Linux:** `<blender_install_dir>/<version>/python/bin/python3.x`
2. Run pip through that interpreter directly:
   ```bash
   "<path-to-blender-python>" -m ensurepip
   "<path-to-blender-python>" -m pip install numpy h5py numba
   ```
   
3. Restart Blender, then confirm it worked by opening the **Scripting** tab and running, in the Python console:
   ```python
   import numpy, h5py
   print(numpy.__version__, h5py.__version__, numba.__version__)
   ```
   If both print a version with no error, the install worked.

## Quickstart
 
There are three runnable examples in the [`Example/`](Example/) folder, each a self-contained notebook with sample data included. It is recommended to go through [`Star_Formation`](Example/Volume_to_VDB/Star_Formation.ipynb) for using high-level API first. 

 
| Example | Demonstrates | Dependency |
|---|---|---|
| [`Star_Formation`](Example/Volume_to_VDB/Star_Formation.ipynb) | Grid AMR snapshot → VDB sequence → Blender Volume Rendering|  `requirements.txt` + `openvdb` |
| [`Stromgren_Ionization_Front`](Example/Particle_to_Surface/quickstart.ipynb) | SPH particle snapshot → Grid data --> Extraction of surface --> HDF5 sequence → Blender Mesh Rendering. |`requirements.txt`. |
 | [`Planet_Impact`](Example/Particle_to_Particle/quickstart.ipynb) | SPH particle snapshot --> Combined Output --> HDF5 sequence --> Blender Mesh Rendering | `requirements.txt`. |

## Next steps

The steps above cover the common path end-to-end. If you need to:
- convert between particle/grid/surface representations manually,
- control per-frame thresholds, materials, or Geometry Nodes effects individually,
- export data with a combined pipeline,


...the lower-level API for each of these is documented per-module:

- [`Documentation/Backend/Volume_Data.md`](Documentation/Backend/Volume_Data.md)
- [`Documentation/Backend/Particle_Data.md`](Documentation/Backend/Particle_Data.md)
- [`Documentation/Backend/Save_and_load.md`](Documentation/Backend/Save_and_load.md)
- [`Documentation/Blender/Animation_setup.md`](Documentation/Blender/Animation_setup.md)
- [`Documentation/Blender/Node_and_shading.md`](Documentation/Blender/Node_and_shading.md)
- [`Documentation/Blender/Object_and_scene.md`](Documentation/Blender/Object_and_scene.md)