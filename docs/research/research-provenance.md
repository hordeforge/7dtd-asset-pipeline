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

Runtime confirmation, same day: a synthesized bundle carrying all three classes
was loaded by a real Unity 2022.3.62f2 runtime through
`AssetBundle.LoadFromFile` (`shamway verify-bundle`). Every asset returned its
own type and name, the TextAsset its text, the Texture2D `4x2 RGBA32` with the
pixels in the right rows, and the AudioClip `channels=1 frequency=44100
samples=4410`. That is the engine's own loader and its own class definitions,
not this repository's parser — but it is not 7DTD, and it is not acceptance.

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
