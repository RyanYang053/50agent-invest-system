#!/usr/bin/env bash
# Operator-only fixed synthetic accounting run. No arbitrary algorithm/config/data.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'Usage: bash sandbox/run-lean-fixture.sh sha256:LOCAL_IMAGE_ID output.json' >&2; exit 2
fi
image=$1; output=$2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'immutable local LEAN image ID required' >&2; exit 2; }
[[ ! -e "$output" && ! -L "$output" ]] || { echo 'output exists' >&2; exit 2; }
[[ "$(docker image inspect --format '{{.Id}}' "$image")" == "$image" ]] || exit 2
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
umask 077
work=$(mktemp -d)
temp=
name="atlas-lean-fixture-$(date +%s)-$$"
cleanup(){ docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf -- "$work"; if [[ -n "$temp" ]]; then rm -f -- "$temp"; fi; }
trap cleanup EXIT
mkdir "$work/data" "$work/input"
python -m atlas_pro.lean_fixture prepare "$work/data" > "$work/manifest.json"
cp -- "$here/lean/fixture_algorithm.py" "$here/lean/config.json" "$work/input/"
chmod 755 "$work/input"
chmod 444 "$work/input/"*
temp=$(mktemp "${output}.tmp.XXXXXXXX")
# Only generated synthetic inputs are mounted. Engine metadata comes from its
# local image. No host repository, home, socket, writable data mount or secrets.
(ulimit -f 32768; timeout --kill-after=15s 300s docker run --rm --name "$name" --pull never \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --user 65532:65532 --memory 4g --memory-swap 4g --cpus 2 --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m --log-driver none \
  --env HOME=/tmp --env TMPDIR=/tmp --env DOTNET_CLI_HOME=/tmp --env PYTHONDONTWRITEBYTECODE=1 \
  --env OMP_NUM_THREADS=1 --env OPENBLAS_NUM_THREADS=1 --env MKL_NUM_THREADS=1 \
  --mount "type=bind,src=$work/input,dst=/atlas-input,readonly" \
  --mount "type=bind,src=$work/data/minute,dst=/Lean/Data/equity/usa/minute,readonly" \
  --mount "type=bind,src=$work/data/daily,dst=/Lean/Data/equity/usa/daily,readonly" \
  --mount "type=bind,src=$work/data/map_files,dst=/Lean/Data/equity/usa/map_files,readonly" \
  --mount "type=bind,src=$work/data/factor_files,dst=/Lean/Data/equity/usa/factor_files,readonly" \
  --entrypoint dotnet "$image" /Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll \
  --config /atlas-input/config.json > "$work/engine.log" 2>&1) || { tail -n 80 "$work/engine.log" >&2; exit 1; }
python -m atlas_pro.lean_fixture verify "$work/engine.log" --image-id "$image" \
  --fixture-dir "$work/data" --algorithm "$work/input/fixture_algorithm.py" --config "$work/input/config.json" > "$temp" || { tail -n 80 "$work/engine.log" >&2; exit 1; }
ln -- "$temp" "$output"
