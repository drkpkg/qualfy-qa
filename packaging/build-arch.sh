#!/usr/bin/env bash
# Build the Arch package from the working tree inside archlinux:latest (makepkg as a
# non-root user), lint it with namcap, install it with pacman -U and smoke-test it.
# Usage: packaging/build-arch.sh [--nocheck] [--no-install]
# Output: dist/qualfy-qa-<ver>-<rel>-any.pkg.tar.zst
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
image=${ARCH_IMAGE:-archlinux:latest}
makepkg_args=()
install_test=1
for arg in "$@"; do
  case $arg in
    --nocheck) makepkg_args+=(--nocheck) ;;
    --no-install) install_test=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$root/dist"
tarball=$("$root/packaging/make-tarball.sh" "$root/dist")

docker run --rm -i \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -e MAKEPKG_ARGS="${makepkg_args[*]:-}" -e INSTALL_TEST="$install_test" \
  -v "$root/packaging/arch:/pkgbuild:ro" \
  -v "$tarball:/src/$(basename "$tarball"):ro" \
  -v "$root/dist:/out" \
  "$image" bash -euo pipefail -s <<'IN_CONTAINER'
pacman -Syu --noconfirm --needed base-devel namcap >/dev/null
# Resolve depends/makedepends/checkdepends from the PKGBUILD itself.
source /pkgbuild/PKGBUILD
pacman -S --noconfirm --needed "${depends[@]}" "${makedepends[@]}" "${checkdepends[@]}" >/dev/null

useradd -m builder
install -d -o builder /build
install -m644 -o builder /pkgbuild/PKGBUILD /build/
# makepkg uses a local file named like the source entry instead of downloading it.
install -m644 -o builder /src/*.tar.gz /build/
cd /build
su builder -c "makepkg --skipchecksums --noconfirm ${MAKEPKG_ARGS}"

pkg=$(ls /build/*.pkg.tar.zst)
echo "== namcap PKGBUILD"; namcap PKGBUILD || true
echo "== contents"; pacman -Qlp "$pkg" | grep -E 'bin/|app\.tcss|dist-info/(METADATA|entry_points)|share/'
install -m644 -o "$HOST_UID" -g "$HOST_GID" "$pkg" /out/

if [[ $INSTALL_TEST != 1 ]]; then
  echo "== namcap $(basename "$pkg")"; namcap "$pkg" || true
else
  pacman -U --noconfirm "$pkg" >/dev/null
  # After install, so namcap can resolve the package's own modules via pacman -Qo.
  echo "== namcap $(basename "$pkg")"; namcap "$pkg" || true
  rc=0
  echo "== qualfy --version"; qualfy --version || rc=1
  echo "== import qualfy"; python -c "import qualfy, sys; print(qualfy.__version__)" || rc=1
  echo "== app.tcss"; python -c "from importlib.resources import files; assert files('qualfy.tui').joinpath('app.tcss').is_file(); print('ok')" || rc=1
  exit $rc
fi
IN_CONTAINER
ls -1 "$root"/dist/*.pkg.tar.zst
