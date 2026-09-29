#!/usr/bin/env bash
#SBATCH --job-name=star_formation_backend
#SBATCH --output=star_formation_backend_%j.out
#SBATCH --error=star_formation_backend_%j.err
#SBATCH --mem=64G


export PYTHONUNBUFFERED=1
export STDBUF_STDOUT=L
export STDBUF_STDERR=L

python -u Star_Formation_Backend.py