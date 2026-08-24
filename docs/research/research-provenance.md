# Research provenance

This project generalizes a working pipeline from the `AtomicDoomsday` mod in
`ywy50/7dtd-mods`. No Atomic Doomsday art or deployable bundle is copied here.

## 7DTD engine-resolution facts

The source project recorded these against 7 Days to Die V3.1.0 b14 by
decompiling the installed `Assembly-CSharp.dll` with `ilspycmd` and/or
`monodis`:

- `ModManager.PatchModPathString` resolves `@modfolder(Name):` using the
  `ModInfo.xml` internal name;
- `DataLoader.ParseDataPathIdentifier` splits bundle path and asset at `?`;
- `AssetBundleManager.LoadAssetBundle` opens the bundle lazily;
- `AssetBundleManager._get` reduces the asset request to file-name stem;
- block model loading subsequently checks the loaded object name, making exact
  case significant;
- item mesh and audio loading traverse the same `DataLoader` family, through
  `DataLoader.LoadAsset<T>` for `GameObject`, `Transform`, and `AudioClip`;
- `Audio.Manager.LoadAudio` resolves a `sounds.xml` `ClipName` bundle URI
  through that same path, and plays nothing beyond the AudioSource prefab's
  `maxDistance`, so a long-range sound needs a mod-owned AudioSource;
- `Audio.Manager.Play` switches to a sound node's `DistantClip` only past
  `DistantFadeStart` metres and stops the near clip past `DistantFadeEnd`;
  `DistantFadeStart` defaults to `-1`, meaning never, so a distant variant
  authored without setting it is never heard;
- `SoundsFromXml.ParseNode` reads each `SoundDataNode`'s `AudioSource`,
  `AudioClip`, and `DistantClip` — which is why a bundle URI works in all three
  — plus `Loop`, `AltSound`, `Noise`, `MaxVoices`, `MaxVoicesPerEntity`,
  `MaxRepeatRate`, `LowestPitch`, `HighestPitch`, `Channel`, `Priority`, and
  the crouch/noise scales, all matched case-insensitively from each element's
  first attribute; it also calls `DataLoader.PreloadBundle` on those names at
  parse time;
- `ItemClass.Init` parses `SoundTick` as `"<group>[,<delaySeconds>]"` with a
  one-second default, and `ItemClassTimeBomb.OnDroppedUpdate` plays it through
  `Entity.PlayOneShot` once per `SoundTickDelay` while `Meta` is above zero;
- `ItemClassesFromXml` and `BlocksFromXml` copy **every** parent property that
  the `Extends` `param1` exclusion list does not name. Deleting a property from
  a child definition therefore does not stop it being inherited — it must be
  excluded by name. Found live: a mod item's own `TintColor` line was removed
  and vanilla's red grenade tint kept multiplying the new olive paint, with a
  clean log, a loading bundle, and a resolving prefab;
- `ItemClassTimeBomb.setActivationTransformsActive` uses `FindInChilds`, which
  also finds inactive children, so an `ActivationTransformToHide` child is
  authored **active** and the engine hides it when holding starts;
- `ModManager.LoadUiAtlases` loads each immediate subfolder of a mod's
  `UIAtlases/` as a runtime-packed atlas, keyed by folder name, with each PNG
  keyed by its filename stem. The V3 item atlas cell measured **160 x 160**,
  read from the installed game's own
  `Data/Addressables/Standalone/automatic_assets_generic/itemicons.bundle`;
  `CustomIconTint` multiplies the icon's colour, so a leftover tint silently
  recolours new art;
- `BlockShapeModelEntity.getPrefab` substitutes `block_missingPrefab`, and
  items fall back to `@:Other/Items/Crafting/leather.fbx`, so a failed load
  still draws something and cannot be ruled out by eye;
- `ItemClass.GetDroppedCorrectionRotation` returns `(-90, 0, 0)`, and
  `ItemClass.CloneModel` applies `UpdateLight.SetTintColor`, which multiplies
  every material `_Color` by the item's `TintColor`.

Added by the second sweep of the source project (2026-08-23), each from
`ilspycmd` on the same V 3.1.0 b14 assembly unless stated:

- `DataLoader.ParseDataPathIdentifier` runs `ModManager.PatchModPathString`
  *before* splitting the `#…?…` form, recognises `@:` as an Addressable, and
  treats anything else as a `Resources` path; `ModManager.TryPatchModPathString`
  logs `[MODS] Mod reference for a mod that is not loaded` on an unknown
  `@modfolder(Name)`; `AssetBundleManager.LoadAssetBundle` treats a rooted
  path as final and a relative one as `Data/Bundles/Standalone<BundleTags.Tag>/…`;
  an opened bundle is cached for the session under its path.
- `GameIO.GetFilenameFromPathWithoutExtension` splits on
  `ResourcePathSeparators = { '/', '\\', '?' }`, which is the mechanism behind
  stem-only addressing; `BlockShapeModelEntity` registers loaded prefabs with
  `GameObjectPool.AddPooledObject` and reads `Model`, `ModelOffset`,
  `LODCullScale` but no scale property.
- The bundle is opened lazily by `LoadManager.LoadAsset`; `LoadManager.AddTask`
  takes the synchronous `LoadSync` branch on `GameManager.IsDedicatedServer`,
  so a dedicated server loads block model prefabs. Measured 2026-08-10: a
  Linux dedicated server opened a Windows-target bundle (probe modlet with a
  vanilla-manifest bundle plus a nonexistent stem: `ERR Model '…' not found`,
  no `Loading AssetBundle … failed`). The Windows client's and Linux server's
  `Entities/trees` differ in MD5 while both headers read 2022.3.62f2.
- `ModManager.LoadLocalizations` builds `mod.Path + "/Config"` and
  `Localization.LoadPatchDictionaries` opens `<that>/Localization.csv`,
  logging `[MODS] Loading localization from mod: <name>`; `Localization.Get`
  returns the key on a miss. Found live 2026-08-10 as every display name
  rendering as its id. **`ywy50/7dtd-mods/docs/best-practices.md` states the
  opposite ("mod root") with an "(Official + Measured)" tag and is wrong**;
  `AtomicDoomsday/scripts/build.sh` cites the same decompile and ships the
  file inside `Config/`. Decompiled evidence beat the wiki-sourced claim, and
  this repository once copied the wrong one.
- `ModManager.LoadUiAtlases` goes through `UIAtlasFromFolder.CreateUiAtlasFromFolder`;
  no atlas is loaded on a dedicated server; the default sprite lookup is the
  item's own name, `CustomIcon` overriding it, and `display_entry icon=` in
  `progression.xml` names a sprite too. `MultiSourceAtlasManager.GetAtlasForSprite`
  returns `atlases[0]` for an unknown sprite. The 160 px cell is the
  `icons_mip0_*` measurement.
- The server sends patched XML to a joining client via `NetPackageConfigFile`;
  `ModManager` loads assemblies from the local mod folder only. A
  `ModInfo.xml` `SkipWithAntiCheat="true"` returns
  `Mod.EModLoadState.SkippedDueToAntiCheat` on an EAC-on client before loading
  anything. `EntityPlayerLocal` is never constructed on a dedicated server
  (V3.1 assembly inspection).
- `ItemClass.CloneModel` resolves `DropMeshFile`, then `HandMeshfile`, then
  `Meshfile`; always adds `UpdateLightOnAllMaterials`; calls
  `SetTintColorForItem` with `TintColor` or the default `255,255,255`
  (`Block.StringToVector3` divides by 255) — white is a no-op; and disables
  every collider on the held copy. `EntityItem.createMesh` applies `DropScale`
  as a uniform local scale (overwriting, not compounding), sets the dropped
  rotation, and enables every collider found in the mesh on layer 13, adding
  `RootTransformRefEntity`. Vanilla `GrenadePrefab` carries a root
  `CapsuleCollider`; `GrenadePrefab` and `timedChargePrefab` are identity
  prefabs with mesh children at the origin (UnityPy on
  `automatic_assets_other/items.bundle`, 2026-08-22).
- `ItemClassTimeBomb.Init` splits `ActivationTransformToHide` on `;`;
  `setActivationTransformsActive` is called with `Meta != 0` from
  `OnMeshCreated`, `true` from `OnDroppedUpdate`, `false` from
  `OnHoldingReset`. `ActivationEmissive` keys on a renderer tag.
- `DynamicProperties.CopyFrom` honours `param1` entries naming a whole
  `<property class>` block or a dotted `Class.Property`; `ItemClassesFromXml`
  builds `Effects` from the child node only (`effect_group` is not inherited);
  `CreativeMode` is never inherited. Item/block/recipe names are global across
  mods and baked into save data.
- `GameManager.explode` calls `ExplosionClient` locally and broadcasts
  `NetPackageExplosionClient`; `ExplosionClient(Vector3, Quaternion, int
  _index, int _blastPower, float _blastRadius, float _blockDamage, int, List<BlockChangeInfo>)`
  instantiates `WorldStaticData.prefabExplosions[_index]` with its
  `AudioPlayer`, at `center - Origin.position` (`monodis` and `ilspycmd`
  agree). `Origin.OriginChanged` is the re-anchoring event (matches vanilla
  `LandClaimBoundsHelper`, which reuses `Materials/LandClaimBoundary`).
- `Audio.Manager.Play(Vector3 position, string group, int entityId = -1,
  bool, float volumeScale)` and `Audio.Manager.PlayInsidePlayerHead(group)`;
  `Block.SoundPickup` defaults to `craft_take_item`; installed
  `Data/Config/sounds.xml` has three clips under `buff_geiger_counter`.
- `GameManager` sets `Application.runInBackground = true` only under
  `Application.isEditor`, and `Application.backgroundLoadingPriority` is never
  assigned in `Assembly-CSharp` — the Proton async-load starvation at world
  load; `Awake IsFocused: False` is the log tell.
- A `Shape=ModelEntity` block without support becomes `EntityFallingBlock` in
  the server's stability pass and logs `fell off the world` on the dedicated
  log (observed live).
- `Constants.cVersionMajor/Minor/Build` = 3/10/14, formatted by
  `VersionInformation` as `V {Major}.{Minor/10}.{Minor%10} (b{Build})`.
- Unity 2022.3.62f2: `UnityEditor.AudioImporter.preloadAudioData` is
  `[Obsolete(…, true)]` (`ilspycmd -t UnityEditor.AudioImporter UnityEditor.dll`),
  found 2026-08-23 by `scripts/compile-editor-scripts.sh`.

### Environment: weather, fog, and light

Recorded 2026-08-24 by `ilspycmd` against the installed `Assembly-CSharp.dll`
for `Constants` 3/10/14 — `V 3.1.0 (b14)` in the engine's own display form,
`V.3.10.14` as `VersionInformation.SerializableString` prints the raw fields.
The editor matched to it is Unity 2022.3.62f2. These are the facts the
[environment-effects lane](../authoring/environment-effects.md) rests on; the
tool run was made in `ywy50/7dtd-mods` against this machine's install, and the
symbols were read from the decompile rather than from a mod's source.

- `WeatherManager.forceClouds` and `forceRain` override cover and
  precipitation on `0`–`1`, and are **`-1f` when unforced**; every reader gates
  on `>= 0f`. `SkyManager.fogDebugDensity` is `-1f` unforced, and
  `fogDebugColor` is ignored while its alpha is `0`. Restoring these means
  writing the sentinel back, not zero — zero is a valid forced value meaning
  permanently clear and dry.
- `WeatherManager.GetCloudThickness()` returns a percentage (`0`–`100`) and
  equals `forceClouds * 100f` while forced;
  `WeatherManager.Instance.GetCurrentCloudThicknessPercent()` is the same value
  on the `0`–`1` scale. `GetCurrentRainfallPercent()` is already `0`–`1` and
  returns `forceRain` while forced. So a baseline re-read during the effect
  returns the effect's own override, and a per-frame re-capture ratchets.
- `SkyManager.SetFogDebug(density, start, end)`, `SetFogDebugColor(color)`,
  `GetFogDensity()`, and `SetWeatherLightScale(scale)` are the fog and daylight
  controls; `WeatherManager.Instance.CloudsFrameUpdateNow()` applies a cloud
  change immediately.
- `WeatherManager.ParticlesFrameUpdate` applies the stock storm light scale at
  its end, so a mod's light reduction survives only as a postfix on it. It is
  an instance method taking an `EntityPlayerLocal` (called with the primary
  player), which makes it client-only independently of any
  `GameManager.IsDedicatedServer` guard.
- `WeatherManager.Cleanup()` resets `forceClouds`, `forceRain`,
  `forceSnowfall`, `forceTemperature`, and `forceWind`; `SkyManager.Cleanup()`
  calls `SetFogDebug()` and `SkyManager.Reset()` returns `weatherLightScale`
  to `1f`. All three run at teardown only, so they cover leaving a world and
  never cover an effect ending inside one.
- `EntityPlayerLocal.OnUpdateLive` is the local player's per-tick update and
  exists only where a local player does; a dedicated server never constructs
  one.

Authoring fact from the same pass, measured with Pillow rather than a
decompiler: a generated "opacity mask" may carry a **real alpha channel that is
not its own luma** (the measured source peaked at alpha 251 against luma 135).
Deriving alpha from brightness there caps the card near half opacity, which is
why `shamway generate cutout` has an `alpha` mode alongside `luma`.

### Evidence tiers

`strings` on an assembly proves a name exists, not a method body; treat such
a fact as "known to exist, API to be confirmed". `ilspycmd` (the primary)
and `monodis`/`ikdasm` (the second opinion) prove bodies. "It seemed to work
in game" is not a tier.

### Re-verifying after a game update

The facts above were recorded at various dates and carried forward on trust
until the source project re-decompiled all of them in one pass. Repeat that
pass after every game update, and record it in this shape:

| | |
|---|---|
| Installed build | `V 3.1.0 (b14)`, from `Constants` |
| Assembly | `$SEVEN_DAYS_TO_DIE_DIR/7DaysToDie_Data/Managed/Assembly-CSharp.dll`, mtime and size |
| Tools | `ilspycmd` version, `monodis`/`ikdasm` |
| Date | |
| Result | *N* claims re-decompiled, *M* confirmed, *K* corrected — and what the corrections were |

`scripts/install-tools.sh --with-research` installs the tools. Then, in
order: `shamway doctor` (does the game's revision still match the editor?),
`shamway build --probe`, re-decompile every method named on this page,
`shamway validate`, and a fresh client.

## Class-142 finding

The originating investigation compared rejected mod bundles with current stock
game bundles using a hand-written UnityFS/SerializedFile reader and UnityPy.
Both used the same Unity revision and Windows platform metadata, but rejected
bundles lacked class 142. Unity's own build log reported that AssetBundle and
particle modules were disabled; the project package manifest was empty.

The chain of evidence, so the next investigator can re-establish it:

1. **The message is Unity's, not the game's.** `strings` on the shipped
   `UnityPlayer.dll` contains `The AssetBundle '%s' could not be loaded because
   it is not compatible with this newer version of the Unity runtime…`; no
   7DTD assembly emits it. It is `AssetBundleLoadResult.NotCompatible` in
   `AssetBundle.bindings.cs` (UnityCsReference, 2022.3 branch), and the
   "newer runtime" wording means the bundle *looks pre-5.0* — which a bundle
   with no container object does. It says nothing about editor version, which
   is why a matching header never contradicted the error.
2. **What a correct object contains.** The shipped game's own
   `Data/Bundles/Standalone/Entities/trees` and `Entities` (2022.3.62f2,
   serialized platform 19, type trees on, UnityFS flags `0x243` = LZ4HC plus
   combined directory) each carry exactly one class-142 `AssetBundle` object
   with `m_RuntimeCompatibility: 1`, `m_PathFlags: 7`, a populated
   `m_Container` (713 entries for `trees`) and `m_PreloadTable`. This is what
   the game builds today, not an old format. `unityfs.py` checks the class ID;
   `inspect --deep` (UnityPy) can read the container to confirm every manifest
   entry is listed.
3. **The rejected bundles parsed to `[1, 4, 21, 23, 28, 33, 48]`** and no
   142, confirmed by UnityPy and by an independent hand-written reader.
4. **Unity's own build log said so**, with a stack trace.

Adding the built-in modules, forcing a full rebuild, and rejecting the warning
produced a class-142 container that a fresh client loaded. This pipeline keeps
all four lessons:

1. package modules are build inputs;
2. disabled-module warnings are fatal;
3. class 142 is a required artifact gate;
4. fresh-client acceptance remains required.

## Bundle-format facts, measured for the editorless writer

Everything `bundle_writer.py` emits was read out of a real artifact before it
was written, on 2026-08-23, against 7DTD V3.1.0 b14 and Unity 2022.3.62f2.
Two artifacts were dissected: a bundle the **installed game ships**
(`Data/Bundles/Standalone/Entities/Entities`, 1563 bytes — small enough to
decode by hand) and a **reference bundle built by this repository's own
`BundleBuilder`** from one PNG and one WAV. The tool was a scratch dissector
over this repository's own `unityfs.py` block decoder, cross-read with UnityPy.

Container, from the shipped bundle:

- `UnityFS` archive **format 8**; engine string `5.x.x`; revision
  `2022.3.62f2`; flags `0x243` (LZ4HC block, block table at the head,
  padding bit set);
- one directory node named `CAB-<32 hex>`, flags 4, holding the serialized
  file; a texture's pixels live beside it in `CAB-<hex>.resS` and a clip's
  bank in `CAB-<hex>.resource`.

SerializedFile, from the same file:

- **version 22**; the four legacy header fields are zero and the real
  `metadata_size`, `file_size` and `data_offset` live in the 28-byte extended
  header, big-endian, with `metadata_size` counted from the end of the 48-byte
  header (measured: metadata ended at 4029, declared 3981, 4029 − 48 = 3981);
- `target_platform` **19** (StandaloneWindows64) and **type trees present**
  (`has_type_tree = 1`) — so the writer emits them too;
- type-tree nodes are 32 bytes (`version u16, level u8, typeFlags u8,
  typeStrOffset u32, nameStrOffset u32, byteSize i32, index i32, metaFlag u32,
  refTypeHash u64`); an `Array` node carries `typeFlags = 1`; names are offsets
  into a local string buffer, or into Unity's built-in common string table when
  the high bit is set (the shipped file uses the common table for nearly every
  name, and so does the writer);
- object entries are 4-byte aligned; `byte_start` is relative to
  `data_offset`, and object data is 8-byte aligned.

Class-142 `AssetBundle` contents, decoded from the shipped bundle with UnityPy:
`m_RuntimeCompatibility: 1`, `m_PathFlags: 7`, `m_Container` mapping a
lowercased asset key to `{preloadIndex, preloadSize, asset: PPtr}`,
`m_MainAsset` a null PPtr, empty `m_Dependencies` and `m_SceneHashes`. These
are the values the writer emits.

Audio, from the editor-built reference bundle's `.resource` node:

- an `AudioClip` carries **no samples**; `m_Resource` names
  `archive:/CAB-<hex>/CAB-<hex>.resource` with an offset and size, and the
  bytes there begin `FSB5`;
- FSB5 header: magic, version 1, sample count, sample-headers size, name-table
  size, data size, **mode** (15 = Vorbis in Unity's own output; the writer uses
  2 = PCM16), then 4 + 4 + 16 + 8 bytes to offset 60;
- the 64-bit sample header decodes as `bit0 = has chunks`, `bits 1–4 =
  frequency index`, `bit 5 = channels − 1`, `bits 6–33 = data offset / 32`,
  `bits 34–63 = sample count`. Decoding Unity's own header returned frequency
  index 8 (44100), 1 channel, offset 0, **4410 samples** — exactly the WAV that
  went in, which is what makes the layout trustworthy rather than plausible;
- the data section begins at `60 + sampleHeadersSize + nameTableSize`, padded
  by Unity to a 32-byte boundary; the writer pads the same way.

Texture, from the same reference bundle: Unity streams pixels into `.resS`
with mip maps generated; the writer instead writes `image data` inline with
`m_StreamData` empty and `m_MipCount: 1`, which the runtime accepts. Unity's
first pixel row is the **bottom** one — a texture written top-down loads
without error and renders upside down, so the writer flips.

### Mesh finding

Measured 2026-08-24 with UnityPy against
`Data/Bundles/Standalone/Entities/trees` in the installed game — a bundle the
game ships, carrying 148 `Mesh` objects. `ScotsPineMed01_LOD3` was decoded
field by field and is what `bundle_writer.mesh` reproduces:

- `m_VertexData` declares the engine's **full 14-slot channel table** and
  zeroes every slot the mesh does not use. The measured mesh filled slot 0
  position (`format 0` float, dimension 3), 1 normal (float3), 2 tangent
  (float4), 3 colour (`format 2`, UNorm8, dimension 4) and 4 UV0;
- all channels sit in **stream 0**, tightly packed, at the offsets their
  predecessors leave: 0, 12, 24, 40, 44 for a 56-byte stride. `m_DataSize` was
  2688 bytes for 48 vertices — 48 × 56 exactly, which is what proves the
  stride is the plain sum and not padded;
- `m_IndexFormat: 0` is UInt16, and `m_IndexBuffer` held 192 bytes for the
  96 indices the single submesh declares;
- the submesh's `localAABB` equals the mesh's `m_LocalAABB` for a one-submesh
  mesh; `m_CompressedMesh` is present with every vector empty;
- `m_IsReadable: true` and `m_CookingOptions: 30` on a mesh the game ships.

The writer fills slots 0, 1 and 4 only. It does not write tangents, so a
normal-mapped material would have none, and it writes one submesh, so one mesh
file is one material's worth of geometry.

Runtime confirmation, 2026-08-24: a synthesized bundle carrying two meshes was
loaded by a real Unity 2022.3.62f2 runtime through `shamway verify-bundle` —
a UV-mapped box at `vertices=8 triangles=12 submeshes=1 uv=True bounds=(0.40,
0.80, 0.40)`, matching the authored extents, and a UV-less icosphere at
`vertices=42 triangles=80 uv=False`. The engine's own loader, its own `Mesh`
class, its own bounds arithmetic.

The **handedness conversion** is this writer's, not the format's: glTF, OBJ,
STL and PLY are right-handed and Unity is left-handed, so X is negated and
triangle winding reversed — the conversion Unity's own importers and every
glTF runtime for Unity apply. It has no evidence in the artifact above because
a mirrored mesh is a perfectly valid `Mesh` object; the test that holds it is
`test_the_right_handed_source_is_converted_rather_than_mirrored`.

### Prefab objects: GameObject, Transform, MeshFilter, MeshRenderer

Measured 2026-08-24 with UnityPy against `Entities/trees`, one real prefab of
each class. `bundle_writer.mesh_prefab` reproduces these values:

- `GameObject`: `m_Component` is a list of `{"component": PPtr}`, plus
  `m_Layer`, `m_Name`, `m_Tag` and `m_IsActive`. The name lives here and
  nowhere else in the group;
- `Transform`: `m_GameObject` back-pointer, identity `m_LocalRotation`
  (`w: 1.0`), zero position, unit scale, `m_Children`, and a null `m_Father`
  for a root;
- `MeshFilter`: two PPtrs, `m_GameObject` and `m_Mesh`, and nothing else;
- `MeshRenderer`: 26 fields, of which the ones that are not obvious were taken
  rather than guessed — `m_LightmapIndex: 65535` and
  `m_LightmapIndexDynamic: 65535` are Unity's "no lightmap" sentinel, not
  missing data; `m_RayTracingMode: 2`; `m_LightProbeUsage: 1`;
  `m_ReflectionProbeUsage: 1`; `m_RenderingLayerMask: 1`;
  `m_LightmapTilingOffset` is `(1, 1, 0, 0)`; `m_Materials` is a PPtr list.

Components carry **no name** and are absent from the class-142 container in
the game's own bundles, so the writer marks them `in_container=False`. Only
the `GameObject` is addressable, which matches what
`DataLoader.LoadAsset<GameObject>` asks for.

Runtime confirmation, same day: a real Unity 2022.3.62f2 runtime loaded a
synthesized prefab through `shamway verify-bundle` and resolved its graph —
`components=3 mesh=shamwayProbeMesh materials=0 children=0`. The renderer
found the synthesized `Mesh` through the `MeshFilter`; `materials=0` is the
honest state of the lane, and an empty renderer draws nothing.

### A material's shader: what is measured closed, and what is not

**Correction, 2026-08-24.** An earlier version of this section concluded that
"compiled shader bytecode is what an offline writer cannot produce" and the
pages that cited it said a shader was impossible offline, full stop. **That was
wrong**, and it is the reason AGENTS.md now carries "Never declare an
impossibility you did not test". What had actually been measured was that a
shader cannot be *borrowed*; nothing had been checked about *authoring* one.
The two findings below stand. The conclusion drawn from them did not.

Borrowing, measured with UnityPy against the installed game — both routes
closed:

- the shipped player's `7DaysToDie_Data/Resources/unity default resources`
  carries **six** shaders, all internal: `Hidden/InternalErrorShader`,
  `Hidden/InternalClear`, `Hidden/Internal-Colored`, `Hidden/Internal-Loading`,
  `GUI/Text Shader`, `Hidden/FrameDebuggerRenderTargetDisplay`. Nothing a prop
  could use;
- the game's own `trees` bundle **embeds its shaders**: 10 `Shader` objects
  inside the archive, and every `Material` in it points at one with
  `m_Shader.m_FileID: 0` — same file. So a mod bundle must carry its own;
- the one external that bundle declares is `Resources/unity_builtin_extra`,
  so the engine does resolve external references at runtime. Recorded as a
  route, not a plan: the player has no such file on disk.

Authoring, checked on the same host the false claim was written on:

```bash
which vkd3d-compiler glslangValidator
```

Both were **already installed**. `vkd3d-compiler` (WineHQ's vkd3d-shader, MIT,
`/usr/bin/vkd3d-compiler`, package `vkd3d` 1.19) compiles HLSL to `dxbc-tpf` —
shader-model 4/5 **DXBC**, which is exactly what Unity's d3d11 sub-programs
carry. `glslangValidator` emits the SPIR-V the Vulkan sub-programs carry. So
the bytecode half has an open-source producer, and the claim that only Unity's
compiler can make one was never checked before it was written down.

### Shader object and sub-program blob layout

**This format is documented upstream, not here.** The container - the
per-platform LZ4 blobs, the 12-byte `(offset, length, segment)` record table,
the code-blob record, the 38-byte DX11 program-data header, the parameter blob
and the bind-channel block - belongs to the engine, not to this pipeline, and
lives in `hordeforge/7dtd-engine-research`:

- [`docs/shader-subprogram-blob.md`](https://github.com/hordeforge/7dtd-engine-research/blob/main/docs/shader-subprogram-blob.md)
- reproduce it with that repository's `tools/shader_blob_dump.py`, which
  re-derives every claim and exits non-zero on disagreement.

It was written there over 2026-08-24 in three parts, each measured against the
stock V3.1.0 b14 install and each gated by that tool:

| Part | What it settles | Sample |
|---|---|---|
| the code blob and its 38-byte header | header bytes 1 to 3 are the SRV, constant-buffer and sampler counts, derived by walking the DXBC token stream | 7366 d3d11 sub-programs |
| the parameter blob | the binding table Unity keeps instead of the stripped `RDEF` chunk | 3403 records, re-emitted byte for byte |
| the bind-channel block | the `ParserBindChannels` block closing every record, and its mesh-channel mapping | 7366 sub-programs |

What this repository keeps is only what a **writer** needs on top of that page,
and the evidence that its output is accepted.

**The 38 bytes this project could not decode are decoded.** The earlier entry
here recorded them as "a per-sub-program descriptor this project has not
decoded", on two samples. Widening to 7366 and correlating against each
program's own bytecode resolved them, and the note is superseded rather than
merely appended to: nothing in the container is undecoded now except header
byte 4 (UAV-related, zero unless the program declares a UAV) and the meaning
of the three empty `m_PlayerSubPrograms` groups.

### Unity's built-in constant buffers, as a writer must declare them

Measured from the same 3403 parameter blobs. These offsets are the engine's;
a writer that gets one wrong renders the mesh in the wrong place rather than
failing, so none of them is invented:

| Buffer | Size | Members (offset) |
|---|---|---|
| `UnityPerDraw` | 176 | `unity_ObjectToWorld` 0, `unity_WorldToObject` 64, `unity_LODFade` 128, `unity_WorldTransformParams` 144 |
| `UnityPerFrame` | 368 | `glstate_lightmodel_ambient` 0, `glstate_matrix_projection` 80, `unity_MatrixV` 144, `unity_MatrixInvV` 208, `unity_MatrixVP` 272 |

`stageCounts` is a per-platform constant across all ten stock `trees` shaders,
independent of tier count: **2** for d3d11 (vertex and fragment are separate
programs) and **1** for OpenGLCore and Vulkan (one source carries both stages
behind `#ifdef VERTEX` / `#ifdef FRAGMENT`).

### What the runtime said about a synthesized shader

`shamway verify-bundle` on a real Unity **2022.3.62f2** editor, the
game-matched revision, against a bundle this writer produced:

```text
VERIFY-SHADER: 'Shamway/Unlit' isSupported=True passes=1 renderQueue=2000 properties=1
VERIFY-MATERIAL: 'prop_mat' shader='Shamway/Unlit' shaderSupported=True _MainTex=prop_albedo
VERIFY-PREFAB: components=3 mesh=prop_mesh materials=1 children=0
```

`Shader.isSupported` is the engine's own verdict on a compiled shader, and it
is the check that found the one structural error in this work. Before the
bind-channel block was written, the same shader produced:

```text
Failed to load GpuProgram from binary shader data in 'Shamway/Unlit'.
VERIFY-SHADER: 'Shamway/Unlit' isSupported=False
```

Three variations moved nothing (a second platform, corrected `stageCounts`, a
real temp-register count). What isolated it was a **bisect**: stock blob
contents inside a synthesized container loaded, which cleared the container,
the record table, the parameter blobs and the `Shader` object, and left the
record wrapper - which a byte diff then showed 32 bytes short. That is the
whole value of an editor here: an offline gate this repository wrote would
have called the broken shader fine, because it was structurally valid by every
rule this repository knew.

Two things the runtime did **not** establish, and no offline gate can:

- **it is a load, not a look.** Nobody has yet seen this shader draw. The test
  cube carries no UVs, so its texture samples one texel; a stretched or
  upside-down texture passes every check above.
- **it is not 7DTD.** A Unity editor is not the game. Acceptance still ends at
  `shamway acceptance-provider`, a fresh client, and a person looking.

### The shader lane's host dependency has a minimum version, and two distributions miss it

**Measured 2026-08-24**, on a GitHub `ubuntu-latest` runner and on the Arch
authoring host, with the tool itself:

```bash
vkd3d-compiler --print-source-types
```

| Host | vkd3d | Reads HLSL |
|---|---|---|
| Arch (`pacman -Qo /usr/bin/vkd3d-compiler` → `vkd3d 1.19-1.1`) | 1.19 | yes |
| `ubuntu-latest` runner, `apt install vkd3d-compiler` | 1.2 | **no** |

HLSL source support entered vkd3d-shader in **1.3** (WineHQ release
announcement, March 2022:
<https://www.winehq.org/pipermail/wine-announce/2022-March/000549.html> — "the
`hlsl` source type specifies High Level Shader Language source code"). Debian
and Ubuntu both still package 1.2: `vkd3d-compiler 1.2-15build1` in Ubuntu
noble and `1.2-15+b2` in Debian sid (packages.ubuntu.com, packages.debian.org,
read 2026-08-24). Fedora Rawhide packages `vkd3d-compiler 1.17`.

What that cost before it was measured: `capabilities.py` probed with
`shutil.which` alone, so the packaged 1.2 reported **available**, `pack_directory`
took the prefab branch, and the build died half-way through with the tool's own
message:

```text
ERROR: vkd3d-compiler failed for profile vs_4_0: Invalid source type 'hlsl' specified.
```

The registry now asks the binary what it reads rather than whether it exists,
which is the same question the writer asks two steps later. A host with 1.2
reports the capability unusable **with the reason**, `doctor` says so instead of
telling it to install what it already has, and the mesh lane degrades to a bare
`Mesh` with a printed caveat — the behaviour that was always intended for an
absent tool, now reached by a present-but-incapable one too.

CI gates both states: `.github/workflows/ci.yml` installs the packaged 1.2,
asserts the degradation, then builds vkd3d 1.19 from source and asserts the
whole prefab chain.

**The source build takes the release tarball, not a git clone**, and that is a
measurement too. A clone fails on this host and on a runner alike:

```text
widl is required to generate include/vkd3d_dxgibase.h
libs/vkd3d-shader/hlsl.h:25:10: fatal error: vkd3d_d3dx9shader.h: No such file or directory
```

`widl` is Wine's IDL compiler, so a clone build drags in Wine to generate
headers. `dl.winehq.org/vkd3d/source/vkd3d-1.19.tar.xz` ships those headers and
a pre-generated `configure`; built on 2026-08-24 against Khronos SPIRV-Headers
and Vulkan-Headers with nothing else, it produced
`vkd3d shader compiler version 1.19` listing `hlsl` among its source types.
WineHQ publishes a GPG `.sign` beside each tarball but no checksum file, so
`install-tools.sh` pins the SHA-256 it verifies
(`034613605baab8ba84674f8d272cf22b5e86bc6bc03fc5728ef9bce07308baa6`) and
refuses a version override that arrives without one.

## Class-table prefix window, measured for the offline reader

Measured 2026-08-24 against the installed game's own bundles (V3.1.0 b14) with
a scratch dissector over this repository's `unityfs.py`, plus `cProfile` on the
same call. The shipped `Data/Bundles/Standalone/Entities/trees` bundle is a
650 MB archive whose single directory node is a 111.6 MB serialized file; its
type table holds **23 types and ends 127,888 bytes into that node**. The
reader's fixed decompression window was then 32 MiB, so every
`doctor`/`status`/`validate` call that reads the game revision decompressed 257
LZ4HC blocks to reach a table that ends inside block 2: **1323 ms per
`inspect_bundle` call** (4.07 s of it `_lz4_decompress` under the profiler).

The window now starts at 1 MiB and grows ×4 up to the same 32 MiB cap before a
full-node read, which answers this bundle in **40.7 ms** with byte-identical
class IDs (`2022.3.62f2`, 23 classes). The growth ladder is pinned by tests:
a fixture whose table runs ~1.4 MiB parses on the second rung, and a table
truncated past the first window still fails with the bounded error.

## Official and community references

- Unity `BuildPipeline.BuildAssetBundles`:
  <https://docs.unity3d.com/2022.3/Documentation/ScriptReference/BuildPipeline.BuildAssetBundles.html>
- Unity AssetBundle Browser:
  <https://github.com/Unity-Technologies/AssetBundles-Browser>
- OCB 7DTD exporter:
  <https://github.com/OCB7D2D/UnityAssetExporter>
- UnityPy: <https://github.com/K0lb3/UnityPy>
- AssetsTools.NET: <https://github.com/nesrak1/AssetsTools.NET>

The OCB exporter informed the Windows graphics-API set and remains a useful
comparison. Exporter API shape alone did not fix the missing container; module
inclusion did.

## Current-version evidence

At extraction time, the configured local **V 3.1.0 b14** install's shipped
`Data/Bundles/Standalone/Entities/Entities` reported Unity **2022.3.62f2**,
changeset **7670c08855a9** — the same pairing the source project pinned in
`ProjectSettings/ProjectVersion.txt` and hardcoded in its editor installer.
Unity's release service independently resolves that revision to the same
changeset and to the windows-mono module MD5 `b5adce741fb7633c039e216348110332`
the source project had hardcoded, which is how the generalized installer
replaces that table without losing accuracy.
The Atomic Doomsday bundle reported the same revision, contained class 142,
and all seven of its XML bundle references passed the source validator.

That version is evidence for the extraction, not a forever constant. New
consumer projects discover their installed game's revision.

The source validator that `validation.py` generalizes was proven both ways
before extraction: it passed on the vanilla client and Linux-server bundles
(both 2022.3.62f2) and failed on all six seeded fixture faults — wrong stem,
case mismatch, duplicate stem, missing bundle, wrong mod name, and a missing
`@modfolder(…)`. Rebuilds were measured byte-identical by SHA-256 before and
after `ForceRebuildAssetBundle`, which is the evidence behind the
determinism advice in [bundle-generation.md](../bundles/bundle-generation.md).

## Live verification of the class-142 finding

The extraction inherited the class-142 rule from the source project's
investigation. It has since been reproduced directly against Unity 2022.3.62f2
and the same installed game, which is stronger evidence than inheritance:

With `Packages/manifest.json` emptied, Unity **exited zero** while logging

```text
'AssetBundle' is not supported because the module AssetBundle is disabled in the build.
'BoxCollider' is not supported because the module Physics is disabled in the build.
```

and wrote a bundle whose serialized class table was `[33, 1, 21, 48, 4, 23]` —
no class 142. The pipeline rejected it on the log gate, and the previously
staged bundle was left byte-identical. Restoring the manifest produced a
class-142 bundle that passed every gate.

## Nuclear-blast voice provenance (2026-08-24)

The dedicated `nuclear-blast` voice was added after a target-game human listen
rejected the generic `blast` result as both too faint and not recognisable as a
nuclear detonation. Its structural choices are grounded in two kinds of
evidence rather than in a renamed oscillator:

- Lawrence Livermore National Laboratory's restored and declassified US
  atmospheric-test film archive documents the relevant event class and the
  large, evolving atmospheric/terrain presentation:
  <https://www.llnl.gov/article/43956/llnl-releases-newly-declassified-test-videos>.
- Arrowsmith and Bowman, *Explosion yield estimation from pressure wave
  template matching*, JASA 141 (2017), uses full measured pressure waveforms
  rather than reducing an explosion to a peak value; the article is US
  Government work and available as PMC5459613:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC5459613/>. That supports treating
  the pressure front and following waveform/coda as the identity, rather than
  assuming peak normalization can turn a generic impact into a nuclear event.

The generated clip deliberately transposes infrasonic identity into audible
low frequencies for consumer speakers. It is therefore a designed game asset,
not a scientific reconstruction. `check-sound` proves its file properties;
only a human listen through the target game's mixer can accept its character.

The same reviewer identified the pre-existing generic `blast` voice as a known
defect: it did not read as a bomb or blast and sounded like crackling. Its near
variant therefore replaces sparse high-band debris and a millisecond-scale
crack with a wider pressure hit, dense audible body, reflected report, and
rolling tail. This remains human-verdict provenance, not a scientific claim;
the test suite locks reproducibility, duration, and file gates, while each
consumer still owes listening in its target mixer.

A follow-up target-game listen of the first `nuclear-blast` version found its
event character substantially better, but heard artificial overdrive and
unclean crackling at the loud end despite zero digitally clipped samples. The
generator deliberately applied `tanh` to the shock, tonal body, and final mix;
that nonlinear saturation was therefore removed rather than hidden by a lower
peak. The consumer separately requested slightly more level, which belongs to
source placement or mixer gain rather than reintroducing waveform distortion.

The fully linear follow-up was also human-rejected: despite a 2 m virtual
source it sounded like a weak poof, and measured source RMS fell from `0.17668`
to `0.09476`. The third design adds peak-envelope dynamics compression before
normalization. This changes level through smooth gain control, not sample
waveshaping, so body and coda can rise without restoring the overdriven
harmonics the first follow-up removed.

The compressed follow-up remained a human-rejected poof because it lacked an
explosion-impact onset. Inspection showed the designed pressure pulse was
largely one-sided and low-frequency before the mandatory 12 Hz high-pass. The
next design added an explicitly audible impact layer—a 165→42 Hz boom sweep
and one dense band-limited pressure crack—while retaining the clean compressed
body/coda and excluding the old sparse debris crackling. Target-game listening
then rejected that version as a dry thump with no perceived lows or boom: the
short crack masked a low sweep that did not sustain enough energy through the
game mixer. The follow-up makes the boom an independent 2.4-second 108→44 Hz
pressure wave, adds a second harmonic for small-speaker audibility, extends its
decay to 1.15 seconds, and substantially lowers the crack in the mix.

Target-game listening judged that follow-up somewhat better, specifically
validating the sustained low layer, but found it lacked the mid/high shattering
character needed for the blast front. The next revision retains the low design
unchanged and adds a dense 650–7,800 Hz tearing-noise burst with a 0.42-second
decay and continuous fast amplitude variation. It is deliberately a coherent
pressure-front texture rather than the earlier sparse debris crackling.

Target-game listening again found the direction better, but the initial thump
remained slightly too prominent relative to the shatter and thunder character.
The follow-up slows the boom attack from 12 to 35 ms and reduces the shock,
boom, and short-crack mix gains. It spends the recovered headroom on three
overlapping delayed copies of the dense shatter front and a separately filtered
32–520 Hz rolling thunder bed with a 160 ms onset and 2.6-second decay.

The target-game repeat judged that design “way better,” validating its layered
structure, but still heard too much short low-mid thump and too little deep
impact. The next revision moves the primary sweep down from 108→44 Hz to
92→38 Hz, slows its attack, reduces its second harmonic and mix gain, and
further lowers the shock/crack. A separately phased 62→44 Hz plus 43→34 Hz
pressure layer rises over 65 ms and decays over 1.75 seconds, supplying the
missing depth without another abrupt transient.

Target-game listening rejected that deeper-pressure revision: it still had too
much knock and weakened the previously successful perception of thunder. The
next revision removes the added deep-pressure oscillators, restores the
108→44 Hz PR #43 boom and its shatter/thunder layers, then limits its change to
softening and lowering the initial shock, boom harmonic, and short crack.

Listening then clarified that the small remaining excess was not the initial
knock but the delayed low/mid thump. The final current-pass adjustment changes
only the first terrain return, at 0.34 seconds, from gain `0.78` to `0.68`.
The accepted opening, shatter, and rolling-thunder structure is unchanged;
further subjective revision is deferred to a later review.

The same investigation decompiled installed V3.1 `Assembly-CSharp.dll` with
`ilspycmd -t Audio.Manager`. `Audio.Manager.Play(Vector3, ...)` subtracts
`Origin.position` internally. A caller must pass one absolute world coordinate;
pre-rebasing it applies the floating origin twice. A source-project listening
run also rejected a 40 m virtual source as too faint through the stock explosion
prefab, which is why the authoring guide now says to validate a much closer
virtual source instead of presenting 40 m as a safe default.

## Module resolution is not module declaration

Testing the above turned up a fact worth recording, because it changes what
"remove a module" means. Deleting `com.unity.modules.assetbundle` from
`manifest.json` did **not** remove it: `packages-lock.json` pinned the
previously resolved set, and after deleting the lock the module returned at
`depth: 1`, pulled in transitively by
`com.unity.modules.unitywebrequestassetbundle` and
`com.unity.modules.unitywebrequestwww`.

So a mod usually acquires the AssetBundle module by accident and works, and
`doctor`'s manifest check is necessary but not sufficient: what ships is what
Unity resolved, not what was declared. The class-142 artifact gate is what
actually decides, which is why it inspects the built file rather than the
project.
