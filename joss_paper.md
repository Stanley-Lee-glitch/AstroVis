# AstroVis: A Python Framework for Bridging Astrophysical Simulation Data and Blender Rendering


## Summary

AstroVis is an open-source Python package that provides a flexible framework to transform astrophysical simulation data into physically interpretable renders. It bridges the scientific data-analysis library `yt` [@turk2011yt] and the 3D interactive graphics software Blender, enabling accurate, reproducible, and cinematic visualization of data alongside exploratory data analysis. AstroVis supports both mesh and volumetric rendering and can visualize a wide range of numerical simulations in astrophysics, from the evolution of stellar structure to feature identification in hydrodynamic flows. It supports both Smoothed Particle Hydrodynamics (SPH) and Adaptive Mesh Refinement (AMR) grid-based simulation outputs, and its backend data-processing layer is decoupled from Blender so it can run on High-Performance Computing (HPC) clusters to accelerate the data-processing stage ahead of rendering.

## Statement of Need

Modern computational astrophysics yields highly complex, high-dimensional, and multi-scale datasets from numerical simulations. Extracting physically meaningful features from these outputs demands advanced visualization pipelines integrated into the scientific workflow. In a comprehensive taxonomy of astronomical visualization, @lan2021visastro divide these approaches into five distinct data-analysis tasks:

- **Data wrangling:** Restructuring raw simulation output into analysis-ready structures.
- **Data exploration:** Exploring an unstructured dataset to uncover underlying patterns.
- **Feature identification:** Isolating features of interest such as shock fronts, filaments, or stellar cores.
- **Object reconstruction:** Producing a visual representation of a physical object or structure.
- **Education and outreach:** Making scientific data accessible to the public.

While each individual task has its own mature pipeline, a major gap exists between rigorous scientific data exploration and high-fidelity object reconstruction. These two crucial steps often remain confined to different, incompatible software ecosystems, forcing researchers to either sacrifice scientific accuracy for visual fidelity or vice versa.

### State of the Field

The current ecosystem for astrophysical visualization can be characterized by three distinct paradigms, each with inherent operational tradeoffs:

1. **General-purpose scientific frameworks (`yt`, ParaView, VisIt):** Tools such as `yt` [@turk2011yt], ParaView [@ahrens2005paraview], and VisIt [@childs2012visit] are built for rigorous scientific data analysis over a wide range of numerical simulation outputs and excel at large-scale parallel processing on HPC clusters. `yt` itself includes a basic volume-rendering module for quick-look 3D previews, and ParaView/VisIt likewise support ray-cast volume rendering. However, these renderers are built primarily for scientific diagnostic plots rather than production-quality scene composition, and lack the physically-based light transport, material shading, and interactive scene-building workflows found in dedicated 3D graphics software. These missing features are important for intuitive feature analysis and for public-facing outreach material.

2. **3D graphics software integrations (AstroBlend, Houdini-based pipelines):** To achieve interactive, cinematic-quality visuals, AstroBlend [@naiman2016astroblend] integrated `yt` with earlier versions of Blender, and a parallel line of work ported simulation data into the VFX package Houdini [@naiman2017houdini] for the same purpose. These tools successfully bring physically-based rendering to astrophysical data, but AstroBlend is tied to now-outdated Blender and `yt` versions and represents simulation data primarily as a static point mesh or pre-baked isosurface file, which loses the fidelity of continuous fluid and AMR grid simulations and does not expose a general SPH-to-volume conversion pathway or animated multi-frame import.

3. **Domain-specific spectral/cube visualization tools:** A third line of tools repurposes general-purpose 3D visualization software for narrower astrophysical use cases, such as applying the medical-imaging package 3D Slicer to spectral-line data cubes for outflow and high-velocity-feature identification. These tools are effective within their specific analysis niche but are not designed as general-purpose particle/grid-to-Blender pipelines, and do not expose the underlying data as reusable Python objects for further scientific post-processing.

Table \ref {tab:comparison} summarizes how AstroVis compares against representative tools from each paradigm.

| Capability | AstroVis | `yt` / ParaView / VisIt | AstroBlend | Houdini-astro | 3D Slicer (cube) |
|---|---|---|---|---|---|
| Particle-based snapshot input | ✓ | ✓ | ✓ | ✓ | — |
| Grid-based snapshot input | ✓ | ✓ | ~ | ✓ | — |
| Volume Rendering | ✓ | ✓ | — | ✓ | ✓ |
| Feature extraction | ✓ | ✓ | ~ | ~ | ~ |
| Physically-based ray-traced rendering | ✓ | ~ | ✓ | ✓ | — |
| Field-driven color mapping | ✓ | ✓ | ~ | ~ | — |
| Multi-frame 3D animation | ✓ | ~ | ✓ | ✓ | — |
| Interactive Visualization |✓ | — | ✓ | ✓ | ✓ |
| Open-source | ✓ | ✓ | ✓ | — | ✓ |

Table: Comparison of AstroVis against representative tools in each paradigm. ✓ indicates full/native support, ~ indicates partial or workaround support, — indicates no support. \label{tab:comparison}

## Contribution

AstroVis introduces an open-source Python framework that bridges the scientific data-handling capabilities of `yt` with the state-of-the-art 3D rendering engine of Blender, coupling data analysis and graphics production into a single pipeline. Unlike prior Blender/Houdini integrations, which represent simulation data as a static point mesh or pre-baked isosurface file [@naiman2016astroblend; @naiman2017houdini], AstroVis exports data directly into native, sparse volumetric and animated mesh representations, and treats particle- and grid-based simulations as equally first-class inputs to the same downstream pipeline. The major contributions of the package include:

1. **Native volumetric rendering via OpenVDB:** AstroVis converts continuous AMR grids and SPH-rasterized fields directly into structured OpenVDB [@museth2013vdb] volumes inside Blender, preserving the continuous, sparse structure of the underlying field rather than approximating it with a discrete point mesh or a single pre-computed isosurface. Internal physical quantities such as temperature or density can then directly drive Blender's volume density, absorption, and emission parameters through procedurally generated, field-driven shader graphs.

2. **Unified particle- and grid-based pipeline:** AstroVis treats SPH particle data and AMR grid data as symmetric first-class inputs, both funneling into the same unified HDF5 exchange format and the same high-level Blender animation entry point. This includes automatic detection and non-overlapping remapping of overlapping AMR grid hierarchies, so that the same downstream materials, lighting, and animation setup can be reused regardless of the originating simulation code.

3. **Feature identification via procedural shading and ridge extraction:** Beyond isosurface extraction, AstroVis includes a Hessian-eigenvalue ridge-detection and Poisson surface reconstruction method for isolating filament- and shock-like structures that lack a single clean density threshold, and maps analytical fields directly onto Blender's material shader graphs for interactive, physically-based exploratory rendering.

# Workflow

AstroVis is structured into three layers, separating scientific data processing from Blender-specific operations.

1. **Backend:** Blender-independent scientific data manipulation.
   - Store particle and grid data.
   - Convert SPH particle data to a grid.
   - Convert grid data to a surface (isosurface or ridge surface) or volume (OpenVDB).
   - Save/load a unified HDF5 exchange format for particle, surface, and grid data.
   - Can be run inside or outside of Blender, including on HPC clusters with no `bpy` dependency.

2. **Blender_Import:** Imports processed data into Blender.
   - Load particle animations.
   - Load surface mesh animations.
   - Load OpenVDB volume animations.

3. **Blender_Effect:** Controls rendering and visual effects inside Blender.
   - Procedurally generate geometry with Geometry Nodes.
   - Create and assign physically-interpretable shaders.
   - Manage scene settings, lighting, and object properties.

A fourth layer, `Blender_Export`, handling final video rendering and export to platforms such as Sketchfab, is planned as future work.

# Design and Functionality

## Data Objects

AstroVis represents simulation data with a small set of lightweight, self-describing dataclasses that are shared across the backend and Blender layers:

- `SPHParticleData`: per-particle coordinates, masses, densities, and smoothing lengths from an SPH simulation, plus an arbitrary dictionary of additional loaded fields (`SPHFields`).
- `FieldHierarchy`: a multi-level AMR volume, composed of `GridLevel` objects that each group the `GridBlock`s sharing a refinement level and cell size.
- `SurfaceData`: a triangulated mesh (vertices, faces, and optional per-vertex normals) produced by isosurface or ridge-surface extraction.

All three object types, including multi-frame animation sequences, are serialized through a single unified HDF5-based save/load interface, giving AstroVis one consistent on-disk exchange format regardless of whether the underlying simulation was particle- or grid-based.

## Data Processing

- **Particle pipeline:** SPH particle data is loaded directly from a `yt` dataset, and can be rasterized onto a uniform grid (`sph_to_grid`) using a smoothed-particle scatter/kernel deposition adapted from `swiftsimio` [@swiftsimio], supporting both intensive (e.g. temperature) and extensive (e.g. mass) field types.
- **Grid pipeline:** AMR grid data is loaded from `yt` into a `FieldHierarchy`, with automatic detection of overlapping grids and, where needed, a non-overlapping remapping onto a fixed block-per-axis layout via `yt`'s covering-grid interface. Grid blocks can then be converted to a surface mesh via marching-cubes isosurface extraction or ridge/filament extraction (Hessian-based ridge detection with Poisson surface reconstruction), or exported directly to OpenVDB for volumetric rendering.

## Data Visualization

- **Animation setup:** A single high-level entry point scans an exported data directory for HDF5 particle/surface sequences and OpenVDB volume sequences, and registers the corresponding Blender animation (frame-change handlers for mesh/particle data, and keyframed visibility for per-frame volume partitions).
- **Node and shading effects:** Procedural Geometry Nodes setups convert particle point clouds into renderable volumes or meshes, and a family of shader-generation functions build physically-interpretable Blender materials — including colormap-driven volume shaders whose density, emission color, and emission strength are all driven directly by a named simulation field.
- **Scene management:** Camera, lighting (including procedural light grids), world background, and render settings are configured through a single scene-management interface, supporting reproducible, scripted scene setup rather than manual configuration in Blender's UI.

# Example of Visualization


Figures demonstrating both the volumetric rendering pathway (an AMR density field exported to OpenVDB) and the mesh rendering pathway (an SPH-derived isosurface) will be included here to illustrate the two primary use cases supported by AstroVis.

# Acknowledgements


# References