<p align="center">
  <img src="assets/icon-256.png" width="128" alt="qualfy">
</p>

<h1 align="center">qualfy</h1>

<p align="center">
  Turn reviewed test tickets into automated Playwright tests with Claude Code.<br>
  Works with GitHub Issues, Jira + Rovo and local specs. Packaged for Arch Linux and Ubuntu 24.04 to 26.04, so you don't need a venv.
</p>

Someone (Rovo, a teammate or Claude) turns a spec ticket into a test ticket. `qualfy` reads that
ticket and asks you about anything ambiguous. Claude Code then writes and runs the tests in your
test repository, and you get the results, a draft comment and a pull request to approve.

```bash
qualfy new my-project        # Playwright repo + CLAUDE.md + qualfy.yaml
cd my-project
qualfy connect               # GitHub or Jira, PR host, Claude Code check
qualfy classify              # rank open issues by urgency, write it back
qualfy start shop-42         # analyze → questions → automate → review → PR → comment
```

## How `qualfy start` works

1. Analyze. qualfy fetches the ticket. If it carries the YAML test contract, the analyzer reviews
   it. Otherwise Claude derives the cases from the description.
2. Clarify. The analyzer returns typed questions (`choice`, `multi`, `confirm`, `text`, `url`,
   `secret`, `data`), and each type gets its own input in the TUI or the terminal. Secrets are
   stored in the keyring and passed to the agent as environment variables; they are never written
   into the spec.
3. Confirm. You check the answers and the cases in scope, then start the run.
4. Automate. Claude Code works in the test repo. It reads `CLAUDE.md`, writes the spec files, runs
   them, sorts failures into `test`, `app` or `env`, and commits to `qa/<KEY>`.
5. Review. You see the result of each case and can edit the draft comment.
6. Pull request. qualfy pushes the branch and opens the PR if you tell it to.
7. Post. The comment goes to the issue, and the labels change, only after you approve it.

Sessions are saved in `.qualfy/sessions/`. Run `qualfy start <KEY>` again to resume, add
`--restart` to start over, or use `--yes --answer id=value` in CI.

## `qualfy classify`

`qualfy classify` gives each open ticket a priority from P0 to P3, with a reason, the expected
impact and whether it can be automated. It shows the results in a table and writes them back once
you confirm or edit them.

- GitHub issues have no built-in priority, so qualfy uses `priority:P0…P3` labels (`qualfy connect`
  creates them). Labels that are already set stay as they are.
- On Jira, urgency maps to the Priority field. If someone (a person or a Rovo triage agent) already
  changed a ticket's priority from the default, qualfy leaves it alone unless you pass `--force`.

There are two classifiers: `rules` (offline keyword and label heuristics) and `claude` (a single
structured call).

## Install

| Platform | |
|---|---|
| Arch Linux | `pacman -U qualfy-qa-*.pkg.tar.zst` from the release, or the PKGBUILD in `packaging/arch` |
| Ubuntu 24.04 to 26.04 | `sudo apt install ./qualfy-qa_*_all.deb` from the release |

All runtime dependencies come from distro packages: `python3-yaml`, `python3-httpx`,
`python3-rich`, and optionally `python3-textual` (for the TUI, on 25.04+ and Arch) and
`python3-keyring`. Ubuntu 24.04 ships Textual 0.1, so `qualfy start` falls back to the inline
terminal wizard there. You also need [Claude Code](https://docs.claude.com/en/docs/claude-code)
(`claude`), `git`, optionally `gh`, and Node.js for the Playwright projects. See
[docs/INSTALL.md](docs/INSTALL.md).

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

The front ends only call `AutomationService`, `SessionRunner` and `triage`. Every step emits a
serializable `Event`, which means an HTTP API could later sit on the same core without changes.

| Slot | Built-in kinds |
|---|---|
| sources | `markdown`, `github-issues`, `jira-rovo` |
| sinks | `json-file`, `github-comment`, `jira-comment` |
| agents | `claude-code`, `dry-run` |
| analyzers | `claude`, `static` |
| classifiers | `claude`, `rules` |
| hosts | `github` |

Third-party adapters register through `qualfy.<slot>` entry points. An adapter is a class with a
`kind`, an `Options` dataclass and the methods of its port in `qualfy.core.ports`.

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
