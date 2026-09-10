# Exporting or Saving Backend Data

*Cover `Backend/save_load_hdf5`*

This is an unified HDF5 scene file format which saves/loads any mix of `FieldHierarchy`, `SPHParticleData`, and `SurfaceData` objects with multi-frame animation, all in one `.hdf5` file.  
This is the format for Blender import to reads for mesh particle/surface animation. (*Note: For volume animation, use the vdb sequence directly.*)  
It is also useful for temporary saving large dataset.

## File format

```
/{object_name}/                  attrs: type ("Volume"|"Particles"|"Surface"), frames (int)
    /frame_0/
        ... type-specific datasets/groups (see below) ...
    /frame_1/
        ...
```

- **Volume** (`FieldHierarchy`): `frame_N/levels/level_{L}/blocks/block_{B}/` with `left_edge`, `right_edge`, `dims` attrs and a `fields/` subgroup of datasets; frame-level attrs store `unit` and `field_units` as JSON strings.
- **Particles** (`SPHParticleData`): datasets `coordinates`, `masses`, `densities`, `smoothing_lengths`, `fields/*`; attrs `time`, `units` (JSON), `left_edge`, `right_edge`.
- **Surface** (`SurfaceData`): datasets `vertices`, `faces`, optional `normals`.

## Main Function: Save and Load

### `save(file_path, data, mode="w", compression="gzip", compression_opts=4)`

`data` is `{object_name: instance_or_list_of_instances}` — a list represents animation frames, and must be a single consistent type per object.  
`mode="a"` appends/replaces named objects while leaving other objects in an existing file untouched while `mode="w"` overwrites the whole file.

```python
save("scene.hdf5", {
    "Planet_Surface": [surface_frame_0, surface_frame_1, ...],
    "Dust":           [particles_frame_0, particles_frame_1, ...],
})
```

### `load(file_path, object_names=None) -> dict`

`object_names` restricts loading to a subset (default: everything in the file). Returns `{object_name: [instances...]}`.

## Other helpers function
### `get_summary(file_path) -> dict`

Lightweight `{object_name: {"Type": ..., "Frames": ...}}`.  
It is useful to call before a full `load` without reading all the data.

### `inspect(file_path, verbose=True) -> dict`

A deeper reports of every dataset's shape and dtype (printed if `verbose`). 

### `validate(file_path, raise_on_error=False) -> list[str]`

Checks a file conforms to the expected structure (required attrs/groups/datasets present for each type).  
Returns a list of problem descriptions (empty if valid); pass `raise_on_error=True` to raise a `ValueError`.

## Notes

- Compression (`gzip` by default) applies only to non-scalar array datasets; scalar arrays are stored uncompressed.
- Unit dicts (yt unit objects) are stored as JSON via `str()` — this preserves the *display* representation but not necessarily round-trippable unit objects; if you need to reconstruct actual `yt` unit-aware quantities from a loaded file, you'll need to re-parse these strings.