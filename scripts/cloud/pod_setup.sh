#!/usr/bin/env bash
# Runs ON a RunPod GPU pod (Ubuntu, NVIDIA). Installs what the flyover render needs:
# system libraries and fonts (per pod), Blender 5.0.1 and its .blender-site packages
# (once, on the /workspace network volume, so later pods reuse them).
# Usage (on the pod): bash /workspace/LRH/scripts/cloud/pod_setup.sh
set -euo pipefail

W=/workspace
LRH=$W/LRH
VER=5.0.1
TAR=blender-$VER-linux-x64.tar.xz
SHA=8019580ee1b7262e505f4196a00237ccf743c88d205b38d34201510676e60b09   # blender-5.0.1.sha256
B=$W/blender-$VER-linux-x64/blender

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq rsync xz-utils fonts-liberation libxi6 libxxf86vm1 libxfixes3 \
    libxrender1 libxkbcommon0 libsm6 libgl1 libegl1 >/dev/null

if [ ! -x "$B" ]; then
    curl -fsSL -o "$W/$TAR" "https://download.blender.org/release/Blender5.0/$TAR"
    echo "$SHA  $W/$TAR" | sha256sum -c -
    tar -xf "$W/$TAR" -C "$W"
    rm "$W/$TAR"
fi

# Linux wheels for Blender's Python (the Mac copy of .blender-site is not synced).
PY=$(ls "$W"/blender-$VER-linux-x64/$(echo $VER | cut -d. -f1-2)/python/bin/python3.*)
if [ ! -f "$LRH/.blender-site/.linux" ]; then
    "$PY" -m ensurepip -q 2>/dev/null || true
    "$PY" -m pip install -q --no-deps --target "$LRH/.blender-site" -r "$LRH/scripts/blender/requirements.txt"
    touch "$LRH/.blender-site/.linux"
fi

nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
"$B" -b --python-expr "import bpy; print('BLENDER OK', bpy.app.version_string)" 2>&1 | grep 'BLENDER OK'
