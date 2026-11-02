import json

import pytest

from qualfy.cli.scaffold import create_project, slugify
from qualfy.core.config import load_config


def test_new_project_layout(tmp_path):
    target = tmp_path / "My Shop E2E"
    written = create_project(target, git=False)
    names = {p.relative_to(target).as_posix() for p in written}
    assert {"qualfy.yaml", "CLAUDE.md", ".claude/settings.json", ".mcp.json", ".gitignore",
            "package.json", "playwright.config.ts", "pages/BasePage.ts", "fixtures/index.ts",
            "specs/EXAMPLE-1.md", ".env.example", "tests/.gitkeep"} <= names

    settings = json.loads((target / ".claude" / "settings.json").read_text())
    assert settings["attribution"] == {"commit": "", "pr": ""}
    assert json.loads((target / "package.json").read_text())["name"] == "my-shop-e2e"
    assert "My Shop E2E" in (target / "CLAUDE.md").read_text()
    assert "${process.env" not in (target / "playwright.config.ts").read_text()

    config = load_config(target / "qualfy.yaml")
    assert config.name == "my-shop-e2e"
    assert config.projects["default"].agent == "claude"


def test_new_refuses_non_empty_dir(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "file").write_text("")
    with pytest.raises(FileExistsError):
        create_project(tmp_path / "x", git=False)
    create_project(tmp_path / "x", git=False, force=True)


def test_git_init(tmp_path):
    import shutil

    if not shutil.which("git"):
        pytest.skip("git not installed")
    create_project(tmp_path / "repo")
    assert (tmp_path / "repo" / ".git").is_dir()


@pytest.mark.parametrize("name, slug", [("My Project", "my-project"), ("--", "qualfy-project"),
                                        ("shop_e2e.v2", "shop-e2e-v2")])
def test_slugify(name, slug):
    assert slugify(name) == slug
