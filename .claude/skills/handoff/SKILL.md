---
name: handoff
description: Session-end checklist, in order - flush FINDINGS.md, write the new HANDOFF.md top section, re-run the suite and fix the count in CLAUDE.md, account for every uncommitted file, commit in the house style. Owner-invoked only (/handoff). Never pushes, never deletes branches.
disable-model-invocation: true
---

# Hand off the session

`HANDOFF.md` outlives the session; the next one reads it before its first
mutating action (CLAUDE.md "Ending a session"). Do the steps IN ORDER -
the test count feeds HANDOFF, HANDOFF feeds the commit. `python` = the
interpreter with the deps (CLAUDE.md "Environment").

## 1. FINDINGS.md - flush, do not summarise

For every fact established this session:

```bash
grep -n "<command, key or symptom>" FINDINGS.md
```

Extend an existing entry; otherwise append at the END of the matching
section (`[NA165]`, `[NA168]`, `[HARNESS]`, `[RECON]`, `[CESIUM]`, ...):

```
## [TAG] YYYY-MM-DD - <the claim, one line>

<What was observed and HOW it was discovered: the command, the fixture,
the file read. End with ESTABLISHED / RESOLVED / OPEN, and for OPEN what
would settle it.>
```

A refuted hypothesis is never deleted: leave the old entry, prefix it
`SUPERSEDED (YYYY-MM-DD, see <the new entry>)`, and let the new entry name
what it supersedes. Deleting one guarantees rediscovering it.

## 2. HANDOFF.md - the new top section

Insert directly under the H1, above the previous section; older sections
stay as written. Match the 2026-09-03 and 2026-09-02 sections:

```
## YYYY-MM-DD - <one-line state>, read this first

<Two or three sentences: what changed, suite count, what is running.>

### Done                (bullets or table; what landed, with commit ids)
### Running             ("Nothing." or per process: PID, command line, log,
                         budget, and the exact RESUME command)
### Ranked loose ends   (numbered, most valuable first, why each matters)
### Artifact locations  (absolute paths; what is verified and how)
### Exact next commands (fenced; every command checked against --help)
```

Open owner decisions carry their roadmap numbers (D1...). Write the
command, not "should".

## 3. Suite, and the count in CLAUDE.md

```bash
python -m pytest testing -q
```

Use the interpreter that has every requirement (`CLAUDE.local.md` names it
per box). If the pass count differs from the CLAUDE.md "Starting a session"
line (`737 passed, 1 skipped (offline: geoid grid)` at the time of writing;
an interpreter without `textual` skips `test_wildscan.py` whole and reports
716 passed, 2 skipped - that is not a changed count), update that line and
say so in HANDOFF. A red suite is never hidden: name
the failing tests in HANDOFF and in the commit body, or do not commit.
Remove an `rs_settings.json` the suite wrote into the repo root (test
hygiene defect, roadmap sec.1.8); it is gitignored, never committed.

## 4. Working tree - clean, or every file named

```bash
git status --short
git diff --stat
git ls-files --eol -- '*.bat' '*.vbs' '*.cmd' | grep -E 'w/(lf|mixed)'
```

Every listed path is either in the commit or named in HANDOFF with a
reason (probe output, half-done, owner-only). The third command prints
nothing - scripts are CRLF on disk (`.claude/hooks/normalize_crlf.py` repairs tool
edits, not scripted ones). Nothing from `<results_root>/_agent/` or a
data volume goes in the repo.

## 5. Commit - house style

```bash
git log -5 --format='%s%n%n%b'
```

Imperative first line, <= 72 chars, subsystem prefix where one is used
(`HANDOFF:`, `decimate:`, `merge_zones:`); blank line; a body that says
WHY - what was observed, what was decided, what was deliberately not done;
trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Write
the message to a scratchpad file; name every file:

```bash
git add <file> <file> ...
git commit -F <scratchpad>/commit_msg.txt
git status --short
```

Never `--amend` a pushed commit, never `--no-verify`.

## 6. Push - only on the owner's word, in this session

`git push origin <branch>` only when the owner says so in chat, this
session - never `--force`, never a branch or tag delete. Headless auth is
the `gh` device flow (`gh auth status`); GCM hangs (HANDOFF 2026-09-02).
Never accept a token pasted in chat.

Final line to the owner: suite count; "Committed <sha> on <branch>; not
pushed." or "nothing to commit"; what is running with its resume command;
the single highest-ranked loose end.

## This skill must NEVER

- push, force-push, rewrite history, or delete a branch or tag;
- delete a FINDINGS entry, or close an OPEN one without evidence;
- rewrite an older HANDOFF section;
- commit `rs_settings.json`, probe output, logs, or data-volume files;
- stop a running process to make "Running: Nothing." true.
