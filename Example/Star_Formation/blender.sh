#!/bin/bash
#SBATCH --job-name=Star_Formation
#SBATCH --output=Star_Formation_%j.out
#SBATCH --error=Star_Formation_%j.err
#SBATCH --cpus-per-task=24
#SBATCH --mem=100G


# Run Blender (headless) 
#export Blender_User_Device=CPU
GALLIUM_DRIVER=llvmpipe ../../../code/blender-4.2.0-linux-x64/blender -b --factory-startup -E CYCLES --python Star_Formation_Blender.py -o "//Blender_Plot/frame_" -s 0 -e 1 -a

