# Component growth & merge strategy — research-grounded design (2026-07-23)

Sources: RealityScan 2.2 local Help (components.htm, mergecomponents*.htm,
alignsettings.htm, allcommands.htm), Epic staff forum answer on merge-vs-
align (forums.unrealengine.com/t/712116, staff member OndrejTrhan), and
this repo's empirical results (NA156 H2023, NA167 merge matrix).

## Established facts

1. **Merge Components is rigid**: "no new images are added"; Epic staff:
   it best-fits existing components without re-optimizing or moving
   camera poses. It can never fix internal distortion, never register an
   orphan, and never shrink anything.
2. **Align is the actual growth/merge engine**: "Run alignment again -
   RealityScan will first use special algorithms designed for merging
   components"; re-runs "try a different strategy"; after
   georeferencing, align "automatically tries to improve accuracy by
   finding additional tie points". Staff recommend align over merge for
   accuracy, and note re-align is CHEAP because features are cached.
3. **Align can shrink**: it re-optimizes, and marginal cameras can drop
   (observed: 3,860 -> 3,855 on H2023). Growth monotonicity is NOT a
   property of align - it must be enforced externally
   (checkpoint/rollback).
4. **featureSource is consumed by ALIGN, not by Merge Components** (the
   Help ties it to "a new alignment of components", set per selected
   input): `0` merge-using-overlaps = only images COMMON to components
   (the duplicated zone-overlap bands are exactly this) - fastest,
   lowest memory; `1` component features = only the component's existing
   tie points - fast, needs components sharing points; `2` all image
   features = full feature pool - slowest, for small camera counts.
5. **Components tolerate duplicate images**, and the official
   fix-and-reimport round trip (export faulty part -> fix in a spare
   scene -> reimport -> align "applies fixes") is a sanctioned pattern.
6. **Georef-rigid fusion** (sfmMergeGeoreferencedComponents=true +
   mergeComponents/-update) unites georeferenced components with ZERO
   visual ties, placing them purely by nav. With ~1-2 m real nav
   accuracy this bakes nav error into the seam and can double surfaces
   where components overlap spatially - a last resort, not a first move.
7. A merged component is georeferenced only if the merge scene holds
   constraints (union flight log + `-update`); component georeferencing
   does not survive into the NEW component otherwise (observed).
8. Export is SELECTION-driven ("only the selected items will be
   exported") - a stray active image selection silently empties an
   export under -silent (observed: flight-log import leaves the matched
   images selected; `-deselectAllImages` before exports is mandatory).

## Challenges to the current owner recipe

The proven recipe: initial align -> mergeComponents x2 (delete stale
after each) -> per component: disable all, enable component + orphans,
align to catch strays -> cleanup.

1. **Merge-first is the weakest opener.** Rigid merge adds no images and
   fixes nothing; anything it can fuse (shared cameras) a re-align fuses
   too, while ALSO picking up orphans in the same pass - at low cost
   (cached features). The x2 repetition compensates for pairwise rigid
   chaining, which align makes unnecessary. What merge-first DOES buy is
   safety (it cannot shrink). Verdict: keep rigid merge, but demote it
   to (a) a free consolidation after aligns, and (b) the LAST-resort
   georef-only fusion of visually untieable pieces; promote a global
   re-align to the opener, wrapped in checkpoint/rollback to preserve
   the never-shrink guarantee.
2. **"Always grow, never shrink" needs enforcement, not hope.** Because
   align can shrink, every risky pass gets: export components + manifest
   before -> run -> manifest after -> accept iff no unique image lost
   and net cameras >= before; else roll back (delete result, reimport
   checkpoint - the official round trip). This converts the recipe's
   aspiration into an invariant.
3. **Per-component isolation is right, but second, not first.** One
   global align (everything enabled) is cheaper than N isolated passes
   and lets RealityScan's merge algorithms see all cross-component ties
   at once. THEN the per-component enable/disable+orphans loop hunts the
   turbidity missing-links the global pass missed, with the isolation
   preventing the re-solve from reshuffling other components. Repeat
   while gains > 0.
4. **featureSource should be explicit per pass**, not left at defaults:
   within-zone growth passes -> component being grown at `1` (component
   features anchor) with orphans contributing full features; cross-zone
   passes over duplicated overlap bands -> `0` (merge using overlaps),
   the documented fast path built for exactly this data shape; tiny
   stubborn components -> `2` (all image features) surgically.
5. **Twins are removable by the recipe's own rule.** "Never throw away
   components that contain unique images" implies: a component whose
   image set is fully contained in another's (no unique images) IS
   discardable - and the weak twin of an overlap band is exactly that.
   Rigid merge cannot fix its warp (fact 1) and align spends effort
   reconciling it; drop it pre-merge, automatically, from the manifest
   containment check + per-camera reprojection quality.
6. **Border gating comes from the manifest, not the GUI.** Georeferenced
   camera positions per component (captured at zone-align time, when
   XMP identity still exists - imported-scene exports go ordinal, B10)
   give each component a bbox; only bordering/overlapping pairs are
   merge candidates. Orphans stay in every scene as potential links.

## Revised order of operations

Per zone (original scene, features cached):
1. Checkpoint (export components + manifest).
2. Global re-align, all images enabled. Accept/rollback per invariant.
3. Rigid mergeComponents (free consolidation of anything now tied).
   Delete stale components (manifest-verified containment).
4. While gains > 0: per component (largest first): disable all ->
   enable component images + orphans -> align (featureSource 1) ->
   accept/rollback -> cleanup stale.
5. Twin scan (containment + quality) -> drop no-unique-image losers.
6. Export final components + manifests.

Cross-zone (fresh scene):
7. Import all zone components (original paths), union flight log +
   CRS params, deselectAllImages.
8. Align with featureSource 0 on the overlap-band members (checkpoint
   first; priors on; rematch on second attempt).
9. Rigid georef merge (+ -update) ONLY for still-disjoint bordering
   leftovers; accept the nav-accuracy seam consciously.
10. -update, verify georeferencing, census, model only after this is
    sound.

## Bookkeeping layer (required)

RealityScan CLI cannot enumerate a component's images. The manifest
system compensates:
- At zone-align time (identity-preserving scene): per-component XMP
  export -> {component name, zone, image basenames, count, georef bbox,
  mean reprojection error if obtainable from reports} -> JSON next to
  the exported .rsalign.
- Deterministic component renames before every export
  (zone_1_c0, ...), because RealityScan names exports after components.
- Imagelist exports per component for the enable/disable selections
  (selectImage set/union/sub composition from lists).
- Every accept/rollback decision and twin drop is logged to the
  manifest history - the audit trail for "what happened to component X".
