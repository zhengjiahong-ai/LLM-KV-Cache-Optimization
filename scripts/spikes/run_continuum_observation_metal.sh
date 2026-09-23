#!/usr/bin/env bash

set -euo pipefail

die() {
  printf 'error: %s\n' "$1" >&2
  exit 2
}

print_command() {
  stderr_path=$1
  shift
  printf '%q' "$1"
  shift
  printf ' %q' "$@"
  printf ' 2> %q\n' "$stderr_path"
}

dry_run=false
runtime_python=""
scenario=""
run_id=""
model=""
model_revision=""
tokenizer=""
tokenizer_revision=""
output_dir=""
observer_mode=""
gpu_memory_utilization=""
vllm_metal_source_checkout=""
pressure_request_count=""
pressure_prompt_tokens=""
max_tokens=""

while (($# > 0)); do
  case "$1" in
    --dry-run)
      dry_run=true
      shift
      ;;
    --python)
      (($# >= 2)) || die "$1 requires a value"
      runtime_python=$2
      shift 2
      ;;
    --scenario|--run-id|--model|--model-revision|--tokenizer|--tokenizer-revision|--output-dir|--observer-mode|--gpu-memory-utilization|--vllm-metal-source-checkout|--pressure-request-count|--pressure-prompt-tokens|--max-tokens)
      (($# >= 2)) || die "$1 requires a value"
      option=${1#--}
      option=${option//-/_}
      printf -v "$option" '%s' "$2"
      shift 2
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$runtime_python" ]] || die "--python is required"
[[ "$runtime_python" == /* ]] || die "--python must be absolute"
[[ -x "$runtime_python" ]] || die "--python must name an executable file"
[[ -n "$scenario" ]] || die "--scenario is required"
[[ -n "$run_id" ]] || die "--run-id is required"
[[ "$run_id" != */* && "$run_id" != "." && "$run_id" != ".." ]] || \
  die "--run-id must be one safe path component"
[[ -n "$model" ]] || die "--model is required"
[[ -n "$model_revision" ]] || die "--model-revision is required"
[[ "$model_revision" =~ ^[0-9a-f]{40}$ ]] || \
  die "--model-revision must be a lowercase 40-hex commit"
[[ -n "$tokenizer" ]] || die "--tokenizer is required"
[[ -n "$tokenizer_revision" ]] || die "--tokenizer-revision is required"
[[ "$tokenizer_revision" =~ ^[0-9a-f]{40}$ ]] || \
  die "--tokenizer-revision must be a lowercase 40-hex commit"
[[ -n "$output_dir" ]] || die "--output-dir is required"
[[ "$observer_mode" == "off" || "$observer_mode" == "on" ]] || \
  die "--observer-mode must be off or on"
[[ -n "$gpu_memory_utilization" ]] || die "--gpu-memory-utilization is required"
[[ -n "$vllm_metal_source_checkout" ]] || \
  die "--vllm-metal-source-checkout is required"
[[ "$vllm_metal_source_checkout" == /* ]] || \
  die "--vllm-metal-source-checkout must be absolute"
[[ -d "$vllm_metal_source_checkout" ]] || \
  die "--vllm-metal-source-checkout must name an existing directory"
[[ "$output_dir" == /* ]] || die "--output-dir must be absolute"
[[ -d "$output_dir" ]] || die "--output-dir must already exist"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)
output_dir=$(cd -- "$output_dir" && pwd -P)
vllm_metal_source_checkout=$(cd -- "$vllm_metal_source_checkout" && pwd -P)
task3_commit_sha=$(git -C "$repo_root" rev-parse --verify HEAD) || \
  die "repository HEAD is unavailable"
task3_worktree_clean=false
if [[ -z "$(git -C "$repo_root" status --porcelain --untracked-files=normal)" ]]; then
  task3_worktree_clean=true
fi

command=(
  env
  "PYTHONPATH=$repo_root/src:$repo_root"
  VLLM_ENABLE_V1_MULTIPROCESSING=0
  VLLM_METAL_USE_PAGED_ATTENTION=1
  VLLM_METAL_MEMORY_FRACTION=auto
  VLLM_MLX_DEVICE=gpu
  VLLM_HOST_IP=127.0.0.1
  "KVOPT_TASK3_COMMIT_SHA=$task3_commit_sha"
  "KVOPT_TASK3_WORKTREE_CLEAN=$task3_worktree_clean"
  "$runtime_python"
  -B
  -m scripts.spikes.run_continuum_vllm_observation
  --scenario "$scenario"
  --run-id "$run_id"
  --model "$model"
  --model-revision "$model_revision"
  --tokenizer "$tokenizer"
  --tokenizer-revision "$tokenizer_revision"
  --output-dir "$output_dir"
  --observer-mode "$observer_mode"
  --gpu-memory-utilization "$gpu_memory_utilization"
  --vllm-metal-source-checkout "$vllm_metal_source_checkout"
)

for option_name in pressure_request_count pressure_prompt_tokens max_tokens; do
  option_value=${!option_name}
  if [[ -n "$option_value" ]]; then
    command+=("--${option_name//_/-}" "$option_value")
  fi
done

run_directory="$output_dir/$run_id"
commands_path="$run_directory/commands.txt"
stderr_path="$run_directory/stderr.log"

if [[ "$dry_run" == true ]]; then
  print_command "$stderr_path" "${command[@]}"
  exit 0
fi

[[ ! -e "$run_directory" && ! -L "$run_directory" ]] || \
  die "run directory must not already exist"
mkdir -- "$run_directory"
(
  umask 077
  print_command "$stderr_path" "${command[@]}" >"$commands_path"
  : >"$stderr_path"
)

exec "${command[@]}" 2>"$stderr_path"
