"""WildScan - the Textual application.

Three screens:
    HomeScreen     workspace picker + live pipeline map (detection census)
    StageScreen    preview -> confirm -> run with streaming log + progress
    ResultsScreen  final components: cameras, measured scale, models, exports

Every scenario the field crew hits maps onto the same flow: an EMPTY folder
shows a pipeline of pending stages and starts at extraction; a MID-CRUISE
workspace opens with done/partial glyphs and the next runnable stage
focused; a FINISHED workspace is a results browser. Detection is pure
artifact census (workspace.py), so the app never guesses.
"""
from __future__ import annotations

import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (Button, DataTable, Footer, Input, Label,
                             ProgressBar, RichLog, Static)

from . import APP_NAME, ORG, TAGLINE, __version__
from .branding import (CSS, FOOTER_NOTE, MIST, OK, SAND, STATUS_COLOR,
                       STATUS_GLYPH, TEAL, WARN, WORDMARK)
from .runner import CommandRunner, LogLine, ProgressUpdate, RunFinished
from .stages import RUNNABLE, build_plan, spec_for
from .workspace import STAGE_ORDER, Workspace


def status_text(status: str, text: str) -> Text:
    colour = STATUS_COLOR.get(status, MIST)
    return Text(f"{STATUS_GLYPH.get(status, '?')} {text}", style=colour)


class HomeScreen(Screen):
    BINDINGS = [
        Binding("enter", "open_stage", "Open stage"),
        Binding("r", "refresh", "Rescan"),
        Binding("c", "components", "Components"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(WORDMARK, id="wordmark")
        yield Static(f"{ORG} · {TAGLINE} · v{__version__}", id="tagline")
        with Vertical(classes="panel"):
            yield Label("Workspace", classes="panel-title")
            yield Input(placeholder="path to a results folder "
                        "(e.g. F:/na156_h2024_v2)", id="workspace-input")
            yield Static("", id="workspace-note")
        with Vertical(classes="panel"):
            yield Label("Pipeline", classes="panel-title")
            table = DataTable(id="pipeline", cursor_type="row")
            table.add_columns("stage", "state", "summary")
            yield table
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        if app.workspace:
            self.query_one("#workspace-input", Input).value = str(app.workspace.root)
            self.refresh_pipeline()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "workspace-input":
            return
        path = Path(event.value).expanduser()
        note = self.query_one("#workspace-note", Static)
        if not path.exists():
            note.update(Text(f"'{path}' does not exist - it will be created "
                             "when the first stage runs", style=WARN))
        else:
            note.update(Text(f"opened {path}", style=OK))
        self.app.workspace = Workspace(path)  # type: ignore[attr-defined]
        self.refresh_pipeline()

    def refresh_pipeline(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        table = self.query_one("#pipeline", DataTable)
        table.clear()
        if not app.workspace:
            return
        statuses = app.workspace.detect()
        for key in STAGE_ORDER:
            st = statuses[key]
            runnable = key in RUNNABLE
            name = Text(st.title, style=SAND if runnable else MIST)
            table.add_row(name, status_text(st.status, st.status),
                          st.summary, key=key)
        # Guide the operator: the first stage that is not done is "next".
        next_key = next((k for k in STAGE_ORDER
                         if statuses[k].status != "done"), None)
        if next_key:
            self.query_one("#workspace-note", Static).update(
                Text(f"Next: {statuses[next_key].title} - "
                     f"{statuses[next_key].summary}", style=TEAL))

    def action_refresh(self) -> None:
        self.refresh_pipeline()

    def action_components(self) -> None:
        if self.app.workspace:  # type: ignore[attr-defined]
            self.app.push_screen(ResultsScreen())

    def action_open_stage(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        table = self.query_one("#pipeline", DataTable)
        if not app.workspace or table.cursor_row is None:
            return
        key = STAGE_ORDER[table.cursor_row]
        if key in RUNNABLE:
            app.push_screen(StageScreen(key))

    def on_data_table_row_selected(self, _event) -> None:
        self.action_open_stage()


class StageScreen(Screen):
    """Ask first, run second: the stage's own declared inputs become the
    form, prefilled from the workspace census and the operator's saved
    answers; the exact command updates live as fields change; Run stays
    disabled until every field validates."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("g", "go", "Run stage"),
        Binding("x", "stop", "Stop"),
    ]

    def __init__(self, stage_key: str) -> None:
        super().__init__()
        self.stage_key = stage_key
        self.runner = CommandRunner(self)
        self.spec = None
        self.plan = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel", id="stage-form-panel"):
            yield Label("", id="stage-title", classes="panel-title")
            yield Static("", id="stage-preview")
            yield Vertical(id="stage-form")
            yield Static("", id="stage-problems")
            yield Static("", id="stage-command")
        with Horizontal(classes="panel"):
            yield Button("Run", id="run", variant="primary")
            yield Button("Stop", id="stop", variant="warning", disabled=True)
            yield ProgressBar(id="stage-progress", total=100, show_eta=False)
            yield Static("", id="stage-eta")
        yield RichLog(id="stage-log", max_lines=2000, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        ws = app.workspace
        assert ws is not None
        self.spec = spec_for(self.stage_key, ws)
        self.query_one("#stage-title", Label).update(
            f"{self.spec.key.upper()}  ·  {ws.root}")
        intro = Text()
        for bullet in self.spec.intro:
            intro.append("  · ", style=TEAL)
            intro.append(bullet + "\n")
        intro.append("  · ", style=TEAL)
        intro.append(f"estimate: {self.spec.estimate}\n", style=MIST)
        self.query_one("#stage-preview", Static).update(intro)

        form = self.query_one("#stage-form", Vertical)
        for f in self.spec.fields:
            label = f.label + ("  *" if f.required else "")
            form.mount(Label(label))
            form.mount(Input(value=f.default, placeholder=f.help or f.label,
                             id=f"field-{f.arg}"))
        self._revalidate()

    # ------------------------------------------------------------- form
    def _values(self) -> dict[str, str]:
        assert self.spec is not None
        return {f.arg: self.query_one(f"#field-{f.arg}", Input).value
                for f in self.spec.fields}

    def _revalidate(self) -> None:
        assert self.spec is not None
        app: WildScanApp = self.app  # type: ignore[assignment]
        values = self._values()
        problems = [p for f in self.spec.fields
                    if (p := f.validate(values.get(f.arg, ""))) is not None]
        problems_widget = self.query_one("#stage-problems", Static)
        if problems:
            problems_widget.update(
                Text("\n".join(f"  ! {p}" for p in problems), style=WARN))
            self.plan = None
            self.query_one("#stage-command", Static).update("")
        else:
            problems_widget.update("")
            self.plan = build_plan(self.stage_key, app.workspace, values)
            self.query_one("#stage-command", Static).update(
                Text(f"$ {self.plan.display_command}", style=MIST))
        self.query_one("#run", Button).disabled = (
            bool(problems) or self.runner.running)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("field-"):
            self._revalidate()

    # ------------------------------------------------------------ actions
    def action_back(self) -> None:
        if not self.runner.running:
            self.app.pop_screen()
            home = self.app.screen
            if isinstance(home, HomeScreen):
                home.refresh_pipeline()

    def action_go(self) -> None:
        self.on_button_pressed(Button.Pressed(self.query_one("#run", Button)))

    def action_stop(self) -> None:
        self.runner.terminate()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        log = self.query_one("#stage-log", RichLog)
        if event.button.id == "run" and not self.runner.running:
            self._revalidate()
            if self.plan is None:
                log.write(Text("fix the highlighted inputs first",
                               style=WARN))
                return
            log.write(Text(f"launching: {self.plan.display_command}",
                           style=TEAL))
            try:
                self.runner.start(self.plan)
            except (OSError, RuntimeError) as exc:
                log.write(Text(f"launch failed: {exc}", style="bold red"))
                return
            self.query_one("#run", Button).disabled = True
            self.query_one("#stop", Button).disabled = False
        elif event.button.id == "stop":
            self.runner.terminate()

    def on_log_line(self, message: LogLine) -> None:
        self.query_one("#stage-log", RichLog).write(message.line)

    def on_progress_update(self, message: ProgressUpdate) -> None:
        bar = self.query_one("#stage-progress", ProgressBar)
        bar.update(progress=message.fraction * 100)
        eta_min = message.eta_s / 60
        self.query_one("#stage-eta", Static).update(
            Text(f" op {message.op} · eta {eta_min:5.1f} min", style=MIST))

    def on_run_finished(self, message: RunFinished) -> None:
        log = self.query_one("#stage-log", RichLog)
        ok = message.returncode == 0
        log.write(Text(f"finished with exit code {message.returncode}",
                       style=OK if ok else "bold red"))
        self.query_one("#stop", Button).disabled = True
        self.query_one("#stage-progress", ProgressBar).update(
            progress=100 if ok else 0)
        self._revalidate()


class ResultsScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Label("Final components", classes="panel-title")
            table = DataTable(id="components", cursor_type="row")
            table.add_columns("component", "cameras", "scale", "verdict",
                              "model", "exports")
            yield table
        with VerticalScroll(classes="panel"):
            yield Static("", id="results-note")
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        ws = app.workspace
        assert ws is not None
        table = self.query_one("#components", DataTable)
        for c in ws.components():
            scale = "-" if c.scale is None else f"{c.scale:.3f}"
            verdict = c.scale_status or "-"
            verdict_style = OK if verdict == "pass" else (
                WARN if verdict in ("", "-") else "bold red")
            model = (f"done ({c.model_minutes:.0f} min)"
                     if c.modelled and c.model_minutes else
                     ("done" if c.modelled else "-"))
            table.add_row(
                Text(c.key, style=SAND),
                f"{c.cameras:,}" if c.cameras else "-",
                scale, Text(verdict, style=verdict_style),
                Text(model, style=OK if c.modelled else MIST),
                ", ".join(c.exported) or "-")
        merge = ws.latest_merge()
        gate = (merge / "EVALUATION_READY.txt") if merge else None
        note = self.query_one("#results-note", Static)
        if gate and gate.is_file():
            note.update(Text(gate.read_text(encoding="utf-8", errors="replace"),
                             style=MIST))

    def action_back(self) -> None:
        self.app.pop_screen()


class WildScanApp(App):
    TITLE = f"{APP_NAME} · {ORG}"
    CSS = CSS

    def __init__(self, workspace: str | None = None) -> None:
        super().__init__()
        self.workspace: Workspace | None = (
            Workspace(workspace) if workspace else None)

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


def main() -> int:
    workspace = sys.argv[1] if len(sys.argv) > 1 else None
    WildScanApp(workspace).run()
    return 0
