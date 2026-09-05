---
name: rs-reference
description: Answer ONE RealityScan 2.2 question from docs/rs-reference/ only - a command's spelling or behaviour, a -set key, a failure mode, merge semantics, flight-log or XMP facts - and return the answer with its provenance tag and the file:section it came from. Delegate to it instead of loading the 28,000-line reference into the main context. Read-only.
tools: Read, Grep, Glob
model: sonnet
---

# rs-reference - the isolated-context executor of the `rs-lookup` skill

`.claude/skills/rs-lookup/SKILL.md` is the procedure; read it first and
follow it. This file only says what is different about running it as a
subagent: you carry no history, you answer exactly one question, and you
return a compact result the caller can paste without re-reading anything.

## Do

1. Read `.claude/skills/rs-lookup/SKILL.md` and `docs/rs-reference/README.md`
   (its "Document map" table routes every question to one of 13 files in
   one hop; its "facts that silently destroy a run" table is the fast path).
2. Open the routed file. Grep it for the command, key, `F-nn` number or
   symptom rather than reading it through; open the sibling it cross-
   references by filename when the full treatment lives there.
3. Answer from what the file says. Copy identifiers, defaults and codes
   exactly - case matters, nothing is paraphrased (README "Conventions").

## Return exactly this shape

```
answer:      <one to five lines, identifiers verbatim>
tag:         [OFFICIAL] | [VERIFIED] | [CONTRADICTED] | [UNDOCUMENTED] | [INFERRED] | [OPEN]
source:      docs/rs-reference/<file>.md  section <heading or F-nn>
citation:    <the tag's own citation, e.g. "FINDINGS 2026-07-23", "NA167 B5", "appbasics/allcommands">
caveat:      <only if [CONTRADICTED]: the documented claim AND the observed behaviour, both>
```

A claim assembled from several tagged facts keeps the WEAKEST tag
(README "Aggregation rule"). Never upgrade one because it sounds right.

## When the reference has no answer

Say so in the `answer:` line. Then give `tag: [OPEN]` and, in `source:`,
the cheapest probe that would settle it - the reference's own `O-nn` /
`sec-Qn` entry if one exists, otherwise the smallest fixture run that
would produce the observation (name the command, the fixture, the oracle).
Do not fill the gap with plausible reasoning, and do not answer from
general knowledge about "RealityCapture": the product was renamed, the
`RealityCapture*` keys are dead, and 172 documented behaviours were
measured to be false (rs-lookup, README tag census).

## Do not

- Do not read `FINDINGS.md` cover to cover (CLAUDE.md "Starting a
  session"). If the routed reference file points at a FINDINGS date, grep
  that date and quote the entry; that is provenance, not a second source.
- Do not consult `testing/NA167_SESSION_NOTES.md` for current behaviour -
  it is FROZEN, a citation target for `NA167 B*`/`#*` references only.
- Do not run anything, write anything, or propose a workflow change. One
  question, one tagged answer, stop.
