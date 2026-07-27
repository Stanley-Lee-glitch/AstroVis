## Import data from npz file to DataStructure
## Python 3.8 compatible rewrite

from .particle_data import SPHParticleData, SPHFields
from .volume_data import GridBlock, GridLevel, FieldHierarchy
from .surface_data import SurfaceData
import numpy as np
import json


# ---------------------------------------------------------------------------
# Internal helpers — all dict/str metadata is stored as JSON-encoded bytes
# to avoid relying on numpy pickle, which is unreliable in Python 3.8 / older
# NumPy versions.
# ---------------------------------------------------------------------------

def _to_json_bytes(obj) -> np.ndarray:
    """Serialise a Python object to a 0-d numpy bytes array via JSON."""
    return np.bytes_(json.dumps(obj))


def _from_json_bytes(arr) -> object:
    """Deserialise a 0-d numpy bytes array that was written by _to_json_bytes."""
    # arr may be a 0-d ndarray wrapping a bytes_ scalar, or a plain bytes_
    raw = arr.flat[0] if isinstance(arr, np.ndarray) else arr
    # raw is np.bytes_ or plain bytes — both work with bytes()
    return json.loads(bytes(raw))


def _units_to_json(units_dict) -> np.ndarray:
    """
    Convert a units dict whose values may be yt unit objects (not JSON-
    serialisable) to a JSON-safe dict of strings, then encode as bytes.
    """
    safe = {k: str(v) for k, v in units_dict.items()}
    return _to_json_bytes(safe)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save(file_path: str, data: dict):
    """
    Save FieldHierarchy, SPHParticleData, and SurfaceData into a single NPZ
    file.

    Parameters
    ----------
    file_path : str
        Output path (the .npz extension is added automatically by numpy if
        not already present).
    data : dict
        Keys are object names, values are a single instance *or* a list of
        instances (one per animation frame).  Each list may only contain one
        type: FieldHierarchy, SPHParticleData, or SurfaceData.

    Example
    -------
    save("scene.npz", {
        "Planet_Surface": [SurfaceData, ...],
        "Emission_Gas":   [FieldHierarchy, ...],
        "Dust":           [SPHParticleData, ...],
    })
    """
    npz_dict = {}
    object_registry = {}  # built up as we go

    for obj_name, frame_datas in data.items():
        if not isinstance(frame_datas, list):
            frame_datas = [frame_datas]

        object_registry[obj_name] = {"Type": None, "Frames": len(frame_datas)}

        for frame_idx, item in enumerate(frame_datas):
            prefix = f"{obj_name}_{frame_idx}"

            # ----------------------------------------------------------------
            # FieldHierarchy
            # ----------------------------------------------------------------
            if isinstance(item, FieldHierarchy):
                object_registry[obj_name]["Type"] = "Volume"

                # Serialise unit dicts as JSON bytes (no pickle dependency)
                npz_dict[f"{prefix}_fh_unit"] = _units_to_json(item.unit)
                npz_dict[f"{prefix}_fh_field_units"] = _units_to_json(item.field_units)

                for level_id, gridlevel in item.levels.items():
                    npz_dict[f"{prefix}_level_{level_id}_cell_size"] = np.array(
                        gridlevel.cell_size, dtype=np.float64
                    )
                    for block in gridlevel.blocks:
                        blk_id = block.block_id
                        base = f"{prefix}_level_{level_id}_block_{blk_id}"
                        npz_dict[f"{base}_left_edge"] = np.array(
                            block.left_edge, dtype=np.float64
                        )
                        npz_dict[f"{base}_right_edge"] = np.array(
                            block.right_edge, dtype=np.float64
                        )
                        npz_dict[f"{base}_dims"] = np.array(
                            block.dims, dtype=np.int64
                        )
                        for field_name, arr in block.fields.items():
                            npz_dict[f"{base}_field_{field_name}"] = arr

            # ----------------------------------------------------------------
            # SPHParticleData
            # ----------------------------------------------------------------
            elif isinstance(item, SPHParticleData):
                object_registry[obj_name]["Type"] = "Particles"

                npz_dict[f"{prefix}_particle_coordinates"] = item.coordinates
                npz_dict[f"{prefix}_particle_masses"] = item.masses
                npz_dict[f"{prefix}_particle_densities"] = item.densities
                npz_dict[f"{prefix}_particle_smoothing_lengths"] = item.smoothing_lengths
                npz_dict[f"{prefix}_particle_time"] = np.array([item.time], dtype=np.float64)
                # Store units dict as JSON bytes
                npz_dict[f"{prefix}_particle_units"] = _units_to_json(item.units)
                npz_dict[f"{prefix}_particle_boxsize"] = (
                    np.array(item.boxsize, dtype=np.float64)
                    if item.boxsize is not None
                    else np.zeros(3, dtype=np.float64)
                )
                for field_name, arr in item.fields.items():
                    npz_dict[f"{prefix}_particle_field_{field_name}"] = arr

            # ----------------------------------------------------------------
            # SurfaceData
            # ----------------------------------------------------------------
            elif isinstance(item, SurfaceData):
                object_registry[obj_name]["Type"] = "Surface"

                npz_dict[f"{prefix}_surface_vertices"] = item.vertices
                npz_dict[f"{prefix}_surface_faces"] = item.faces
                if item.normals is not None:
                    npz_dict[f"{prefix}_surface_normals"] = item.normals

    # Store the registry as JSON bytes — no pickle needed
    npz_dict["Object_registry"] = _to_json_bytes(object_registry)

    np.savez(file_path, **npz_dict)
    print(f"Saved to {file_path}")


# ---------------------------------------------------------------------------

def load(file_path: str) -> dict:
    """
    Load FieldHierarchy, SPHParticleData, and SurfaceData from an NPZ file
    produced by :func:`save`.

    Returns
    -------
    dict
        {
            "Particles": {object_name: [SPHParticleData, ...]},
            "Volume":    {object_name: [FieldHierarchy,  ...]},
            "Surface":   {object_name: [SurfaceData,     ...]},
        }
    """
    # allow_pickle=False is safe here because we no longer store raw dicts
    npz = np.load(file_path, allow_pickle=False)

    object_registry = _from_json_bytes(npz["Object_registry"])

    result = {
        "Particles": {},
        "Volume": {},
        "Surface": {},
    }

    # Partition names by type for clarity
    by_type = {"Particles": {}, "Volume": {}, "Surface": {}}
    for obj_name, meta in object_registry.items():
        by_type[meta["Type"]][obj_name] = meta["Frames"]

    # ----------------------------------------------------------------
    # Load FieldHierarchy objects
    # ----------------------------------------------------------------
    for name, num_frames in by_type["Volume"].items():
        result["Volume"][name] = []

        for i in range(num_frames):
            prefix = f"{name}_{i}"

            unit = _from_json_bytes(npz[f"{prefix}_fh_unit"])
            field_units = _from_json_bytes(npz[f"{prefix}_fh_field_units"])
            fh = FieldHierarchy(unit=unit, field_units=field_units)

            # Collect all keys that belong to this prefix/frame
            prefix_level = f"{prefix}_level_"
            temp_levels = {}  # level_id -> {"cell_size": ..., "blocks": {blk_id: {...}}}

            for k in npz.files:
                if not k.startswith(prefix_level):
                    continue

                # Strip the common prefix so we parse the structural part only
                key_core = k[len(prefix_level):]
                # key_core examples:
                #   "0_cell_size"
                #   "0_block_3_left_edge"
                #   "0_block_3_field_density"
                parts = key_core.split("_")
                level_id = int(parts[0])

                if level_id not in temp_levels:
                    temp_levels[level_id] = {"cell_size": None, "blocks": {}}

                remainder = "_".join(parts[1:])  # everything after the level id

                if remainder == "cell_size":
                    temp_levels[level_id]["cell_size"] = tuple(npz[k].tolist())
                    continue

                if not remainder.startswith("block_"):
                    continue  # unexpected key shape — skip safely

                # remainder = "block_3_left_edge" or "block_3_field_density"
                block_parts = remainder.split("_")
                # block_parts[0] == "block", block_parts[1] == block_id
                blk_id = int(block_parts[1])
                attr = "_".join(block_parts[2:])  # "left_edge", "right_edge", "dims", "field_density" …

                if blk_id not in temp_levels[level_id]["blocks"]:
                    temp_levels[level_id]["blocks"][blk_id] = {"fields": {}}

                blk_dict = temp_levels[level_id]["blocks"][blk_id]

                if attr == "left_edge":
                    blk_dict["left_edge"] = tuple(npz[k].tolist())
                elif attr == "right_edge":
                    blk_dict["right_edge"] = tuple(npz[k].tolist())
                elif attr == "dims":
                    blk_dict["dims"] = tuple(int(x) for x in npz[k].tolist())
                elif attr.startswith("field_"):
                    field_name = attr[len("field_"):]
                    blk_dict["fields"][field_name] = npz[k]

            # Reconstruct levels and blocks in sorted order
            for level_id in sorted(temp_levels.keys()):
                level_data = temp_levels[level_id]
                fh.levels[level_id] = GridLevel(
                    level=level_id, cell_size=level_data["cell_size"]
                )
                for blk_id in sorted(level_data["blocks"].keys()):
                    bd = level_data["blocks"][blk_id]
                    block = GridBlock(
                        block_id=blk_id,
                        left_edge=bd["left_edge"],
                        right_edge=bd["right_edge"],
                        dims=bd["dims"],
                        fields=bd["fields"],
                    )
                    fh.levels[level_id].blocks.append(block)

            result["Volume"][name].append(fh)

    # ----------------------------------------------------------------
    # Load SPHParticleData objects
    # ----------------------------------------------------------------
    for name, num_frames in by_type["Particles"].items():
        result["Particles"][name] = []

        for i in range(num_frames):
            prefix = f"{name}_{i}"
            prefix_field = f"{prefix}_particle_field_"

            fields_dict = {}
            for k in npz.files:
                if k.startswith(prefix_field):
                    fname = k[len(prefix_field):]
                    fields_dict[fname] = npz[k]

            boxsize_arr = npz[f"{prefix}_particle_boxsize"]
            boxsize = tuple(boxsize_arr.tolist()) if not np.all(boxsize_arr == 0) else None

            particle_data = SPHParticleData(
                coordinates=npz[f"{prefix}_particle_coordinates"],
                masses=npz[f"{prefix}_particle_masses"],
                densities=npz[f"{prefix}_particle_densities"],
                smoothing_lengths=npz[f"{prefix}_particle_smoothing_lengths"],
                time=float(npz[f"{prefix}_particle_time"][0]),
                fields=SPHFields(data=fields_dict),
                units=_from_json_bytes(npz[f"{prefix}_particle_units"]),
                boxsize=boxsize,
            )
            result["Particles"][name].append(particle_data)

    # ----------------------------------------------------------------
    # Load SurfaceData objects
    # ----------------------------------------------------------------
    for name, num_frames in by_type["Surface"].items():
        result["Surface"][name] = []

        for i in range(num_frames):
            prefix = f"{name}_{i}"
            normals_key = f"{prefix}_surface_normals"
            surface = SurfaceData(
                vertices=npz[f"{prefix}_surface_vertices"],
                faces=npz[f"{prefix}_surface_faces"],
                normals=npz[normals_key] if normals_key in npz.files else None,
            )
            result["Surface"][name].append(surface)

    return result