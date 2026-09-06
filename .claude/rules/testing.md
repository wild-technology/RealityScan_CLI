---
paths:
  - "testing/**"
---

# Rules for the test suite

- **Unit tests never boot RealityScan.** Stub `run_batch_script` /
  `run_attach_script`, or write a stub executable and stub workflow `.bat`
  into `tmp_path` - CRLF on Windows, because an LF stub intermittently
  breaks cmd's label search even at three lines. Copy
  `testing/test_attach_mode.py` (`_write_script`, `_stub_exe`,
  `_stub_workflow`, `FakeStore`); `test_cmd_boundary_guards.py` goes further
  and makes any `subprocess` call an assertion failure. [CLAUDE.md hard
  rule 1; test_attach_mode.py header]
- **The store never touches the repo root** - `testing/conftest.py`
  points every `SettingsStore()` at `tmp_path` (module attribute +
  `RS_SETTINGS_PATH` for child processes), scrubs `RS_*` from the test
  environment, and FAILS the session if `rs_settings.json` appears in the
  root. Do not construct `SettingsStore(path=<repo path>)` in a test. The
  suite wrote the root file until 2026-09-05 (`main.parse_arguments`,
  `BatchDirectory`). [FINDINGS `[HARNESS]` 2026-09-05; AGENT_OPERATIONS sec.5]
- **Hook tests feed payloads through Python, never `echo`.** Bash `echo`
  mangled `\` inside the JSON tool call and made two block cases look like
  hook failures. Use `run_hook()` in `testing/test_agent_hooks.py`
  (`subprocess.run([sys.executable, script], input=json.dumps(payload))`).
  Every guard hook keeps a liveness test: inject a known violation, prove
  exit 2. [FINDINGS `[HARNESS]` 2026-08-31; CLAUDE.md "Agent-facing entry
  points"]
- **The baseline statement lives in `CLAUDE.md` ("Session start") and the
  platform-bound failure set in `testing/conftest.py`'s docstring, nowhere
  else.** Windows: fully green. macOS/Linux: 11 alignment tests (RealityScan
  install tree) + 11 basename tests (drive-letter paths on POSIX). Update
  both in the change that moves them. [FINDINGS `[HARNESS]` 2026-09-05]
- **Run `python -m pytest testing -q`** (`py -3.13` is absent on some boxes;
  one offline skip, the geoid grid). ASCII-only output - the cp1252 console
  crashes otherwise. [CLAUDE.md "Environment"; HANDOFF 2026-09-03]
- **Campaign drivers and frozen notes are citation targets, not tests.**
  They live in `archive/campaign_drivers/`; `testing/run_on2026_run2.py`
  stays only because `test_feature_merge.py` imports its `stage_features`
  (decision D9). `NA167_SESSION_NOTES.md` is frozen. [CLAUDE.md hard rule 9]
- **Do not leak global logging state.** `test_rig_mounts.py` leaves
  `logging.disable(CRITICAL)` armed; a test that needs `caplog` must reset it
  (`test_unattended_prompts.py`'s `log` fixture) until that leak is fixed.