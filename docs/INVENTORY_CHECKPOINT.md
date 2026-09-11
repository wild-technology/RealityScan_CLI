# Resumable inventory and full image verification

`modules.inventory_checkpoint.scan_inventory` is a synchronous worker API. The
controller runs it off the UI thread and owns its cancellation event, settings,
review persistence, and explicit confirmation. It returns a `SourceInventory`.

```python
from modules.inventory_checkpoint import scan_inventory

items = scan_inventory(
    source,
    checkpoint_dir,
    launch=launch_utc,
    recovery=recovery_utc,
    cancelled=cancel_event.is_set,
    progress=lambda stage, done, total, path: report(stage, done, total, path),
)
```

Both paths must be disjoint. Use a dedicated, private checkpoint directory in
project metadata; do not use the source tree, an existing arbitrary directory,
or a live reference worker's directory. One OS file lock protects each checkpoint
from competing writers. The function never starts RealityScan, stages images,
modifies source data, loads selection decisions, or grants approval.

## What is repeated and what is reused

1. Call the existing `scan_source` on every invocation. It checks the whole
   source tree before and after discovery. There is no second image scanner.
2. Validate the exact metadata snapshot against the fresh scan, including paths,
   associations, timestamps, file identities, and the source-tree fingerprint.
   Source changes create a fresh generation; old generations remain untouched.
3. Replay validated hash records and call existing
   `hash_identities(..., resume=True)`. Completed hashes are reused only for the
   same source snapshot. Duplicate/conflict classification is rerun.
4. Call `verify_images` with versioned successful decode proofs. Every image or
   mask is opened for its current dimensions. A matching SHA-256 plus dimensions
   permits reuse of a successful full decode. Mask/image dimension comparisons
   run again even when both payloads have cached proofs.
5. Recheck the complete source fingerprint. Only after the final callback and
   successful durable state write does the function return completed inventory.

A different launch/recovery window reuses unchanged content work but recomputes
window flags and the resulting content-review token. Cached selections, exception
strings, completion flags, or an old token cannot supply a current decision.

`hashing_complete` and `verification_complete` mean the passes completed, not that
every file was acceptable. A returned inventory may contain unknown-camera,
outside-window, decode-failure, mask, or duplicate conflicts requiring review.
Existing staging refuses included unresolved exceptions. The controller must
still obtain explicit inventory confirmation; this API does not do that.

## Full pixel decoding and evidence version

The previous Pillow `Image.verify()` call did **not** decode JPEG pixels. A JPEG
with a valid header and truncated compressed payload could pass it. The current
implementation first verifies structure, then reopens the image and calls
`load()` to force pixel decoding. The default limit is 89,478,485 pixels per
image, independent of a caller weakening Pillow's decompression threshold.
Verification refuses to run when Pillow's global `LOAD_TRUNCATED_IMAGES` is true.

Successful proofs use `(sha256, width, height)` and the version
`full-pixel-decode-v1`, Pillow version, and configured pixel limit. Failed decodes
are never cached. Identical content is decoded once, while every path retains
its own file-identity, header, and association checks. On an inventory without
a completed hash pass, `verify_images` computes hashes itself before deduplicating;
it does not infer trust from equal filenames, sizes, or timestamps.

An old reference worker that already imported the earlier function keeps running
unchanged. Its completion is **not full-pixel-decode evidence**. Optional hash
import, described below, never accepts its old verification or completion claims.

Decoder success establishes readable structure/pixels, not scientific image
quality or proof that arbitrary visually plausible corruption never occurred.
The processing-quality review remains a separate gate.

## Cancellation, crashes, and progress

`progress(stage, done, total, path)` is called on the worker thread; callback
exceptions propagate. Stages are `scan`, `invalidate`, `import`, `hash`, `verify`, and
`complete`. Scan totals are unknown until discovery finishes. The existing scanner
can be cancelled at its boundaries; hashing polls between read chunks, and
verification polls between Pillow calls. A single native decoder call is not
preempted. This API adds no background threads or worker processes.

Cancellation raises `InterruptedError`. Any failure leaves completion flags false.
The next call rescans metadata and resumes valid work without trusting the prior
completion state. A crash can lose a bounded number of unflushed journal records;
those files are simply reprocessed. The final unterminated journal record is
discarded as uncommitted. A malformed **committed** record is an error.

The journal appends small per-file records and flushes after 64 records or at the
next append after one second, plus at phase boundaries and exception unwinding.
Snapshots are written once per new metadata generation, never per file. Only small
state files are rewritten for invocation/completion status. No automatic cleanup
removes older generations. Logs and generations can be managed by a separate
explicit checkpoint-retention policy.

Atomic checkpoint writes reuse `module_base.atomic_io.replace_file`: up to 21
attempts with 0.05-second waits for Windows sharing/access errors 5/32/33. There
is no permission change or forced destination deletion. If a persistent error
also prevents writing incomplete state, the original exception is preserved with
a diagnostic note and completed journal records remain available for resume.
An older state file can remain on disk in that case: state flags are advisory,
never an approval source. A successful current API return is required.

## Cache validation and limits

The owner record binds the absolute source and checkpoint directory. Snapshot
checksums, fresh-scan equality, chained journal checksums, strict record schemas,
hash syntax, exact source-relative path membership, and decode/hash/version binding
reject malformed, altered, reordered, cross-source, and mismatched evidence.
Links, hardlinked cache files, source/cache overlap, case-insensitive inventory
path collisions, and unowned checkpoint directories are refused.

These are local integrity checks, **not authentication against an attacker able
to rewrite the cache and recompute all its checksums**. Keep checkpoint storage
private to the project owner. The existing metadata-based hash resume contract
also cannot detect a hostile source writer restoring every recorded identity and
timestamp. Ordinary additions, removals, replacements, and edits invalidate the
generation; staging independently checks copied bytes against approved hashes.

## Importing a trusted prior hash journal

The optional `hash_import` keyword preserves completed hashing from a separately
validated producer without treating its older verification claims as evidence:

```python
from modules.inventory_checkpoint import HashJournalImport, scan_inventory

donor = HashJournalImport(
    snapshot=prior_snapshot_path,
    journal=prior_journal_path,
    snapshot_sha256=pinned_snapshot_sha256,
    journal_sha256=pinned_journal_sha256,
)
items = scan_inventory(source, checkpoint_dir, launch=launch_utc,
                       recovery=recovery_utc, hash_import=donor,
                       cancelled=cancel_event.is_set, progress=report)
```

The donor snapshot uses `source_root`, `fingerprint`, and `items` containing
`SourceItem` fields. The journal contains JSONL `{path, sha256}` entries. Both
artifact byte hashes must match the explicitly supplied pins. Donor source,
whole-tree fingerprint, each exact path, and all five recorded file-identity
fields must match the fresh scan. Malformed, conflicting, changed, or redirected
evidence is refused before import records are appended. No source image content
is reread just to import a completed hash; missing hashes still run normally.

Only hash records transfer. Fresh scanning and the requested window supply every
classification, timestamp, mask association, exception, and selection default.
Every payload still requires current-version full decode evidence. An import
receipt records the artifact pins; subsequent resumes can omit `hash_import`.
Cancellation during import retains committed seed records.

Pins establish the identity of an artifact, not the honesty of its producer.
The caller must explicitly trust how those donor hashes were computed. Do not
automatically adopt arbitrary external journals or change a pin merely to bypass
a mismatch. Neither donor files nor a live donor worker are modified by import.

Offline tests cover clean resume, cancellation in both phases, interrupted final
records, callback failures, changed source/windows, corrupted cache records,
cross-source/path injection, lock contention, decoder-version changes, truncated
JPEGs, pixel limits, content deduplication, and mask-dimension checks on resume.
