import os
import re
from typing import Dict, List, Optional, Union

import numpy as np


def _snapshot_sort_key(name: str):
    """Sort snapshot files naturally by their trailing integer, if present."""
    stem = os.path.splitext(os.path.basename(name))[0]
    match = re.search(r"(\d+)$", stem)
    if match:
        return (0, int(match.group(1)), name.lower())
    return (1, name.lower())


def _collect_snapshot_files(
    input_dir: str,
    patterns: Optional[Union[str, List[str]]] = None,
    suffixes: Optional[Union[str, List[str]]] = None,
) -> List[str]:
    """
    Collect and sort snapshot files from a directory.

    Users may provide either glob patterns (e.g. "*.hdf5") or suffixes
    (e.g. [".hdf5", ".h5"]). If neither is given, the default supported set is
    used: .athdf, .hdf5, .h5.
    """
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Snapshot directory does not exist: {input_dir}")

    if patterns is None and suffixes is None:
        patterns = ["*.athdf", "*.hdf5", "*.h5"]

    if isinstance(patterns, str):
        patterns = [patterns]
    if isinstance(suffixes, str):
        suffixes = [suffixes]

    discovered = []
    seen = set()

    def add_match(path: str):
        if os.path.isfile(path) and path not in seen:
            discovered.append(path)
            seen.add(path)

    if patterns:
        import fnmatch
        for pattern in patterns:
            if pattern == "*":
                for name in sorted(os.listdir(input_dir)):
                    full_path = os.path.join(input_dir, name)
                    if os.path.isfile(full_path):
                        add_match(full_path)
            else:
                for name in sorted(os.listdir(input_dir)):
                    if fnmatch.fnmatch(name, pattern):
                        add_match(os.path.join(input_dir, name))

    if suffixes:
        normalized = []
        for suffix in suffixes:
            if suffix is None:
                continue
            suffix = str(suffix)
            if not suffix.startswith("."):
                suffix = "." + suffix
            if suffix == ".*":
                normalized.append(".*")
            else:
                normalized.append(suffix)

        for name in os.listdir(input_dir):
            full_path = os.path.join(input_dir, name)
            if not os.path.isfile(full_path):
                continue
            if any(name.endswith(suffix) for suffix in normalized):
                add_match(full_path)

    if not discovered:
        return []
    
    print(f"Discovered {len(discovered)} snapshot files in '{input_dir}':")
    print(f" from {discovered[0]} to {discovered[-1]}")

    return sorted(discovered, key=lambda path: _snapshot_sort_key(os.path.basename(path)))


def export_volume_vdb_sequence(
    input_dir: str,
    output_dir: str,
    field: str = "density",
    vtype: str = "gas",
    preview_every: Optional[int] = 10,
    log: bool = True,
    multi_vdb: bool = True,
) -> Dict[str, object]:
    """Volume snapshot directory -> VDB sequence + preview output."""
    import yt
    from .volume_data import load_volume
    from .grid_to_vdb import hierarchy_to_multiple_vdbs, hierarchy_to_vdb

    snapshot_files = _collect_snapshot_files(input_dir)
    if not snapshot_files:
        raise ValueError(f"No supported snapshot files found in: {input_dir}")
    snapshot_names = [os.path.basename(path) for path in snapshot_files]

    os.makedirs(output_dir, exist_ok=True)
    preview_samples = []
    global_min = float("inf")
    global_max = float("-inf")

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        hierarchy = load_volume(ds, vtype=vtype, fields=[field])

        analysis = hierarchy.analyze_field_data(fields=field, log=log)
        current_range = analysis["ranges"]
        if field not in current_range:
            raise ValueError(f"Field '{field}' was not found in snapshot '{snapshot_name}'.")

        field_min, field_max = current_range[field]
        global_min = min(global_min, field_min)
        global_max = max(global_max, field_max)

        if preview_every is not None and preview_every > 0 and (frame_num % preview_every) == 0:
            preview_samples.append((frame_num, hierarchy))

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        if multi_vdb:
            hierarchy_to_multiple_vdbs(
                hierarchy,
                field=field,
                file_name_prefix=os.path.join(frame_dir, field),
                log=log,
            )
        else:
            hierarchy_to_vdb(
                hierarchy,
                field=field,
                file_path=os.path.join(frame_dir, f"{field}.vdb"),
                log=log,
            )

    field_range = (global_min, global_max)
    preview_paths = []
    for frame_num, hierarchy in preview_samples:
        preview_path = os.path.join(output_dir, f"preview_{frame_num:04d}.png")
        hierarchy.analyze_field_data(
            fields=field,
            output_path=preview_path,
            log=log,
            value_ranges={field: field_range},
        )
        preview_paths.append(preview_path)

    return {
        "field": field,
        "field_range": field_range,
        "preview_paths": preview_paths,
        "snapshot_count": len(snapshot_names),
    }


def export_volume_surface_sequence(
    input_dir: str,
    output_dir: str,
    field: str = "density",
    vtype: str = "gas",
    threshold: Optional[float] = None,
    **kwargs,
):
    """
    Volume snapshot directory -> surface HDF5 sequence.

    Experimental AMR merge prototype: this assumes load_volume() already returns a
    non-overlapping hierarchy and then stitches the block-level surfaces together.
    It is intentionally kept here and not in the low-level converter module.

    Note on `threshold`: if left as None, it is auto-computed ONCE from the field
    range of the first snapshot's frame, then reused unchanged for every
    subsequent frame -- this keeps the isosurface threshold consistent across
    the animation rather than drifting frame-to-frame. Pass an explicit
    `threshold` if you want a fixed value from the start, or set it yourself
    per-frame by calling grid_to_surface directly in a loop.
    """
    
    import yt
    from .volume_data import load_volume
    from .grid_to_surface import grid_to_surface
    from .save_load_hdf5 import save

    snapshot_names = sorted(
        name for name in os.listdir(input_dir)
        if name.endswith((".athdf", ".hdf5", ".h5"))
    )
    if not snapshot_names:
        raise ValueError(f"No supported volume snapshot files found in: {input_dir}")

    def _merge_surface_blocks(surfaces):
        if not surfaces:
            raise ValueError("No surfaces were provided to merge.")
        if len(surfaces) == 1:
            return surfaces[0]

        vertices = []
        faces = []
        normals = []
        vertex_offset = 0

        for surface in surfaces:
            if surface is None:
                continue
            verts = np.asarray(surface.vertices, dtype=float)
            face_arr = np.asarray(surface.faces, dtype=int)
            if verts.size == 0 or face_arr.size == 0:
                continue
            vertices.append(verts)
            if surface.normals is not None:
                normals.append(np.asarray(surface.normals, dtype=float))
            faces.append(face_arr + vertex_offset)
            vertex_offset += verts.shape[0]

        if not vertices:
            raise ValueError("No valid surfaces remained after merge filtering.")

        merged_vertices = np.concatenate(vertices, axis=0)
        merged_faces = np.concatenate(faces, axis=0) if faces else np.empty((0, 3), dtype=int)
        merged_normals = np.concatenate(normals, axis=0) if normals else None
        return type(surfaces[0])(vertices=merged_vertices, faces=merged_faces, normals=merged_normals)

    os.makedirs(output_dir, exist_ok=True)
    exports = []

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        hierarchy = load_volume(ds, vtype=vtype, fields=[field])

        if threshold is None:
            field_range = hierarchy.get_field_value_ranges(fields=field, log=False).get(field, (0.0, 1.0))
            threshold = float((field_range[0] + field_range[1]) / 2.0)

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        block_surfaces = []
        for level in sorted(hierarchy.levels.keys()):
            for block in hierarchy.levels[level].blocks:
                if field not in block.fields:
                    continue
                block_surface = grid_to_surface(
                    block,
                    threshold=threshold,
                    field=field,
                    center=False,
                    scale=1.0,
                    plot_surface=False,
                )
                if block_surface is None:
                    continue
                block_vertices = np.asarray(block_surface.vertices, dtype=float) + np.asarray(block.left_edge, dtype=float)
                block_surface.vertices = block_vertices
                block_surfaces.append(block_surface)

        if not block_surfaces:
            raise ValueError(f"No block surface could be extracted for field '{field}' from the volume hierarchy.")

        surface = _merge_surface_blocks(block_surfaces)
        surface_path = os.path.join(frame_dir, "surface.h5")
        save(surface_path, {"surface": surface})

        exports.append({
            "frame": frame_num,
            "path": frame_dir,
            "surface_path": surface_path,
            "threshold": threshold,
            "status": "immature_amr_merge_prototype",
        })

    return {
        "field": field,
        "output_dir": output_dir,
        "snapshot_count": len(snapshot_names),
        "exports": exports,
        "status": "immature_amr_merge_prototype",
    }


def export_volume_particle_sequence(
    input_dir: str,
    output_dir: str,
    field: str = "density",
    vtype: str = "gas",
    **kwargs,
):
    """Volume snapshot directory -> particle HDF5 export sequence. To do."""
    raise NotImplementedError(
        "Volume-to-particle HDF5 sequence export is not implemented yet."
    )


def export_particle_vdb_sequence(
    input_dir: str,
    output_dir: str,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str]]] = None,
    res: int = 256,
    field: str = "density",
    log: bool = True,
    intensive: bool = True,
    center: bool = True,
    scale: float = 1.0,
    multi_vdb: bool = True,
) -> Dict[str, object]:
    """Particle snapshot directory -> VDB sequence export."""
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_vdb import grid_to_vdb

    snapshot_names = sorted(
        name for name in os.listdir(input_dir)
        if name.endswith((".athdf", ".hdf5", ".h5"))
    )
    if not snapshot_names:
        raise ValueError(f"No supported particle snapshot files found in: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)
    exports = []

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        particles = load_particles(ds, ptype=ptype, fields=fields)
        volume = sph_to_grid(
            particles,
            fields=field if fields is None else fields,
            res=res,
            intensive=intensive,
            center=center,
        )

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        if multi_vdb:
            grid_to_vdb(volume, field=field, scale=scale, file_path=os.path.join(frame_dir, field), log=log)
        else:
            grid_to_vdb(volume, field=field, scale=scale, file_path=os.path.join(frame_dir, f"{field}.vdb"), log=log)

        exports.append({
            "frame": frame_num,
            "path": frame_dir,
            "field_range": volume.get_field_value_ranges(fields=field, log=log)[field],
        })

    return {
        "field": field,
        "output_dir": output_dir,
        "snapshot_count": len(snapshot_names),
        "exports": exports,
    }


def export_particle_surface_sequence(
    input_dir: str,
    output_dir: str,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str]]] = None,
    res: int = 256,
    field: str = "density",
    threshold: Optional[float] = None,
    log: bool = True,
    intensive: bool = True,
    center: bool = True,
    scale: float = 1.0,
    **kwargs,
):
    """Particle snapshot directory -> surface HDF5 sequence."""
    import yt
    from .particle_data import load_particles
    from .sph_particle_to_grid import sph_to_grid
    from .grid_to_surface import grid_to_surface
    from .save_load_hdf5 import save

    snapshot_names = sorted(
        name for name in os.listdir(input_dir)
        if name.endswith((".athdf", ".hdf5", ".h5"))
    )
    if not snapshot_names:
        raise ValueError(f"No supported particle snapshot files found in: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)
    exports = []

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        particles = load_particles(ds, ptype=ptype, fields=fields)
        volume = sph_to_grid(
            particles,
            fields=field if fields is None else fields,
            res=res,
            intensive=intensive,
            center=center,
        )

        if threshold is None:
            field_range = volume.get_field_value_ranges(fields=field, log=log).get(field, (0.0, 1.0))
            threshold = float(np.mean(field_range))

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        surface = grid_to_surface(
            volume,
            threshold=threshold,
            field=field,
            center=center,
            scale=scale,
            plot_surface=False,
        )

        surface_path = os.path.join(frame_dir, "surface.h5")
        if surface is not None:
            save(surface_path, {"surface": surface})

        exports.append({
            "frame": frame_num,
            "path": frame_dir,
            "surface_path": surface_path,
            "threshold": threshold,
        })

    return {
        "field": field,
        "output_dir": output_dir,
        "snapshot_count": len(snapshot_names),
        "exports": exports,
    }


def export_particle_particle_sequence(
    input_dir: str,
    output_dir: str,
    ptype: str = "stars",
    fields: Optional[Union[str, List[str]]] = None,
    **kwargs,
):
    """Particle snapshot directory -> particle HDF5 sequence."""
    import yt
    from .particle_data import load_particles
    from .save_load_hdf5 import save

    snapshot_names = sorted(
        name for name in os.listdir(input_dir)
        if name.endswith((".athdf", ".hdf5", ".h5"))
    )
    if not snapshot_names:
        raise ValueError(f"No supported particle snapshot files found in: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)
    exports = []

    for frame_num, snapshot_name in enumerate(snapshot_names):
        ds = yt.load(os.path.join(input_dir, snapshot_name))
        particles = load_particles(ds, ptype=ptype, fields=fields)

        frame_dir = os.path.join(output_dir, f"frame_{frame_num:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        particle_file = os.path.join(frame_dir, "particles.h5")
        save(particle_file, {"particles": particles})

        exports.append({
            "frame": frame_num,
            "path": frame_dir,
            "particle_file": particle_file,
        })

    return {
        "output_dir": output_dir,
        "snapshot_count": len(snapshot_names),
        "exports": exports,
    }

