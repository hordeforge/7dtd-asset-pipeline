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

> **Correction, 2026-08-24 (later the same day).** The `isSupported=true` below
> was measured with `-nographics`, where there is no device to compile a
> sub-program against and the value means nothing. Re-measured with a real
> graphics device, the same bundle reports **`isSupported=False`**, `passes=3`,
> and the material's `_MainTex=<unbound>`:
>
> ```text
> VERIFY-SHADER: 'Shamway/Unlit' isSupported=False passes=3 ... device=OpenGLCore
> VERIFY-FAIL: shamway/unlit loaded but the runtime reports it unsupported
> ```
>
> The synthesized shader **does not run**. A block using it places in 7DTD and
> renders nothing, which is how this was found. `verify-bundle` now prints the
> graphics device beside the verdict and refuses to call the headless answer a
> verdict at all; `verify-bundle --draw` is the measurement that has one.

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

- **it is a load, not a look.** At this measurement nobody had yet seen this
  shader draw; the first live-client look has since happened and signed off
  against an orientation card ([blockers.md](../status/blockers.md)). The rule
  stands either way: every check above passes identically on a stretched or
  upside-down texture.
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

### What a live client says about a synthesized prefab

**Measured 2026-08-24**, 7 Days to Die **V.3.10.14** through
`shamway script playtest-acceptance`, on a **freshly generated world**, against
a bundle written with no editor anywhere in its path:

```text
shamwayPropProof: shamwayPropProof children=0 renderers=1
shamwayPropProof_mesh: shamwayPropProof_mesh vertices=24 submeshes=1 bounds=(0.30, 0.50, 0.20)
shamwayPropProof_mat: shamwayPropProof_mat shader=Shamway/Unlit
shamwayPropProof_albedo: shamwayPropProof_albedo 256x256 RGBA32
SUMMARY pass=5 fail=0 skip=0 total=5
```

Every one of those is a `DataLoader.LoadAsset<T>` by **stem**, the way the
engine resolves a `#@modfolder(...)` URI, so the class-142 `m_Container` table
this writer emits is being read by the game rather than by this repository's
parser. Four things that could each have been wrong and were not:

- the **prefab answers to the source file's stem** — the name `Meshfile` and
  block `Model` resolve — rather than the mesh answering to it;
- it carries its renderer: `renderers=1`, not an empty `GameObject`, which is
  what a prefab with a dropped `MeshRenderer` would have reported;
- the mesh's bounds are what was authored (0.30 x 0.50 x 0.20 after the Y-up
  conversion), so the vertex stream, channel table and index buffer decoded;
- the material names `Shamway/Unlit`, the shader compiled here by
  `vkd3d-compiler` — the engine followed a cross-object `PPtr` chain the writer
  resolved by name, into a shader no Unity editor produced.

A fifth case asked for a stem the bundle does not contain and got null, so
those passes are not a loader answering everything.

**The first run of this suite failed, and the defect was ours.** `acceptance.plan`
mapped a manifest entry's extension to a class — `.glb` to `Mesh` — and asked
for it at the bare stem, which the prefab now owns:

```text
shamwayPropProof: LoadAsset<Mesh> returned null
FAIL shamwaypropproof_bundle/load_shamwayPropProof
```

The engine answered correctly. The provider now derives its cases from
`bundle_writer.synthesized_members`, the writer's own naming, so an extension
mapping cannot drift from the writer again.

**This is a load, not a look.** Nothing here says a pixel was rasterized: every
case above passes on a prop that draws mirrored, face-down, or in the wrong
place entirely. [status/blockers.md](../status/blockers.md) entry 6 holds that,
and it is the only thing left on this lane.

### The GLCore sub-program record, read out of the game's own bundles

**Measured 2026-08-24** with UnityPy and `lz4.block` against the shipped
`Nature/SpeedTree Billboard`, whose blob carries a `ShaderCompilerPlatform`
15 (`GLCore`) entry. The blob's record table is
`u32 count` then `count × (u32 offset, u32 length, u32 segment)`, which is what
`assemble_blob()` writes — an earlier reading of it as
`(index, offset, length)` was simply wrong and produced a zero-length record.

A GLCore **code** record is:

```text
u32  BLOB_VERSION (202012090)
u32  program type (6 = GL_CORE_32)
u32  ×4 zero
u32  keyword count
     per keyword: u32 length, bytes, pad to 4      e.g. 1 × "DIRECTIONAL"
u32  source length
     GLSL source, pad to 4
```

The source carries **both stages in one record**, which is why `stageCounts`
for GLCore is 1 where d3d11 is 2:

```glsl
#ifdef VERTEX
#version 150
#extension GL_ARB_explicit_attrib_location : require
...
#endif
#ifdef FRAGMENT
...
```

`source_blob()` writes that layout with a keyword count of zero, and
`UNLIT_GLSL` has the same `#ifdef` shape, so neither is obviously wrong.

**One discrepancy is measured and not yet explained.** Every parameter record
in the stock GLCore blob is program type **2** — the histogram across the whole
blob is `{2: 236, 6: 334}`, nothing else. This writer emits its two parameter
records as types **3** and **1**, and emits the same GLSL source twice as two
type-6 records:

```text
stock GLCore : types {2 × 236, 6 × 334}
this writer  : types [3, 1, 6, 6]
```

That is a fact about the bytes, not yet a diagnosis: the parameter types may be
per-stage and legal, or they may be why the runtime answers `Failed to load
GpuProgram from binary shader data`. Deciding it needs the stock type-2 record
decoded and compared against `ParameterBlob.to_bytes()`, which is the next
measurement rather than a change to make now.
[reports/2026-08-24-synthesized-shader-does-not-run.md](../reports/2026-08-24-synthesized-shader-does-not-run.md)
holds the failure this belongs to.

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


## The tail of a GLCore sub-program record

**Measured 2026-08-24** with `lz4.block` + `struct` over the twelve type-6
records of `Legacy Shaders/Transparent/Cutout/VertexLit`, read out of the
installed game with UnityPy. Editor 2022.3.62f2, `ShaderCompilerPlatform` 15
(GLCore), record version `202012090`.

A GLCore code record **does not end at its source text**. After the source, and
after that source is padded to a 4-byte boundary, come two more `u32` words:

| Word | Value observed | Meaning |
|---|---|---|
| 0 | `19` or `57` | vertex-attribute bitmask |
| 1 | `0` in all twelve | not decoded |

All twelve records carry exactly eight trailing bytes; the 9–11 bytes a naive
subtraction shows are those eight plus the source's own padding.

The mask indexes Unity's `VertexAttribute` enum. That was derived, not assumed,
from two records whose declared `in_*` names differ:

| Record | Declares | Mask | Bits |
|---|---|---|---|
| 6 | `in_POSITION0`, `in_NORMAL0`, `in_TEXCOORD0` | 19 | 0, 1, 4 |
| 14 | `in_POSITION0`, `in_COLOR0`, `in_TEXCOORD0`, `in_TEXCOORD1` | 57 | 0, 3, 4, 5 |

The two share exactly `POSITION` and `TEXCOORD0`, and exactly bits 0 and 4;
subtracting gives `NORMAL`=1, `COLOR`=3, `TEXCOORD1`=5. That is
`VertexAttribute` — `Position, Normal, Tangent, Color, TexCoord0, TexCoord1, …`
— with bit 2 (`Tangent`) unobserved here and inferred from the enum's order
alone, so treat bit 2 as the one value in this table that no artifact
confirmed.

**Why it matters:** this writer omitted both words until 2026-08-24. The
runtime's entire report of an eight-byte-short record was `Failed to load
GpuProgram from binary shader data` and `Shader.isSupported == False`. It
named no length and no field. `tests/test_shader_writer.py`,
`GLCoreRecordTailTests`, is what keeps the tail present.

## GLSL 150 needs the location extension declared in *each* half

**Measured 2026-08-24** with `glslangValidator` (`/usr/bin/glslangValidator`),
by splitting `UNLIT_GLSL` on its `#ifdef VERTEX` / `#ifdef FRAGMENT` guards —
the way Unity's loader does — and compiling each half alone:

```text
ERROR: 0:7: 'location' : not supported for this version or the enabled extensions
```

`layout(location = ...)` is not part of GLSL 150; it needs
`#extension GL_ARB_explicit_attrib_location : require`, and the directive is
per-compilation-unit, so a shader whose vertex half declares it and whose
fragment half does not is **half broken**. That was exactly this writer's bug:
the vertex half had the line, the fragment half used `layout(location = 0) out
vec4 SV_Target0;` without it. Stock GLCore fragment programs carry the line.

Unity reports none of this. It reports an unsupported shader. The lesson is
worth more than the fix: **a GLSL payload can be validated offline, by a
compiler that explains itself, without an editor and without a device.** Doing
that first would have cost one command.


## `<noninit>`: the sentinel in a shader render-state value

**Measured 2026-08-24** with UnityPy against `Game/EntityTintMaskSSS` and
`Legacy Shaders/Transparent/Cutout/VertexLit`, read out of
`Data/Bundles/Standalone/Entities/trees` in the installed game. Editor
2022.3.62f2.

Every field of a pass's `m_State` - `srcBlend`, `destBlend`, `colMask`,
`zTest`, `zWrite`, `culling`, the stencil and fog fields - is a
`SerializedShaderFloatValue`:

```text
{'val': 15.0, 'name': '<noninit>'}
```

`val` is the constant. `name`, when set, is the **material property** the value
comes from instead - which is how a shader gets `Cull [_Cull]`. Unity writes the
literal string `<noninit>` when there is no property.

**`""` is not equivalent.** It is a property whose name is the empty string:
the runtime looks it up, finds nothing, and substitutes 0. Applied to a whole
render state that turns `colMask` into 0 - the pass writes no colour channels -
and the object is invisible while nothing reports an error. The shader loads,
`Shader.isSupported` is true, `Material.SetPass(0)` returns true, and Unity does
not fall back, because from its point of view nothing failed.

`SerializedShaderVectorValue` (`fogColor`) carries the same `name` field and the
same rule.

**Verified both ways.** Stock's `rtBlend0` and this writer's differ *only* in
that string - every `val` matched - and restoring stock's `rtBlend0` alone made
a mutated stock shader draw again, while restoring `gpuProgramID`, `culling`,
`m_Tags` or `zTest` alone did not. With the sentinel written,
`verify-bundle --draw` reports `covered=38.8% zoomed-out=2.4%` for a synthesized
prop that had read `0.0%` for the whole investigation.

`bundle_writer.NO_PROPERTY` holds the string; `RenderStateSentinelTests` fails
if any render-state value carries an empty name again.


## The prefab needs a collider, and a box is what there is an artifact for

**Reported from a live client 2026-08-24** and confirmed there: blocks built
from a synthesized prefab place, stack, and can be **walked through**. 7DTD's
`ModelEntity` block takes its collision from the model, and this writer's
prefab carried a `Transform`, a `MeshFilter` and a `MeshRenderer` and no
collider at all.

**Measured** with UnityPy over the installed game's
`Data/Bundles/Standalone/Entities/trees`: the bundle contains `BoxCollider`,
`CapsuleCollider` and `SphereCollider` objects and **no `MeshCollider`**. So a
box is the collider there is a real field layout for, and it is also the cheap
one and an exact hull for the boxy props this writer makes.

`BoxCollider` is class **65**, and its 2022.3 layout is:

```text
m_GameObject, m_Material, m_IncludeLayers {m_Bits}, m_ExcludeLayers {m_Bits},
m_LayerOverridePriority, m_IsTrigger, m_ProvidesContacts, m_Enabled,
m_Size {x,y,z}, m_Center {x,y,z}
```

`m_IncludeLayers`, `m_ExcludeLayers` and `m_LayerOverridePriority` are the
fields 2022.3 added; an older layout copied from a wiki omits them.

**`m_Size` is a full size, `m_LocalAABB.m_Extent` is a half-extent**, so the
writer doubles it. A collider at half the mesh's size is the kind of error that
looks right in a dump and is wrong in the world.

Limitation, recorded rather than hidden: a sculpted mesh gets a box that
over-covers it. That is in
[../status/improvements.md](../status/improvements.md), not a silent surprise.


## The three shader platforms a 7DTD shader carries

**Measured 2026-08-24** with UnityPy over every `Shader` in the installed
game's `Data/Bundles/Standalone/Entities/*`. Ten shaders, and all ten carry
exactly the same three `ShaderCompilerPlatform` ids:

| id | platform | shaders carrying it |
|---|---|---|
| 4 | `D3D11` | 10 of 10 |
| 15 | `GLCore` | 10 of 10 |
| 18 | `Vulkan` | 10 of 10 |

**There is no separate Direct3D 12 id.** Unity's desktop D3D12 backend consumes
the same DXBC sub-programs as D3D11, so `4` covers both and a shader that works
under d3d11 works under d3d12. That is why this repository's platform list is
three entries and not four - stated here because "we do not emit d3d12" reads
like a gap and is not one.

This writer emits `4` and `15`. **`18` is missing**, so a client running Vulkan
has no sub-program at all to create.


## The Vulkan sub-program record (platform 18), decoded

**Measured 2026-08-24** with UnityPy + `lz4.block` over the Vulkan blobs of
`Legacy Shaders/Transparent/Cutout/VertexLit`, `Standard`,
`Game/Autodesk XFade` and `Game/EntityTintMaskSSS` in the installed game.
This writer does **not** emit platform 18; this is the format it would have to
produce.

A Vulkan **code** record is program type **25** (not the `GL_CORE_32`/`DX11*`
values), and unlike d3d11 and GLCore its payload is a container of its own:

| word | value | meaning |
|---|---|---|
| 0 | `0x02000060` / `0x02000061` | version and flags |
| 1 | varies | size of section **A** |
| 2 | varies | size of section **B** |
| 3 | `176` in all four | size of section A's header |
| 4 | = word1 − 176 | section A's payload |
| 5 | `0` | not decoded |

`word1 + word2 == payload length` **exactly** in all four records:

```text
Standard        2940 = 1199 + 1741      XFade      3449 = 1708 + 1741
EntityTintMask  3758 =  922 + 2836      VertexLit  4631 =  703 + 3928
```

Both sections hold **SMOL-V**, Unity's compressed SPIR-V: at payload offset
`word1`, and again at offset 176 inside section A, the first four bytes are
`4c 4f 4d 53` - the SMOL-V magic `0x534D4F4C`. Two modules per record, which is
why `stageCounts` is 1 for Vulkan: one record carries both stages, where d3d11
uses two records and reports 2.

**What emitting this would take**, so the next session does not re-scope it:

1. SPIR-V from the HLSL this writer already compiles. Available today:
   `vkd3d-compiler -x dxbc-tpf -b spirv-binary` accepts this writer's own DXBC,
   verified on 2026-08-24.
2. A **SMOL-V encoder**. **Built**, and deliberately not here:
   [ywy50/zmol-v](https://github.com/ywy50/zmol-v) is a Zig implementation of
   [aras-p/smol-v](https://github.com/aras-p/smol-v), checked byte-for-byte
   against the reference C++ encoder on real SPIR-V modules. It lives outside
   this repository because a SPIR-V codec has nothing to do with 7 Days to Die -
   it is useful to anyone reading or writing Unity Vulkan shader data, and
   vendoring it here would be the "re-solved locally" pattern this repository
   exists to avoid.
3. The 176-byte section-A header, which is the one piece with no prior art and
   would be decoded the way this table was.

None of that is blocked; it is unbuilt, and the route is the three steps above.
The container decode in this section is mirrored in `zmol-v`'s README, so the
codec and the format it is used for are documented together.


## Unity's `UnityPerFrame` layout, and why getting it wrong is invisible

**Measured 2026-08-24** by reading the `RDEF` chunk of this writer's own
`vs_4_0` bytecode - the bytecode's account of where it will look - and
comparing it against the offsets the runtime fills.

A constant buffer is filled by the runtime to **its** layout and read by the
bytecode **by offset**. The HLSL must therefore reproduce Unity's member order
byte for byte, *including members the shader never reads*.

`UnityPerFrame`, as Unity lays it out:

| offset | member |
|---|---|
| 0 | `glstate_lightmodel_ambient` |
| 16 | `unity_AmbientSky` |
| 32 | `unity_AmbientEquator` |
| 48 | `unity_AmbientGround` |
| 64 | `unity_IndirectSpecColor` |
| 80 | `glstate_matrix_projection` |
| 144 | `unity_MatrixV` |
| 208 | `unity_MatrixInvV` |
| **272** | **`unity_MatrixVP`** |
| 336 | `unity_StereoEyeIndex` |

This writer's HLSL omitted the four ambient `float4`s. Everything after them
packed **64 bytes early**, so `unity_MatrixVP` compiled to offset **208** while
the runtime writes it at **272**: the vertex shader read the tail of
`unity_MatrixInvV` as its view-projection matrix and put every vertex nowhere.

**Nothing reported it.** The shader loaded, `Shader.isSupported` was true, the
pass set up, and no error appeared in any log. And it was wrong on **d3d11
only** - GLSL binds uniforms by name, so the OpenGL Core sub-program out of the
same writer, with the same declared metadata, rendered correctly. A live client
showed an invisible block on its default API and a correct, textured, solid one
under `-force-glcore`, which is what isolated it.

`shader_blob.assert_cbuffer_layout` now refuses any buffer whose compiled
offsets disagree with the declared ones, and runs on every synthesize.
Deleting the four members again produces
`UnityPerFrame.glstate_matrix_projection is declared at byte 80 but the
compiled bytecode reads it at 16`.

**The general rule, worth more than the fix:** a constant-buffer layout is a
contract with the runtime, not a convenience for the author. Padding is not
optional, and an offline check that reads `RDEF` is the only cheap place to
catch a violation - the expensive place is a person looking at a block on two
graphics APIs.


## Emitting a Vulkan sub-program: what is built, and the two guesses in it

**Built 2026-08-24.** `shader_blob.unlit_textured` now emits platform 18 when
the SMOL-V encoder is available, giving `platforms [4, 15, 18]` and
`stageCounts [2, 1, 1]` - the same shape every stock shader carries.

The route, all three steps now real:

1. `compile_spirv` translates this writer's own DXBC with
   `vkd3d-compiler -x dxbc-tpf -b spirv-binary`. The d3d11 and Vulkan
   sub-programs therefore come from **one** source and cannot drift apart,
   which is worth more than the hop it costs: a day was spent on d3d11 and
   GLCore disagreeing about a constant-buffer layout.
2. `compress_smolv` loads [ywy50/zmol-v](https://github.com/ywy50/zmol-v)
   through its C ABI. Not vendored: a SPIR-V codec has nothing to do with this
   game.
3. `vulkan_code_blob` writes the container decoded above, and its invariants
   are asserted against the built record: `word1 + word2` equals the payload
   length, `word3` is 176, `word4` is `word1 - 176`, and both sections start
   with the SMOL-V magic.

**Vulkan is optional and additive.** A host without the encoder builds the same
two platforms it always did rather than failing, because the game reaches for
platform 18 only under `-force-vulkan`. Adding it does not disturb the others:
with all three present, `verify-bundle --draw` still reports the prop at
`covered=38.8% zoomed-out=2.4%` on OpenGL Core.

**Two things in it are inferred, not decoded**, and they are why this lane is
not called finished:

- **Which section holds which stage.** Section B is the larger module in all
  four stock shaders measured, and `VertexLit` does its lighting per-vertex,
  which makes the vertex program the larger one - so B is written as the vertex
  stage. That is an argument from size, not a decode.
- **The 32 bytes at words 20..27.** They look like a hash and they differ per
  shader, so they are content-derived rather than constant. No MD5, SHA-1 or
  SHA-256 of either module, of both concatenated, or of the payload matched, so
  this writer sets them to zero. If the runtime only uses them to key a shader
  cache, zero costs a recompile; if it validates them, the record is rejected.

A live client launched with `-force-vulkan` loads the bundle with **no shader
errors at all**, which rules out the record being rejected on sight. Whether it
*draws* is the open question, and only a look answers it.
## The Vulkan record's 32-byte field: what it is not

**Measured 2026-08-24.** The 32 bytes at words 20..27 of a Vulkan code record
are the last undecoded piece, and these are the candidates ruled out, so nobody
re-runs them:

- **not a digest of the modules.** MD5, SHA-1, SHA-256, BLAKE2s and BLAKE2b of
  section A, of section B, of both concatenated, and of the whole payload from
  offset 176 all fail to match either half.
- **not a plain `Hash128`.** Unity's `Hash128` is SpookyHash V2 - confirmed in
  Unity's own [`SpookyHash.cs`](https://github.com/Unity-Technologies/UnityCsReference/blob/master/Runtime/Export/Hashing/SpookyHash.cs)
  - and the reference SpookyHash V2 with zero seeds over the same five inputs
  matches neither half. If it is SpookyHash it is seeded, or taken over
  something other than the stored bytes.
- **not constant.** It differs per shader, so it is content-derived rather than
  a magic number that could simply be copied.

What is known about its shape: it is **two 16-byte halves**, which is the size
of a `Hash128`, and word 19 immediately before it is `1` in every record
examined - consistent with a count of the entries that follow.

**What this costs.** Written as zero, a live client on Vulkan loads the bundle
with no shader errors and then draws the prop in Unity's **magenta error
shader**: the runtime finds the sub-program and refuses it. Swapping which
section carries which stage does not change that, so the section order is not
the cause and this field is the remaining suspect.

**That experiment has now run, and the wiring is correct.** A *whole stock
Vulkan blob* - `Legacy Shaders/Transparent/Cutout/VertexLit`'s - was
transplanted into this writer's shader, with the sub-programs' `m_BlobIndex`
pointed at its type-25 record, and launched under `-force-vulkan`:

> the block's build preview shows **the correct texture**, and the block
> collides. It is no longer magenta.

Magenta is Unity substituting its error shader for one it refused; a real
texture is a sub-program that was **accepted and compiled**. So this writer's
`PlatformBlob` for platform 18 - its indices, its `stageCounts`, its place in
the `platforms` list - is right, and what the runtime refuses is the **content**
of the record this writer builds. The 32-byte field is the remaining suspect,
and the section order is already eliminated.

The prop is invisible once placed in that transplant, which is expected and is
not a second finding: it is another shader's program driven by this mod's mesh
and material, so its vertex inputs and constant buffers do not match what is
bound. It draws where that happens to work - the preview - and not where it
does not.

Collision is unaffected on every graphics API, including Vulkan, which is
consistent with the collider being a prefab component rather than anything the
shader touches.


## The Vulkan platform needs its own parameter records

**Measured 2026-08-24** over the Vulkan blob of
`Legacy Shaders/Transparent/Cutout/VertexLit`. This is the best-supported
explanation left for why a Vulkan sub-program out of this writer is refused,
and it is a **structural** difference rather than a value one.

A Vulkan blob's records are `{3: 10, 25: 12, 5: 2}` - the 25s are the code
records, the rest parameters. One Vulkan parameter record declares **both
stages at once**, with stage-prefixed buffer names:

```text
PGlobals1706107946   _Cutoff                                    (P = pixel)
VGlobals1706107946   _Color, _Emission, _MainTex_ST, _Shininess (V = vertex)
```

That matches `stageCounts` being 1 for Vulkan: one record carries both stages,
so one parameter record describes both.

**This writer emits two**, copied verbatim from the d3d11 platform, declaring
`UnityPerDraw` and `UnityPerFrame`. Those are the names d3d11 binds by; nothing
in the Vulkan blob uses them.

What is eliminated around it, each measured in a live client on
`-force-vulkan`, and none of them the cause:

| Tried | Result |
|---|---|
| a whole **stock** Vulkan blob in this writer's shader | **renders** - so the platform wiring, `PlatformBlob` indices and `stageCounts` are correct |
| our modules with **stock's 32-byte hash** | magenta - so that field is not what is checked |
| swapping which section carries which stage | magenta, and the order was later **proven** the other way from `OpEntryPoint` |
| constant buffers moved to **descriptor set 1**, Unity's convention | magenta |
| SPIR-V from **glslang** rather than translated from DXBC, matching Unity's own generator | magenta |

So: the container is right, the wiring is right, the modules are valid SPIR-V
compiled the way Unity compiles them, and what remains unlike Unity's is the
parameter description beside them.


## RETRACTED: the Vulkan hash is NOT validated, and it was never the blocker

**Overturned 2026-08-25 by the experiment none of the three sections below ran.**
Corrupting **every byte** of the hash in an otherwise-untouched *stock* Vulkan
blob and loading it under `-force-vulkan` **still renders** (measured card
colour `(53, 60, 49)` - the albedo's navy, not magenta). Unity does not check
the field. Everything below about "the hash is validated" and the hunt for its
algorithm is wrong, and is kept only as the record of a wrong turn.

The real blocker was found the same day by byte-diffing our record against a
stock one carrying the **same** SMOL-V modules: they were identical but for the
(unvalidated) hash, and stock was **32 bytes longer**. Those 32 bytes are a
`ParserBindChannels` block - a source mask, a count, and (mesh channel, shader
input) pairs - the same block a d3d11 vertex record carries. `vulkan_code_blob`
omitted it, and a Vulkan code record without it is refused silently. See
"The Vulkan record needs its bind channels" below.

This is the negative-observation trap a fourth time in one investigation: three
sections and two merged PRs concluded the hash mattered, from a controlled pair
that had a *second* difference nobody had measured. The lesson, again: a
controlled experiment is only controlled for the variables you checked.

---

## The Vulkan hash IS validated - a correction

> **Retracted.** This section and the two below it are the wrong turn the
> section above overturns: the hash field is **not** validated (a live client
> renders a stock blob with every byte corrupted). Kept only as the record of
> the negative-observation trap. The real blocker was the bind-channels block,
> and after that the parameter record's entries — see the entry-encoding
> section at the end of this page.

**Measured 2026-08-25**, with the automated capture loop, and it corrects an
earlier conclusion on this page.

The decisive pair, both run in a live client on `-force-vulkan` with the frame
machine-captured:

| Record | Modules | Hash | Result |
|---|---|---|---|
| stock's | stock's | stock's | **renders** |
| **ours** | **stock's** | zero | **magenta** (measured `(255, 22, 255)`) |

The two records' heads are byte-identical (`ver, 25, six zeros, length`) and
their size tables agree word for word. With the *same* SMOL-V modules inside
both, the only remaining difference is the 32-byte field at words 20..27 - so
**Unity validates it**, and a mismatch is rejected silently: no log line, the
error shader substituted.

The earlier entry that "our modules with stock's hash still went magenta" and
called the hash *not* the cause was measured while the record still had other
defects in flight, and its inference is withdrawn - the same
negative-observation trap this repository keeps writing down.

What is now known about the field: it is two 16-byte halves; it is derived from
the module content; it is not MD5, SHA-1, SHA-256, BLAKE2 or zero-seeded
SpookyHash V2 of either module, both concatenated, or the payload. The next
route is not more guessing: Unity ships `UnityPlayer.dll`'s hashing in the
player, and the function that reads this record can be found in a disassembly
of the Vulkan GfxDevice - or the hash can be brute-checked against seeded
SpookyHash with the section sizes as seeds, which is one script rather than a
session.


## Hunting the Vulkan hash: what the player binary says, and what is left

> **Retracted.** Same wrong turn — see above. The field is unvalidated, so
> nothing here matters; the "is validated" conclusion at the end of this
> section is the trap, not a finding.

**Measured 2026-08-25** against `UnityPlayer.dll` (31 MB) in the installed game,
by scanning for constants:

- the SMOL-V magic `0x534D4F4C` appears at **two** sites - the decoder is in
  the player;
- SpookyHash's `0xDEADBEEFDEADBEEF` appears at **seven** - Unity's `Hash128`
  machinery is there too.

So the field is almost certainly a SpookyHash-derived `Hash128` pair. What it is
**not**, each candidate computed with the reference SpookyHash V2 and compared
against a stock record's stored halves:

| Input | Variants tried |
|---|---|
| each SMOL-V module | seeds (0,0); seeds from a 12-value sweep including both section sizes, 176, 25, 18; seed pairs equal to each length |
| both modules | one-shot concat, incremental Init/Update/Update/Final, both orders |
| chained | hash(A) then hash(B) seeded with A's result, and the reverse |
| each **decoded SPIR-V** module | seeds (0,0), the chained pairs, MD5/SHA-1/SHA-256 |

None matches either half. The input is therefore not the stored bytes or the
decoded module under any straightforward convention.

**The remaining route is disassembly**: the two SMOL magic sites in
`UnityPlayer.dll` locate the record reader, and the code around them says what
is hashed, with which seeds, before the modules are decoded. That is bounded
work with a named starting address, not an open search.

Until then the Vulkan lane's state is: everything except this field is
byte-equivalent to stock or proven irrelevant, and the field is **validated** -
our record carrying stock's own modules with a zero hash is refused, while
stock's identical record with its real hash renders.


## The Vulkan hash: offline shortcuts are exhausted, it is disassembly now

> **Retracted.** Same wrong turn — see above. The field is unvalidated; the
> disassembly this section calls for never happened and never needed to.

**Measured 2026-08-25.** Two automated sweeps closed the cheap routes, so the
next attempt goes straight to the binary rather than re-permuting hashes.

**Debug-stripped SPIR-V** (Option C, the likeliest recipe): `spirv-opt
--strip-debug` on each decoded stock module, then SpookyHash V2 seeds 0,0.
No match. Stripping removed only the `OpSource` line (24 bytes), and the result
hashes to neither stored half.

**A 1.5-million-hash seed sweep** (Option B): seed1 over 0..65535, seed2 in
{0, seed1, byte length, word length}, across six inputs - each SMOL-V module,
each decoded SPIR-V, each debug-stripped - compared against *both* stored
halves. Plus both concatenations (A+B, B+A, in SMOL-V and SPIR-V) over the same
seed range, and the seeds {0, 0xDEADBEEFDEADBEEF, 0xDEADBEEF, the golden ratio
constant, an arbitrary 64-bit value} in every pair. **Nothing matched either
half.**

The conclusion is firm: the hashed input is **not** any stored or decoded module
buffer, or their concatenation, under any straightforward seed. It is either a
Unity-internal representation (a canonicalised or re-serialized program struct)
or uses a transform this side cannot guess. That is exactly what a disassembly
reads off directly, and only a disassembly will.

Starting points in `UnityPlayer.dll`, re-confirmed: SMOL-V magic at file offsets
`0x8925bc` and `0x8e7a1b` (the latter inside `smolv::Decode`'s header check),
SpookyHash's `0xDEADBEEFDEADBEEF` at seven sites near `0xa36ef4`. Find
`Decode`'s caller; the buffer, length and seeds it hashes before decoding are
the recipe.


## The Vulkan record needs its bind channels

**Measured 2026-08-25.** A Vulkan code record does not end at its SMOL-V
payload. After the payload (padded to 4), it carries a `ParserBindChannels`
block, byte-for-byte the same structure a d3d11 vertex code record ends with:

| field | bytes | meaning |
|---|---|---|
| source mask | u32 | bit per mesh channel bound (bit 0 Position, 4 TexCoord0, ...) |
| count | u32 | number of channel pairs |
| pairs | count x (u32, u32) | (mesh channel, shader input slot) |

For `Legacy Shaders/Transparent/Cutout/VertexLit` (Position+Normal+TexCoord0)
the block reads mask `19` (bits 0,1,4), count `3`, pairs `(0,13) (1,14) (4,15)`.
For this writer's unlit shader (Position+TexCoord0) it is mask `17`, count `2`.

`vulkan_code_blob` omitted it entirely - the record ended at the payload - and
the runtime refused the sub-program the way it refuses any malformed record: the
shader loads, `Shader.isSupported` is true, and the prop draws in the magenta
error shader with no log line. Exactly the GLCore "eight bytes short" failure
from earlier in this investigation, on a different record.

The channels come from the vertex **DXBC** the SPIR-V was compiled from - the
same `bind_channels(dxbc)` the d3d11 lane already used - so the Vulkan and d3d11
sub-programs bind the same mesh data by construction.


## Bind channels present: the record is now accepted, and the client hangs

**Measured 2026-08-25.** With the `ParserBindChannels` block appended, a live
client on `-force-vulkan` no longer draws the magenta error shader. It **stages
the prop and then hangs** during the hold - the log stops at `scene staged`, the
client stops advancing, and the orchestrator tears it down at its timeout with
no screenshot written. Every prior Vulkan run captured its frame cleanly; this
one does not, and the only change is the bind-channels tail.

A hang at render, where before there was a clean fallback, means the runtime is
now **executing** our sub-program rather than rejecting it - the record is
accepted. So the missing block was the acceptance blocker, confirmed. What hangs
is the draw itself.

The most likely cause is the **target** values in the block. This writer reuses
`bind_channels(vertex_dxbc)`, which emits the d3d11 slot targets - `(0, 0)` and
`(4, 5)` for Position and TexCoord0. Stock's *Vulkan* record used different
targets for the same channels: `(0, 13) (1, 14) (4, 15)`. The d3d11 targets are
Unity's fixed vertex-component slots; the Vulkan targets look like SPIR-V input
**locations** offset by a base, and pointing the mesh binding at the wrong input
would feed the vertex shader garbage and can fault the GPU.


## Bind-channel targets: the declaration slot plus 13, decoded from seven stock shaders

**Decoded 2026-08-25** from the installed game's own Vulkan platform blobs
(`7DaysToDie_Data/data.unity3d`, each shader's `compressedBlob` decompressed
with LZ4, the `ParserBindChannels` block read from the end of each type-25 code
record, the vertex SMOL-V module decoded and its `OpDecorate ... Location`
values read with `spirv-dis`). A Vulkan bind-channel **target is not** the
SPIR-V location as stored in the module: every stock shader's module carries
locations `0, 1, 2, ...` in declaration order while its bind record carries the
same order offset by **13**:

| Shader | channels (source, target) | module SPIR-V locations |
|---|---|---|
| VertexLit, Diffuse, Specular, Transparent/* (Position, Normal, TexCoord0) | `(0,13) (1,14) (4,15)` | 0, 1, 2 |
| Bumped Diffuse (Position, Normal, Tangent, TexCoord0) | `(0,13) (1,14) (2,15) (4,16)` | 0, 1, 2, 3 |
| Particles/Additive (Position, Color, TexCoord0) | `(0,13) (3,14) (4,15)` | 0, 1, 2 |

So the target is the attribute's slot in the program's vertex-input declaration
(which Unity's compiler numbers in declaration order, hence the SPIR-V
locations) **plus 13** - the offset Unity's Vulkan pipeline reserves for the
shader's input list. `#99` had already stopped reusing the d3d11 targets and
emitted `(0,0) (4,1)` (the bare locations of this writer's glslang module), but
the correct targets for this writer's two inputs are **`(0,13) (4,14)`**, and
that is what `vulkan_bind_channels()` now writes. A live client with those
targets stages the prop and still dies at the draw (see the sampler section
below) - so the targets were necessary but not sufficient; the record is now
stock-shaped in every measurable dimension, and the fault is in what the
record carries, not its shape.


## The Vulkan fragment is a combined image-sampler, and the HLSL form is not

**Measured 2026-08-25** against the installed game's Vulkan fragment modules
(decoded from `data.unity3d`, disassembled with `spirv-dis`). Every stock
fragment module - VertexLit, Diffuse, Bumped Diffuse, Specular,
Particles/Additive, Transparent/* - declares its texture as **one**
`OpTypeSampledImage` variable at descriptor set 0, binding 0, because Unity
compiles its Vulkan modules with glslang from the GLSL its HLSLCC emits, where
`uniform sampler2D` is one object.

This writer's fragment was compiled from HLSL (`Texture2D` + `SamplerState`),
and glslang's HLSL front end renders that as **two** variables - an
`OpTypeImage` and an `OpTypeSampler` - both decorated binding 0. No stock
module has that shape. The live client under `-force-vulkan` with the bind
channels in place no longer drew magenta: the record was accepted, the prop
staged, and then the client **died** about five seconds into the draw - AMD
RADV (RX 7900 XTX), no log line, no crash dump, the process simply gone. The
same record shape draws fine on d3d11, GLCore and d3d12, which is why this
stayed hidden until the Vulkan draw actually executed.

The fix mirrors stock: the Vulkan fragment is now authored in GLSL 450
(`UNLIT_FRAGMENT_GLSL_VULKAN`) and compiled with glslang in GLSL mode, which
produces exactly the stock shape - one combined image-sampler at set 0,
binding 0 - and the Vulkan parameter record drops the separate sampler entry,
naming the texture's own sampler (`0xffffffff`) as the measured VertexLit
record does. `test_the_vulkan_fragment_is_one_combined_image_sampler` pins the
module shape.

**That was not the whole blocker.** With the combined sampler in place the live
client (AMD RADV, RX 7900 XTX, Proton) still dies about five seconds after the
prop starts drawing: staged at 41.9s of client time, the process gone by 46.9s,
no log line, no crash dump - the same signature as before the change. Three
live runs so far, all three dead at the draw: bare targets `(0,0) (4,1)`,
convention targets `(0,13) (4,14)`, and `(0,13) (4,14)` plus the combined
sampler. The record is accepted and executed each time (the scene stages and
the prop's renderer is reported), and the same bundle draws on d3d11, GLCore
and d3d12 - so the fault is in the Vulkan draw of this writer's sub-program.
The measured fact that VGlobals member offsets are per-record, not fixed -
ObjectToWorld sits at 0 in Diffuse and Particles/Additive but 256 in VertexLit
- ruled out one candidate, and a live bisection from the known-good control (a
whole stock Vulkan blob transplanted into this writer's shader rendered on
2026-08-24) pinned the rest.


## The crash was the parameter record's entries: stock encodes `(stage << 24) | (kind << 16) | slot`

**Pinned 2026-08-25 by live bisection** (each run ~2 min, verdict read from the
orchestrator's run-ended marker). The bisection started from the known-good
control (a whole stock Vulkan blob transplanted into this writer's shader) and
swapped records toward the writer's own: the blob layout (2/3/7/12 records),
the code record (our SMOL-V modules, version word 0x60 or 0x61, hash zero or
stock's - that field is unvalidated), the bind-channels tail (none, our pair,
or stock's three), the buffer name (`VGlobals` or `VGlobals<hash>`), the
member set and offsets (2 members at 0/64, stock's 14 at per-record offsets),
the buffer size (128 or 688) - all pass. The one block that never passed was
the parameter record's **entries**: with this writer's entries the client died
~5s after the draw started - AMD RADV, no log line, no crash dump - and with
stock's entries the suite passed end to end.

Stock entry indices are not plain slots. Measured across every stock param
record in the installed game (VertexLit, Diffuse, Bumped Diffuse, Specular,
Particles/Additive, Transparent/*): the index is
`(stage << 24) | (kind << 16) | slot` with stage 0x04 = vertex program,
0x08 = fragment program, kind 0x01 = constant buffer, 0x00 = texture:

| entry | stock index |
|---|---|
| `_MainTex` (texture, fragment stage, slot 0) | `0x08000000` |
| `VGlobals` in a vertex record (cbuffer, vertex stage, slot 0) | `0x04010000` |
| `VGlobals` in a fragment record (slot 1, after PGlobals) | `0x04010001` |
| `PGlobals` (cbuffer, fragment stage, slot 0) | `0x08010000` |

This writer emitted plain indices (texture 0, cbuffer 0) with `array_size 1`
where stock writes 0 - an interim reading of the texture slot as "8" (the t-slot
of VertexLit's HLSL) was the first break in the bisection but the cbuffer
entry stayed wrong and later rounds still died at the draw. The shipped record
carries the measured encoding for both entries: texture `_MainTex` at
`0x08000000` (sampler `0xffffffff`, dim 4), cbuffer `VGlobals` at `0x04010000`
with `array_size 0`. The module's own descriptor bindings stay set 0 binding 0
(texture) and set 1 binding 0 (cbuffer); the runtime derives the bindings from
the modules, and the entry indices are what the material binder keys on.

**Live result (2026-08-25, entryfix build):** `SUMMARY pass=6 fail=0 skip=0`,
DONE written, orchestrator exit 0; the captured 2560×1920 frame has zero
magenta pixels and shows the textured card. `test_the_vulkan_texture_entry_uses_the_stock_index`
and `test_the_vulkan_cbuffer_entry_uses_the_stock_index` pin both entries.


## The Vulkan payload length is padded to 4 before the bind-channels block

**Measured 2026-08-25.** The runtime reads a code record's payload length and
then reads the `ParserBindChannels` block that follows the payload. A SMOL-V
pair whose payload summed to **882 bytes** (176-byte header + 353 + 353) made
the runtime read the bind block from mid-padding and fault the Vulkan draw -
AMD RADV, device lost, no log line - while the same modules with a
4-aligned payload length rendered. Every stock code record measured carries a
payload length that is a multiple of 4, and the writer pads the payload
before writing the length field. `test_the_record_satisfies_every_measured_invariant`
asserts the padding.

## A held block places through ItemClass.ExecuteAction, and UseHoldingItem cannot reach it

**Decompiled 2026-08-25** from `hordeforge/7dtd-engine-research`
(`EntityAlive.il.txt`, `ItemClassBlock.il.txt`, `BlockToolSelection.il.txt`).
`EntityAlive.UseHoldingItem(idx, released)` indexes
`holdingItem.Actions[idx]` directly and skips a null entry - and the implicit
`ItemClassBlock` item every block gets sets **no** Actions, so
`UseHoldingItem` on a held block is a silent no-op (measured: 40s of calls,
no placement, no log line). The real input path is the virtual
`ItemClass.ExecuteAction(actionIdx, data, released, playerActions)` -
`PlayerMoveController`'s click - which `ItemClassBlock` overrides into
`GameManager.GetActiveBlockTool()`: action 0 to `ExecuteAttackAction`,
action 1 to `ExecuteUseAction`. Three of that tool's properties matter to a
caller: it places on the **press** (`_bReleased == true` returns
immediately - the opposite of `ItemActionPlaceAsBlock`), it reads the
engine-maintained `EntityPlayerLocal.HitInfo` rather than any argument, and
it dereferences `playerActions` unconditionally on the place path, so the
caller must pass `Platform.PlatformManager.NativePlatform.Input.PrimaryPlayer`,
never null. An explicit `<item>` with a `PlaceAsBlock` Action1 (the
2026-08-25 items.xml, since removed) is a different, preview-less path that
also replaces the frame-style in-hand behaviour of the implicit item.

## The Vulkan vertex stage carries the clip-space Y flip

**Measured 2026-08-25 by live A/B** (GFX_API=vulkan against the d3d11
control, same bundle, fresh saves). Without a flip the writer's Vulkan draw
is mirrored vertically: the block's albedo upside down (arrows down, orange
band on top against the d3d11 frame), its top face swapped, and the mirror
pivot moving with the camera. With `output.position.y = -output.position.y`
in `UNLIT_VERTEX_HLSL_VULKAN` the Vulkan frame matches d3d11 exactly (arrow
up, orange band at the bottom). The flip is shader semantics and lives in
this writer's HLSL - not in the SMOL-V codec, which is a lossless byte
transport and must not change what a module computes.

## BlockShapeModelEntity seats a model at modelOffset (0, 0.5, 0) by default

**Decompiled 2026-08-25** (`BlockShapeModelEntity.il.txt`: the constructor
stores `new Vector3(0f, 0.5f, 0f)` before `Properties.ParseVec("ModelOffset")`
may overwrite it) and **counted in the installed game's own config**
(`Data/Config/blocks.xml`: 488 model blocks override `ModelOffset` to
`0,0,0`, the single most common value). A prefab whose pivot is at its base -
this pipeline's synthesized prefabs put the mesh AABB at y 0..h under an
identity transform - floats half a block on the default and needs
`ModelOffset` `0,0,0` in the block definition.

## ParticleSystem, ParticleSystemRenderer, SkinnedMeshRenderer, Mesh skin channels (2026-08-30)

**Type trees.** UnityPy `get_typetree_node` at Unity `2022.3.62f2` for class
IDs 198 (ParticleSystem, 3848-line tree, serializedVersion 8), 199
(ParticleSystemRenderer, version 6), 137 (SkinnedMeshRenderer, version 2),
43 (Mesh, including `m_BindPose`, `m_BoneNameHashes`, `m_RootBoneNameHash`,
vertex channels 12/13), 4 (Transform `m_Children`/`m_Father`), 1
(GameObject). A class without a tree at this revision is still refused.

**ParticleSystem field values.** Read-only UnityPy `read_typetree` of the
installed game's
`Data/Addressables/Standalone/zombies_assets_entities/zombies/lab.bundle`
(118 ParticleSystem + 118 ParticleSystemRenderer). Shape type histogram:
4=Cone (78), 10=Circle (16), 2=Hemisphere (14), 0=Sphere (10). Renderer
modes: 1=Stretch (64), 4=Mesh (28), 0=Billboard (26). MinMaxCurve
`minMaxState` 0/1/2/3, empty unused curves with `m_PreInfinity=2`,
`m_PostInfinity=2`, `m_RotationOrder=4`. Gradients: `ctime1=atime1=65535`,
`m_ColorSpace=-1`, two keys. Emission bursts: `time`, `countCurve`,
`cycleCount`, `repeatInterval`, `probability`.

**ParticleSystemRenderer billboard defaults.** AtomicDoomsday editor-authored
YAML prefab
`_meta/unity/AtomicDoomsdayAssets/Assets/AtomicDoomsday/Bundle/Generated/Vfx/atomicDoomsdayNukeDetonationVfxLow.prefab`
(class 199, serializedVersion 6): `m_RenderMode` 0 (billboard) and 2
(horizontal billboard), `m_UseCustomVertexStreams: 0`, `m_VertexStreams:
00010304` (bytes 0,1,3,4), `m_CastShadows: 0`, `m_ReceiveShadows: 0`,
`m_LightProbeUsage: 0`, `m_MaxParticleSize: 0.5`, `m_LengthScale: 2`,
`m_NormalDirection: 1`, `m_EnableGPUInstancing: 1`. Additive vs fade blend
factors from `GeneratedAsset.ParticleMaterial`: SrcAlpha=5, One=1,
OneMinusSrcAlpha=10, ZWrite 0, queue 3000.

**SkinnedMeshRenderer and Mesh skin channels.** Installed game
`Data/Addressables/Standalone/player_assets_entities/player/female/gear/nomad.bundle`
(16 SkinnedMeshRenderer, 8 Mesh). SMR: `m_Quality: 0`,
`m_UpdateWhenOffscreen: False`, `m_SkinnedMotionVectors: True`, `m_Bones`
as PPtr array, `m_RootBone`, `m_AABB`, `m_DirtyAABB: False`. Mesh
`bodyCloth`: channel 12 BlendWeight stream 2 offset 0 format 0 dim 4;
channel 13 BlendIndices stream 2 offset 16 format 10 (UInt32) dim 4;
179 bind poses; 179 `m_BoneNameHashes`; `m_RootBoneNameHash` 1722913273
for GameObject `Hips`. Transform `m_Father`/`m_Children` from the same
bundle and from AtomicDoomsday `atomicDoomsdayNukeTimedHeld.prefab` (child
`armedLamp`).

**Box shape type.** Unity `ParticleSystemShapeType.Box = 5` (docs.unity3d.com
2022.3 ScriptReference). lab.bundle had no type-5 system; the field layout
is the same ShapeModule as types 0/2/4/10 (UnityPy type tree), so box uses
`m_Scale` / `boxThickness` already present on those harvested modules.
