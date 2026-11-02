<p align="center">
  <img src="assets/icon-256.png" width="128" alt="qualfy">
</p>

<h1 align="center">qualfy</h1>

<p align="center">
  Turn reviewed test tickets into automated Playwright tests with Claude Code.<br>
  GitHub Issues · Jira + Rovo · local specs — Arch Linux and Ubuntu 24.04–26.04 packages, no venv.
</p>

---

A spec ticket becomes a test ticket (written by Rovo, a teammate or Claude). `qualfy` reads it,
asks you what's ambiguous, lets Claude Code write and run the tests in your test repository, and
hands you the results, a draft comment and a pull request to approve.

```bash
qualfy new my-project        # Playwright repo + CLAUDE.md + qualfy.yaml
cd my-project
qualfy connect               # GitHub or Jira, PR host, Claude Code check
qualfy classify              # rank open issues by urgency, write it back
qualfy start shop-42         # analyze → questions → automate → review → PR → comment
```

## How `qualfy start` works

1. **Analyze** — fetches the ticket. If it carries the YAML test contract, the analyzer reviews it;
   if not, Claude derives the cases from the description.
2. **Clarify** — the analyzer returns *typed* questions (`choice`, `multi`, `confirm`, `text`,
   `url`, `secret`, `data`). Each kind renders as its own input, in the TUI or in the terminal.
   Secrets go to the keyring and reach the agent as environment variables, never the spec.
3. **Confirm** — review the answers and the cases in scope, then start.
4. **Automate** — Claude Code works in the test repo: reads `CLAUDE.md`, writes the spec files,
   runs them, classifies failures (`test` / `app` / `env`) and commits to `qa/<KEY>`.
5. **Review** — per-case results and an editable draft comment.
6. **Pull request?** — qualfy pushes the branch and opens the PR when you say so.
7. **Post?** — the comment goes to the issue (and labels move) only after you approve it.

Sessions are saved in `.qualfy/sessions/`; rerun `qualfy start <KEY>` to resume, `--restart` to
start over, `--yes --answer id=value` for CI.

## `qualfy classify`

Ranks open tickets P0–P3 with a reason, impact and whether they are automatable, shows a table,
and writes the result back after you confirm (or edit) it:

- **GitHub** — issues have no native priority, so qualfy uses `priority:P0…P3` labels (created by
  `qualfy connect`) and keeps labels that are already set.
- **Jira** — maps urgency to the Priority field. Tickets whose priority was already changed from
  the default (by a person or a Rovo triage agent) are respected unless you pass `--force`.

Classifiers: `rules` (offline keyword/label heuristics) and `claude` (one structured call).

## Install

| Platform | |
|---|---|
| Arch Linux | `pacman -U qualfy-qa-*.pkg.tar.zst` from the release, or the PKGBUILD in `packaging/arch` |
| Ubuntu 24.04 – 26.04 | `sudo apt install ./qualfy-qa_*_all.deb` from the release |

Runtime dependencies are distro packages only: `python3-yaml`, `python3-httpx`, `python3-rich`,
optional `python3-textual` (TUI, 25.04+ and Arch) and `python3-keyring`. Ubuntu 24.04 ships
Textual 0.1, so there `qualfy start` uses the inline terminal wizard. You also need
[Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`), `git`, `gh` (optional) and
Node.js for the Playwright projects. See [docs/INSTALL.md](docs/INSTALL.md).

## Architecture

```
src/qualfy/
├── core/          UI-agnostic: models + stdlib schema, contract, ports, registry, config,
│                  secrets, events, store, service, session (start), triage (classify)
├── adapters/      sources/ sinks/ agents/ analyzers/ classifiers/ hosts/ + Jira/GitHub/Claude clients
├── cli/           argparse CLI, connect, inline wizard, prompt fields
├── tui/           Textual dashboard + start wizard, forms, brand theme
└── templates/     `qualfy new` project template (Playwright)
```

Front ends only talk to `AutomationService`, `SessionRunner` and `triage`, and every step emits
serializable `Event`s, so a future HTTP API can reuse the core unchanged.

| Slot | Built-in kinds |
|---|---|
| sources | `markdown`, `github-issues`, `jira-rovo` |
| sinks | `json-file`, `github-comment`, `jira-comment` |
| agents | `claude-code`, `dry-run` |
| analyzers | `claude`, `static` |
| classifiers | `claude`, `rules` |
| hosts | `github` |

Third-party adapters register through `qualfy.<slot>` entry points: a class with a `kind`, an
`Options` dataclass and the methods of its port in `qualfy.core.ports`.

### Test ticket contract

```yaml
key: PROJ-123
spec: PROJ-120
cases:
  - id: TC-1
    title: Discount applied above threshold
    priority: high          # low | medium | high | critical
    automatable: true
    preconditions: [User with role salesman]
    data: {customer: ACME}
    steps:
      - Create a quotation with 3 units
      - action: Apply pricelist "Wholesale"
        expected: [Discount line visible]
    expected: [Total is 270]
```

`qualfy schema spec|analysis|report|result` prints the JSON Schemas.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## License

MIT
