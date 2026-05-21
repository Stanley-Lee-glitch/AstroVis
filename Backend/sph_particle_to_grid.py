"""
SPH kernel and scatter implementation adapted from swiftsimio
(https://github.com/SWIFTSIM/swiftsimio).

"""

import numpy as np
from numba import jit
from .particle_data import SPHParticleData
from .volume_data import GridBlock


# Taken from Dehnen & Aly 2012
kernel_gamma = 1.936492
kernel_constant = 21.0 * 0.31830988618379067154 / 2.0


@jit(nopython=True, fastmath=True)
def kernel(r: float | np.float32, H: float | np.float32) -> float:
    """
    Kernel implementation for swiftsimio.

    Parameters
    ----------
    r : float or np.float32
        Distance from particle.

    H : float or np.float32
        Kernel width (i.e. radius of compact support of kernel).

    Returns
    -------
    float
        Contribution to density by particle at distance `r`.

    Notes
    -----
    Swiftsimio uses the Wendland-C2 kernel as described in [1]_.

    References
    ----------
    .. [1] Dehnen W., Aly H., 2012, MNRAS, 425, 1068
    """
    inverse_H = 1.0 / H
    ratio = r * inverse_H

    kernel = 0.0

    if ratio < 1.0:
        one_minus_ratio = 1.0 - ratio
        one_minus_ratio_2 = one_minus_ratio * one_minus_ratio
        one_minus_ratio_4 = one_minus_ratio_2 * one_minus_ratio_2

        kernel = max(one_minus_ratio_4 * (1.0 + 4.0 * ratio), 0.0)

        kernel *= kernel_constant * inverse_H * inverse_H * inverse_H

    return kernel

"""
Basic volume render for SPH data.

Takes the 3D positions of the particles and projects them onto a grid.
"""

@jit(nopython=True, fastmath=True)
def scatter(
    x: np.float64,
    y: np.float64,
    z: np.float64,
    m: np.float32,
    h: np.float32,
    res: int,
    box_x: np.float64 = 0.0,
    box_y: np.float64 = 0.0,
    box_z: np.float64 = 0.0,
) -> np.ndarray:
    """
    Create a weighted voxel grid.

    Computes contributions to a voxel grid from particles with positions
    (`x`,`y`,`z`) with smoothing lengths `h` weighted by quantities `m`.
    This includes periodic boundary effects.

    Parameters
    ----------
    x : np.ndarray[np.float64]
        Array of x-positions of the particles. Must be bounded by [0, 1].

    y : np.ndarray[np.float64]
        Array of y-positions of the particles. Must be bounded by [0, 1].

    z : np.ndarray[np.float64]
        Array of z-positions of the particles. Must be bounded by [0, 1].

    m : np.ndarray[np.float32]
        Array of masses (or otherwise weights) of the particles.

    h : np.ndarray[np.float32]
        Array of smoothing lengths of the particles.

    res : int
        The number of voxels along one axis, i.e. this returns a cube
        of res * res * res.

    box_x : np.float64
        Box size in x, in the same rescaled length units as x, y and z.
        Used for periodic wrapping.

    box_y : np.float64
        Box size in y, in the same rescaled length units as x, y and z.
        Used for periodic wrapping.

    box_z : np.float64
        Box size in z, in the same rescaled length units as x, y and z.
        Used for periodic wrapping.

    Returns
    -------
    np.ndarray[np.float32, np.float32, np.float32]
        Voxel grid of quantity.

    See Also
    --------
    scatter_parallel
        Parallel implementation of this function.

    slice_scatter
        Create scatter plot of a slice of data.

    slice_scatter_parallel
        Create scatter plot of a slice of data in parallel.

    Notes
    -----
    Explicitly defining the types in this function allows for a 25-50% performance
    improvement. In our testing, using numpy floats and integers is also an improvement
    over using the numba np.ones.
    """
    # Output np.array for our image
    image = np.zeros((res, res, res), dtype=np.float32)
    maximal_array_index = np.int32(res) - 1

    # Change that integer to a float, we know that our x, y are bounded
    # by [0, 1].
    float_res = np.float32(res)
    pixel_width = 1.0 / float_res

    # We need this for combining with the x_pos and y_pos variables.
    float_res_64 = np.float64(res)

    # If the kernel width is smaller than this, we drop to just PIC method
    drop_to_single_cell = pixel_width * 0.5

    # Pre-calculate this constant for use with the above
    inverse_cell_volume = float_res * float_res * float_res

    if box_x == 0.0:
        xshift_min = 0
        xshift_max = 1
    else:
        xshift_min = -1  # x_min is always at x=0
        xshift_max = int(np.ceil(1 / box_x) + 1)  # tile the box to cover [0, 1]
    if box_y == 0.0:
        yshift_min = 0
        yshift_max = 1
    else:
        yshift_min = -1  # y_min is always at y=0
        yshift_max = int(np.ceil(1 / box_y) + 1)  # tile the box to cover [0, 1]
    if box_z == 0.0:
        zshift_min = 0
        zshift_max = 1
    else:
        zshift_min = -1  # z_min is always at z=0
        zshift_max = int(np.ceil(1 / box_z) + 1)  # tile the box to cover [0, 1]

    for x_pos_original, y_pos_original, z_pos_original, mass, hsml in zip(
        x, y, z, m, h
    ):
        # loop over periodic copies of the particle
        for xshift in range(xshift_min, xshift_max):
            for yshift in range(yshift_min, yshift_max):
                for zshift in range(zshift_min, zshift_max):
                    x_pos = x_pos_original + xshift * box_x
                    y_pos = y_pos_original + yshift * box_y
                    z_pos = z_pos_original + zshift * box_z

                    # Calculate the cell that this particle; use the 64 bit version of the
                    # resolution as this is the same type as the positions
                    particle_cell_x = np.int32(np.floor(float_res_64 * x_pos))
                    particle_cell_y = np.int32(np.floor(float_res_64 * y_pos))
                    particle_cell_z = np.int32(np.floor(float_res_64 * z_pos))

                    # SWIFT stores hsml as the FWHM.
                    kernel_width = kernel_gamma * hsml

                    # The number of cells that this kernel spans
                    cells_spanned = np.int32(1.0 + kernel_width * float_res)

                    if (
                        particle_cell_x + cells_spanned < 0
                        or particle_cell_x - cells_spanned > maximal_array_index
                        or particle_cell_y + cells_spanned < 0
                        or particle_cell_y - cells_spanned > maximal_array_index
                        or particle_cell_z + cells_spanned < 0
                        or particle_cell_z - cells_spanned > maximal_array_index
                    ):
                        # Can happily skip this particle
                        continue

                    if kernel_width < drop_to_single_cell:
                        # Easygame, gg
                        if (
                            particle_cell_x >= 0
                            and particle_cell_x <= maximal_array_index
                            and particle_cell_y >= 0
                            and particle_cell_y <= maximal_array_index
                            and particle_cell_z >= 0
                            and particle_cell_z <= maximal_array_index
                        ):
                            image[
                                particle_cell_x, particle_cell_y, particle_cell_z
                            ] += mass * inverse_cell_volume
                    else:
                        # Now we loop over the square of cells that the kernel lives in
                        for cell_x in range(
                            # Ensure that the lowest x value is 0, otherwise we segfault
                            max(0, particle_cell_x - cells_spanned),
                            # Ensure that the highest x value lies within the np.array
                            # bounds, otherwise we'll segfault (oops).
                            min(
                                particle_cell_x + cells_spanned, maximal_array_index + 1
                            ),
                        ):
                            # The distance in x to our new favourite cell -- remember that
                            # our x, y are all in a box of [0, 1]; calculate the distance
                            # to the cell centre
                            distance_x = (
                                np.float32(cell_x) + 0.5
                            ) * pixel_width - np.float32(x_pos)
                            distance_x_2 = distance_x * distance_x
                            for cell_y in range(
                                max(0, particle_cell_y - cells_spanned),
                                min(
                                    particle_cell_y + cells_spanned,
                                    maximal_array_index + 1,
                                ),
                            ):
                                distance_y = (
                                    np.float32(cell_y) + 0.5
                                ) * pixel_width - np.float32(y_pos)
                                distance_y_2 = distance_y * distance_y
                                for cell_z in range(
                                    max(0, particle_cell_z - cells_spanned),
                                    min(
                                        particle_cell_z + cells_spanned,
                                        maximal_array_index + 1,
                                    ),
                                ):
                                    distance_z = (
                                        np.float32(cell_z) + 0.5
                                    ) * pixel_width - np.float32(z_pos)
                                    distance_z_2 = distance_z * distance_z

                                    r = np.sqrt(
                                        distance_x_2 + distance_y_2 + distance_z_2
                                    )

                                    kernel_eval = kernel(r, kernel_width)

                                    image[cell_x, cell_y, cell_z] += mass * kernel_eval

    return image

# Convert SPH particle data to GridBlock with center at origin and boxwidth at 1
def sph_to_grid(
    particle_data: SPHParticleData,
    field: str = "density",
    res: int = 256
    ) -> GridBlock :
    x = (particle_data.coordinates[:, 0] / particle_data.boxsize[0]).astype(np.float64)
    y = (particle_data.coordinates[:, 1] / particle_data.boxsize[1]).astype(np.float64)
    z = (particle_data.coordinates[:, 2] / particle_data.boxsize[2]).astype(np.float64)
    h = (particle_data.smoothing_lengths / particle_data.boxsize[0]).astype(np.float32)


    m_particle = particle_data.masses.astype(np.float32)
    rho = particle_data.densities.astype(np.float32)
    
    if field == "density":
        field_values = particle_data.densities
    
    elif field == 'smoothing_lengths':
        field_values = particle_data.smoothing_lengths.astype(np.float32)
    else:
        field_values = particle_data.fields[field].astype(np.float32)


    weight_num = m_particle * field_values / rho
    weight_den = m_particle / rho

    num = scatter(
        x, y, z,
        weight_num,
        h,
        res,
    )

    den = scatter(
        x, y, z,
        weight_den,
        h,
        res,
    )

    attribute_grid = np.zeros_like(num)
    mask = den > 0
    
    attribute_grid[mask] = num[mask] / den[mask]
    
    return GridBlock(
        block_id=0,
        left_edge=(-0.5, -0.5, -0.5),
        right_edge=(0.5, 0.5, 0.5),
        dims=(res, res, res),
        fields={field: attribute_grid}
    )