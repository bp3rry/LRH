#!/usr/bin/env bash
# Runs on the Mac. Copies the pod's rendered frames and logs back into out/<build-date>/;
# safe to repeat while the render runs. Encode locally once all frames are in:
#   Blender -b out/<date>/lrh_baseline.blend --python-exit-code 1 --python scripts/blender/flyover.py \
#       -- --variant low --layout pairs --4k --encode-only
# Usage: scripts/cloud/pull.sh <pod-ip> <ssh-port> <build-date>
set -euo pipefail

HOST=$1 PORT=$2 DAY=$3
cd "$(dirname "$0")/../.."
SSH="ssh -i $HOME/.ssh/runpod_ed25519 -p $PORT -o StrictHostKeyChecking=accept-new"
for part in video cloud_logs; do
    rsync -rltz --exclude 'raw_*' -e "$SSH" root@"$HOST":/workspace/LRH/out/"$DAY"/$part out/"$DAY"/
done
for d in out/"$DAY"/video/*/frames; do echo "$d: $(ls "$d" | grep -c '^f_') frames"; done
