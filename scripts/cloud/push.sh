#!/usr/bin/env bash
# Runs on the Mac. Copies what the flyover render reads to the pod's /workspace/LRH,
# keeping the repo layout (the .blend refers to ../../assets/... by relative path), then
# runs pod_setup.sh there. About 3 GB the first time; later runs send only changes.
# Usage: scripts/cloud/push.sh <pod-ip> <ssh-port> [build-date, default newest out/*/lrh_baseline.blend]
set -euo pipefail

HOST=$1 PORT=$2
cd "$(dirname "$0")/../.."
DAY=${3:-$(basename "$(dirname "$(ls out/*/lrh_baseline.blend | sort | tail -1)")")}
SSH="ssh -i $HOME/.ssh/runpod_ed25519 -p $PORT -o StrictHostKeyChecking=accept-new"
DEST=root@$HOST:/workspace/LRH

send() { rsync -az -e "$SSH" "$@"; }

$SSH root@"$HOST" "command -v rsync >/dev/null || (apt-get update -qq && apt-get install -y -qq rsync >/dev/null);
    mkdir -p /workspace/LRH/out/$DAY /workspace/LRH/inputs/terrain /workspace/LRH/assets"
send --exclude /.git --exclude /.blender-site --exclude __pycache__ --exclude /out --exclude /inputs \
    --exclude /assets ./ "$DEST"/
send inputs/terrain/origin.json "$DEST"/inputs/terrain/
send out/derived "$DEST"/out/
send out/"$DAY"/lrh_baseline.blend "$DEST"/out/"$DAY"/
send assets/generated assets/polyhaven "$DEST"/assets/
$SSH root@"$HOST" "bash /workspace/LRH/scripts/cloud/pod_setup.sh"
echo "PUSHED out/$DAY to $HOST:$PORT"
