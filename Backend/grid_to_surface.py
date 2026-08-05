from skimage import measure
from skimage.measure import marching_cubes
import trimesh
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt
from .volume_data import GridBlock
from .surface_data import SurfaceData
from typing import Union, List, Dict

def preview_field_slice(
    grid_data : GridBlock,
    fields    : Union[str, List[str]] = None,
    axis      : int = 0,
    slice_idx : int = None,
):
    """
    Quick look at one or more fields before choosing an extraction method.

    - A field with a clean, single-mode threshold in its histogram and a
      blob-like slice -> grid_to_surface (isosurface) is usually enough.
    - A field with filamentary / ridge-like structure and no clean single
      threshold -> grid_to_ridge_surface is usually better.

    Parameters
    ----------
    grid_data : GridBlock
    fields    : str or list[str] or None
        Field name(s) to preview. If None, previews every field in grid_data.fields.
    axis      : int   axis_map = {'z': 0, 'y': 1, 'x': 2} (default: 'z')
    slice_idx : int   Index along `axis` for plot (default: middle of that axis)
    """
    if fields is None:
        fields = list(grid_data.fields.keys())
    elif isinstance(fields, str):
        fields = [fields]

    valid_fields = [f for f in fields if f in grid_data.fields]
    for f in fields:
        if f not in grid_data.fields:
            print(f"  [WARNING] Field '{f}' not found in grid_data.fields; skipping.")

    if not valid_fields:
        print("  [WARNING] No valid fields to preview.")
        return

    n = len(valid_fields)
    fig, axes = plt.subplots(n, 2, figsize=(12, 5 * n), squeeze=False)
    fig.suptitle(f"Field Preview  |  axis={axis}")

    for row, field in enumerate(valid_fields):
        volume = grid_data.fields[field]
        s_idx = slice_idx if slice_idx is not None else volume.shape[axis] // 2
        slice_2d = np.take(volume, s_idx, axis=axis)

        im = axes[row, 0].imshow(slice_2d, cmap='viridis', origin='lower')
        axes[row, 0].set_title(f"'{field}'  |  index={s_idx}")
        plt.colorbar(im, ax=axes[row, 0])

        axes[row, 1].hist(volume.ravel(), bins=100, color='steelblue')
        axes[row, 1].set_yscale('log')
        axes[row, 1].set_title(f"'{field}' value distribution")
        axes[row, 1].set_xlabel(field)
        axes[row, 1].set_ylabel("Voxel count (log)")

    plt.tight_layout()
    plt.savefig(f"preview.png", dpi=150)
    plt.show()
    print(f"  Saved: preview.png")

# Method 1: Isosurface Extraction

def grid_to_surface(
    grid_data   : GridBlock,
    threshold   : float,
    field       : str = None,
    # --- Parameters of surface ---
    build_obj   : bool = False,
    center      : bool = True,
    scale       : float = 1.0,
    # --- Plotting Check ---
    plot_surface: bool = True,
    axis        : int  = 0,
    slice_idx   : int  = None,
) -> SurfaceData:
    """
    Extract an isosurface from a single 3D grid field using marching cubes.
    """
    if field is None:
        field = list(grid_data.fields.keys())[0] if len(grid_data.fields) == 1 else "density"

    print(f"\n{'='*50}")
    print(f"Running Isosurface Extraction for field {field} at threshold {threshold}...")
    print(f"{'-'*50}")

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
        print(f"  Left edge: {grid_data.left_edge - center_of_mass}, Right edge: {grid_data.right_edge - center_of_mass}")
    else:
        print(f"  Left edge: {grid_data.left_edge}, Right edge: {grid_data.right_edge}")

    if build_obj:
        obj_path = f"{field}_surface.obj"
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
        mesh.export(obj_path)
        print(f"  Exported  : {obj_path}")

    if plot_surface:
        field_volume = grid_data.fields[field]
        s_idx = slice_idx if slice_idx is not None else field_volume.shape[axis] // 2
        slice_2d = np.take(field_volume, s_idx, axis=axis)

        fig, ax = plt.subplots(figsize=(6, 6))
        im = ax.imshow(slice_2d, cmap='viridis', origin='lower')
        ax.contour(slice_2d, levels=[threshold], colors='red', linewidths=1.5)
        plt.colorbar(im, ax=ax)
        ax.set_title(f"Isosurface Extraction  |  field='{field}'  index={s_idx}\nthreshold={threshold}")
        plt.tight_layout()
        plt.savefig(f"{field}_isosurface.png", dpi=150)
        plt.show()
        print(f"  Saved        : {field}_isosurface.png")

    print(f"{'='*50}\n")
    return SurfaceData(vertices=verts, faces=faces, normals=normals)


def grid_to_surfaces(
    grid_data : GridBlock,
    threshold : float,
    fields    : Union[str, List[str]] = None,
    **kwargs,
) -> Dict[str, SurfaceData]:
    """
    Run grid_to_surface across multiple fields. Extra keyword arguments are
    passed through to grid_to_surface for every field (e.g. build_obj, center,
    scale, plot_surface, axis, slice_idx).

    Parameters
    ----------
    fields : str | list[str] | None   Field name(s) (default: all fields in grid_data)

    Returns
    -------
    dict[str, SurfaceData]   One entry per successfully extracted field.
                              Fields that fail marching_cubes are skipped with a warning
                              and simply omitted from the result.
    """
    if fields is None:
        fields = list(grid_data.fields.keys())
    elif isinstance(fields, str):
        fields = [fields]

    surfaces = {}
    for field in fields:
        result = grid_to_surface(grid_data, threshold, field=field, **kwargs)
        if result is not None:
            surfaces[field] = result
        else:
            print(f"  [WARNING] Skipping '{field}' due to extraction failure.")
            print(f"{'='*50}\n")

    return surfaces


# Method 2: Ridge Surface Extraction

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
    plot_check       = True,   # If True, plot all three diagnostic figures: raw ridge, cleaned ridge, chi+contour
    print_components = True,   # Print component size table after filtering
    axis             = 0,      # Axis to slice diagnostic plots along: 'x', 'y', or 'z'
    slice_idx        = None,   # Index along `axis` for diagnostic plots (default: middle)
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
    plot_check       : bool         Plot ridge detection and surface result (default True)
    print_components : bool         Print connected component table (default True)
    axis             : int          0 for z-axis, 1 for y-axis, 2 for x-axis (default: z)
    slice_idx:       : int          Index along `axis` for plot  (default: middle)
    build_obj        : bool         If True, export mesh as .obj file
    center           : bool         If True, center the surface at the origin (default True)

    """
    if field is None:
        field = list(grid_data.fields.keys())[0] if len(grid_data.fields) == 1 else "density"
        
    volume = grid_data.fields[field]
    shape = volume.shape

    # STEP 1: Ridge Detection via Hessian + NMS
    print(f"\n{'='*50}")
    print(f"Running Ridge Surface Extraction for field {field}...")
    print(f"{'-'*50}")
    print(f"STEP 1: Ridge Detection")
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

    # STEP 2: Connected Component Filtering
    print(f"\n{'-'*50}")
    print(f"STEP 2: Component Filtering")
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

    # STEP 3: Poisson Surface Reconstruction
    print(f"\n{'-'*50}")
    print(f"STEP 3: Poisson Reconstruction")
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
    

    print(f"\n  {'-'*44}")
    print(f"  Final Surface:")
    print(f"  Vertices : {len(verts)}")
    print(f"  Faces    : {len(faces)}")
    print(f"  {'-'*44}\n")
    
    if build_obj:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        obj_path = f"{field}_surface.obj"
        mesh.export(obj_path)
        print(f"  Exported     : {obj_path}")

    if plot_check:
        shape = volume.shape
        s_idx = slice_idx if slice_idx is not None else shape[axis] // 2
        
        smoothed_slice = np.take(smoothed, s_idx, axis=axis)
        raw_ridge_slice = np.take(thin_ridge_mask, s_idx, axis=axis)
        cleaned_slice = np.take(cleaned_mask, s_idx, axis=axis)
        chi_slice = np.take(chi, s_idx, axis=axis)

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(f"Ridge Surface Extraction  |  field='{field}'  axis={axis}, index={s_idx}")

        # Panel 1: raw detected ridge
        axes[0].imshow(smoothed_slice, cmap='gray', origin='lower')
        r0, c0 = np.where(raw_ridge_slice)
        axes[0].scatter(c0, r0, color='red', s=1)
        axes[0].set_title(f"Step 1: Raw Ridge  (n={thin_ridge_mask.sum()})")

        # Panel 2: cleaned ridge
        axes[1].imshow(smoothed_slice, cmap='gray', origin='lower')
        r1, c1 = np.where(cleaned_slice)
        axes[1].scatter(c1, r1, color='lime', s=1)
        axes[1].set_title(f"Step 2: Cleaned Ridge  (n={cleaned_mask.sum()}, min={min_cluster_size})")

        # Panel 3: chi field + isocontour
        im3 = axes[2].imshow(chi_slice, cmap='RdBu', origin='lower')
        axes[2].contour(chi_slice, levels=[isovalue], colors='yellow', linewidths=1.5)
        plt.colorbar(im3, ax=axes[2])
        axes[2].set_title(f"Step 3: Chi Field + Isocontour\nisovalue={isovalue:.4f} (pct={isovalue_pct})")

        plt.tight_layout()
        plt.savefig(f"{field}_ridge_surface.png", dpi=150)
        plt.show()
        print(f"  Saved        : {field}_ridge_surface.png")
        print(f"  {'='*50}\n")

    return SurfaceData(vertices=verts, faces=faces)