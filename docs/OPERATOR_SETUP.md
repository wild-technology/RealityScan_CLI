# Operator setup - per box, once

What has to be true on a machine before an agent drives a run there. Every
item is checked or enforced by code where it can be; the rest is listed so
it is not forgotten.

## 1. Interpreter

- `python` on PATH must be the interpreter that has `requirements.txt`
  installed. The `.claude` hooks call `python` by name; a hook that cannot
  import the repo is a guard nobody enforces. `python rs.py preflight` checks
  this (`hooks interpreter` line) and blocks on Windows if it fails.
- Coyote: Microsoft Store Python 3.13, no `py` launcher. Honeybadger: `py -3.13`
  exists; make sure plain `python` resolves to the same interpreter.

## 2. `CLAUDE.local.md` (gitignored, beside `CLAUDE.md`)

```
# This box
- Interpreter: C:\...\python.exe (3.13) - `python` on PATH
- Data volumes: D:\ (imagery), Y:\ (NAS deliverables), M:\ (cache)
- Agent instance names in use: RSAGENT; owner instances: RS1, RSGUI
- RealityScan install: C:\Program Files\Epic Games\RealityScan_2.2\
```

Keep it to facts that differ per machine. Anything true everywhere goes in
`CLAUDE.md` or a skill.

## 3. Permission mode

The `ask` tier in `.claude/settings.json` (`schtasks`, `taskkill`, `rm -rf`,
`Stop-Process`, `Remove-Item`, `git push`) is the safety gate for the
scheduler-owned lane. Before the first drive on a box, confirm those
commands still prompt under the permission mode you use. If a mode
auto-approves them, drive in default mode.

## 4. User-level deny list (defense in depth, every repo on the box)

`~/.claude/settings.json` on the box (merge with what is there):

```json
{
  "permissions": {
    "deny": [
      "Bash(git push --force*)",
      "Bash(git push -f *)",
      "Bash(git reset --hard*)",
      "Bash(git clean -fd*)",
      "Bash(rm -rf ~*)",
      "Bash(rm -rf /*)"
    ]
  }
}
```

The repo carries the same denies; this makes them hold in repos that do not.

## 5. Launching Claude Code for a drive

Set `RS_RUN_CHARTER=<absolute RUN_CHARTER.json>` in the shell that starts
Claude Code. That single variable arms the write guard, pins the agent's
instance and cache, and refuses stored-settings inheritance in every child.

## 6. The 30-minute monitor

After `python rs.py launch`, paste the printed `/loop 30m ...` line. Each tick
runs the `run-monitor` agent (small model, read-only) and reports one verdict
block. Stop the loop on `failed`, `stalled`, or a budget line and decide;
the monitor never acts.

## 7. Owner prompt habits

- Start a driving session with `/charter`; put the six answers, in order, in
  the first message so the skill restates instead of asking.
- Say "status" for a read-only verdict; `/status` is auto-invocable.
- A named review, test or audit request is the whole turn; the standing
  rules shape how it is done, never whether.

## 8. Windows checks after a fresh clone

```bash
python -m pytest testing -q          # fully green expected on Windows
python rs.py preflight --charter <C> # READY before any run
git ls-files --eol -- '*.bat' '*.vbs' '*.cmd' | grep -E 'w/(lf|mixed)'   # prints nothing
```
