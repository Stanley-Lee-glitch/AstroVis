import bpy

import sys
sys.path.append(r"../../..") 
from AstroVis.api import *

import numpy as np

vdb_path = "Output.zip"

scene = SceneManager()
scene.clear_scene(use_empty=False)
scene.set_camera(location=(1, 1, 1), look_at=(0, 0, 0))

object_name = "Star_Formation"

# Create a volume material for the field data
material = create_field_volume_material(
    object_name,
    field_min=-2,  # Set the minimum field value for visualization
    field_max=5,
    emission_multiplier=0.1,
    apply=False,
)[object_name]

setup_animation(data_path=vdb_path,
                object_material = {object_name: material})


scene.set_world_background(color=(0.0, 0.0, 0.0, 1.0), strength=0.0)

scene = bpy.context.scene
scene.cycles.device = 'GPU'                    # confirm OptiX/CUDA is selected in prefs
scene.cycles.samples = 32                       # plenty for a structure check
scene.cycles.use_denoising = False              # denoising can hide real detail at low res
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.05

scene.cycles.volume_step_rate = 2.0             # coarser steps = big speedup
scene.cycles.volume_max_steps = 256              # 1024 was overkill for a test render
scene.cycles.volume_bounces = 1                  # 0-1 is enough to check shape/structure

scene.render.resolution_percentage = 50          # half-res for a fast preview

