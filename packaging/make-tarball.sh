#!/usr/bin/env bash
# Create dist/qualfy-qa-<version>.tar.gz from the working tree, laid out like GitHub's
# archive/refs/tags/v<version>.tar.gz (top-level dir qualfy-qa-<version>/).
# Includes tracked + untracked-but-not-ignored files, so it works before the first commit.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
version=$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml | head -n1)
name=qualfy-qa
out=${1:-$root/dist}
mkdir -p "$out"
tarball="$out/$name-$version.tar.gz"

git ls-files -z --cached --others --exclude-standard \
  | while IFS= read -r -d '' f; do [[ -e $f ]] && printf '%s\0' "$f"; done \
  | tar --null --files-from=- --sort=name --owner=0 --group=0 --numeric-owner \
        --mtime='2000-01-01 00:00Z' --transform "s|^|$name-$version/|" \
        -czf "$tarball"
echo "$tarball"
