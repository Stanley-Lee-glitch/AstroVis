import os
import yt

import sys
sys.path.append("../../..")

from AstroVis.backend import (
    generate_species_fraction_fields,
    load_particles,
    sph_to_grid,
    grid_to_surface,
    grid_to_ridge_surface,
    save,
)

input_dir = r"Data"
export_dir = r"Surface"
ptype = "PartType0"

os.makedirs(export_dir, exist_ok=True)

snapshots = sorted(
    f for f in os.listdir(input_dir)
    if f.endswith(".hdf5")
)

target_species = ["OI_fraction", "OII_fraction", "OIII_fraction", "OIV_fraction"]
surface_frames = {name: [] for name in target_species}

print(f"Found {len(snapshots)} snapshot(s).")

for frame_num, snapshot in enumerate(snapshots):
    ds = yt.load(os.path.join(input_dir, snapshot))
    oxygen_fields = generate_species_fraction_fields(ds, "O")

    particles = load_particles(
        ds,
        ptype=ptype,
        fields=oxygen_fields,
    )

    for species_name in target_species:
        grid = sph_to_grid(
            particles,
            fields=[species_name],
            res=256,
            intensive=True,
            center=True,
        )

        if species_name in {"OI_fraction", "OIV_fraction"}:
            surface = grid_to_surface(
                grid,
                threshold=0.5,
                field=species_name,
                plot_surface=(frame_num == 0),
                center=True,
                scale=1.0,
                path=os.path.join(export_dir, f"{species_name}_isosurface_frame{frame_num}.png")
            )
        else:
            surface = grid_to_ridge_surface(
                grid,
                field=species_name,
                sigma=1.2,
                lambda_pct=10,
                min_cluster_size=250,
                plot_check=(frame_num == 0),
                center=True,
                scale=1.0,
                path=os.path.join(export_dir, f"{species_name}_ridge_surface_frame{frame_num}.png")
            )

        if surface is not None:
            surface_frames[species_name].append(surface)

export_payload = {
    f"{species_name}_surface": frames
    for species_name, frames in surface_frames.items()
    if frames
}

save("Surface/oxygen_surfaces.hdf5", export_payload)
