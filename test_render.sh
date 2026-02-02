#!/bin/bash
cd "$(dirname "$0")"
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate pt1
python test_render.py "$@"
