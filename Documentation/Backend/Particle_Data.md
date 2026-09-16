# Processing Particle Data

*Covers `Backend/particle_data.py`, `Backend/sph_particle_to_grid.py`, and `Backend/swift_species_map.py`.*

Particle data refers to simulation snapshots produced by **Smoothed Particle Hydrodynamics (SPH)** codes, which represent a fluid as a set of discrete particles rather than a fixed grid. Each particle carries a position, mass, and a *smoothing length* — the radius over which its contribution is spread. [SWIFT](https://swift.strw.leidenuniv.nl/) is one example of an SPH code, and is used as the running example throughout this page.

## Data Structures

### `SPHParticleData`
The main container, returned by `load_particles()`.

| Attribute | Type | Meaning |
|---|---|---|
| `coordinates` | `(N,3) np.ndarray` | Particle positions |
| `smoothing_lengths`, `masses`, `densities` | `(N,) np.ndarray` | Per-particle SPH quantities |
| `fields` | `SPHFields` | Any additional loaded fields |
| `time` | `float` | Snapshot time |
| `units` | `dict` | Length/mass/time unit info |
| `left_edge`, `right_edge` | `(3,) np.ndarray` | Domain bounds |

### `SPHFields`
Thin wrapper around `dict[str, np.ndarray]`, held by `SPHParticleData.fields`. Supports both `fields["name"]` and `fields.name` access, `in` membership checks, and `.filter(mask)` (used internally — see `SPHParticleData.filter` below).

## Loading the Data

### ```load_particles(ds, ptype="stars", fields=None, region=None) -> SPHParticleData```

Loads particle data for one particle type (`ptype`) from a yt dataset. `SmoothingLengths`, `Mass`, and `Densities` are read if present on the dataset, otherwise defaulted to arrays of `1`. Available `ptype`/field combinations can be checked via `ds.derived_field_list` / `ds.field_list`, which list them as `(ptype, field)` tuples.

```python
ds = yt.load("dataset")
particles = load_particles(ds, ptype="stars", fields="temperature")
```

`fields` accepts three forms:

- **`str` or `list[str]`** — a single field name or several.
- **`dict[str, Callable]`** — custom fields computed by a supplied getter function, for derived quantities not directly stored as a yt field. Each callable takes no arguments and returns an `(N,)` array. For example, to pull a single raw species-fraction column directly:

  ```python
  def OI_fraction():
      ad = ds.all_data()
      all_species = ad['PartType0', "SpeciesFractions"]
      return np.ascontiguousarray(np.array(all_species[:, 23]))  # column 23 = OI in SWIFT

  particles = load_particles(ds, ptype="PartType0", fields={"OI_fraction": OI_fraction})
  ```

  This is the same pattern `generate_species_fraction_fields` uses internally — see [Chemistry Species Helper for SWIFT](#chemistry-species-helper-for-swift) below.

`region` restricts loading to a subset of the domain (a sphere, box, disk, etc.) instead of the full `ds.all_data()`:

```python
sp = ds.sphere("c", (100, "kpc"))  # 100 kpc sphere centered on the domain center
particles = load_particles(ds, ptype="gas", region=sp)
```

## Accessing the Data

Both core attributes and `fields` entries can be accessed either dictionary- or attribute-style:

```python
particles["masses"]        # same as particles.masses
particles["OI_fraction"]   # same as particles.OI_fraction, falls through to fields
```

Useful attributes and methods:

| Member | Meaning |
|---|---|
| `.N` | Particle count |
| `.keys()` | All available field names, including core attributes and `fields` |
| `.filter(mask)` | Returns a new `SPHParticleData` with every array (core attributes and all fields) subset by the same boolean mask |

```python
particles = load_particles(ds, ptype="PartType0", fields=["temperature"])
hot_mask = particles.temperature > 1e6
hot_particles = particles.filter(hot_mask)
```
## Exporting the Data to Blender
After manipulating the dataset, you can save it into a .hdf5 file and prepare it for Blender.
### `save(file_path, data, mode="w", compression="gzip", compression_opts=4)`

`data` is `{object_name: instance_or_list_of_instances}` — a list represents animation frames, and must be a single consistent type per object.  
`mode="a"` appends/replaces named objects while leaving other objects in an existing file untouched while `mode="w"` overwrites the whole file.

```python
save("Planet.hdf5", {
    "Planet_Core":    [core_frame_0, core_frame_1, ...],
    "Dust":           [dust_frame_0, dust_frame_1, ...],
})
```

## Transforming to Grid Data

If you want to deposit SPH particle data onto a uniform grid to use the volume pipeline instead of importing particles directly into Blender, `sph_to_grid` converts an `SPHParticleData` into a `GridBlock` of resolution `res³`.

### ```sph_to_grid(particle_data, fields=None, res=256, intensive=True, center=True) -> GridBlock```

| Param | Default | Meaning |
|---|---|---|
| `fields` | `None` | Field name(s) to rasterize. `density` is always included regardless of what's passed. If `None`, every field present in `particle_data` is rasterized. |
| `intensive` | `True` | `True` for intensive quantities (e.g. temperature, velocity): each field is mass-weighted-scattered and then divided by the scattered density, matching the standard SPH kernel-density estimator. `False` for extensive quantities (e.g. mass itself): scattered directly without normalization. |
| `center` | `True` | Recenters the resulting block on the origin. |

```python
grid = sph_to_grid(particles, fields=["temperature"], res=256)
```

### Methodology: `scatter` / `kernel`

The core rasterization is adapted from [`swiftsimio`](https://github.com/SWIFTSIM/swiftsimio)'s scatter implementation:

- **[`kernel(r, H)`](https://github.com/SWIFTSIM/swiftsimio/blob/master/swiftsimio/visualisation/slice_backends/sph.py)** — the Wendland-C2 smoothing kernel (Dehnen & Aly 2012), evaluated as a function of distance `r` and smoothing width `H`.
- **[`scatter(x, y, z, m, h, res, box_x=0, box_y=0, box_z=0)`](https://github.com/SWIFTSIM/swiftsimio/blob/master/swiftsimio/visualisation/volume_render_backends/scatter.py)** — for each particle, deposits its weighted contribution (`m`) into every voxel within its kernel's compact support, using the SPH kernel as the deposit weight. Positions and smoothing lengths are first normalized to `[0,1]` for deposition, and the resulting grid is rescaled back to its original physical size.

## Chemistry Species Helper for SWIFT

Since `yt` doesn't natively support SWIFT's chemistry-species convention, `swift_species_map.py` provides lookup tables and a helper to expose them as loadable fields.

### Species map
`ELEMENT_MAP` and `MOLECULE_MAP` are lookup tables encoding SWIFT's fixed `SpeciesFractions` column indexing.

### ```generate_species_fraction_fields(ds, species) -> dict[str, Callable]```

Given a yt dataset `ds` and a species/molecule name (e.g. `"O"`, `"Fe"`, `"H2"`), returns a dict of `{field_name: getter_function}` suitable for passing directly as the `fields` argument to `load_particles`.

- For an **element** in `ELEMENT_MAP` (e.g. `"O"`), returns one getter per ionization state (`OI_fraction`, `OII_fraction`, ...), each normalizing that ion's raw `SpeciesFractions` column by the sum across all ionization states of the element — so fractions sum to 1 within the element.
- For a **molecule** in `MOLECULE_MAP` (e.g. `"H2"`), returns a single unnormalized getter (`H2_fraction`) directly.

To load fractions for multiple species/molecules together, merge the returned dicts before calling `load_particles`:

```python
fields = {**generate_species_fraction_fields(ds, "O"), **generate_species_fraction_fields(ds, "H2")}
particles = load_particles(ds, ptype="gas", fields=fields)
```

## See also
- [`Animation`](../Blender/Animation_setup.md) — `setup_animation`, the entry point for bringing an exported `.h5`/`.vdb` sequence into Blender
- [`Volume_data`](Volume_Data.md) — the AMR/grid-native counterpart to this module, for datasets that aren't SPH