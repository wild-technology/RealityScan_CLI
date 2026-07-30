"""WildScan - the Wild Technology user interaction portal.

RC_Main's flow, kept faithfully, as screens:

    SessionScreen    expedition / dive / data location / results root,
                     with live raw-data detection and the results layout
    StagePickScreen  the RC_Main checkbox - stages in order, resume-aware
                     pre-selection (done stages start unticked)
    WizardScreen     ONE question at a time, in module order, each
                     parameter's own description as the prompt
    SummaryScreen    the parameter printout, then Run
    RunScreen        sequential stage commands with live log + progress and
                     a press-enter gate between stages (unless Continue
                     Automatically)
    StatusScreen     the pipeline census + final-components browser

The portal never touches data handling: chained modules run in one main.py
invocation (their in-process hand-off IS the pipeline), post stages run the
canonical drivers, and every answer round-trips through rs_settings.json so
the last run becomes the next run's defaults.
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
                             ProgressBar, RichLog, SelectionList, Static)
from textual.widgets.selection_list import Selection

from . import APP_NAME, ORG, TAGLINE, __version__
from .branding import (CSS, MIST, OK, SAND, STATUS_COLOR, STATUS_GLYPH, TEAL,
                       WARN, WORDMARK)
from .runner import CommandRunner, LogLine, ProgressUpdate, RunFinished
from .session import (ALL_STAGES, Session, build_commands, build_questions,
                      default_enabled, default_session, export_names_file,
                      prepare_results_root, save_last_run, scan_raw_data)
from .workspace import STAGE_TITLES, Workspace


def status_text(status: str, text: str) -> Text:
    colour = STATUS_COLOR.get(status, MIST)
    return Text(f"{STATUS_GLYPH.get(status, '?')} {text}", style=colour)


class SessionScreen(Screen):
    """Question order exactly as the pipeline has always asked: who and
    where, before anything else."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Static(WORDMARK, id="wordmark")
        yield Static(f"{ORG} · {TAGLINE} · v{__version__}", id="tagline")
        with VerticalScroll(classes="panel"):
            yield Label("Session", classes="panel-title")
            yield Label("Expedition (e.g. NA156)")
            yield Input(id="s-expedition")
            yield Label("Dive (e.g. H2024)")
            yield Input(id="s-dive")
            yield Label("Raw data — Cruise Dive Folder (video + nav as "
                        "delivered)")
            yield Input(id="s-cruise")
            yield Label("Raw data — Raw Images (folder of stills)")
            yield Input(id="s-rawimages")
            yield Label("Raw data — Video (specific survey video)")
            yield Input(id="s-video")
            yield Label("Processed Data (ROVDataConcat already run — "
                        "datatables — but no zones yet)")
            yield Input(id="s-processed")
            yield Label("Results root (created if missing; the pipeline "
                        "builds its structure inside)")
            yield Input(id="s-results")
            yield Static("", id="s-detect")
            yield Button("Continue", id="s-continue", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        s = app.session
        self.query_one("#s-expedition", Input).value = s.expedition
        self.query_one("#s-dive", Input).value = s.dive
        self.query_one("#s-cruise", Input).value = s.cruise_folder
        self.query_one("#s-rawimages", Input).value = s.raw_images_dir
        self.query_one("#s-video", Input).value = s.video_path
        self.query_one("#s-processed", Input).value = s.processed_data
        self.query_one("#s-results", Input).value = s.results_root
        self._refresh_detection()

    def _pull(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        s = app.session
        s.expedition = self.query_one("#s-expedition", Input).value.strip()
        s.dive = self.query_one("#s-dive", Input).value.strip()
        s.cruise_folder = self.query_one("#s-cruise", Input).value.strip()
        s.raw_images_dir = self.query_one("#s-rawimages", Input).value.strip()
        s.video_path = self.query_one("#s-video", Input).value.strip()
        s.processed_data = self.query_one("#s-processed", Input).value.strip()
        s.results_root = self.query_one("#s-results", Input).value.strip()

    def _refresh_detection(self) -> None:
        from .session import scan_cameras, scan_processed_data
        app: WildScanApp = self.app  # type: ignore[assignment]
        self._pull()
        s = app.session
        text = Text()
        if s.cruise_folder:
            app.scan = scan_raw_data(s.cruise_folder)
            text.append("Cruise folder:\n", style=SAND)
            for line in app.scan.summary_lines():
                text.append("  · ", style=TEAL)
                text.append(line + "\n")
        if s.raw_images_dir:
            cams = scan_cameras(s.raw_images_dir)
            text.append("Raw images — camera identification:\n", style=SAND)
            for line in cams.summary_lines() or ["no imagery found there"]:
                style = WARN if line.startswith("UNRECOGNISED") else TEAL
                text.append("  · ", style=style)
                text.append(line + "\n")
        if s.processed_data:
            processed = scan_processed_data(s.processed_data)
            text.append("Processed data:\n", style=SAND)
            if processed["datatables"]:
                text.append("  · ", style=TEAL)
                text.append(f"ROVDataConcat output: "
                            f"{processed['datatables'][0].name}\n")
            if processed["utm_logs"]:
                text.append("  · ", style=TEAL)
                text.append(f"georeferenced log: "
                            f"{processed['utm_logs'][0].name}\n")
            if not (processed["datatables"] or processed["utm_logs"]):
                text.append("  · ", style=WARN)
                text.append("no datatables found there\n")
        if s.results_root:
            text.append("\nResults structure (pipeline-created):\n",
                        style=SAND)
            for name, desc in (
                    ("raw_images/", "imagery"),
                    ("batched_images_by_zone/", "zones"),
                    ("aligned_components/", "components"),
                    ("merged/ · exports/ · RC_projects/", "deliverables")):
                text.append(f"  {name:32s}", style=MIST)
                text.append(desc + "\n", style=MIST)
        self.query_one("#s-detect", Static).update(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in ("s-cruise", "s-rawimages", "s-processed",
                              "s-video"):
            self._refresh_detection()
        elif event.input.id in ("s-expedition", "s-dive"):
            app: WildScanApp = self.app  # type: ignore[assignment]
            self._pull()
            results = self.query_one("#s-results", Input)
            if app.session.label and not results.value.strip():
                results.value = app.session.suggested_results_root(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "s-continue":
            return
        app: WildScanApp = self.app  # type: ignore[assignment]
        self._pull()
        s = app.session
        if not s.results_root:
            self.query_one("#s-detect", Static).update(
                Text("a results root is required", style=WARN))
            return
        prepare_results_root(s)
        s.enabled = default_enabled(s.workspace())
        app.push_screen(StagePickScreen())


class StagePickScreen(Screen):
    """RC_Main's checkbox, verbatim in spirit: arrow keys to move, space to
    select, enter to confirm."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "confirm", "Confirm", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Label("Select stages to run (arrow keys to move, space to "
                        "select, enter to confirm)", classes="panel-title")
            yield SelectionList(id="stage-pick")
            yield Static("", id="pick-note")
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        ws = app.session.workspace()
        statuses = ws.detect()
        picker = self.query_one("#stage-pick", SelectionList)
        for key in ALL_STAGES:
            st = statuses.get(key)
            note = f" - {st.summary}" if st and st.summary else ""
            picker.add_option(Selection(
                f"{STAGE_TITLES.get(key, key)}{note}", key,
                key in app.session.enabled))
        done = [STAGE_TITLES[k] for k in ALL_STAGES
                if statuses.get(k) and statuses[k].status == "done"]
        if done:
            self.query_one("#pick-note", Static).update(
                Text("already done (unticked): " + ", ".join(done),
                     style=MIST))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_confirm(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        picker = self.query_one("#stage-pick", SelectionList)
        app.session.enabled = [k for k in ALL_STAGES
                               if k in picker.selected]
        if not app.session.enabled:
            self.query_one("#pick-note", Static).update(
                Text("select at least one stage", style=WARN))
            return
        app.questions = build_questions(app.session, app.scan)
        if app.questions:
            app.push_screen(WizardScreen())
        else:
            app.push_screen(SummaryScreen())


class WizardScreen(Screen):
    """One question at a time - the parameter's own description, prefilled
    from detection, then the last run, then the module default."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Label("", id="w-progress", classes="panel-title")
            yield Static("", id="w-stage")
            yield Label("", id="w-prompt")
            yield Input(id="w-answer")
            yield Static("", id="w-problem")
            with Horizontal():
                yield Button("Back", id="w-back")
                yield Button("Next", id="w-next", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._show()

    def _question(self):
        app: WildScanApp = self.app  # type: ignore[assignment]
        return app.questions[self.index]

    def _show(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        q = self._question()
        total = len(app.questions)
        self.query_one("#w-progress", Label).update(
            f"Question {self.index + 1} of {total}")
        self.query_one("#w-stage", Static).update(
            Text(STAGE_TITLES.get(q.stage,
                                  "Camera identification"
                                  if q.stage == "cameras" else q.stage),
                 style=TEAL))
        self.query_one("#w-prompt", Label).update(
            q.prompt + ("  *" if q.required else ""))
        answer = self.query_one("#w-answer", Input)
        answer.value = app.session.answers.get(q.arg, q.default)
        self.query_one("#w-problem", Static).update("")
        answer.focus()

    def _commit_and(self, delta: int) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        q = self._question()
        value = self.query_one("#w-answer", Input).value
        if delta > 0:
            problem = q.validate(value)
            if problem:
                self.query_one("#w-problem", Static).update(
                    Text(f"! {problem}", style=WARN))
                return
        app.session.answers[q.arg] = value.strip()
        self.index += delta
        if self.index < 0:
            self.app.pop_screen()
        elif self.index >= len(app.questions):
            app.push_screen(SummaryScreen())
        else:
            self._show()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "w-answer":
            self._commit_and(+1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "w-next":
            self._commit_and(+1)
        elif event.button.id == "w-back":
            self._commit_and(-1)

    def action_back(self) -> None:
        self._commit_and(-1)


class SummaryScreen(Screen):
    """RC_Main printed 'Parameters:' before running - same, plus the gate
    style choice, then Run."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel"):
            yield Label("Parameters", classes="panel-title")
            yield Static("", id="sum-params")
            yield Label("Continue automatically between stages? (true/false)")
            yield Input(id="sum-auto")
            yield Button("Run", id="sum-run", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        s = app.session
        text = Text()
        text.append(f"  expedition_dive: {s.label or '(unset)'}\n")
        text.append(f"  cruise folder:   {s.cruise_folder or '(unset)'}\n")
        text.append(f"  raw images:      {s.raw_images_dir or '(unset)'}\n")
        text.append(f"  video:           {s.video_path or '(unset)'}\n")
        text.append(f"  processed data:  {s.processed_data or '(unset)'}\n")
        text.append(f"  results root:    {s.results_root}\n")
        text.append(f"  stages:          "
                    f"{', '.join(STAGE_TITLES.get(k, k) for k in s.enabled)}\n\n")
        for q in app.questions:
            text.append(f"  {q.arg:24s} {s.answers.get(q.arg, '')}\n",
                        style=MIST)
        self.query_one("#sum-params", Static).update(text)
        self.query_one("#sum-auto", Input).value = (
            "true" if s.continue_automatically else "false")

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "sum-run":
            return
        app: WildScanApp = self.app  # type: ignore[assignment]
        app.session.continue_automatically = (
            self.query_one("#sum-auto", Input).value.strip().lower() == "true")
        save_last_run(app.session)     # the next session's defaults
        app.push_screen(RunScreen())


class RunScreen(Screen):
    """Stages in sequence; between stages, a gate - RC_Main's 'Press enter
    to continue...' - unless Continue Automatically."""

    BINDINGS = [
        Binding("enter", "gate", "Continue", priority=True),
        Binding("x", "stop", "Stop stage"),
        Binding("escape", "leave", "Status"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.runner = CommandRunner(self)
        self.commands = []
        self.current = -1
        self.waiting_gate = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Label("", id="r-title", classes="panel-title")
            yield Static("", id="r-gate")
            with Horizontal():
                yield Button("Continue", id="r-continue", variant="primary",
                             disabled=True)
                yield Button("Stop stage", id="r-stop", variant="warning",
                             disabled=True)
                yield ProgressBar(id="r-progress", total=100, show_eta=False)
                yield Static("", id="r-eta")
        yield RichLog(id="r-log", max_lines=3000, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        if "export" in app.session.enabled:
            export_names_file(app.session)
        self.commands = build_commands(app.session)
        self._advance()

    def _advance(self) -> None:
        self.current += 1
        log = self.query_one("#r-log", RichLog)
        if self.current >= len(self.commands):
            self.query_one("#r-title", Label).update("All stages finished")
            self.query_one("#r-gate", Static).update(
                Text("Esc for the pipeline status view.", style=OK))
            self.query_one("#r-continue", Button).disabled = True
            return
        cmd = self.commands[self.current]
        self.query_one("#r-title", Label).update(
            f"Stage {self.current + 1} of {len(self.commands)}: {cmd.stage}")
        log.write(Text(f"launching: {cmd.display}", style=TEAL))
        try:
            self.runner.start(cmd)
        except (OSError, RuntimeError) as exc:
            log.write(Text(f"launch failed: {exc}", style="bold red"))
            return
        self.query_one("#r-stop", Button).disabled = False
        self.query_one("#r-continue", Button).disabled = True
        self.query_one("#r-gate", Static).update("")

    def on_log_line(self, message: LogLine) -> None:
        self.query_one("#r-log", RichLog).write(message.line)

    def on_progress_update(self, message: ProgressUpdate) -> None:
        self.query_one("#r-progress", ProgressBar).update(
            progress=message.fraction * 100)
        self.query_one("#r-eta", Static).update(
            Text(f" op {message.op} · eta {message.eta_s / 60:5.1f} min",
                 style=MIST))

    def on_run_finished(self, message: RunFinished) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        log = self.query_one("#r-log", RichLog)
        ok = message.returncode == 0
        log.write(Text(f"stage finished with exit code {message.returncode}",
                       style=OK if ok else "bold red"))
        self.query_one("#r-stop", Button).disabled = True
        if not ok:
            self.query_one("#r-gate", Static).update(
                Text("Stage failed - fix and press Continue to retry the "
                     "NEXT stage, or Esc for status.", style=WARN))
            self.query_one("#r-continue", Button).disabled = False
            self.waiting_gate = True
            return
        if (app.session.continue_automatically
                or self.current + 1 >= len(self.commands)):
            self._advance()
        else:
            nxt = self.commands[self.current + 1].stage
            self.query_one("#r-gate", Static).update(
                Text(f"Press enter to continue with: {nxt}", style=SAND))
            self.query_one("#r-continue", Button).disabled = False
            self.waiting_gate = True

    def action_gate(self) -> None:
        if self.waiting_gate and not self.runner.running:
            self.waiting_gate = False
            self._advance()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "r-continue":
            self.action_gate()
        elif event.button.id == "r-stop":
            self.runner.terminate()

    def action_stop(self) -> None:
        self.runner.terminate()

    def action_leave(self) -> None:
        if not self.runner.running:
            self.app.push_screen(StatusScreen())


class StatusScreen(Screen):
    """The census + final components - presenting results."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Label("Pipeline", classes="panel-title")
            table = DataTable(id="st-pipeline", cursor_type="row")
            table.add_columns("stage", "state", "summary")
            yield table
        with VerticalScroll(classes="panel"):
            yield Label("Final components", classes="panel-title")
            comps = DataTable(id="st-components", cursor_type="row")
            comps.add_columns("component", "cameras", "scale", "verdict",
                              "model", "exports")
            yield comps
        yield Footer()

    def on_mount(self) -> None:
        app: WildScanApp = self.app  # type: ignore[assignment]
        ws = app.session.workspace()
        table = self.query_one("#st-pipeline", DataTable)
        for key, st in ws.detect().items():
            table.add_row(Text(st.title, style=SAND),
                          status_text(st.status, st.status), st.summary)
        comps = self.query_one("#st-components", DataTable)
        for c in ws.components():
            scale = "-" if c.scale is None else f"{c.scale:.3f}"
            comps.add_row(
                Text(c.key, style=SAND),
                f"{c.cameras:,}" if c.cameras else "-",
                scale, c.scale_status or "-",
                "done" if c.modelled else "-",
                ", ".join(c.exported) or "-")

    def action_back(self) -> None:
        self.app.pop_screen()


class WildScanApp(App):
    TITLE = f"{APP_NAME} · {ORG}"
    CSS = CSS

    def __init__(self, workspace: str | None = None) -> None:
        super().__init__()
        self.session: Session = default_session()
        if workspace:
            self.session.results_root = workspace
        self.scan = scan_raw_data(self.session.cruise_folder) \
            if self.session.cruise_folder else scan_raw_data("")
        self.questions = []

    @property
    def workspace(self) -> Workspace | None:
        return (Workspace(self.session.results_root)
                if self.session.results_root else None)

    def on_mount(self) -> None:
        self.push_screen(SessionScreen())


def main() -> int:
    workspace = sys.argv[1] if len(sys.argv) > 1 else None
    WildScanApp(workspace).run()
    return 0
