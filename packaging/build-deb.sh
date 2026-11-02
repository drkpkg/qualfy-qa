#!/usr/bin/env bash
# Build the qualfy-qa .deb from the working tree inside an Ubuntu container.
# Usage: packaging/build-deb.sh [ubuntu-release] [--nocheck] [--no-lintian]
#   ubuntu-release: docker tag of ubuntu (default 24.04; the noble build installs on 24.04+)
# Output: dist/qualfy-qa_<version>_all.deb (+ .buildinfo/.changes)
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
release=24.04
build_opts=""
lintian=1
for arg in "$@"; do
  case $arg in
    --nocheck) build_opts="nocheck"; profiles="nocheck" ;;
    --no-lintian) lintian=0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) release=$arg ;;
  esac
done

mkdir -p "$root/dist"
tarball=$("$root/packaging/make-tarball.sh" "$root/dist")

docker run --rm -i \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -e DEB_BUILD_OPTIONS="$build_opts" -e DEB_BUILD_PROFILES="${profiles:-}" \
  -e LINTIAN="$lintian" -e DEBIAN_FRONTEND=noninteractive \
  -v "$tarball:/src.tar.gz:ro" \
  -v "$root/dist:/out" \
  "ubuntu:$release" bash -euo pipefail -s <<'IN_CONTAINER'
apt-get update -qq || {
  # EOL releases move to old-releases.ubuntu.com
  sed -i -E 's#https?://(archive|security|ports)\.ubuntu\.com/ubuntu(-ports)?#http://old-releases.ubuntu.com/ubuntu#' \
    /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
  apt-get update -qq
}
apt-get install -y -qq --no-install-recommends build-essential >/dev/null
mkdir -p /build && tar -xzf /src.tar.gz -C /build
cd /build/qualfy-qa-*
apt-get build-dep -y -qq ${DEB_BUILD_PROFILES:+-P "$DEB_BUILD_PROFILES"} ./ >/dev/null
dpkg-buildpackage -us -uc -b
cd /build
deb=$(ls qualfy-qa_*_all.deb)
echo "== $deb"; dpkg-deb -I "$deb"; dpkg-deb -c "$deb"
if [[ $LINTIAN == 1 ]]; then
  apt-get install -y -qq --no-install-recommends lintian >/dev/null
  echo "== lintian"; lintian "$deb" || true
fi
install -m644 -o "$HOST_UID" -g "$HOST_GID" qualfy-qa_*_all.deb qualfy-qa_*.buildinfo qualfy-qa_*.changes /out/
IN_CONTAINER
ls -1 "$root"/dist/*.deb
