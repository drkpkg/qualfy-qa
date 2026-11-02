# Arch Linux / AUR packaging

`PKGBUILD` builds `qualfy-qa` from the GitHub tag tarball
(`https://github.com/drkpkg/qualfy-qa/archive/refs/tags/v$pkgver.tar.gz`) with
`python-build` + `python-installer` + `python-hatchling`. Runtime dependencies are all in
`extra`; `claude-code` (AUR) is an optdepend because the agent CLI is installed separately.

## Build and test from the working tree (before a tag exists)

```bash
packaging/build-arch.sh            # archlinux:latest container: makepkg as non-root, namcap, pacman -U, smoke test
packaging/build-arch.sh --nocheck  # skip check()
```

Without docker, on an Arch host:

```bash
packaging/make-tarball.sh packaging/arch   # writes packaging/arch/qualfy-qa-<ver>.tar.gz
cd packaging/arch
makepkg -si --skipchecksums                # makepkg uses the local file instead of downloading
```

This works because the tarball has the same name (`qualfy-qa-<ver>.tar.gz`) and layout
(`qualfy-qa-<ver>/`) as the `source=()` entry, and makepkg only downloads sources that are not
already present. `--skipchecksums` is needed because the checksum in the PKGBUILD is for the
GitHub tarball. If `python` resolves to a pyenv/conda shim, run makepkg with
`env PATH=/usr/bin:/bin makepkg ...` so the system Python (with python-hatchling) is used. Clean up with `rm -rf src pkg *.tar.gz *.pkg.tar.zst`.

## Publishing to the AUR

One-time setup: an AUR account with your SSH public key, then

```bash
git clone ssh://aur@aur.archlinux.org/qualfy-qa.git aur-qualfy-qa   # empty repo on first push
```

For every release (after the `vX.Y.Z` tag is pushed and the GitHub Release exists):

```bash
cd aur-qualfy-qa
cp ../qualfy-qa/packaging/arch/PKGBUILD .
# set pkgver=X.Y.Z and pkgrel=1 (bump only pkgrel for packaging-only changes)
updpkgsums                          # downloads the tag tarball, replaces sha256sums=('SKIP')
makepkg -Cf                         # clean build + check() against the real source
namcap PKGBUILD *.pkg.tar.zst
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "Update to X.Y.Z"
git push origin master              # the AUR only accepts the master branch
```

Copy the checksummed `PKGBUILD` and regenerated `.SRCINFO` back into this repo so they stay in
sync. The `.SRCINFO` here is generated with `makepkg --printsrcinfo` and must be regenerated
whenever the PKGBUILD changes.

### namcap notes

- `namcap PKGBUILD` is clean.
- Run `namcap` on the package *after* installing it (as `build-arch.sh` does); before that,
  it reports the package's own `qualfy.*` modules as "uninstalled dependencies".

## Release `.pkg.tar.zst`

The release workflow (`.github/workflows/release.yml`) builds the package in `archlinux:latest`
from the tagged tree and attaches `qualfy-qa-<ver>-<rel>-any.pkg.tar.zst` to the GitHub
Release, installable with `sudo pacman -U`.
