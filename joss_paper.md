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

## State of the Field

The current ecosystem for astrophysical visualization can be characterized by four related but distinct paradigms, each with inherent operational tradeoffs:

1. **General-purpose scientific frameworks (`yt`, ParaView, VisIt):** `yt` [@turk2011yt] is an astrophysics-native analysis toolkit with its own ray-casting volume renderer, driven by user-defined transfer functions that map field values to color and opacity; it excels at physically meaningful, script-driven analysis but its rendering is oriented toward diagnostic plots rather than production scene composition. ParaView [@ahrens2005paraview] and VisIt [@childs2012visit] are more general VTK-based platforms with a considerably larger interactive toolset: both offer full GUI-driven pipeline editing, a broad library of native filters (isosurfacing, slicing, thresholding, streamline and particle tracking), in-situ/distributed rendering for HPC-scale data, and, in ParaView's case, experimental ray/path-tracing engines (OSPRay, OptiX) for improved visual fidelity. However, none of the three provide the physically-based material shading, lighting design, or scene-composition workflow of a dedicated 3D content-creation suite, and none natively support exporting simulation data into sparse volumetric assets that persist and animate as first-class objects in such a suite.

2. **3D graphics software integrations (AstroBlend, Houdini-based pipelines):** To bring physically-based rendering to astrophysical data, AstroBlend [@naiman2016astroblend] integrated `yt` with earlier versions of Blender, and a parallel line of work ported simulation data into the VFX package Houdini [@naiman2017houdini]. Houdini in particular has long-standing, first-class native support for both particle simulation and OpenVDB volumes, since OpenVDB itself originated in the VFX industry. However, AstroBlend represents simulation data primarily as a static point mesh or pre-baked isosurface file, which loses the fidelity of continuous fluid and AMR grid simulations, and neither tool exposes a general, scripted, automatically-remapped AMR-to-volume pipeline; Houdini's use for this purpose is also constrained by its cost, being commercial software (with a limited non-commercial tier) rather than free and open-source like Blender.

3. **General scientific-visualization toolkits for Blender (SciBlend):** More recently, SciBlend [@marin2025sciblend] introduced a modular Blender add-on suite that imports VTK/NetCDF/Shapefile data (typically pre-processed in ParaView) and drives Blender's Cycles and EEVEE renderers through a dedicated shader-generation module, supporting up to 32-stop scientific colormaps, legends, annotations, and cinematographic scene composition. SciBlend demonstrates that a mature, general-purpose field-driven shading and animation workflow in Blender is achievable, and its results are directly relevant to this work. However, SciBlend is domain-agnostic by design: it has no adaptive-mesh-refinement-aware grid handling, no astrophysics-specific data loaders (e.g. `yt` integration or SPH kernel rasterization), and no native sparse-volume (OpenVDB) export — its visual outputs are exclusively surface and point meshes, with any isosurface or feature extraction performed upstream in ParaView rather than within the toolkit itself.

4. **Domain-specific tools repurposed for a narrow astrophysical use case:** A fourth, more ad-hoc pattern is the repurposing of general-purpose 3D software from outside either scientific-computing or VFX, applied to a specific astrophysical data type. For example, researchers have applied the medical-imaging platform 3D Slicer to spectral-line data cubes (right ascension, declination, and velocity) for outflow and high-velocity-feature identification, exploiting the fact that a spectral cube is structurally analogous to the dense scanned volumes Slicer was built to render. Such tools can be effective within their specific analysis niche, but they are not maintained as general-purpose particle/grid-to-Blender pipelines, do not expose the underlying data as reusable Python objects for further scientific post-processing, and are not designed with astrophysical simulation data (as opposed to observational data cubes) in mind.

Table \ref{tab:comparison} summarizes how AstroVis compares against representative tools from the first three paradigms above, which are the closest functional comparators; the fourth paradigm is included here for completeness but, being a one-off repurposing of unrelated medical-imaging software rather than a maintained astrophysics or VFX tool, is not a meaningful subject for feature-by-feature comparison.

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

Table: Comparison of AstroVis against representative tools from the general-purpose, 3D-graphics-integration, and Blender-toolkit paradigms. ✓ indicates full/native support, ~ indicates partial or workaround support, — indicates no support. \label{tab:comparison}
## Contribution

AstroVis introduces an open-source Python framework that bridges the scientific data-handling capabilities of `yt` with the state-of-the-art 3D rendering engine of Blender, coupling data analysis and graphics production into a single pipeline. Unlike prior Blender/Houdini integrations, which represent simulation data as a static point mesh or pre-baked isosurface file [@naiman2016astroblend; @naiman2017houdini], AstroVis exports data directly into native, sparse volumetric and animated mesh representations, and treats particle- and grid-based simulations as equally first-class inputs to the same downstream pipeline. The major contributions of the package include:

1. **Native volumetric rendering via OpenVDB:** AstroVis converts continuous AMR grids and SPH-rasterized fields directly into structured OpenVDB [@museth2013vdb] volumes inside Blender, preserving the continuous, sparse structure of the underlying field rather than approximating it with a discrete point mesh, a dense voxel array, or a single pre-computed isosurface. Internal physical quantities such as temperature or density can then directly drive Blender's volume density, absorption, and emission parameters through procedurally generated shader graphs.

2. **Unified, astrophysics-native particle- and grid-based pipeline:** AstroVis treats SPH particle data and AMR grid data as symmetric first-class inputs, loaded directly from `yt` datasets and funneled into the same unified HDF5 exchange format and the same high-level Blender animation entry point. This includes automatic detection and non-overlapping remapping of overlapping AMR grid hierarchies, so that the same downstream materials, lighting, and animation setup can be reused regardless of the originating simulation code, without the manual pre-processing step (e.g. through ParaView) that general-purpose scientific visualization toolkits for Blender require.

3. **Feature identification via ridge extraction and field-driven shading:** Beyond isosurface extraction, AstroVis includes a Hessian-eigenvalue ridge-detection and Poisson surface reconstruction method for isolating filament- and shock-like structures that lack a single clean density threshold, and maps analytical fields directly onto Blender's material shader graphs for interactive, physically-based exploratory rendering. General-purpose Blender visualization toolkits such as SciBlend [@marin2025sciblend] offer comparable, and in some respects more developed, field-driven shading tools; AstroVis's contribution here is coupling that shading step directly to astrophysics-native data ingestion and ridge/filament feature extraction, rather than requiring simulation data to be pre-processed into a generic surface mesh format first.

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