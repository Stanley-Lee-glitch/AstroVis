#!/bin/bash
#SBATCH --job-name=star_formation_blender
#SBATCH --output=star_formation_blender_%j.out
#SBATCH --error=star_formation_blender_%j.err
#SBATCH --cpus-per-task=24
#SBATCH --mem=100G


# Run Blender (headless) 
#export Blender_User_Device=CPU
GALLIUM_DRIVER=llvmpipe ../../../code/blender-4.2.0-linux-x64/blender -b --factory-startup -E CYCLES --python Star_Formation_Blender.py -o "//Blender_Plot/frame_" -s 0 -e 4 -a

