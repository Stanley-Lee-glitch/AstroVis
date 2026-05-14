from dataclasses import dataclass
import numpy as np

@dataclass
class SurfaceData:
    vertices: np.ndarray       # (N,3)
    faces: np.ndarray          # (M,3)
    normals: np.ndarray = None # optional, (N,3)

    @property
    def N_vertices(self):
        return self.vertices.shape[0]

    @property
    def N_faces(self):
        return self.faces.shape[0]