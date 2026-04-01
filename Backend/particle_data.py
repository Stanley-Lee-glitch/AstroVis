# SPH particle data structures and loading functions for yt datasets.

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Union, Callable, Tuple

@dataclass
class SPHFields:
    data: Union[Dict[str, np.ndarray], Callable[[], Dict[str, np.ndarray]]] = field(default_factory=dict)

    def __post_init__(self):
        if callable(self.data):
            self.data = self.data()
        
        if not isinstance(self.data, dict):
            raise ValueError("SPHFields 'data' must be a dict or a callable returning a dict.")

    def __getitem__(self, key: str) -> np.ndarray:
        if key in self.data:
            return self.data[key]
        raise KeyError(f"Field '{key}' not found in SPH fields.")
    
    def __getattr__(self, key: str) -> np.ndarray:
        if key in self.data:
            return self.data[key]
        raise AttributeError(f"Field '{key}' not found in SPH fields.")
    
@dataclass
class SPHParticleData:
    coordinates: np.ndarray          # (N, 3)
    smoothing_lengths: np.ndarray    # (N,)
    masses: np.ndarray              # (N,)
    densities: np.ndarray           # (N,)
    fields: SPHFields
    time: float
    units: Dict[str, object] = field(default_factory=dict)
    boxsize: Tuple[float, float, float] = None

    @property
    def N(self) -> int:
        return self.coordinates.shape[0]
    
    
def load_particles(ds, 
                   ptype="stars", 
                   fields: Union[list, Dict[str, Callable[[], np.ndarray]]] = None, 
                   region=None):
    """
    Load particle data from a yt dataset.

    Parameters
    ----------
    ds : yt Dataset
        The yt dataset object.
    ptype : str
        Particle type name (e.g., 'stars', 'dark_matter')
    fields : list or dict or Callable
        - List of field names to extract (e.g., ['mass', 'temperature']),
            [ptype, field] can be checked by ds.derived_field_list 
        - Dict of field name to callable that returns the field array.
    region : yt object or None
        A region (sphere, box) to subset particles

    Returns
    -------
    SPHParticleData
        A structured container of particle data, including coordinates, smoothing lengths, fields, time, and units.
    """
    # Select all particles
    data_source = ds.all_data() if region is None else region

    # Basic SPH quantities
    coordinates = data_source[ptype, "Coordinates"].to_value()
    smoothing_lengths = data_source[ptype, 'SmoothingLengths'].to_value()
    if smoothing_lengths is None:
        smoothing_lengths = np.ones(coordinates.shape[0]) * 0.1  # Default smoothing length
        print("SmoothingLengths field not found; using default value of 0.1 for all particles.")
    masses = data_source[ptype, "Mass"].to_value()
    densities = data_source[ptype, "Densities"].to_value()
    
    boxsize = ds.domain_width.to_value() if ds.domain_width is not None else None

    # Particle fields 
    field_data = {}
    if fields is not None:
        if isinstance(fields, list):
            for f in fields:
                field_data[f] = data_source[ptype, f].to_value()
        
        elif isinstance(fields, dict):
            for f, func in fields.items():
                if callable(func):
                    field_data[f] = func()
                else:
                    raise ValueError(f"Field '{f}' in fields dict must be a callable returning an array.")
        else:
            raise ValueError("Fields parameter must be a list of field names or a dict of field name to callable.")
                    
    sph_fields_data = SPHFields(data=field_data)

    unit_dict = {
        "length": (ds.length_unit.v, str(ds.length_unit.units)),
        "mass": (ds.mass_unit.v, str(ds.mass_unit.units)),
        "time": (ds.time_unit.v, str(ds.time_unit.units)),
    }
   
    return SPHParticleData(
        coordinates=coordinates,
        smoothing_lengths=smoothing_lengths,
        masses=masses,
        densities=densities,
        fields=sph_fields_data,
        time=ds.current_time.v, 
        units=unit_dict,
        boxsize=boxsize
    )