import pytest

from qualfy import tui

pytestmark = pytest.mark.skipif(not tui.available(), reason=tui.unavailable_reason()
                                if not tui.available() else "")


async def test_dashboard_browse_and_run(service):
    from textual.widgets import DataTable, OptionList, Static

    from qualfy.tui.app import DashboardApp

    app = DashboardApp(service)
    async with app.run_test(size=(160, 45)) as pilot:
        await app.workers.wait_for_complete()
        specs = app.query_one("#specs", OptionList)
        assert specs.option_count == 1
        specs.focus()
        specs.highlighted = 0
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.spec is not None and app.query_one("#cases", DataTable).row_count == 3
        assert app.theme == "qualfy"

        await pilot.press("a")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "skipped" in str(app.query_one("#status", Static).render())


async def test_start_wizard(service):
    from textual.widgets import Button, ContentSwitcher, SelectionList, TextArea

    from qualfy.core.models import SessionState
    from qualfy.core.session import SessionRunner
    from qualfy.tui.forms import QuestionField
    from qualfy.tui.start import StartApp

    class Sink:
        kind, interactive = "fake", True

        def __init__(self):
            self.posted = []

        def draft(self, spec, result):
            return "draft body"

        async def publish(self, spec, result, body):
            self.posted.append(body)
            return "posted-url"

    sink = Sink()
    service.project().sinks["tracker"] = sink
    runner = SessionRunner.open(service, "EXAMPLE-1")
    app = StartApp(runner)
    async with app.run_test(size=(140, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        steps = app.query_one("#steps", ContentSwitcher)
        assert steps.current == "clarify"
        fields = {f.question.id: f for f in app.query(QuestionField)}
        assert type(fields["scope"]).__name__ == "MultiQuestion"
        assert type(fields["test_password"]).__name__ == "SecretQuestion"
        fields["scope"].query_one(SelectionList).deselect("TC-2")

        app.query_one("#to-confirm", Button).press()
        await pilot.pause()
        assert steps.current == "confirm"
        assert [c.id for c in runner.spec.automatable_cases] == ["TC-1"]

        app.query_one("#start", Button).press()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert steps.current == "review" and runner.state == SessionState.AUTOMATED
        assert app.query_one("#pr", Button).disabled  # dry run: nothing automated, no host
        area = app.query_one("#draft-0", TextArea)
        area.text = "edited draft"

        app.query_one("#post", Button).press()
        await pilot.pause()
        await pilot.click("#ok")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert sink.posted == ["edited draft"]
        assert app.query_one("#post", Button).disabled

        app.query_one("#finish", Button).press()
        await pilot.pause()
    assert runner.state == SessionState.DONE
