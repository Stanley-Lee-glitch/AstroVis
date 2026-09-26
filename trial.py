import sys
sys.path.append("..")

from AstroVis.backend import export_particle_surface_sequence

input_dir = "Example/Particle_to_Surface/Data"
output_dir = "Example/Particle_to_Surface"

export_particle_surface_sequence(
    input_dir=input_dir,
    output_dir=output_dir,
    ptype="PartType0",
    field="density",
)