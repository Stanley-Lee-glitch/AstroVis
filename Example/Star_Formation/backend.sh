#!/usr/bin/env bash
#SBATCH --job-name=star_formation
#SBATCH --output=star_formation_%j.out
#SBATCH --error=star_formation_%j.err
#SBATCH --mem=64G


export PYTHONUNBUFFERED=1
export STDBUF_STDOUT=L
export STDBUF_STDERR=L

python -u Star_Formation_Backend.py