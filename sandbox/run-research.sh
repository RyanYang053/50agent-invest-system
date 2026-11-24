#!/usr/bin/env bash
# Operator-only. Do not expose Docker control to any model or research worker.
set -euo pipefail
engine_args=(); qlib=0
if [[ ${1:-} == --qlib ]]; then engine_args=(--qlib); qlib=1; shift; fi
if [[ $# -ne 2 && $# -ne 4 ]]; then
  echo 'Usage: bash sandbox/run-research.sh [--qlib] sha256:LOCAL_IMAGE_ID output.json [panel.json file_sha256]' >&2; exit 2
fi
image=$1; output=$2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'local immutable image ID required' >&2; exit 2; }
[[ ! -e "$output" && ! -L "$output" ]] || { echo 'output already exists' >&2; exit 2; }
command -v docker >/dev/null || { echo 'Docker unavailable; no unsafe fallback' >&2; exit 2; }
[[ "$(docker image inspect --format '{{.Id}}' "$image")" == "$image" ]] || exit 2
args=(--demo); mounts=(); input_dir=; tmp=
name="atlas-research-$(date +%s)-$$"
umask 077
cleanup(){ docker rm -f "$name" >/dev/null 2>&1 || true; if [[ -n "$tmp" ]]; then rm -f -- "$tmp"; fi; if [[ -n "$input_dir" ]]; then rm -f -- "$input_dir/panel.json"; rmdir -- "$input_dir"; fi; }
trap cleanup EXIT
if [[ $# == 4 ]]; then
  [[ -f "$3" && ! -L "$3" && "$4" =~ ^[0-9a-f]{64}$ ]] || exit 2
  file=$(realpath "$3")
  [[ "$file" != *','* && "$(sha256sum "$file" | cut -d' ' -f1)" == "$4" ]] || exit 2
  # Copy the exact input to an isolated temporary directory; never mount the repo or home.
  input_dir=$(mktemp -d); chmod 700 "$input_dir"; cp -- "$file" "$input_dir/panel.json"; chmod 444 "$input_dir/panel.json"
  mounts=(--mount "type=bind,src=$input_dir/panel.json,dst=/input.json,readonly")
  args=(--panel /input.json --sha256 "$4")
fi
tmp=$(mktemp "${output}.tmp.XXXXXXXX")
# Hard time, CPU, memory, process and output bounds. No host network, secrets,
# broker mounts, writable repo, privileged flag, socket or dynamic executable.
(ulimit -f 65536; timeout --kill-after=10s 180s docker run --rm --name "$name" --pull never \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --user 65532:65532 --memory 2g --memory-swap 2g --cpus 2 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m --log-driver none \
  --entrypoint python "${mounts[@]}" "$image" -m atlas_pro.sandbox_entry "${args[@]}" "${engine_args[@]}" > "$tmp")
python - "$tmp" "$qlib" <<'PY'
import json,sys
with open(sys.argv[1]) as f: r=json.load(f)
if r.get('can_trade') is not False or r.get('promotion_allowed') is not False or not r.get('models'):raise SystemExit('unsafe/malformed research output')
if sys.argv[2]=='1':
    receipts=r.get('external_engine_receipts',[])
    if 'qlib_ridge' not in r['models'] or len(receipts)!=r['folds'] or any(x.get('engine')!='qlib' or x.get('version')!='0.9.7' or x.get('test_labels_supplied') is not False for x in receipts):raise SystemExit('Qlib execution receipt missing')
PY
# Atomic creation, never overwrite an existing report.
ln -- "$tmp" "$output"
