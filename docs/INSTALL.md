# Installing qualfy

qualfy ships as a regular distro package that uses only distro Python libraries (PyYAML,
httpx, rich, optionally textual and keyring), so no virtualenv or pip is involved.

| Platform | Package | Interactive TUI |
| --- | --- | --- |
| Arch Linux / Manjaro | AUR `qualfy-qa` or release `.pkg.tar.zst` | yes |
| Ubuntu 26.04, 25.10, 25.04 | release `.deb` | yes (python3-textual 2.1) |
| Ubuntu 24.04 | release `.deb` | no: textual in noble is too old, qualfy uses plain prompts |

Release assets are at <https://github.com/drkpkg/qualfy-qa/releases>; verify them against
`SHA256SUMS`:

```bash
sha256sum --check --ignore-missing SHA256SUMS
```

## Arch Linux / Manjaro

From the AUR with any helper:

```bash
yay -S qualfy-qa        # or: paru -S qualfy-qa
```

Or the prebuilt package from a release:

```bash
sudo pacman -U ./qualfy-qa-0.1.2-1-any.pkg.tar.zst
```

Optional extras: `sudo pacman -S --asdeps python-keyring github-cli nodejs npm git`.

## Ubuntu 24.04 – 26.04

One `.deb` works on 24.04 (noble), 25.04 (plucky), 25.10 (questing) and 26.04 (resolute):

```bash
sudo apt install ./qualfy-qa_0.1.2-1_all.deb
```

Use `apt install ./file.deb` (not `dpkg -i`) so the dependencies are pulled in. It depends on
`python3-yaml`, `python3-httpx` and `python3-rich`, recommends `python3-textual (>= 2.1)`,
`python3-keyring` and `git`, and suggests `gh`, `nodejs` and `npm`.

On **24.04** the `python3-textual` in the archive (0.1.x) does not satisfy the recommendation,
so apt skips it and qualfy runs without the full-screen TUI; every command still works with
plain prompts. For the TUI, upgrade to 25.04 or newer. Installing a newer textual with
`pip install --break-system-packages` is not supported.

Remove with `sudo apt remove qualfy-qa`.

## From source with system packages

Prefer the packages above. To run a checkout directly without installing anything into the
system Python:

```bash
# Ubuntu
sudo apt install python3-yaml python3-httpx python3-rich python3-keyring python3-textual  # textual: 25.04+
# Arch
sudo pacman -S python-yaml python-httpx python-rich python-keyring python-textual

git clone https://github.com/drkpkg/qualfy-qa && cd qualfy-qa
PYTHONPATH=src python3 -c "from qualfy.cli.main import main; main()" --version
```

To build the distro packages yourself (needs docker):

```bash
packaging/build-deb.sh 24.04          # -> dist/qualfy-qa_<ver>-1_all.deb
packaging/test-install.sh             # installs it on ubuntu 24.04/25.04/25.10/26.04 containers
packaging/build-arch.sh               # -> dist/qualfy-qa-<ver>-1-any.pkg.tar.zst
```

`python3 -m pip install --no-deps --break-system-packages .` also works but bypasses the package
manager (no clean uninstall, can be shadowed or broken by distro upgrades); it is not
recommended.

For development, use `uv sync` and `uv run qualfy` (see the README).

## Prerequisites for running tests with an agent

qualfy itself only orchestrates; the agent and integrations are external tools.

- **Claude Code** (`claude`), the agent that writes and runs the tests. It is not in the
  Ubuntu archive. Install it with Anthropic's installer or npm, then log in once:

  ```bash
  curl -fsSL https://claude.ai/install.sh | bash      # or: npm install -g @anthropic-ai/claude-code
  claude                                               # complete login
  ```

  On Arch it is also in the AUR as `claude-code`.

- **GitHub CLI** (`gh`) for the GitHub issues source/comment sink: `sudo apt install gh` /
  `sudo pacman -S github-cli`, then `gh auth login`.
- **git**, used to work in the target test repository.
- **Node.js + npm** for Playwright test projects: `sudo apt install nodejs npm` /
  `sudo pacman -S nodejs npm`; then `npx playwright install --with-deps` inside the test
  repository.
- **Secrets**: with `python3-keyring` / `python-keyring` installed, API tokens are stored in the
  system keyring; otherwise use environment variables.
