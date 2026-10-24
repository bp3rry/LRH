#!/usr/bin/env bash
# Runs ON the pod. One Blender per GPU, each on its own --shard, each in a retry loop
# (a GPU out-of-memory stop resumes, skipping finished frames). Detaches; logs go next to
# the frames. Extra arguments are passed to flyover.py.
# Usage (on the pod): bash scripts/cloud/render.sh <build-date> --variant low --layout pairs --4k
#        test first: bash scripts/cloud/render.sh <build-date> ... --frames 0,1600,3000 (shared out across the GPUs)
set -euo pipefail

DAY=$1; shift
cd /workspace/LRH
B=/workspace/blender-5.0.1-linux-x64/blender
N=$(nvidia-smi -L | wc -l)
LOGS=out/$DAY/cloud_logs
mkdir -p "$LOGS"
# Threads per Blender from the pod's CPU quota, not the host's core count: Blender otherwise
# starts a thread per host core (128) and the quota throttles it hard (GPU idle, 450 s
# 4K frames in the 24 Oct 2026 test).
if [ -f /sys/fs/cgroup/cpu.max ]; then read -r Q P < /sys/fs/cgroup/cpu.max
else Q=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us); P=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us); fi
if [ "$Q" = max ] || [ "$Q" -le 0 ]; then CPUS=$(nproc); else CPUS=$((Q / P)); fi
T=$(( CPUS / N > 1 ? CPUS / N : 1 ))
for i in $(seq 0 $((N - 1))); do
    if [ "$N" -gt 1 ]; then GPU="CUDA_VISIBLE_DEVICES=$i"; SHARD="--shard $i/$N"; else GPU=""; SHARD=""; fi
    nohup bash -c "for a in \$(seq 1 30); do env $GPU $B -b out/$DAY/lrh_baseline.blend -t $T --python-exit-code 1 \
        --python scripts/blender/flyover.py -- $* $SHARD > $LOGS/gpu${i}_\$a.log 2>&1 && break; \
        echo \"gpu $i attempt \$a stopped\"; done; echo \"gpu $i DONE\"" > "$LOGS/gpu${i}_loop.log" 2>&1 &
done
echo "started $N process(es), $T threads each; logs in /workspace/LRH/$LOGS"
