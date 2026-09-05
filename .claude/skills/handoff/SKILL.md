---
name: handoff
description: Session-end checklist, in order - flush FINDINGS.md, write the new HANDOFF.md top section, re-run the suite and refresh the baseline line in CLAUDE.md, account for every uncommitted file, commit in the house style. Owner-invoked only (/handoff). Never pushes, never deletes branches.
disable-model-invocation: true
---

# Hand off the session

`HANDOFF.md` outlives the session; the next one acts on its top section
first. Steps IN ORDER. `python` = the interpreter with the deps.

## 1. FINDINGS.md - flush, do not summarise

For each fact established this session: `grep -n "<command, key or
symptom>" FINDINGS.md`; extend the entry or append at the END:

```
## [TAG] YYYY-MM-DD - <the claim, one line>

<What was observed and HOW: the command, the fixture, the file read. End
with ESTABLISHED / RESOLVED / OPEN (+ what would settle it).>
```

Refuted hypotheses are never deleted: prefix the old entry
`SUPERSEDED (date, see <new entry>)`. New owner decisions go to
`docs/DECISIONS.md` as a row. A finding that states RealityScan BEHAVIOUR
also goes into the matching `docs/rs-reference/` file, as the next `A<n>`
under its `## Addenda` section, citing the FINDINGS date (decision D14);
campaign-specific and harness-internal facts stay in FINDINGS only.

## 2. HANDOFF.md - the new top section

Insert under the H1, above the previous section; older sections stay as
written. Sections older than the two most recent may move verbatim to
`docs/history/HANDOFF_<range>.md`.

```
## YYYY-MM-DD - <one-line state>, read this first
<Two or three sentences: what changed, suite result, what is running.>
### Done                (what landed, with commit ids)
### Running             ("Nothing." or per process: PID, command, log, budget, RESUME command)
### Ranked loose ends   (numbered, most valuable first, why each matters)
### Artifact locations  (absolute paths; what is verified and how)
### Exact next commands (fenced; every command checked against --help)
```

## 3. Suite and the baseline line

```bash
python -m pytest testing -q
```

Windows: fully green expected. macOS/Linux: exactly the platform-bound set
named in `testing/conftest.py`. If the result differs, name every failing
test in HANDOFF and the commit body - or do not commit. A red tree is never
hidden. The suite must leave no `rs_settings.json` in the repo root (the
conftest fails the run if it does).

## 4. Working tree - clean, or every file named

```bash
git status --short
git ls-files --eol -- '*.bat' '*.vbs' '*.cmd' | grep -E 'w/(lf|mixed)'
```

The second command prints nothing. Every listed path is in the commit or
named in HANDOFF with a reason. Nothing from `<results>/_agent/` or a data
volume goes in the repo.

## 5. Commit - house style

Imperative first line <= 72 chars with a subsystem prefix where one is used
(`HANDOFF:`, `merge_zones:`); a body that says WHY and what was deliberately
not done; trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
Message in a scratchpad file; `git add <files>`; `git commit -F <file>`.
Never `--amend` a pushed commit, never `--no-verify`.

## 6. Push - only on the owner's word, this session

`git push origin <branch>`; never `--force`, never a branch or tag delete.
Headless auth is the `gh` device flow; never accept a token pasted in chat.

Final line to the owner: suite result; "Committed <sha> on <branch>; not
pushed." or "nothing to commit"; what is running with its resume command;
the single highest-ranked loose end.

## This skill must NEVER

push, force-push, rewrite history or delete a branch/tag; delete a FINDINGS
entry or close an OPEN one without evidence; rewrite an older HANDOFF
section; commit `rs_settings.json`, probe output, logs or data-volume files;
stop a running process to make "Running: Nothing." true.
