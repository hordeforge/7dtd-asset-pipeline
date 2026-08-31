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
which is `zlib.crc32` of UTF-8 `Origin/Hips`, not of the leaf `Hips`
(3738240529) and not of the prefab-rooted path
`gearFemaleNomadPrefab/Origin/Hips` (3321112063). Every hash in that
179-bone table is the slash-separated Transform path starting at
`Origin` inclusive; the prefab root is not in the path. Transform
`m_Father`/`m_Children` from the same bundle and from AtomicDoomsday
`atomicDoomsdayNukeTimedHeld.prefab` (child `armedLamp`).

**Box shape type.** Unity `ParticleSystemShapeType.Box = 5` (docs.unity3d.com
2022.3 ScriptReference). lab.bundle had no type-5 system; the field layout
is the same ShapeModule as types 0/2/4/10 (UnityPy type tree), so box uses
`m_Scale` / `boxThickness` already present on those harvested modules.

## Entity-class model wiring, from the dedicated-server IL dump (2026-08-30)

Facts for the custom-entity lane, read with `monodis` from
`il/full-v3.1.0/_global/` in `hordeforge/7dtd-engine-research` (a
dedicated-server build of V3.1.0). File and line references below are to
that tree, `EntityClass.il.txt` unless stated otherwise.

- **`Prefab` is mandatory.** `EntityClass` reads `Prefab` into `prefabPath`
  and throws if absent or empty: `Mandatory property 'prefab' missing in
  entity_class '<name>'` (IL_009D–IL_00D6).
- **`Mesh` is optional on top** and becomes `meshPath` (IL_0157–IL_01D6);
  both are `String` fields on `EntityClass` (field list line 3:
  `PropPrefab`, `PropPrefabCombined`, `PropMesh`, `PropMeshFP`, `PropParent`,
  `PropAvatarController`, `PropLocalAvatarController`, `PropSkinTexture`,
  `PropRightHandJointName`, …).
- **Both load as GameObjects.** `EntityInstanceAssets.Load` calls
  `LoadManager.LoadAsset<GameObject>(prefabPath, …)`; `EModelInstanceAssets.Load`
  does the same with `meshPath` (both files' `Load` methods). So the model is
  a prefab, and the bundle-URI resolution is the same `DataLoader`
  `#@modfolder(Mod):…?stem` chain recorded in the skinned-gear section above.
- **`Entities/` is prefixed only for in-Resources paths.** `Mesh` values
  pass `DataLoader.IsInResources`; only a true resources path gets
  `"Entities/"` prepended (IL_01BC–IL_01CE), so a mod bundle URI is used
  verbatim. Same for `Prefab` (resources paths get `Prefabs/prefabEntity`,
  IL_0139–IL_0151).
- **`ModelType` chooses the EModel class** (`EModel`/`EModelCustom`, IL
  ~IL_0321–IL_036C); the default class is the base `EModelBase`, and
  `EModelCustom` has only a constructor — the behaviour is the base's.
- **`EModelBase` walks the loaded model.** `GetComponentsInChildren<Animator>`
  (disabled on dedi when `AvatarController` is set, which also adds an
  `AvatarControllerDummy`), `GetComponent<Animation>` (null-guarded in the
  ragdoll paths, `EModelBase.il.txt` IL_00D5/IL_0121), `GetComponentInChildren
  <CharacterGazeController>`, `GetComponentsInChildren<Rigidbody>`, and the
  `bipedRootTransform` / `bipedPelvisTransform` / `headTransform` /
  `neckTransform` / `neckParentTransform` fields — the hierarchy is walked,
  not required by name.
- **No `EntityClass.AddClass` in the dedi build.** `grep AddClass` finds it
  in neither `EntityClass.il.txt` nor `EntityFactory.il.txt`. The
  `7dtd-fps-bots` repo's `config/entityclasses.xml` documents the same
  observation live: appended human classes get negative ids on a dedi and
  render nothing on clients, so bots reuse `zombieSoldier` bodies (positive
  id).
- **`m_RootBoneNameHash` 1722913273 for `Hips` is not a standard digest.**
  Measured 2026-08-30: crc32 of `Hips` = 3738240529, crc32 of `hips` =
  2128849199, ×31 (`(h·31+c)&0xFFFFFFFF`) of `Hips` = 2249444 and of `hips`
  = 3202756 — none equal 1722913273, so Unity's `StringToHash` differs from
  all of them. The writer stores crc32 of each joint name as authored
  (`bundle_writer.bone_name_hash`), which is self-consistent between the
  mesh field and the bone GameObjects. Not checked: whether any engine path
  compares these hashes — SDCS binding is string-keyed (see skinned-gear
  section), and nothing else has been shown to read them.

**The entityclasses.xml merge shape** the generator emits (`<append
xpath="/entity_classes">` wrapping `<entity_class>` with `Prefab`/`Mesh`) is
the documented SphereII mod family pattern
([0-SCore docs, nexusmods.com/7daystodie/mods/6176](https://www.nexusmods.com/7daystodie/mods/6176?tab=docs)),
and the `entity_class` element name is confirmed by the engine's own error
message above.

## UserSpawnType gates console spawning (2026-08-30)

`EntityClass/UserSpawnType` is a three-value enum: `None`, `Console`, `Menu`
(`il/full-v3.1.0/_global/EntityClass_UserSpawnType.il.txt`, dedi V3.1.0).
`ConsoleCmdSpawnEntity.Execute` walks `EntityClass.list` and lists a class
only when `userSpawnType` is non-zero (`IL_00D5: ldfld userSpawnType;
brfalse.s IL_010C` — `ConsoleCmdSpawnEntity.il.txt`), so a class without
`UserSpawnType` cannot be spawned from the console. The entity generator
therefore emits `UserSpawnType="Menu"` in its `entityclasses.xml` patch;
`Console` is the alternative for a class that should only come from code or
a spawn file.

## Animal movement: GameObjectAnimalAnimation drives a legacy Animation by clip name (2026-08-30)

`GameObjectAnimalAnimation : AvatarController` (dedi V3.1.0 IL,
`GameObjectAnimalAnimation.il.txt`) is how animals move: the entity class
sets `AvatarController = GameObjectAnimalAnimation`, its `Awake` finds the
model, grabs the figure GameObject's legacy `UnityEngine.Animation`
component, and `Animation.Play(name)` clips by conventional names —
`Idle1`, `Idle2`, `Attack1`, `Attack2`, `Pain`, `Jump`, `Death`, `Run`,
`Walk`, `Swim` (the `cAnim*` fields + `get_Item("Idle1")` /
`Play("Idle1")` at IL_006A–IL_0086). A state machine switches idle vs
run/walk on `lastAbsMotion`, attack/pain/jump/death on entity state.

So a synthesized animal needs, beyond the skinned prefab: a legacy
`Animation` component carrying looping clips under those names, and
`AvatarController = GameObjectAnimalAnimation` on the entity class. The
runtime plays `m_Clip` (the compiled stream), not `m_EditorCurves`, so a
clip without a valid `m_Clip` block loads but never plays. Not checked
yet: whether the writer can emit a minimal `m_Clip` (UnityPy parses the
format — a parser is a spec — but nothing here writes one).

## The controller's prefab contract: Animation must be on an active *figure* child (2026-08-30)

`ilspycmd -t GameObjectAnimalAnimation` on the installed
`Assembly-CSharp.dll` shows the `Awake` contract a spawned animal prefab
must meet — the reason a generated creature **floats and NREs every frame**
when spawned as a real `EntityAnimalStag`:

- `parentT = EModelBase.FindModel(base.transform)` finds the model root.
- `figureT` = the first **active** child of that root
  (`parentT.GetChild(num)` in reverse, keeping the first whose
  `activeSelf`).
- `anim = figureT.GetComponent<Animation>()` — the legacy `Animation`
  component must be on **that child**, not the model root. If it is not,
  `anim` is null.
- `anim["Idle1"]` / `anim["Attack1"]` / `anim["Attack2"]` are indexed.

`Update()` then dereferences `anim["Death"]` and `anim["Pain"]` on every
frame. With `anim == null` this is the `NullReferenceException` at
`GameObjectAnimalAnimation.Update [0x00360]` — the error the walking-entity
run printed dozens of times.

Our writer attaches the entity's `Animation` component to the **prefab
root**, and the generated prefab's children are direct bone transforms
(`Root`, `Pelvis`, …) — the first active child carries no `Animation`, so
`anim` is null on a spawned entity. The staged-prefab path never hit this
because it played clips via `playAutomatically` on the root without the
controller.

**Blocked, with the route measured closed for now:** making a generated
creature run as a real game animal needs (1) the prefab restructured so the
model root's first active child is a "figure" GameObject carrying the
`Animation`, and (2) a `PhysicsBody` whose collider is authored to the
*creature's* proportions (feet at the root), not "Stag" — the stag-shaped
collider does not align with our mesh's feet, which is the "floating in the
air" symptom. Both are concrete, engine-adjacent work; neither is a
one-liner, and neither has been built yet.

A generated creature that spawns as a real `EntityAlive` **does** work as
far as the spawner is concerned: `EntityClass.FromString` + 
`EntityFactory.CreateEntity` + `SpawnEntityInWorld` produce an entity that
travels (verified: spawned_id=172, travelled 9.6 m over a 12 s hold when the
harness drives its position forward). What does not work is the game
grounding it (physics-body alignment) and the controller animating it
(prefab structure), both recorded above.

**(1) is now fixed.** `attach_anim_objects` inserts a `figure` GameObject
between the prefab root and its children and puts the legacy `Animation` on
the figure — the model root's single active child — while `Root` stays a
child of the figure so the clip paths (`Root/Pelvis/...`, authored relative
to the Animation's own GameObject) still resolve. Live-verified on
2026-08-30: the per-frame `GameObjectAnimalAnimation.Update` NREs are gone
(the controller plays the Walk clip and the entity travels), where before
there were dozens per second. One NRE remains in `Awake` at spawn
(`createAvatarController` → `AddComponent → Awake [0x00064]`, likely a
transient first-pass `FindModel` miss) — still open. **(2), the
physics-body alignment, is the remaining blocker for a *grounded* walk.**

**(2) experiment, measured closed for this route (2026-08-30):** the float is
because `PhysicsBody="Stag"` binds colliders to stag bone paths
(`Hips`, `LeftUpLeg`, …) that the generated quadruped does not have (it is
`Pelvis`, `LeftFrontUpper`, …), so no collider builds and gravity never
grounds it — it stays at its +3 m spawn offset. A mod-side
`Config/physicsbodies.xml` body (`ShamwayCreature`) with `Detail` colliders
on the creature's own bone paths (Pelvis + every leg bone + paw) was
authored and tested live: it **did not ground** — the spawned creature still
floated in the treeline, paws against foliage. The stock `Detail` colliders
work for a real stag because its mesh/bones are authored to them; our
procedural primitives' `Detail` colliders are bone-centered and do not reach
the feet. The next route is a non-`Detail` body (an explicit box/capsule
collider sized feet-to-shoulder at the model root, i.e. a grounding collider
whose bottom is at the root), which is the unbuilt change.

**(2) second attempt, also measured closed:** prefixing the collider paths
with `Root/` (the creature's bones sit under a `Root` bone — the model is
model → Root → Pelvis — unlike the stag's `Hips` which is directly under the
model) did not ground it either; the creature still floated in the treeline.
So the `Detail` collider type is not building a grounding collider for our
procedural skinned mesh regardless of path. Route B (an explicit box/capsule
body) remains unbuilt, and the whole grounded-walk is a dedicated
engine-integration problem requiring either that or a mod-side C# physics
body — a live-verified grounded walk is the outstanding acceptance, not yet
achieved.

**(2) third attempt, measured closed — and the config route is exhausted:**
`type="Normal"` (the other per-bone collider type) with `Root/`-prefixed
paths also floats in the treeline. `EnumColliderType` (from
`PhysicsBodyColliderConfiguration.il.txt`) is only `None`/`Normal`/`Detail`/
`All` — there is **no explicit box/capsule type** — and both `Normal` and
`Detail` build per-bone Unity `CapsuleCollider`s that the procedural skinned
mesh does not ground with. So the *config-`physicsbodies.xml`* route is
measured closed for the grounded walk. The remaining route is a **mod-side C#
physics body** (a custom component that adds a grounding collider to the
spawned entity) — which is a C# mod, not an asset-pipeline output. That is
the honest limit: the asset pipeline produces the entity, clips and XML; a
procedurally-skinned creature's *physics grounding* is not achievable via
generated config alone in this engine revision. A generated creature
animates and travels (verified), but a fully grounded walk needs a C# mod
component — recorded as the outstanding, non-pipeline item.

**RESOLVED (2026-08-30): the grounded walk works by spawning the creature
non-remote.** The earlier "client does not gravity-simulate a client-spawned
entity" measured limit had a concrete fix: the client DOES simulate an entity
it considers local. `CaseDef.WalkEntity` now creates the creature then sets
`Entity.isEntityRemote = false` (a settable field), so the client runs it
like a local entity — it grounds, follows/climbs the terrain, and plays the
gait. Live-verified: y = the ground surface (was +3 m before), it climbs
elevation (its ground height follows the terrain), travels ~9.8 m along the
ground, and is visible. A server-side `spawnentity` (barrier/telnet) is the
equivalent non-remote route and was implemented but the simpler client-flag
achieves the same without orchestrator plumbing.

**Remaining: the legs clip into the ground.** With the creature grounded and
moving, its *feet* do not touch the surface — the body/root sits at the
surface and the legs render below it (the user read it as "collision on the
torso instead of the feet"). The ground-contact point is above the mesh's
feet, so the entity's feet-to-root offset does not match where the game
places the root. The next fix: raise the spawn/ground so the mesh's *lowest
rendered point* (the feet) meets the terrain — i.e. offset the entity by its
measured feet-below-root amount, or ground by a feet-level collider. Not yet
measured in the animated pose.

**The CC capsule grounds the *average*, not the animated feet (2026-08-30,
live-confirmed):** the `Physics`-node capsule (#165) stops the creature
floating at spawn and grounds it in the walk-entity look — but across the
12 s clip it is still inconsistent, exactly as the user read it: legs clip
into the ground, then float above it, and over a rise it rides too high before
settling. The reason is structural, not a missing collider: the capsule is
sized from the **static bind-pose** mesh AABB (feet at y=-0.02), while the
`Idle1` bob and `Walk` trot move the pelvis and legs, so the visual lowest
point oscillates around that fixed capsule bottom; and over terrain the
capsule rides the collider surface while the animation phase swings the feet
above/below it. A single static capsule cannot track an animated rig's feet.
The remaining route is a per-frame ground offset (the model's posed feet-below
root, re-measured each tick) or a proper animated ground clamp — the item
recorded above, still open.

**The hide contrast (2026-08-30, live-confirmed):** the atlased role-aware
hide works mechanically, but the first palette (pale cream base ~205) washed
out to a single pale blob under the client's daytime sun. Re-authoring the
fixture hide with a dark warm palette (base 118,96,66, paw near-black
22,16,12, limb 74,58,40, outline 12,10,8) made the legs and body separate and
the paw tips read — so a rendered creature's hide needs mid-to-dark tones and
strong value separation, not light pastel, to survive in-game lighting.

**The true collider-missing finding, and why the look suite still floats
(2026-08-30):** `PhysicsBodyInstance.bindCollider` (from
`PhysicsBodyInstance.il.txt`) does `modelRoot.Find(path)` then
`GetComponent<Box/Capsule/SphereCollider>()` on the found bone — and, finding
none, creates a `PhysicsBodyNullCollider`. **Up to now the generated
creature's bones had no collider components at all**, so every collider
config became a null collider and the entity had no collision. The writer
now adds a small `BoxCollider` to every skinned bone GameObject, so
`bindCollider` builds real colliders and the creature is physically solid.
**However**, the walk-entity acceptance spawns the creature **client-side**
(in the `CaseDef.WalkEntity` look), and the client does not
gravity-simulate a spawned entity the way the server does — so the client
still renders it at its +3 m spawn offset, i.e. it still *looks* floating in
that harness. The collider fix is the correct, necessary asset change
(server-side and real-gameplay entities then ground properly); the remaining
"grounded in the client look" gap is a harness/engine-simulation limitation,
not an asset one. **Measured, not inferred:** the instrumented
WalkEntity reports the spawned entity's Y each tick; with bone
colliders present it ends the run at y=64.08 — exactly its +3 m
spawn offset (player 61.08 + 3) — i.e. the client never pulls it
down. A client-side spawn cannot demo grounding no matter the asset. Recorded so the next session does not re-diagnose the
float as a missing collider (it is not, now).

**The grounding mechanism the asset can control (2026-08-30): the CC capsule
on a `Physics` child of the model root.** The bone-collider work above made
the creature *physically solid* but could not ground it, because a
procedurally-skinned creature's per-bone colliders are bone-centred and do
not reach the feet, and `EnumColliderType` has no explicit box/capsule body
type. The engine has a second, independent grounding path that *is*
asset-controllable and that the prior work never touched. Verified from
`Entity.il.txt` (the installed `Assembly-CSharp.dll`, decompiled):

- `Entity::PhysicsInit` finds a transform named **`Physics`** under the
  model root (`Transform.Find("Physics")`, `Entity.il.txt:1282`; the
  first-choice `FindTagInChilds("Physics")` at :1238 is a Unity-**tag**
  match, which the engine itself applies later — `Init` at :1149 does
  `PhysicsTransform.gameObject.tag = "Physics"` — so the name-based
  `Transform.Find` is the reliable authoring route). If no `Physics`
  node exists, `PhysicsTransform` stays null and **no CharacterController
  is created at all**.
- `Entity::AddCharacterController` (Entity.il.txt:800) reads the `Physics`
  GameObject's **`CapsuleCollider`** `center`/`height`/`radius`, wraps it in
  `CharacterControllerUnity`, and calls `SetSize` (:1001). For a normal (non-
  player, non-large-entity) entity the `physicsHeightScale` is 1.0, so the CC
  capsule *is* that collider. If no `CapsuleCollider` exists it adds a
  default (center.y=0.9, height=1.8, radius=0.3, :930-938).
- The CC capsule bottom is `center.y - height/2`. Unity grounds the
  `CharacterController` so that bottom rests on the terrain, and the model
  hangs off the same root — so the feet meet the surface exactly when the
  capsule bottom sits at the model's feet depth.

Real animal prefabs author exactly this: `animalDeerStag` (from the shipped
`automatic_assets_entities/animals.bundle`, read with UnityPy) has a
`Physics` child of the prefab root at local (0,0,0) with a **CapsuleCollider
radius 0.22, height 1.20, center.y 0.60** — capsule bottom at y=0, i.e. at
the root, where the stag's feet are. Snake, deer, wolf, boar, bear, rabbit,
chicken and the insects each carry the same `Physics` + CapsuleCollider
pattern. **So the fix for a generated creature is an asset one after all:
emit a `Physics` child node of the model root with a CapsuleCollider whose
bottom = the mesh's feet**, and the engine grounds the entity on its feet —
no C# mod, no `physicsbodies.xml` config. The prior "config route is
measured closed" finding remains true for per-bone bodies; this is the
non-per-bone capsule body that `EnumColliderType`'s three values cannot
express.

## Ground height: GetTerrainHeight is the voxel surface; GetHeightAt is not (2026-08-30)

`ilspycmd -t World` on the installed `Assembly-CSharp.dll` (Unity 2022.3
revision the game runs) shows two surface-height queries on `World`:

- `public byte GetTerrainHeight(int worldX, int worldZ)` — the chunk's
  height of the top terrain **block** (block-space byte, 0 for an empty
  column); the **voxel surface**, i.e. where a thing actually stands.
  World coordinates in, block coordinates resolved internally
  (`toChunkXZ`/`toBlockXZ`), so no `worldToBlockPos` call is needed. The
  block's top face in world units is `GetTerrainHeight + 1`.
- `public float GetHeightAt(float worldX, float worldZ)` — the terrain
  **generator's** heightmap (`GetTerrainGenerator().GetTerrainHeightAt`),
  null-guarded to `0f`. This is the *uncarved* surface: it ignores voxel
  edits, POI basements and dug ground.

## Grounding a staged prefab: raycast to the surface; terrain-height APIs failed live (2026-08-30)

The generated acceptance look cases ground their staged prefab by
raycasting straight down from the staging point onto the game's own
"traversable voxel surface" layer mask and placing the prefab's lowest
renderer bounds point on the hit:

```csharp
Physics.Raycast(placed, Vector3.down, out var groundHit, 200f, 268500992)
```

Mask `268500992` = layers 13+15+28 — the mask the game's own fall-point
check raycasts with (`EntityAlive` fall detection:
`Physics.Raycast(position - Origin.position, Vector3.down, out var hitInfo, 999f, 268500992)`,
verified with `ilspycmd` on the installed `Assembly-CSharp.dll`, Unity
2022.3 revision the game runs). Physics operates in the same (rebased)
transform space as the camera, so no `Origin.position` arithmetic is
needed, and the ray measures the *actual* collider surface at the column —
slopes and carved pits included.

The terrain-height APIs were tried first and both failed live, each in a
distinct way that is worth recording so the next session does not re-try
them:

- `World.GetHeightAt(float, float)` is the terrain **generator's**
  uncarved heightmap (`GetTerrainGenerator().GetTerrainHeightAt`), not the
  voxel surface; it grounded a staged entity 60 m above the camera on a
  column with carved ground beneath it.
- `World.GetTerrainHeight(int, int)` (byte, top block) is the voxel
  surface, but it takes **absolute** world coordinates while Unity
  transforms are rebased by `Origin.position`
  (`Entity.transform.position = position - Origin.position`), and it
  returns 0 on an unloaded chunk. Querying with the raw rebased staging
  point hit the map-origin column (wrong place) or returned 0 (grounding
  skipped, the entity stayed hovering at the camera offset).

Each failing run still passed its assertions (`renderers=1`), which is
exactly why a look is a person's look, not an assertion: the run's own
evidence could not say whether the entity was visible, in frame, or on the
ground.

A fourth failure is not the ground query at all but the staging rotation:
`Quaternion.LookRotation(-ahead, up)` pitches the staged prefab by the
camera's own pitch, and the look camera looks *down* at the staged entity
(~25° in the playtest), so a quadruped leaned back head-up with its hind
feet ~0.17 m below its front feet — grounding by the (unrotated) lowest
bound point then sank the hind legs into the floor, which the user read as
"clipped into the floor" even with the ground height correct. The staged
prefab now faces the camera with yaw only
(`Quaternion.Euler(0, Atan2(-ahead.x, -ahead.z), 0)`), which keeps every
foot at one height, so the lowest bound point is the standing surface.

**The ground itself: the game spawns entities at `chunk.GetHeight + 1`,
not at `GetTerrainHeight`.** The definitive answer came from the game's own
spawner: `World.FindRandomSpawnPointNearPosition` places ground entities
at `chunk.GetHeight(blockX, blockZ) + 1`, and `World.GetHeight(worldX,
worldZ)` resolves to that same `m_HeightMap` — the chunk's *actual* top
block. `World.GetTerrainHeight` reads `m_TerrainHeight`, the terrain
generator's cached height, which ignores voxel edits and sat a staged
entity ~2 blocks under the visible surface — the "completely clipped"
read that survived three ground-query iterations. The look case now
grounds with `world.GetHeight((int)abs.x, (int)abs.z) + 1f` (absolute
coordinates, `+ Origin.position` for the rebase), with a ground-mask
raycast as the fallback when the chunk is not yet loaded.

## A generated creature must own its entity class and clips, not borrow a stock one (2026-08-30)

The walk acceptance kept returning a creature that "spawns, collides on the
torso, speeds away" and an `NullReferenceException` during spawn. Root cause,
pinned from the installed engine IL:

- **Using `Class="EntityAnimalStag"` borrows a stock animal's C# type.** That
  type brings a pre-authored model (`Mesh`/`Prefab` → the game's own
  `Animals/...` assets), a stock `PhysicsBody` whose collider paths are stag
  bone names the generated rig does not have (`Hips`, `LeftUpLeg`, …), and a
  template `AITask` tree (Wander etc.) that roams — the "speeds away". Reusing
  a stock class proves nothing about the pipeline and inherits expectations a
  generated rig cannot meet. **The asset pipeline's goal is to author its own
  assets, so the generated creature must declare its own class.**

- **A mod DLL can define the entity class.** `EntityClass` resolves `Class`
  via `Type.GetType(string)` (EntityClass.il.txt:349) and logs
  `Could not instantiate class 'X' for entity_class Y` when it returns null.
  `Type.GetType` searches **all loaded assemblies**, so a mod whose DLL ships
  at the mod root (root-level `*.dll`; `shamway client deploy` copies exactly
  those) can name `Class="<ns>.<Type>, <Assembly>"` and the engine
  instantiates the mod's own `EntityAlive` subclass. Verified: the fixture's
  `ShamwaySelfTestCreature.cs` (`public class ShamwaySelfTestCreature :
  EntityAlive`) compiled to `ShamwaySelfTestCreature.dll`, loaded by the client
  and server, resolved by `Class`, and `CreateEntity` proceeded past the class
  lookup (the old "Could not instantiate class" is gone).

- **The remaining spawn blocker is a controller-init NRE, not the class.**
  `EntityFactory.CreateEntity` → `CreateEntityOperation.CompleteEntity` →
  `EModelBase.createAvatarController` → `AddComponent<GameObjectAnimalAnimation>`
  → its `Awake` NREs at `anim["Idle1"]` (GameObjectAnimalAnimation.il.txt:46,
  offset 0x0064) because `anim == null`. `Awake` does
  `figureT = parentT.GetChild(reverse-first-active)` then
  `anim = figureT.GetComponent<Animation>()`. The controller is added to the
  model GameObject during `createAvatarController`; at that moment the figure
  child does not resolve to the one carrying the `Animation` (the model
  hierarchy has not settled), so `anim` is null and `CreateEntity` aborts.
  This matches the earlier recorded "one NRE remains in Awake at spawn —
  likely a transient first-pass FindModel miss". **The controller's own
  `[UnityEngine.Scripting.Preserve]`/init ordering is the open engine-interop
  piece** (a `GameObjectAnimalAnimation.Awake` re-query / defer, or adding the
  component after the model is attached).

- **`GameObjectAnimalAnimation` reveals the figure-child contract.** `Awake`
  reverses over the model root's children to find the first *active* one and
  reads the `Animation` off it. So the prefab needs a `figure` child carrying
  the `Animation`, as the **first active child** of the model root. A
  `Physics` sibling added for grounding must be **inactive** (or the
  reverse-iteration picks it, finds no Animation, and NREs) — verified: root
  children `[figure(active), Physics(false)]` makes the reverse-iteration land
  on `figure`.

- **The grounding capsule must be as wide as the model's footprint.** A thin
  capsule (radius 0.207) under a wide quadruped (depth extent 0.415) lets the
  body drape past the collider and tip onto the torso. The `Physics` node's
  `CapsuleCollider` radius should be ≈ the mesh's widest footprint half-extent
  (0.415) and bottom at the feet (`center.y - height/2 == aabb.min.y`), so the
  engine grounds the feet, not the torso.

- **The clip recorder photographs the player's framebuffer.** `ClipRecorder`
  uses `ScreenCapture.CaptureScreenshot` — whatever the client's camera shows.
  To frame a spawned walking creature the player is not inside, detach the
  camera with `EntityPlayerLocal.SetCameraAttachedToPlayer(false, false)`
  (sets `cameraTransform.parent = null` — the game's own detached/debug camera,
  EntityPlayerLocal.il.txt:2877) and position `playerCamera.transform` each
  tick; `GameObjectAnimalAnimation`/the recorded framebuffer then show the
  creature instead of the player's own first-person view. Re-attach with
  `(true, false)` after the case.

**Still open:** the `GameObjectAnimalAnimation.Awake` init-ordering NRE, which
is what actually aborts spawn — the class, the Physics capsule, and the
figure-first-active-child contract are all now correct offline; the runtime
controller-init ordering is the remaining engine-interop blocker for a spawn
that survives `CompleteEntity`.

## Game animals use an Mecanim Animator, not a legacy Animation, in this revision (2026-08-30)

Read the shipped `automatic_assets_entities/animals.bundle` with UnityPy: the
modern animals (`animalDeerStag`, `animalRabbit`, `animalBoar`, `animalWolf`,
`animalBirdChicken`, …) carry a Unity **`Animator` (type 95)** on the model
root GameObject — a Mecanim `Animator` + controller — while the
legacy `Animation` (type 111) appears only on a few old-style prefabs
(`PIG`, `CHICKEN`, a `Model` node). `GameObjectAnimalAnimation` (the
`AvatarController` the generator wires) drives a **legacy** `Animation`
component by clip name (`Awake` → `figureT.GetComponent<Animation>()` →
`anim["Idle1"]`). So pairing `AvatarController = GameObjectAnimalAnimation`
with a prefab that carries a legacy `Animation` is a *legacy-animal* path that
does not match how the current animals are authored (Mecanim), which is likely
why the spawned creature's controller `Awake` NREs: the node it inspects for
the legacy `Animation` does not carry one, because the generated prefab's
layout and the modern animal layout differ.

**Two distinct routes to a moving animal, both feasible:**
- *Legacy-clip route (what the generator builds):* keep
  `AvatarController = GameObjectAnimalAnimation` and ensure the legacy
  `Animation` component (with the clips) is on **the exact node the
  controller's `GetChild(first-active)` resolves** — the node `FindModel`
  returns, whose first active child is the prefab root once the prefab is
  `Instantiate`d under it (`EModelBase.createModel` does
  `Instantiate(assets.Mesh, modelTransformParent)`). Placement of that
  `Animation` is the contract that must match — see the controller-Awake NRE
  note above.
- *Mecanim route:* ship the model's own `Animator` + controller (TFP's
  controllers cannot ship in a mod bundle — the game's bundles embed their
  assets same-file), so a mod would have to author its own
  `AnimatorController` — the hard lane the entity docs already call unbuilt.

## The live client E2E fails at AUTHORIZE: client/server game-version skew, not Steamworks (2026-08-31, corrected)

The walk-entity live runs failed before the scenario armed: after
`NET: LiteNetLib: Connected to server` the client sits in
`[7dtd-fastconnect] boot hb ticks=… action=done` forever, and the
7dtd-playtest mod logged `queue cases=1` but no `DONE` — the run ends
`FAIL harness: no DONE from primary playtest mod`. The client log shows the
**real** cause, at connect time, not boot:

```
Client failed to authorize server: Game Version Mismatch: you have 'V 3.2.0' and server has 'V 3.1.0'
```

The installed Steam client auto-updated to **V 3.2.0** (buildid 24911213;
engine still Unity 2022.3.62f2, per `Initialize engine version: 2022.3.62f2`),
while this host's dedicated server is **V 3.1.0** (the build the project's RE
and `docs/research/research-provenance.md` were written against). The client
refuses the version-authorization gate, never joins the world, and idles at
the menu (`action=done`) until the harness times out. This is an environment
skew, not the asset, the harness logic, or the bundle — and the engine/Unity
revision is unchanged, so a 3.1.0-targeted bundle still loads in the 3.2.0
client.

**The `Steamworks is not initialized` exception is NOT the blocker.** It is
`Steamworks.SteamApps.GetCurrentBetaName` from the Analytics boot path
(`[Analytics] Failed to find current Steam Branch`), it is **caught**, and the
client proceeds past it through mod load → `NET: LiteNetLib: Connected to
server` → to the version check. A log that shows that exception and a
`Game Version Mismatch` line must be read as "version skew", never as
"Steamworks init" — prior runs misread it as a boot hang, which sent the
diagnosis down a dead end.

Fix is to align the dedicated server with the client's version via SteamCMD
(appid 294420, `+login anonymous +app_update 294420 validate`), then point
`SEVEN_DAYS_TO_DIE_SERVER_DIR` at the matching build.

Recheck before re-diagnosing a grounded-walk "failure": if the client log has
`Client failed to authorize server ... Game Version Mismatch` and
`action=done` (or `no DONE from primary playtest mod`), the run did not reach
the asset at all — do not treat a PASS/FAIL as evidence about the creature.
Confirm `client V` equals `server V` first.

## Generated creature spawns and walks once the controller and Physics node are the mod's own (2026-08-31)

The walk-entity case was blocked in turn by three NREs, each fixed and each
verified against the live client on V 3.2.0:

1. **Stock controller NRE.** `GameObjectAnimalAnimation.Awake` NREs at
   `anim["Idle1"]` (IL offset 0x64) because the controller is added during
   `EModelBase.Init` (`createAvatarController` → `AddComponent`), before the
   model hierarchy it inspects is settled, so its
   `GetChild(reverse-first-active).GetComponent<Animation>()` returns null.
   Fix: the mod-owned `ShamwayAnimalController` binds the figure's legacy
   `Animation` lazily on the first `Update`, and finds the figure by **name**
   (`transform.Find("figure")`).
2. **Grounding NRE.** With the NRE fixed, the spawn moved to
   `Entity.AddCharacterController`: it does
   `PhysicsTransform.gameObject.AddComponent<KinematicCharacterMotor>()`, and
   that motor binds its `Capsule` field in its own `Awake`
   (`GetComponent<CapsuleCollider>()`). The writer's `Physics` node was
   **inactive** (a #165 fix), which defers the motor's Awake forever, so
   `SetCapsuleDimensions` NREs on a null `Capsule`. Fix: the `Physics` node is
   **active** (the real-animal standard).
3. **Incompatibility.** The stock `GameObjectAnimalAnimation` is fundamentally
   incompatible with an active `Physics` node: active → the controller's
   first-active-child lookup picks `Physics` and NREs at `anim["Idle1"]`;
   inactive → the motor capsule is never bound and NREs at
   `SetCapsuleDimensions`. So a generated entity **must** use a mod-owned
   controller that finds the figure by name — this is why the generator wires a
   mod-owned `AvatarController` and mod-owned `Class`.

After both fixes the case passes: `spawned_id=172`, `travelled=…m`, a
`SkinnedMeshRenderer`, and captured frames under
`playtest-shots/clips/motion_shamwaySelfTestCreature/`. The rig still does not
behave like a grounded animal: with the borrowed stock `EntityAnimalSnake`
class the case measured `travelled=292 m` in a 12 s hold (the walk case sets
`moveSpeed=0.8`) and `y[61.02..74.11]` — far too fast and a 13 m Y-spread,
because the stock class drags a pre-authored AI/speed. The next slice is the
walk behaviour: the walk case's motor-drive, the CharacterController capsule
tuning, and the detached-camera framing (the captured frames still show the
player's first-person view, not the creature).

## The detached-camera frames: the player FP arm is not a toggleable renderer (2026-08-31)

The walk-entity clip frames showed a first-person arm filling the view, so the
creature was never visible. `EntityPlayerLocal.playerCamera` is the FP rig
(`vp_FPController`/`vp_FPCamera`); hiding its renderers and the player's renderers
did not remove the arm because it is part of the FP controller's rendered
composite, not a child renderer. `ClipRecorder`/`CaptureClipFrame` uses
`ScreenCapture.CaptureScreenshot`, which captures the composited game view, so
the arm is always in it. Fix: a dedicated capture camera — on
`Helpers.DetachCamera`, disable `player.playerCamera` and `player.finalCamera`
and create a plain `Camera`; `PointCameraAt` drives that camera at the creature;
`AttachCamera` re-enables the player cameras and destroys the capture camera.
This clears the arm; the frames now show the world (the creature is still not
framed because it moves too fast — measured ~264 m in a 12 s hold, and climbs
the terrain, so the walk behaviour is the next slice).

## The generated creature's walk is CharacterController-instability, not a moveSpeed override (2026-08-31)

The walk-entity case drives a spawned mod-owned `EntityAlive` with
`moveSpeed=0.8` + `SetMoveForward(1f)`, yet the creature's travel is erratic and
run-to-run variable (`travelled` 264 m, then 462 m, in the 12 s hold) and its Y
climbs (61 to 74, then 81). So the movement is not a `moveSpeed` artifact — the
Kinematic Character Controller is unstable: the creature is spawned ~2 m above
the terrain with a large grounding capsule (radius 0.8, height 2.75, the model
AABB-derived) on an ACTIVE `Physics` node, and the motor/CC flings and climbs it
erratically. A controllable gait therefore needs the CharacterController/capsule
tuning (spawn-at-surface, footprint vs height, slope/step handling) and the
`EntityAlive.MoveEntityHeaded` motion-lerp constants (0.546, 2.5, 0.3, 0.01)
reconciled to a grounded crawl — an engine-physics slice distinct from the
spawn/controller/grounding-NRE work already landed.

Walk-instability negative: spawning the creature at the player's surface level
(offset Y 2 -> 0) did not help — the case measured `travelled=514 m`, `y[61..84]`,
and the run-to-run travel is chaotic (264 m, 462 m, 514 m; peak y 74, 81, 84).
So the launch is not from a spawn drop; the Kinematic Character Controller for
this generated rig is unstable regardless, and needs the capsule dimensions /
KinematicCharacterMotor config / `MoveEntityHeaded` constants reconciled — not
the spawn offset.

Capsule-radius negative: reducing the grounding capsule radius cap 0.8 -> 0.35
did not stabilize the walk (still `travelled=471 m`, `y[61..82]`). Three
hypotheses are now ruled out by measurement: not a moveSpeed override, not the
spawn drop (spawn-at-surface made it worse), not an oversized capsule radius.
The instability is a deeper engine-physics interaction (KinematicCharacterMotor
+ `MoveEntityHeaded` motion-lerp constants + the generated rig) that needs a
systematic RE and modelling pass, not one-off parameter guesses. That RE
groundwork is now written up where the stock facts belong:
`hordeforge/7dtd-engine-research`
[entity-movement.md](https://github.com/hordeforge/7dtd-engine-research/blob/main/docs/entity-movement.md)
(`Entity::AddCharacterController`, `CharacterControllerKinematic`/
`KinematicCharacterMotor`, and the `MoveEntityHeaded` 0.546 / 2.5 / 0.3 / 0.01
constants). A generated creature can now be modelled against those facts instead
of guessing; the live-slice tuning and the detached-camera framing are the
remaining work.

## The generated creature is invisible because Shamway/Unlit does not skin (2026-08-31)

The walk-entity look that "should" show the creature showed only terrain: the
`Shamway/Unlit` material on the creature's `SkinnedMeshRenderer` renders
**nothing**. Verified live on V 3.2.0 by a runtime material swap in the walk
case: assigning the player's own skinned material (`Game/SDCS/Skin`) to the
creature's renderer made the creature **draw** (seen for a moment in the clip),
then it fell through the floor — so the invisibility and the fall are **two
separate failures**.

- **Invisibility (confirmed, root cause).** `Shamway/Unlit`'s vertex stage is
  `mul(unity_ObjectToWorld, input.vertex)` with **no bone-matrix skinning**
  (`shader_blob.unlit_textured` -> `UNLIT_VERTEX_HLSL`, `shader_blob.py:181`);
  its cbuffers carry `unity_ObjectToWorld`/`unity_MatrixVP` but no per-mesh
  bone matrices. It renders a `MeshRenderer` (the block prop) correctly, so the
  block lane is not affected. On a `SkinnedMeshRenderer` a vertex shader must
  apply the bone matrices or the mesh is degenerate / draws nothing: the
  creature's mesh is otherwise **healthy** — the probe read
  `verts=1382`, `meshSize=(0.33, 1.04, 0.83)`, `smrEnabled=True`,
  `meshActive=True`, `rootActive=True`, and the world AABB centred on the
  entity transform. A generated **entity** therefore needs a **skinning-capable**
  shader (either `Shamway/Unlit` gains bone-matrix support, or the entity lane
  assigns a stock skinning shader such as `Game/SDCS/Skin`). This is the
  handover task; see `docs/status/improvements.md` and
  `docs/authoring/entities.md`.

**RE of 7DTD's skinning shader — it is engine-provided, not authorable from the
bundles (2026-08-31).** The fix is **shader-only** (the material swap proved the
generated `SkinnedMeshRenderer` carries per-vertex blend weights, so the mesh
is fine). But the skinning shader to copy is **not in any asset bundle**: the
engine-research `shader_blob_dump.py` decode found **zero** shaders with more
than the four base vertex bind channels across `data.unity3d` (199 shaders,
5472 d3d11 sub-programs) and the 118 Addressables `automatic_assets_*` bundles,
and no shader named `Game/SDCS/Skin`. So it is a **built-in / always-included**
shader. Unity 2022.3's own `CGIncludes/UnityCG.cginc` and
`UnityShaderVariables.cginc` likewise carry **no `unity_SkinnedMeshBoneMatrix`**
and no skinning macro, and the skinning function (`Unity_LinearBlendSkinning`,
ShaderGraph's linear-blend node) is **runtime-provided** (compiled into Unity's
shader library, no source in the editor install). Conclusion: the GPU-skinning
convention (`unity_SkinnedMeshBoneMatrix` / the bone texture + blend inputs) is
**engine internals**, not derivable from 7DTD's bundles or the editor's source.
Authoring a compatible skinning shader needs that runtime convention as a
reference (a Unity-built skinned mesh's shader, or Unity's documented skinning
bindings), and is the remaining open item. Reproducing the *classic* cbuffer
bone-matrix vertex stage is the wrong route for this engine — 2022.3 uses the
ShaderGraph/runtime `Unity_LinearBlendSkinning` path.

**Refinement (2026-08-31): `Unity_LinearBlendSkinning` is DOTS-only, and the
non-DOTS path may be CPU-skinned — so the invisibility might be bind-channel
alignment, not GPU skinning.** Unity's own docs say the
[Linear Blend Skinning node] is **Entities Graphics (DOTS) only** (you provide
skinned matrices in a `_SkinMatrices` buffer), i.e. not the standard
`SkinnedMeshRenderer` path at all. For a standard (non-DOTS) `SkinnedMeshRenderer`,
Unity performs skinning **on the CPU** in the common case — the vertex shader
receives already-transformed vertices ([Unity discussion]). That reframes the
fix: if the mesh is CPU-skinned, a *plain* vertex shader should draw it, so
`Shamway/Unlit` drawing nothing is more likely a **bind-channel alignment**
failure (its declared POSITION/NORMAL/UV0 channels not matching the
`SkinnedMeshRenderer` mesh's vertex layout) than a missing GPU-skinning shader.
Next diagnostic before authoring anything: compare the mesh's vertex channel
sources (the writer emits POSITION 0, NORMAL 1, UV0 4, blend 12/13) against
`Shamway/Unlit`'s bind-channel block; a misalignment there is the smaller,
fully-editorless fix. Also verify whether the creature is CPU- or GPU-skinned at
runtime (e.g. whether the SkinnedMeshRenderer updates the mesh each frame).

[Linear Blend Skinning node]: https://docs.unity3d.com/Packages/com.unity.shadergraph@14.0/manual/Linear-Blend-Skinning-Node.html
[Unity discussion]: https://discussions.unity.com/t/how-would-you-access-skinned-mesh-pre-skinned-vertex-positions-in-shaders-these-days/918845
- **Fall / grounding (separate, the walk-instability).** With the mesh finally
  drawn, the creature "fell off the world" to
  `pos=(512.2, -2.5, 940.6)` while the case reported `y[60.05..63.07]`
  (`travelled=4.26 m`). The entity's `GetPosition()` (save/world frame) and its
  `transform.position` (Unity render frame) diverge by `World.Origin` —
  `getpos=(512,60,940)` vs `tf=(1.5,15,15.5)` in the probe — so the walk case
  must frame and ground on `transform.position`, not `GetPosition()`: the
  camera framing was corrected to `e.transform.position` (the render frame) and
  the creature is then followed. The motor/capsule grounding that still drops
  it is the engine-physics item already documented above.

Also measured in the same session: the spawn-area "car" that occluded the shot
is a **static world prop**, not an `EntityVehicle`, so despawning vehicles
(`Helpers.Vehicles`, `EntityVehicle`) does not remove it; a clear spawn or a
vehicle-agnostic camera vantage is needed for a clean look.
