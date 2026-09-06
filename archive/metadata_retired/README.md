# metadata_retired/ - texture and unwrap presets retired by decision D13

Retired 2026-09-05 (owner, `docs/DECISIONS.md` D13): every workflow textures
and unwraps with `unwrapStyle=AdaptiveTexelSize` at a 4096 page cap
(`RS_CLI/Metadata/Texturing_AdaptiveTexel_4k.xml` /
`Unwrapping_AdaptiveTexel_4k.xml`), never 16K and never a forced 4 x 8K page
budget, and the final unwrap falls back to `Unwrapping_MaxCount4_4k.xml`
only when adaptive rejects a mesh. Nothing live references the files below
(`testing/test_texture_policy.py` pins that); `modules/preflight.py` blocks
any live preset above 4096. They are kept because FINDINGS, the rs-reference
manual and the NA156..NA168 production records cite them by name, and so an
old project's texture layout can still be read back.

| File | Style | Pages | Max res | Last live use |
|---|---|---|---|---|
| `Texturing_MaxTextureCount4_8k.xml` | `MaxTexturesCount` | 4 | 8192 | `GenerateModel.bat` [6/8] and `ModelToFinal.bat` preset `4x8k` (default), 2026-07-31 .. 2026-09-05; the NA165/H2060 high-poly bakes |
| `Unwrapping_Simplified_4x8k.xml` | `MaxTexturesCount` | 4 | 8192 | `GenerateModel.bat` [8/8] and the `4x8k` unwrap in `ModelToFinal.bat`, same window |
| `Texturing_MaxTextureCount1_8k.xml` | `MaxTexturesCount` | 1 | 8192 | `ModelToFinal.bat` preset `8k` (opt-in) |
| `Texturing_MaxTextureCount1_16k.xml` | `MaxTexturesCount` | 1 | 16384 | `ModelToFinal.bat` preset `16k` (opt-in) |
| `Texturing_MaxTextureCount4_16k.xml` | `MaxTexturesCount` | 4 | 16384 | `GenerateModel.bat` [6/8] until the 8K cap of 2026-07-31; unreferenced since |
| `Unwrapping_Simplified_4x16k.xml` | `MaxTexturesCount` | 4 | 16384 | `GenerateModel.bat` [8/8] until 2026-07-31; unreferenced since |
| `Texturing_HighPolyTexture.xml` | `MaxTexturesCount` | 2 | 16384 | `ModelToFinal.bat` preset `highpoly`; `AlignImagesFromFolder.bat` (deprecated) |
| `Texturing_SimplifiedTexture.xml` | `MaxTexturesCount` | 2 | 16384 | byte-identical to `Texturing_HighPolyTexture.xml`; declared by `AlignImagesFromFolder.bat`, consumed by nothing |
| `Unwrapping_Simplified.xml` | `MaxTexturesCount` | 1 | 16384 | `ModelToFinal.bat`'s unwrap for every preset but `4x8k` (the live 16K leak, rs-reference 10 A4) and `AlignImagesFromFolder.bat` |

Reading an old project: a model whose report says `Unwrapping style: Maximal
texture count, 4 x 8192` was baked with the first two rows.
