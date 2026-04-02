# AstroVis

**AstroVis** is a modular astrophysical visualization framework designed to transform simulation data into physically interpretable renders in Blender. It provides a bridge between scientific data libraries like `yt` and the powerful rendering capabilities of Blender, enabling automated and reproducible visualization workflows.

## Architecture

AstroVis is structured into four distinct layers, separating scientific data processing from Blender-specific operations.

1.  **Backend**: Blender-independent scientific data manipulation.
    -   Store particle and grid data.
    -   Convert SPH particle data to a grid.
    -   Convert grid data to a surface (isosurface) or volume (VDB).
    -   Can be run inside or outside of Blender.

2.  **Blender\_Import**: Imports the processed data into Blender.
    -   Load particle animations.
    -   Load surface mesh animations.
    -   Load VDB volume animations.

3.  **Blender\_Effect**: Controls rendering and visual effects inside Blender.
    -   Procedurally generate geometry with Geometry Nodes.
    -   Create and assign physically-interpretable shaders.
    -   Manage scene settings, lighting, and object properties.

4.  **Blender\_Export**: Handles the final output.
    -   Video rendering.
    -   Sketchfab export.

## Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/stanley-lee-glitch/AstroVis.git
    ```

2.  **Install Dependencies**
    AstroVis relies on several scientific Python libraries. These can be installed in your preferred Python environment.
    ```bash
    pip install yt numpy numba scikit-image trimesh pyopenvdb
    ```
    *Note: `pyopenvdb` requires Python 3.8 or compatible versions.*

3.  **Setup in Blender**
    To use the full framework, make the `AstroVis` modules available to Blender's internal Python environment. The simplest way is to add the cloned repository's path to Blender's script paths:
    `Edit > Preferences > File Paths > Data > Scripts`.

## Usage Guide

The typical workflow involves two main stages:
1.  **Backend Processing**: Load and convert your simulation data into a render-friendly format (`.npz` for meshes, `.vdb` for volumes). This can be done in a standard Python script.
2.  **Blender Workflow**: Import the processed data into Blender and apply visual effects using the AstroVis API within Blender's scripting environment.

### 1. Backend: Data Processing

The backend layer performs all physics-aware data processing and can be executed entirely outside of Blender.

#### Loading SPH Particle Data

Use `load_particles` to extract coordinates, smoothing lengths, masses, densities, and other specified fields from a `yt` dataset.

**Basic Example:**
```python
from AstroVis.backend import *
import yt

ds = yt.load("output_7bin_HHeZdust_real_0060.hdf5")
particles = load_particles(ds, ptype="PartType0", fields=["Mass"])
```

**Using Custom (Callable) Fields:**
You can define functions to compute derived fields on the fly.
```python
import numpy as np
import yt

ds = yt.load("output_7bin_HHeZdust_real_0060.hdf5")
ad = ds.all_data()

def HI_fraction():
    return np.ascontiguousarray(ad['PartType0', "SpeciesFractions"][:, 1])

# Pass the function in a dictionary
particles_with_HI = load_particles(
    ds,
    ptype="PartType0",
    fields={"HI_fraction": HI_fraction}
)
```

#### Loading Volumetric (AMR) Data

Use `load_volume` for grid-based data, which organizes the data into a hierarchy of refinement levels and blocks.

```python
import yt
from AstroVis.backend import load_volume

ds = yt.load("DiskForm.hydro.00140.athdf")
protostar_volume = load_volume(ds, vtype="gas", fields=["density"])

# Access data from a specific block
density_grid = protostar_volume.levels[0].blocks[0].fields['density']
```

#### Data Conversion

AstroVis provides tools to convert between data representations.

**1. SPH Particles → Grid**
Convert SPH data into a uniform grid representation for a specific field.
```python
# Convert particles to a 128x128x128 grid based on "HI_fraction"
HI_grid = sph_to_grid(particles_with_HI, field="HI_fraction", res=128)
```

**2. Grid → Surface Mesh**
Extract an isosurface from a grid using a threshold value (marching cubes).
```python
# Create a surface where the HI fraction is 0.5
HI_surface = grid_to_surface(HI_grid, threshold=0.5, field="HI_fraction")

# Export the surface data to an .npz file for Blender
np.savez("stromgren_surface.npz", **HI_surface.__dict__)
```

**3. Grid → VDB Volume**
Convert a grid block into a `.vdb` file for volumetric rendering in Blender.
```python
from AstroVis.Backend.grid_to_vdb import convert_vdb

# Assuming protostar_volume is loaded from the AMR example
first_block = protostar_volume.levels[0].blocks[0]
convert_vdb(first_block, output_path="density.vdb")
```

### 2. Blender: Importing and Animating Data

These functions must be run from within Blender's Python scripting environment.

#### Importing Mesh Animations

The `setup_mesh_animation` function can import sequences of particle or surface data to create frame-by-frame animations.

**1. Prepare Frame Data (Outside Blender)**
First, process each simulation snapshot and collect the results. This example creates surface data for each frame.
```python
# This part is run in a standard Python environment
import numpy as np
import yt
from AstroVis.backend import *

all_surface_frames = []
file_list = sorted(glob.glob("path/to/sim/output_*.hdf5"))

for f in file_list:
    ds = yt.load(f)
    # ... (load particles, convert to grid, etc.) ...
    HI_grid = sph_to_grid(...)
    surface_data = grid_to_surface(HI_grid, 0.5)
    all_surface_frames.append(surface_data)

# Save the entire animation sequence
np.savez("surface_animation.npz", frames=all_surface_frames)
```

**2. Import Animation (Inside Blender)**
Load the `.npz` file in Blender and set up the animation.
```python
# This part is run in Blender's script editor
import bpy
import numpy as np
from AstroVis.Blender_Import.mesh_animation import setup_mesh_animation

# Load the pre-processed frame data
data = np.load("path/to/surface_animation.npz", allow_pickle=True)
animation_frames = data['frames']

# Create the animated object in Blender
setup_mesh_animation(
    animation_frames,
    object_name="HI_Front_Animation",
    position_scale=20
)
```

### 3. Blender: Applying Visual Effects

The `Blender_Effect` module provides high-level functions to apply Geometry Nodes and shaders to your imported objects.

#### Geometry Nodes

Automate the creation of node setups for common visualization tasks.

**SPH Particles → Volume**
Render SPH particles as a volume.
```python
from AstroVis.Blender_Effect.node import sph_point_to_volume

# 'particle_obj' is the animated particle object in Blender
sph_point_to_volume(
    obj='particle_obj',
    attribute_name='density', # Use 'density' attribute to drive volume
    voxel_size=0.02,
    density=0.2
)
```

**SPH Particles → Mesh Surface**
Generate a solid mesh surface from particles.
```python
from AstroVis.Blender_Effect.node import sph_point_to_mesh

sph_point_to_mesh(
    obj='particle_obj',
    radius_attr='smoothing_lengths', # Use smoothing length for particle radius
    voxel_size=0.3,
    radius_multiplier=1.1
)
```

#### Shading

Create physically-interpretable shaders for volumetric and surface renderings.

**Volume Shaders**
Generates emission-based volume shaders. Ideal for visualizing gas density or temperature.
```python
from AstroVis.Blender_Effect.shading import create_volume_shaders

# Create shaders for one or more species (Blender objects)
create_volume_shaders(
    species_names=["Gas_Cloud", "Stellar_Outflow"],
    emission_multiplier=5.0,
    density_attribute="density" # Name of the vertex attribute driving density
)
```

**Mesh Shaders**
Generates standard surface shaders with emission.
```python
from AstroVis.Blender_Effect.shading import create_mesh_shaders

create_mesh_shaders(
    species_names=["HI_Front_Animation"],
    base_color=(0.8, 0.1, 0.1, 1.0),
    emission_color=(1.0, 0.2, 0.2, 1.0),
    emission_strength=2.0
)