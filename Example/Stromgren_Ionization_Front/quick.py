import sys
sys.path.append("../../..")

from AstroVis.backend import export_particle_surface_sequence, generate_species_fraction_fields

input_dir = "Data"
output_dir = "Output"
plot_dir = "Plots"

generate_species_fraction_fields(ds, species)

export_particle_surface_sequence(
    input_dir=input_dir,
    output_dir=output_dir,
    num_snapshot=None,
    ptype="PartType0",
    fields=None,
    res=256,
    field=field_name,
    threshold=None,
    log=True,
    intensive=True,
    center=True,
    scale=1.0,
    interpolate_missing=True,
    max_interp_gap=3,
)