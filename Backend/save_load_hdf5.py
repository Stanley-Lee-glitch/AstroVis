## Save/load FieldHierarchy, SPHParticleData, and SurfaceData to/from HDF5 files. 

from .particle_data import SPHParticleData, SPHFields
from .volume_data import GridBlock, GridLevel, FieldHierarchy
from .surface_data import SurfaceData
import numpy as np
import h5py
import json


_VALID_TYPES = ("Volume", "Particles", "Surface")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dict_to_attr(group, key, d):
    """Store a (possibly yt-unit-valued) dict as a JSON string attribute."""
    safe = {k: str(v) for k, v in d.items()}
    group.attrs[key] = json.dumps(safe)


def _attr_to_dict(group, key):
    return json.loads(group.attrs[key])


def _write_fields(group, fields_dict, ds_kwargs):
    """Write a dict of {field_name: array} as datasets inside a 'fields' subgroup."""
    fgroup = group.create_group("fields")
    for field_name, arr in fields_dict.items():
        _create_dataset(fgroup, field_name, arr, ds_kwargs)


def _read_fields(group):
    if "fields" not in group:
        return {}
    fgroup = group["fields"]
    return {name: fgroup[name][()] for name in fgroup}


def _create_dataset(group, name, arr, ds_kwargs):
    """create_dataset wrapper — compression only applies to non-scalar arrays."""
    arr = np.asarray(arr)
    if arr.ndim >= 1 and arr.size > 0:
        group.create_dataset(name, data=arr, **ds_kwargs)
    else:
        group.create_dataset(name, data=arr)

## Sort keys like "frame_0", "frame_1", ... by the trailing integer,
def _sorted_by_trailing_int(keys, sep="_"):
    return sorted(keys, key=lambda s: int(s.split(sep)[-1]))

# Public API — save / load

def save(file_path, data, mode="w", compression="gzip", compression_opts=4):
    """
    Save FieldHierarchy, SPHParticleData, and SurfaceData objects into a
    single HDF5 file. Supports any number of named objects, each with any
    number of frames (for animation), mixed freely across types.

    Parameters
    ----------
    file_path : str
    data : dict
        Keys are object names, values are a single instance *or* a list of
        instances (one per animation frame). Each list may only contain one
        type: FieldHierarchy, SPHParticleData, or SurfaceData.
    mode : str
        h5py file mode. "w" (default) overwrites the whole file. "a" opens
        for append/update — existing objects with the same name are replaced,
        other objects already in the file are left untouched.
    compression : str or None
        Passed to h5py.create_dataset for array datasets. None disables
        compression.
    compression_opts : int
        Compression level, used only when compression == "gzip".

    Example
    -------
    save("scene.h5", {
        "Planet_Surface": [SurfaceData, ...],
        "Emission_Gas":   [FieldHierarchy, ...],
        "Dust":           [SPHParticleData, ...],
    })
    """
    ds_kwargs = {}
    if compression is not None:
        ds_kwargs["compression"] = compression
        if compression == "gzip":
            ds_kwargs["compression_opts"] = compression_opts

    with h5py.File(file_path, mode) as f:
        
        ## Save for each object
        for obj_name, frame_datas in data.items():
            if not isinstance(frame_datas, list):
                frame_datas = [frame_datas]

            if obj_name in f:
                del f[obj_name]  # replace any existing object of this name
            obj_group = f.create_group(obj_name)

            obj_type = None

            ## Save for each frame
            for frame_idx, item in enumerate(frame_datas):
                frame_group = obj_group.create_group(f"frame_{frame_idx}")

                # FieldHierarchy
                if isinstance(item, FieldHierarchy):
                    obj_type = "Volume"
                    _dict_to_attr(frame_group, "unit", item.unit)
                    _dict_to_attr(frame_group, "field_units", item.field_units)

                    levels_group = frame_group.create_group("levels")
                    for level_id, gridlevel in item.levels.items():
                        lg = levels_group.create_group(f"level_{level_id}")
                        lg.attrs["cell_size"] = np.array(gridlevel.cell_size, dtype=np.float64)

                        blocks_group = lg.create_group("blocks")
                        for block in gridlevel.blocks:
                            bg = blocks_group.create_group(f"block_{block.block_id}")
                            bg.attrs["left_edge"] = np.array(block.left_edge, dtype=np.float64)
                            bg.attrs["right_edge"] = np.array(block.right_edge, dtype=np.float64)
                            bg.attrs["dims"] = np.array(block.dims, dtype=np.int64)
                            _write_fields(bg, block.fields, ds_kwargs)

                # SPHParticleData
                elif isinstance(item, SPHParticleData):
                    obj_type = "Particles"
                    _create_dataset(frame_group, "coordinates", item.coordinates, ds_kwargs)
                    _create_dataset(frame_group, "masses", item.masses, ds_kwargs)
                    _create_dataset(frame_group, "densities", item.densities, ds_kwargs)
                    _create_dataset(frame_group, "smoothing_lengths", item.smoothing_lengths, ds_kwargs)
                    frame_group.attrs["time"] = float(item.time)
                    _dict_to_attr(frame_group, "units", item.units)
   
                    frame_group.attrs["left_edge"] = np.array(item.left_edge, dtype=np.float64)
                    frame_group.attrs["right_edge"] = np.array(item.right_edge, dtype=np.float64)
                    _write_fields(frame_group, item.fields, ds_kwargs)

                # SurfaceData
                elif isinstance(item, SurfaceData):
                    obj_type = "Surface"
                    _create_dataset(frame_group, "vertices", item.vertices, ds_kwargs)
                    _create_dataset(frame_group, "faces", item.faces, ds_kwargs)
                    if item.normals is not None:
                        _create_dataset(frame_group, "normals", item.normals, ds_kwargs)

                else:
                    raise TypeError(
                        f"Unsupported object type for '{obj_name}' frame {frame_idx}: "
                        f"{type(item).__name__}"
                    )

            obj_group.attrs["type"] = obj_type
            obj_group.attrs["frames"] = len(frame_datas)

    print(f"Saved to {file_path}")


def load(file_path, object_names=None):
    """
    Load FieldHierarchy, SPHParticleData, and SurfaceData from an HDF5 file
    produced by`save`.

    Parameters
    ----------
    file_path : str
    object_names : list of str, optional
        If given, only load these objects (default: load everything in the
        file).

    Returns
    -------
    dict
        {
            "Particles": {object_name: [SPHParticleData, ...]},
            "Volume":    {object_name: [FieldHierarchy,  ...]},
            "Surface":   {object_name: [SurfaceData,     ...]},
        }
    """
    result = {"Particles": {}, "Volume": {}, "Surface": {}}

    with h5py.File(file_path, "r") as f:
        names = object_names if object_names is not None else list(f.keys())

        # Load per object
        for obj_name in names:
            if obj_name not in f:
                raise KeyError(f"Object '{obj_name}' not found in {file_path}")

            obj_group = f[obj_name]
            obj_type = obj_group.attrs["type"]
            num_frames = int(obj_group.attrs["frames"])

            if obj_type not in _VALID_TYPES:
                raise ValueError(f"Unknown type '{obj_type}' for object '{obj_name}'")

            frames_out = []

            # Load per frame
            for i in range(num_frames):
                frame_group = obj_group[f"frame_{i}"]

                if obj_type == "Volume":
                    unit = _attr_to_dict(frame_group, "unit")
                    field_units = _attr_to_dict(frame_group, "field_units")
                    fh = FieldHierarchy(unit=unit, field_units=field_units)

                    levels_group = frame_group["levels"]
                    for level_key in _sorted_by_trailing_int(levels_group.keys()):
                        level_id = int(level_key.split("_")[-1])
                        lg = levels_group[level_key]
                        cell_size = tuple(lg.attrs["cell_size"].tolist())
                        fh.levels[level_id] = GridLevel(level=level_id, cell_size=cell_size)

                        blocks_group = lg["blocks"]
                        for block_key in _sorted_by_trailing_int(blocks_group.keys()):
                            bg = blocks_group[block_key]
                            block_id = int(block_key.split("_")[-1])
                            block = GridBlock(
                                block_id=block_id,
                                left_edge=tuple(bg.attrs["left_edge"].tolist()),
                                right_edge=tuple(bg.attrs["right_edge"].tolist()),
                                dims=tuple(int(x) for x in bg.attrs["dims"].tolist()),
                                fields=_read_fields(bg),
                            )
                            fh.levels[level_id].blocks.append(block)

                    frames_out.append(fh)

                elif obj_type == "Particles":

                    particle_data = SPHParticleData(
                        coordinates=frame_group["coordinates"][()],
                        masses=frame_group["masses"][()],
                        densities=frame_group["densities"][()],
                        smoothing_lengths=frame_group["smoothing_lengths"][()],
                        time=float(frame_group.attrs["time"]),
                        fields=SPHFields(data=_read_fields(frame_group)),
                        units=_attr_to_dict(frame_group, "units"),
                        left_edge=np.array(frame_group.attrs["left_edge"].tolist(), dtype=np.float64),
                        right_edge=np.array(frame_group.attrs["right_edge"].tolist(), dtype=np.float64)
                    )
                    frames_out.append(particle_data)

                elif obj_type == "Surface":
                    surface = SurfaceData(
                        vertices=frame_group["vertices"][()],
                        faces=frame_group["faces"][()],
                        normals=frame_group["normals"][()] if "normals" in frame_group else None,
                    )
                    frames_out.append(surface)

            result[obj_type][obj_name] = frames_out

    return result


# ---------------------------------------------------------------------------
# Format inspection / validation helpers
# ---------------------------------------------------------------------------

def get_summary(file_path):
    """
    Return {object_name: {"Type": ..., "Frames": ...}}
    """
    summary = {}
    with h5py.File(file_path, "r") as f:
        for obj_name in f.keys():
            obj_group = f[obj_name]
            summary[obj_name] = {
                "Type": obj_group.attrs.get("type", "?"),
                "Frames": int(obj_group.attrs.get("frames", 0)),
            }
    return summary


def inspect(file_path, verbose=True):
    """
    Print (if verbose) and return a summary of an HDF5 scene file: every
    object, its type and frame count, plus dataset shapes/dtypes for frame 0
    of each object.

    Returns
    -------
    dict
        {object_name: {"type": ..., "frames": ..., "frame_0": {...nested...}}}
    """
    summary = {}

    def _walk(group, indent):
        entries = {}
        for key in group.keys():
            item = group[key]
            if isinstance(item, h5py.Dataset):
                entries[key] = {"shape": item.shape, "dtype": str(item.dtype)}
                if verbose:
                    print(f"{indent}{key}: shape={item.shape} dtype={item.dtype}")
            elif isinstance(item, h5py.Group):
                if verbose:
                    print(f"{indent}{key}/")
                entries[key] = _walk(item, indent + "    ")
        return entries

    with h5py.File(file_path, "r") as f:
        for obj_name in f.keys():
            obj_group = f[obj_name]
            obj_type = obj_group.attrs.get("type", "?")
            num_frames = int(obj_group.attrs.get("frames", 0))
            summary[obj_name] = {"type": obj_type, "frames": num_frames, "frame_0": {}}

            if verbose:
                print(f"[{obj_name}]  type={obj_type}  frames={num_frames}")

            if num_frames > 0 and "frame_0" in obj_group:
                summary[obj_name]["frame_0"] = _walk(obj_group["frame_0"], "    ")

    return summary


def validate(file_path, raise_on_error=False):
    """
    Check that an HDF5 scene file conforms to the format written by save().

    Parameters
    ----------
    file_path : str
    raise_on_error : bool
        If True, raise ValueError listing all problems found instead of
        just returning them.

    Returns
    -------
    list of str
        Problem descriptions.
    """
    problems = []

    required_datasets = {
        "Particles": ["coordinates", "masses", "densities", "smoothing_lengths"],
        "Surface": ["vertices", "faces"],
    }

    try:
        with h5py.File(file_path, "r") as f:
            for obj_name in f.keys():
                obj_group = f[obj_name]

                if "type" not in obj_group.attrs:
                    problems.append(f"{obj_name}: missing 'type' attribute")
                    continue
                obj_type = obj_group.attrs["type"]

                if obj_type not in _VALID_TYPES:
                    problems.append(f"{obj_name}: unknown type '{obj_type}'")
                    continue

                if "frames" not in obj_group.attrs:
                    problems.append(f"{obj_name}: missing 'frames' attribute")
                    continue
                num_frames = int(obj_group.attrs["frames"])

                for i in range(num_frames):
                    frame_key = f"frame_{i}"
                    if frame_key not in obj_group:
                        problems.append(f"{obj_name}: missing '{frame_key}' group")
                        continue
                    frame_group = obj_group[frame_key]

                    if obj_type == "Volume":
                        if "unit" not in frame_group.attrs or "field_units" not in frame_group.attrs:
                            problems.append(f"{obj_name}/{frame_key}: missing unit metadata")
                        if "levels" not in frame_group:
                            problems.append(f"{obj_name}/{frame_key}: missing 'levels' group")
                            continue
                        for level_key in frame_group["levels"].keys():
                            lg = frame_group["levels"][level_key]
                            if "cell_size" not in lg.attrs:
                                problems.append(
                                    f"{obj_name}/{frame_key}/levels/{level_key}: missing cell_size"
                                )
                            if "blocks" not in lg:
                                problems.append(
                                    f"{obj_name}/{frame_key}/levels/{level_key}: missing 'blocks' group"
                                )
                                continue
                            for block_key in lg["blocks"].keys():
                                bg = lg["blocks"][block_key]
                                for attr in ("left_edge", "right_edge", "dims"):
                                    if attr not in bg.attrs:
                                        problems.append(
                                            f"{obj_name}/{frame_key}/levels/{level_key}/"
                                            f"{block_key}: missing '{attr}'"
                                        )
                    else:
                        for req in required_datasets[obj_type]:
                            if req not in frame_group:
                                problems.append(f"{obj_name}/{frame_key}: missing dataset '{req}'")

    except (OSError, KeyError) as exc:
        problems.append(f"Could not open/parse file: {exc}")

    if raise_on_error and problems:
        raise ValueError("Invalid HDF5 scene file:\n" + "\n".join(problems))

    return problems