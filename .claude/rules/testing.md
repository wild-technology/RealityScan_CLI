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
- **`SettingsStore` takes a `tmp_path` path, never the default.** The suite
  once wrote `rs_settings.json` into the repo root (`test_preprocess_module.py`
  calling `SettingsStore()`; found while baselining 2026-09-03). A shared
  store also lets one test's persisted answer feed the next through the
  same path that caused the stored-merge-options incident.
  [AGENT_NATIVE_ROADMAP.md sec. 1.8; AGENT_OPERATIONS.md sec. 5, 2026-07-29]
- **Hook tests feed payloads through Python, never `echo`.** Bash `echo`
  mangled `\` inside the JSON tool call and made two block cases look like
  hook failures. Use `run_hook()` in `testing/test_agent_hooks.py`
  (`subprocess.run([sys.executable, script], input=json.dumps(payload))`).
  Every guard hook keeps a liveness test: inject a known violation, prove
  exit 2. [FINDINGS `[HARNESS]` 2026-08-31; CLAUDE.md "Agent-facing entry
  points"]
- **The suite count lives in `CLAUDE.md` ("Baseline before touching
  anything"), nowhere else.** Update that line in the same change that moves
  it; a stale count is how a broken tree gets inherited. [CLAUDE.md
  "Starting a session"; roadmap Status, the 498 vs 597 drift]
- **Run `python -m pytest testing -q`** (`py -3.13` is absent on some boxes;
  one offline skip, the geoid grid). ASCII-only output - the cp1252 console
  crashes otherwise. [CLAUDE.md "Environment"; HANDOFF 2026-09-03]
- **Campaign drivers and frozen notes are citation targets, not tests.**
  `run_on2026_*.py` carry hardcoded data paths (bound for `archive/`);
  `NA167_SESSION_NOTES.md` is frozen. Do not "fix" them into the unit
  suite. [CLAUDE.md hard rule 9; roadmap sec. 1.8]
