from skimage import measure
import trimesh
from .volume_data import GridBlock
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import generate_binary_structure, binary_closing, binary_dilation, binary_fill_holes
from collections import deque

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

## Type 1: Isosurface Extraction from a Single Grid Field
def grid_to_surface(
    grid_data: GridBlock,
    threshold: float,
    field: str = None,
    build_obj: bool = False,
) -> SurfaceData:

    if field is None:
        if len(grid_data.fields) == 1:
            field = list(grid_data.fields.keys())[0]
        else: 
            field = "density"
        
    dx = 1 / grid_data.dims[0]
    dy = 1 / grid_data.dims[1]
    dz = 1 / grid_data.dims[2]
    
    try:
        verts, faces, normals, _ = measure.marching_cubes(
            volume=grid_data.fields[field],
            level=threshold,
            spacing=(dx, dy, dz)  
        )
    except ValueError as e:
        print(f"[WARNING] marching_cubes failed for {field}: {e}")
        return None
    
    if build_obj:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
        mesh.export(f"{field}_{threshold:.3f}.obj")
        print(f"Exported surface mesh to {field}_{threshold:.3f}.obj")
    
    return SurfaceData(
        vertices=verts,
        faces=faces,
        normals=normals
    )
    
## Method 2: Local Maximum Extraction 

def grid_to_surface_local_max(
    grid_data: GridBlock,
    field: str = None,
    build_obj: bool = False,
    base_thresh: float = 0.3,
    volume_iteration: int = 5,
    shell_iteration: int = 3,
    smoothing: int = 25,
    outer: bool = True,
    center: bool = True,
    plot: bool = True   
) -> SurfaceData:
    
    if field == None:
        if len(grid_data.fields) == 1:
            field = list(grid_data.fields.keys())[0]
        else: 
            field = "density"
    
    grid = grid_data.fields[field]
    
    neighbor_offsets = [
        (i,j,k) for i in [-1,0,1] for j in [-1,0,1] for k in [-1,0,1] 
        if not (i==0 and j==0 and k==0)
    ]

    Nx, Ny, Nz = grid.shape
    
    def valid_bounds(v):
        return (0 <= v[0] < Nx) and (0 <= v[1] < Ny) and (0 <= v[2] < Nz)

    def get_outer_seeds():
        seeds = []
        for i in range(Nx):
            for j in range(Ny):
                seeds.extend([(i, j, 0), (i, j, Nz-1)])
        for i in range(Nx):
            for k in range(Nz):
                seeds.extend([(i, 0, k), (i, Ny-1, k)])
        for j in range(Ny):
            for k in range(Nz):
                seeds.extend([(0, j, k), (Nx-1, j, k)])
        return list(set(seeds))

    center = (Nx//2, Ny//2, Nz//2)

    # STAGE 1: SEQUENTIAL FLOODING

    print("Stage 1: Sequential flooding ")

    ## Find the "Volume Shell" that separates Inner from Outer
    structure = generate_binary_structure(3, 3) # 26-neighbor connectivity
    shell_mask = (grid >= base_thresh)
    structure = generate_binary_structure(3, 3) 
    shell_closed_v = binary_closing(shell_mask, structure=structure, iterations=volume_iteration)
    shell_thick_v = binary_dilation(shell_closed_v, structure=structure, iterations=1)
    solid_inner_volume = binary_fill_holes(shell_thick_v)

    shell_closed_s = binary_closing(shell_mask, structure=structure, iterations= shell_iteration)
    shell_thick_s = binary_dilation(shell_closed_s, structure=structure, iterations=1)
    solid_shell = binary_fill_holes(shell_thick_s)

    region_map = np.zeros_like(grid, dtype=np.int8)

    def flood_outer_sequential(seeds):
    
        queue = deque(seeds)
        for s in seeds:
            if not solid_inner_volume[s] and not solid_shell[s]:
                region_map[s] = 2
                
        while queue:
            v = queue.popleft()
            for off in neighbor_offsets:
                nbr = (v[0]+off[0], v[1]+off[1], v[2]+off[2])
                if valid_bounds(nbr) and region_map[nbr] == 0:
                    if not solid_inner_volume[nbr] and not solid_shell[nbr]:
                        region_map[nbr] = 2
                        queue.append(nbr)

    def flood_inner_sequential(seeds):
        queue = deque(seeds)
        for s in seeds:
            if solid_inner_volume[s] and not solid_shell[s]:
                region_map[s] = 1
                
        while queue:
            v = queue.popleft()
            for off in neighbor_offsets:
                nbr = (v[0]+off[0], v[1]+off[1], v[2]+off[2])
                if valid_bounds(nbr) and region_map[nbr] == 0:
                    if solid_inner_volume[nbr] and not solid_shell[nbr]:
                        region_map[nbr] = 1
                        queue.append(nbr)

    # Execute sequentially
    print("-> Flooding Outer...")
    flood_outer_sequential(get_outer_seeds())

    print("-> Flooding Inner...")
    flood_inner_sequential([center])

    print("Stage 1 complete. Regions should be separated by the shell. If not, please alter the iteration.")
    print("Generating Stage 1 Sanity Check...")

    def plot_sanity_check():
        
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        
        cmap = ListedColormap(['black', 'blue', 'red', 'cyan', 'orange', 'white'])

        fig, axes = plt.subplots(3, 3, figsize=(15, 15))
        
        # Subplot 1: The Region Map (The 'Pincer' result)
        # 0: Shell (Black), 1: Inner (Blue), 2: Outer (Red)
        ax1 = axes[0, 0]
        ax1.imshow(region_map[:, :, Nz//2], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax1.set_title(f"Stage 1: Region Map (z={Nz//2})\n Black = The Barrier Shell")
        

        ax2 = axes[1, 0]
        ax2.imshow(region_map[:, Ny//2, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax2.set_title(f"Stage 1: Region Map (y={Ny//2})\n Black = The Barrier Shell")
        
        ax3 = axes[2, 0]
        ax3.imshow(region_map[Nx//2, :, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax3.set_title(f"Stage 1: Region Map (x={Nx//2})\n Black = The Barrier Shell")
        
        ax4 = axes[0, 1]
        ax4.imshow(region_map[:, :, Nz//4], origin='lower', cmap= cmap, vmin=0, vmax=5)
        ax4.set_title(f"Stage 1: Region Map (z={Nz//4})\n Black = The Barrier Shell")
        
        ax5 = axes[1, 1]
        ax5.imshow(region_map[:, Ny//4, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax5.set_title(f"Stage 1: Region Map (y={Ny//4})\n Black = The Barrier Shell")
        
        ax6 = axes[2, 1]
        ax6.imshow(region_map[Nx//4, :, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax6.set_title(f"Stage 1: Region Map (x={Nx//4})\n Black = The Barrier Shell")
        
        ax7 = axes[0, 2]
        ax7.imshow(region_map[:, :, 3*Nz//4], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax7.set_title(f"Stage 1: Region Map (z={3*Nz//4})\n Black = The Barrier Shell")
        
        ax8 = axes[1, 2]
        ax8.imshow(region_map[:, 3*Ny//4, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax8.set_title(f"Stage 1: Region Map (y={3*Ny//4})\n Black = The Barrier Shell")
        
        ax9 = axes[2, 2]
        ax9.imshow(region_map[3*Nx//4, :, :], origin='lower', cmap=cmap, vmin=0, vmax=5)
        ax9.set_title(f"Stage 1: Region Map (x={3*Nx//4})\n Black = The Barrier Shell")
        
        # Legend for the Region Map
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='black', label='Shell higher than base_thresh'),
            Patch(facecolor='blue', label='Inner Region'),
            Patch(facecolor='red', label='Outer Region')
        ]
        
        ax1.legend(handles=legend_elements, loc='upper right', fontsize='small')

        plt.tight_layout()
        plt.savefig(f"{field}_{volume_iteration}_{shell_iteration}_sanity_check_stage1.png", dpi=150)
        print(f"Sanity check saved to {field}_{volume_iteration}_{shell_iteration}_sanity_check_stage1.png")

    if plot is True:
        plot_sanity_check()

    from skimage import measure
    from scipy.ndimage import gaussian_filter

    mask = np.zeros_like(region_map, dtype=bool)

    if outer == True:
        for i,j,k in np.ndindex(region_map.shape):
            if region_map[i,j,k] == 2:  # Outer
                mask[i,j,k] = True
            else:  # Inner or Shell
                mask[i,j,k] = False
    
    else:
        for i,j,k in np.ndindex(region_map.shape):
            if region_map[i,j,k] == 1:  # Inner
                mask[i,j,k] = True
            else:  # Outer or Shell
                mask[i,j,k] = False

    # =====================
    # 2. SMOOTHING (ANTI-ALIASING)
    # =====================
    # Marching cubes works best on continuous data. 
    # A slight Gaussian blur removes the "staircase" effect of the grid.
    smoothed_mask = gaussian_filter(mask, sigma=1)

    # =====================
    # 3. MARCHING CUBES
    # =====================
    dx, dy, dz = 1 / np.array(grid.shape)
    
    try:
        verts, faces, normals, values = measure.marching_cubes(smoothed_mask, 
                                                           level=0.5,
                                                           spacing = (dx, dy, dz) )
    
   
    except ValueError as e:
        print(f"[WARNING] marching_cubes failed for {field}: {e}")
        return None
    
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
    
    if center:
        verts -= verts.mean(axis=0)
    
    trimesh.smoothing.filter_laplacian(mesh, iterations=smoothing)
    
    if build_obj:
        if outer:
            mesh.export(f"{field}_localmax_outer_{base_thresh:.3f}.obj")
            print(f"Exported surface mesh to {field}_localmax_outer.obj")
        else:
            mesh.export(f"{field}_localmax_inner_{base_thresh:.3f}.obj")
            print(f"Exported surface mesh to {field}_localmax_inner.obj")
    
    return SurfaceData(
        vertices=mesh.vertices,
        faces=mesh.faces,
        normals=mesh.vertex_normals
    )
    
    


        