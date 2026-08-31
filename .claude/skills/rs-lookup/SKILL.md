---
name: rs-lookup
description: Answer any RealityScan 2.2 CLI question - command spelling, parameters, -set/-preset settings keys, XMP/sidecar semantics, flight logs and coordinate frames, alignment tuning, component merge behaviour, .rsInfo/params XML, export and publishing, or why something "succeeded" without doing anything. Routes to the consolidated manual in docs/rs-reference/ instead of answering from general knowledge. Use whenever a RealityScan command, key, file format or failure mode comes up.
---

# Look a RealityScan fact up - never recall it

RealityScan's CLI contradicts its own documentation in 172 recorded
places. General knowledge about "RealityCapture" is worse than useless
here: the product was renamed, the `RealityCapture*` settings keys are
dead, and several documented behaviours were measured to be false.

**Never answer a RealityScan question from memory. Route it, read the
file, cite the tag.**

## Route in one hop

| Question is about... | Read |
|---|---|
| Starting/controlling RS: instances, `-delegateTo`, `-waitCompleted`, `-getStatus`, shutdown, progress files, exit codes, multi-GPU, cache | `docs/rs-reference/01-cli-fundamentals.md` |
| Exact spelling/parameters/behaviour of **any** command (all 218) | `02-command-reference.md` |
| A `-set`/`-preset` key: type, default, allowed values, whether it is dead | `03-settings-keys.md` |
| Getting images in, `.imagelist`, `-addFolder`, image identity, selection, calibration groups, masks | `04-image-input-and-handling.md` |
| XMP sidecars, `xcr:` attributes, prior semantics, the auto-import trap, `sensorsdb.xml` | `05-metadata-xmp-and-sidecars.md` |
| Flight logs, `FlightLogParams.xml`, CRS, GCPs, metric scale, **the vertical datum** | `06-georeferencing-flightlogs-and-scale.md` |
| Running/tuning alignment, `sfm*`/`lis*` keys, `AlignmentParams.xml`, judging a bad solve | `07-alignment.md` |
| Components, `.rsalign`, `.complist`, **merge semantics - what actually fuses** | `08-components-and-merge.md` |
| Writing/debugging a params XML, `.rsInfo`, decoding `transformToModel` | `09-xml-parameter-files.md` |
| Reconstruction, texturing, simplify/unwrap/reproject, every export command, LoD/3D Tiles, publishing | `10-reconstruction-texturing-export.md` |
| Building the harness: `:run`, ErrorWriter, marker files, the cmd/.bat data boundary, stall monitoring, checkpoint/rollback | `11-automation-patterns.md` |
| **Something failed, hung, or "succeeded" without doing anything** - 88 numbered failure modes, exit/result code tables, diagnostic playbook | `12-failure-modes-and-race-conditions.md` |
| Camera rigs, priors, `xcr:Rig`, distortion models, rotation conventions, coordinate frames | `13-camera-rigs-priors-and-orientation.md` |

Start at `docs/rs-reference/README.md` when the row is not obvious - its
"facts that silently destroy a run" table is the highest-value page in the
repo.

## Report what you found with its tag

Every claim in the reference carries exactly one provenance tag. Carry it
into your answer:

- `[OFFICIAL]` - Epic's shipped Help says so.
- `[VERIFIED]` - measured here, with the citation.
- `[CONTRADICTED]` - docs say X, observation says Y. **State both.**
- `[UNDOCUMENTED]` / `[INFERRED]` / `[OPEN]` - say which, and for
  `[OPEN]` say what probe would settle it.

**A claim built from tagged facts keeps the WEAKEST tag.** Do not upgrade
one because it sounds right.

If the reference does not answer it, say so and name the cheapest probe
that would - do not fill the gap with plausible reasoning.

## Raw sources behind the reference

`FINDINGS.md` is the dated raw log (grep it; do not read it through).
`testing/NA167_SESSION_NOTES.md` is FROZEN - the citation target for
`NA167 B*`/`#*` references, read for provenance only.
