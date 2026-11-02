#!/usr/bin/env bash
# Install a built .deb in fresh Ubuntu containers and smoke-test it.
# Usage: packaging/test-install.sh [path/to/qualfy-qa_*.deb] [ubuntu-tag...]
#   default tags: 24.04 25.04 25.10 26.04
# Env: STRICT=0 to only report failures of `qualfy --version` without failing the run.
set -uo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
deb=${1:-}
[[ -n $deb ]] && shift || deb=$(ls -t "$root"/dist/qualfy-qa_*_all.deb 2>/dev/null | head -n1)
[[ -f $deb ]] || { echo "no .deb found (build one with packaging/build-deb.sh)" >&2; exit 2; }
deb=$(realpath "$deb")
tags=("$@")
[[ ${#tags[@]} -gt 0 ]] || tags=(24.04 25.04 25.10 26.04)

declare -A result
for tag in "${tags[@]}"; do
  echo "=================== ubuntu:$tag"
  if ! docker pull -q "ubuntu:$tag" >/dev/null 2>&1; then
    result[$tag]="MISSING (no ubuntu:$tag on Docker Hub)"; continue
  fi
  docker run --rm -i -e DEBIAN_FRONTEND=noninteractive -e STRICT="${STRICT:-1}" \
    -v "$deb:/tmp/$(basename "$deb"):ro" "ubuntu:$tag" bash -uo pipefail -s <<'IN_CONTAINER'
. /etc/os-release; echo "$PRETTY_NAME"
apt-get update -qq 2>/dev/null || {
  echo "(EOL release: switching to old-releases.ubuntu.com)"
  sed -i -E 's#https?://(archive|security|ports)\.ubuntu\.com/ubuntu(-ports)?#http://old-releases.ubuntu.com/ubuntu#' \
    /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null
  apt-get update -qq || exit 10
}
apt-get install -y -qq /tmp/qualfy-qa_*_all.deb >/tmp/apt.log 2>&1 || { cat /tmp/apt.log; exit 11; }
dpkg-query -W -f='${Package} ${Version}\n' qualfy-qa python3 python3-yaml python3-httpx python3-rich \
  python3-textual python3-keyring 2>/dev/null
rc=0
echo "-- python3 -c 'import qualfy'"
python3 -c "import qualfy; print(qualfy.__version__, qualfy.__file__)" || rc=12
echo "-- app.tcss"
python3 -c "from importlib.resources import files; assert files('qualfy.tui').joinpath('app.tcss').is_file(); print('ok')" || rc=13
echo "-- qualfy --version"
if ! qualfy --version; then
  [[ $STRICT == 1 ]] && rc=14 || echo "(qualfy --version failed; STRICT=0 so not fatal)"
fi
exit $rc
IN_CONTAINER
  rc=$?
  case $rc in
    0) result[$tag]=PASS ;;
    10) result[$tag]="FAIL (apt-get update)" ;;
    11) result[$tag]="FAIL (dependencies did not resolve)" ;;
    12) result[$tag]="FAIL (import qualfy)" ;;
    13) result[$tag]="FAIL (app.tcss missing)" ;;
    14) result[$tag]="FAIL (qualfy --version)" ;;
    *) result[$tag]="FAIL (exit $rc)" ;;
  esac
done

echo "=================== summary: $(basename "$deb")"
fail=0
for tag in "${tags[@]}"; do
  printf '  ubuntu:%-6s %s\n' "$tag" "${result[$tag]}"
  [[ ${result[$tag]} == FAIL* ]] && fail=1
done
exit $fail
