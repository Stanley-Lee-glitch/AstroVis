# SPH particle data structures and loading functions for yt datasets.

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Union, Callable, Tuple



@dataclass
class SPHFields:
    data: Dict[str, np.ndarray] = field(default_factory=dict)

    def __getitem__(self, key: str) -> np.ndarray:
        """Access fields using dictionary-style indexing."""
        try:
            return self.data[key]
        except KeyError:
            raise KeyError(f"Field '{key}' not found in SPH fields.")

    def __getattr__(self, key: str) -> np.ndarray:
        """Access fields using attribute-style, e.g., fields.rho"""
        # Only intercept keys that exist in data
        if key in self.data:
            return self.data[key]
        # Otherwise, let normal attribute lookup raise AttributeError
        raise AttributeError(f"SPHFields has no attribute '{key}'")

    # Safe methods for dictionary-like operations
    def keys(self):
        """Return all field names."""
        return self.data.keys()

    def values(self):
        """Return all field values."""
        return self.data.values()

    def items(self):
        """Return all (key, value) pairs."""
        return self.data.items()
    
    def filter(self, mask: np.ndarray):
        """
        Return a new SPHFields object with fields filtered by mask.
        
        mask: boolean array of shape (N,)
        """
        filtered_data = {name: arr[mask] for name, arr in self.data.items()}
        return SPHFields(data=filtered_data)

    
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
    
    def __getitem__(self, key: str) -> np.ndarray:
    # First try direct attribute (masses, densities, smoothing_lengths, etc.)
        if hasattr(self, key):
            return getattr(self, key)
        # Then fall back to fields dict
        if key in self.fields:
            return self.fields[key]
        raise KeyError(f"Field '{key}' not found in particle data or fields.")
    
    def __getattr__(self, key: str) -> np.ndarray:
        # Look for field data
        if "fields" in self.__dict__ and key in self.fields:
            return self.fields[key]
        raise AttributeError(f"'{key}' not found in particle data or fields.")

    def filter(self, mask: np.ndarray):
        """
        Return a new SPHParticleData object with particles filtered by mask.
        
        mask: boolean array of shape (N,)
        """
        if mask.dtype != bool:
            raise ValueError("Mask must be a boolean array")
        
        if mask.shape[0] != self.N:
            raise ValueError("Mask length must match number of particles")

        return SPHParticleData(
            coordinates=self.coordinates[mask],
            masses=self.masses[mask],
            densities=self.densities[mask],
            smoothing_lengths=self.smoothing_lengths[mask],
            fields=self.fields.filter(mask),
            time=self.time,
            units=self.units,
            boxsize=self.boxsize
        )
    
    
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
            Example: 
            def custom_field():
                ad = ds.all_data()
                data = ad[ptype, "SomeField"].to_value()
                return np.ascontiguousarray(data)
            You may use generate_species_fraction_fields to create such a dict for species fractions for SWIFT datasets.
            However, addition fields must be added manually to the dict by callable functions.
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
    
    if (ptype, "SmoothingLengths") in ds.field_list:
        smoothing_lengths = data_source[ptype, 'SmoothingLengths'].to_value()
    else:
        smoothing_lengths = np.ones(coordinates.shape[0]) * 1  # Default smoothing length
        print("SmoothingLengths field not found; using default value of 1 for all particles.")
    
    if (ptype, "Mass") in ds.field_list:
        masses = data_source[ptype, "Mass"].to_value()
    else:
        masses = np.ones(coordinates.shape[0]) * 1  # Default mass
        print("Mass field not found; using default value of 1 for all particles.")

    if (ptype, "Densities") in ds.field_list:
        densities = data_source[ptype, "Densities"].to_value()
    else:
        densities = np.ones(coordinates.shape[0]) * 1  # Default density
        print("Densities field not found; using default value of 1 for all particles.")

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