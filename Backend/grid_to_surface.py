from skimage import measure
from skimage.measure import marching_cubes
import trimesh
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt
from .volume_data import GridBlock
from .surface_data import SurfaceData


# ============================================================
# Method 1: Isosurface Extraction
# ============================================================

def grid_to_surface(
    grid_data   : GridBlock,
    threshold   : float,
    field       : str  = None,
    # --- Parameters of surface ---
    build_obj   : bool = False,
    center      : bool = True,
    scale       : float = 1.0,
    # --- Quick check ---
    plot_surface: bool = False
) -> SurfaceData:
    """
    Extract an isosurface from a 3D grid field using marching cubes.

    Parameters
    ----------
    grid_data   : GridBlock   Input volumetric data
    threshold   : float       Isovalue for surface extraction
    field       : str         Field name to use (default: only/density field)
    build_obj   : bool        If True, export mesh as .obj file
    center      : bool        If True, center the surface at the origin
    scale       : float       The scale factor for the surface (from the width of GridBlock)
    plot_surface : bool       If True, plot the surface cross-section
    """
    if field is None:
        field = list(grid_data.fields.keys())[0] if len(grid_data.fields) == 1 else "density"

    print(f"\n{'='*50}")
    print(f"Running Isosurface Extraction...")
    print(f"{'='*50}")
    print(f"  Field     : {field}")
    print(f"  Threshold : {threshold}")

    ## Assume the grid having box width of 1
    dx = 1 / grid_data.dims[0]
    dy = 1 / grid_data.dims[1]
    dz = 1 / grid_data.dims[2]

    try:
        verts, faces, normals, _ = measure.marching_cubes(
            volume  = grid_data.fields[field],
            level   = threshold,
            spacing = (dx, dy, dz)
        )
    except ValueError as e:
        print(f"  [WARNING] marching_cubes failed for {field}: {e}")
        return None

    print(f"  Vertices  : {len(verts)}")
    print(f"  Faces     : {len(faces)}")
   
    scale_factor = np.array([grid_data.right_edge[0] - grid_data.left_edge[0], 
                             grid_data.right_edge[1] - grid_data.left_edge[1], 
                             grid_data.right_edge[2] - grid_data.left_edge[2]]) * scale
    verts *= scale_factor
    print(f"  Width of domain: {scale_factor}")
    
    if center:
        center_of_mass = verts.mean(axis=0)
        verts -= center_of_mass
        print(f"  Mesh is relocated at centered.")
        
    if build_obj:
        obj_path = f"{field}_surface.obj"
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
        mesh.export(obj_path)
        print(f"  Exported  : {obj_path}")

    if plot_surface:
        print("  Plotting surface cross-section...") # To-do
        
    print(f"{'='*50}\n")
    return SurfaceData(vertices=verts, faces=faces, normals=normals)


# ============================================================
# Method 2: Ridge Surface Extraction
# ============================================================

def grid_to_ridge_surface(
    grid_data   : GridBlock,
    field       : str  = None,
    # --- Step 1: Ridge Detection ---
    sigma            = 1.2,    # Gaussian smoothing. Higher = smoother, loses fine detail
    lambda_pct       = 10,     # Percentile of l3 threshold. Higher = more surface (looser)
    # --- Step 2: Component Filtering ---
    min_cluster_size = 250,    # Remove components smaller than this
    # --- Step 3: Poisson Reconstruction ---
    normal_k         = 20,     # Neighbors for normal estimation
    grid_sigma       = 1.5,    # Normal field smoothing
    isovalue_pct     = 50,     # 50=median. Lower=expand surface, Higher=shrink
    # --- Quick Checks ---
    plot_ridge       = True,   # Plot 2D slice after ridge detection
    print_components = True,   # Print component size table after filtering
    plot_surface     = True,   # Plot chi field + mesh after reconstruction
    # --- Parameter of Surface ---
    center           = True,   # If True, center the surface at the origin
    scale            = 1.0,    # The scale factor for the surface (from the width of GridBlock)
    build_obj        = False,   # If True, export mesh as .obj file
):
    """
    Extract a surface from a 3D volume by detecting intensity ridges.

    Steps
    -----
    1) Ridge detection via Hessian eigenvalues + non-maximum suppression (NMS)
    2) Connected component filtering to remove small isolated pieces
    3) Poisson surface reconstruction via FFT to produce a smooth mesh

    Parameters
    ----------
    grid_data        : GridBlock    The grid data containing the 3D volume
    field            : str          The field to extract the surface from
    sigma            : float        Gaussian smoothing before Hessian (default 1.2)
    lambda_pct       : int          Percentile of l3 for surface threshold (default 10)
    min_cluster_size : int          Min voxels to keep a connected component (default 250)
    normal_k         : int          KNN neighbors for normal estimation (default 20)
    grid_sigma       : float        Smoothing of normal vector field (default 1.5)
    isovalue_pct     : int          Percentile of chi at ridge for isovalue (default 50)
    scale            : float        Scale factor for the surface (default 1.0)
    plot_ridge       : bool         Plot ridge detection result (default True)
    print_components : bool         Print connected component table (default True)
    plot_surface     : bool         Plot final surface result (default True)
    build_obj        : bool         If True, export mesh as .obj file
    center           : bool         If True, center the surface at the origin (default True)

    """
    if field is None:
        field = list(grid_data.fields.keys())[0] if len(grid_data.fields) == 1 else "density"
        
    volume = grid_data.fields[field]
    shape = volume.shape

    # --------------------------------------------------------
    # STEP 1: Ridge Detection via Hessian + NMS
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Running Ridge Surface Extraction...")
    print(f"STEP 1: Ridge Detection")
    print(f"{'='*50}")
    print(f"  Field        : {field}")
    print(f"  Volume shape : {shape}")
    print(f"  Sigma        : {sigma}")
    print(f"  Lambda pct   : {lambda_pct}")

    if volume.max() > 50:
        volume = np.log1p(volume - volume.min())
    smoothed = ndimage.gaussian_filter(volume, sigma=sigma)

    grad_z, grad_y, grad_x = np.gradient(smoothed)
    Izz, Izy, Izx = np.gradient(grad_z)
    _,   Iyy, Iyx = np.gradient(grad_y)
    _,   _,   Ixx = np.gradient(grad_x)

    hessian_matrix = np.zeros((volume.size, 3, 3))
    hessian_matrix[:, 0, 0] = Ixx.ravel()
    hessian_matrix[:, 1, 1] = Iyy.ravel()
    hessian_matrix[:, 2, 2] = Izz.ravel()
    hessian_matrix[:, 0, 1] = hessian_matrix[:, 1, 0] = Iyx.ravel()
    hessian_matrix[:, 0, 2] = hessian_matrix[:, 2, 0] = Izx.ravel()
    hessian_matrix[:, 1, 2] = hessian_matrix[:, 2, 1] = Izy.ravel()

    eigvals, eigvecs = np.linalg.eigh(hessian_matrix)
    l3 = eigvals[:, 0].reshape(shape)
    l2 = eigvals[:, 1].reshape(shape)
    v3 = eigvecs[:, :, 0].reshape((*shape, 3))

    lambda_th = np.percentile(l3, lambda_pct)
    print(f"  Threshold l3 : {lambda_th:.6f}  (percentile {lambda_pct})")

    wide_surface_zone = (l3 < lambda_th) & (l3 < l2)
    print(f"  Wide zone    : {wide_surface_zone.sum()} / {volume.size} voxels")

    thin_ridge_mask = np.zeros_like(volume, dtype=bool)
    z_indices, y_indices, x_indices = np.where(wide_surface_zone)

    for z, y, x in zip(z_indices, y_indices, x_indices):
        if (z == 0 or z == shape[0]-1 or
            y == 0 or y == shape[1]-1 or
            x == 0 or x == shape[2]-1):
            continue
        normal = v3[z, y, x]
        step   = np.round(normal).astype(int)
        if np.all(step == 0):
            ax       = np.argmax(np.abs(normal))
            step[ax] = 1 if normal[ax] > 0 else -1
        dz, dy, dx   = step
        val_center   = smoothed[z,      y,      x     ]
        val_forward  = smoothed[z + dz, y + dy, x + dx]
        val_backward = smoothed[z - dz, y - dy, x - dx]
        if val_center >= val_forward and val_center >= val_backward:
            thin_ridge_mask[z, y, x] = True

    print(f"  Ridge voxels : {thin_ridge_mask.sum()}  (after NMS)")

    if plot_ridge:
        slice_idx = shape[0] // 2
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(f"Step 1: Ridge Detection  |  slice z={slice_idx}  |  sigma={sigma}, lambda_pct={lambda_pct}")

        axes[0].imshow(smoothed[slice_idx], cmap='gray', origin='lower')
        axes[0].set_title("Smoothed Volume")

        axes[1].imshow(smoothed[slice_idx], cmap='gray', origin='lower')
        y_r, x_r = np.where(thin_ridge_mask[slice_idx])
        axes[1].scatter(x_r, y_r, color='red', s=1)
        axes[1].set_title(f"Ridge Points  (n={thin_ridge_mask.sum()})")

        im3 = axes[2].imshow(l3[slice_idx], cmap='RdBu', origin='lower')
        axes[2].set_title("l3 Hessian Eigenvalue")
        plt.colorbar(im3, ax=axes[2])

        plt.tight_layout()
        plt.savefig(f"{field}_ridge_check.png", dpi=150)
        plt.show()
        print(f"  Saved        : {field}_ridge_check.png")

    # --------------------------------------------------------
    # STEP 2: Connected Component Filtering
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"STEP 2: Component Filtering")
    print(f"{'='*50}")
    print(f"  Min cluster size : {min_cluster_size}")

    struct = ndimage.generate_binary_structure(3, 3)
    labeled, num_features = ndimage.label(thin_ridge_mask, structure=struct)
    component_sizes = np.bincount(labeled.ravel())
    sorted_sizes    = np.sort(component_sizes[1:])[::-1]

    if print_components:
        print(f"  Total components : {num_features}")
        print(f"\n  {'Rank':>4}  {'Size (voxels)':>14}  {'Kept?':>6}")
        print(f"  {'-'*30}")
        for i, s in enumerate(sorted_sizes[:30]):
            kept = "YES" if s >= min_cluster_size else "no"
            print(f"  #{i+1:>3}  {s:>14}  {kept:>6}")
        if len(sorted_sizes) > 30:
            print(f"  ... ({len(sorted_sizes)-30} more, all smaller than #{30})")

    large_components    = component_sizes >= min_cluster_size
    large_components[0] = False
    cleaned_mask        = large_components[labeled]
    n_kept              = int(large_components[1:].sum())

    print(f"\n  Components kept  : {n_kept} / {num_features}")
    print(f"  Voxels           : {thin_ridge_mask.sum()} → {cleaned_mask.sum()}")

    # --------------------------------------------------------
    # STEP 3: Poisson Surface Reconstruction
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"STEP 3: Poisson Reconstruction")
    print(f"{'='*50}")
    print(f"  Normal K     : {normal_k}")
    print(f"  Grid sigma   : {grid_sigma}")
    print(f"  Isovalue pct : {isovalue_pct}")

    z_pts, y_pts, x_pts = np.where(cleaned_mask)
    points = np.column_stack([x_pts, y_pts, z_pts]).astype(np.float32)
    print(f"  Ridge points : {len(points)}")

    tree      = cKDTree(points)
    _, idx    = tree.query(points, k=normal_k)
    neighbors = points[idx]
    centered  = neighbors - neighbors.mean(axis=1, keepdims=True)
    cov       = np.einsum('nki,nkj->nij', centered, centered)
    _, eigvecs = np.linalg.eigh(cov)
    normals   = eigvecs[:, :, 0].astype(np.float32)

    outward   = points - points.mean(axis=0)
    flip_mask = np.einsum('ni,ni->n', normals, outward) < 0
    normals[flip_mask] *= -1
    print(f"  Normals      : computed")

    xi, yi, zi = x_pts.astype(int), y_pts.astype(int), z_pts.astype(int)
    nx_grid = np.zeros(shape, dtype=np.float32)
    ny_grid = np.zeros(shape, dtype=np.float32)
    nz_grid = np.zeros(shape, dtype=np.float32)
    np.add.at(nx_grid, (zi, yi, xi), normals[:, 0])
    np.add.at(ny_grid, (zi, yi, xi), normals[:, 1])
    np.add.at(nz_grid, (zi, yi, xi), normals[:, 2])
    nx_grid = ndimage.gaussian_filter(nx_grid, sigma=grid_sigma)
    ny_grid = ndimage.gaussian_filter(ny_grid, sigma=grid_sigma)
    nz_grid = ndimage.gaussian_filter(nz_grid, sigma=grid_sigma)
    print(f"  Normal field : splatted")

    divergence = (np.gradient(nx_grid, axis=2) +
                  np.gradient(ny_grid, axis=1) +
                  np.gradient(nz_grid, axis=0))

    div_fft          = np.fft.fftn(divergence)
    kx               = np.fft.fftfreq(shape[2]) * 2 * np.pi
    ky               = np.fft.fftfreq(shape[1]) * 2 * np.pi
    kz               = np.fft.fftfreq(shape[0]) * 2 * np.pi
    KZ, KY, KX       = np.meshgrid(kz, ky, kx, indexing='ij')
    lap_eig          = -(KX**2 + KY**2 + KZ**2)
    lap_eig[0, 0, 0] = 1.0
    chi_fft          = div_fft / lap_eig
    chi_fft[0, 0, 0] = 0.0
    chi              = np.real(np.fft.ifftn(chi_fft)).astype(np.float32)
    print(f"  Poisson      : solved, chi range [{chi.min():.4f}, {chi.max():.4f}]")

    isovalue = np.percentile(chi[zi, yi, xi], isovalue_pct)
    print(f"  Isovalue     : {isovalue:.6f}  (percentile {isovalue_pct})")

    verts, faces, _, _ = marching_cubes(chi, level=isovalue)
    
    if center:
        verts -= verts.mean(axis=0)
        print(f"  Mesh is relocated at centered.")
    
    width = np.array(grid_data.right_edge) - np.array(grid_data.left_edge)
    verts *= width * scale / np.array(shape)
    print(f"  Width of domain: {width * scale}")
    

    print(f"\n  {'='*44}")
    print(f"  Final Surface:")
    print(f"  Vertices : {len(verts)}")
    print(f"  Faces    : {len(faces)}")
    print(f"  {'='*44}\n")
    
    if build_obj:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        obj_path = f"{field}_surface.obj"
        mesh.export(obj_path)
        print(f"  Exported     : {obj_path}")

    if plot_surface:
        slice_idx = shape[0] // 2
        fig = plt.figure(figsize=(15, 5))
        fig.suptitle(f"Step 3: Reconstructed Surface  |  isovalue_pct={isovalue_pct}, grid_sigma={grid_sigma}")

        # Panel 1: chi field + isocontour
        ax1 = fig.add_subplot(1, 3, 1)
        im  = ax1.imshow(chi[slice_idx], cmap='RdBu', origin='lower')
        ax1.contour(chi[slice_idx], levels=[isovalue], colors='yellow', linewidths=1)
        plt.colorbar(im, ax=ax1)
        ax1.set_title("Chi field + isocontour")

        # Panel 2: ridge pts vs mesh cross-section
        # grid is (Z,Y,X) → marching cubes verts are (x, y, z)
        # imshow slice[z] shows (row=y, col=x) with origin='lower'
        # → scatter(x, y) = scatter(verts[:,0], verts[:,1]), filter by verts[:,2] ≈ slice_idx
        ax2 = fig.add_subplot(1, 3, 2)
        ax2.imshow(smoothed[slice_idx], cmap='gray', origin='lower')
        y_c, x_c = np.where(cleaned_mask[slice_idx])
        ax2.scatter(x_c, y_c, color='lime', s=1, label='Ridge pts')
        near = np.abs(verts[:, 2] - slice_idx) < 1.0
        if near.sum() > 0:
            ax2.scatter(verts[near, 0], verts[near, 1],
                        color='red', s=1, label='Mesh verts')
        ax2.legend(loc='upper right', markerscale=4)
        ax2.set_title("Ridge pts vs Mesh (slice)")

        # Panel 3: 3D vertex scatter preview
        ax3        = fig.add_subplot(1, 3, 3, projection='3d')
        n_preview  = min(3000, len(verts))
        sample_idx = np.random.choice(len(verts), n_preview, replace=False)
        sv         = verts[sample_idx]
        ax3.scatter(sv[:, 0], sv[:, 1], sv[:, 2],
                    s=0.3, c=sv[:, 2], cmap='viridis', alpha=0.5)
        ax3.set_title(f"3D Mesh Preview\n({len(verts)} verts, {len(faces)} faces)")
        ax3.set_xlabel("X"); ax3.set_ylabel("Y"); ax3.set_zlabel("Z")

        plt.tight_layout()
        plt.savefig(f"{field}_surface.png", dpi=150)
        plt.show()
        print(f"  Saved        : {field}_surface.png")

    return SurfaceData(vertices=verts, faces=faces)