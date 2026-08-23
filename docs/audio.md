# Sound

How a sound gets from nothing into a mod, and the engine facts that decide
whether a correctly loaded clip is actually heard. Audio has more silent
failure modes than any other lane: a clip that loads, resolves, and validates
can still be inaudible, and nothing offline will say so.

## Two ways a clip reaches the bundle

Unity's importer encodes a WAV to Vorbis and stores the bank in the bundle's
`.resource` stream. The editorless backend (`bundle_source = "synthesized"`)
stores the clip as **16-bit PCM inside an FSB5 bank** it writes itself: larger,
and exactly the samples that were authored and signed off on, with no encoder
in between. FMOD in a real Unity runtime decodes it (see
[research-provenance.md](research-provenance.md) for the measurement).

Two constraints come from FMOD's own sample header, and both are refused rather
than worked around, because a clip that plays at the wrong pitch passes every
other gate:

- the sample rate must be one FMOD's table names — 8000, 11000, 11025, 16000,
  22050, 24000, 32000, 44100, 48000 or 96000;
- the clip must be 16-bit, mono or stereo.

```bash
ffmpeg -i in.wav -ar 44100 -ac 1 -c:a pcm_s16le out.wav
```

```bash
shamway check-sound out.wav
```

## Quick start

Synthesize a clip, gate it, put it in the bundle, and wire it:

```bash
shamway generate sound blast assets-src/audio/blast-near.wav --seed 7 \
    --promote tools/shamway/UnityProject/Assets/ModAssets/Bundle/Sounds/myModBlastNear.wav
shamway check-sound assets-src/audio/blast-near.wav
shamway build && shamway validate
```

`--promote` writes the bundle copy from the same run, byte-identical, under
its mod-prefixed stem. Promote from the generator, never by hand-copying: the
shipped clip is then the recorded design by construction and cannot drift.

Print the `Config/sounds.xml` entry to paste:

```bash
shamway generate sound sounds-xml myModBlastNear \
    --group myModBlast --mod MyMod --bundle mymod.unity3d
```

Everything below is detail.

## How the engine finds a clip

A `sounds.xml` `ClipName` may point at a mod-folder bundle URI, because
`Audio.Manager.LoadAudio` resolves it through the same
`DataLoader.LoadAsset<AudioClip>` path that block models and item meshes use.
The URI form and its four contractual pieces are in
[game-integration.md](game-integration.md); the same stem, case, and uniqueness
rules apply, and `shamway validate` checks a `ClipName` exactly as it
checks a `Model`, because it discovers every bundle URI under `Config/**/*.xml`
without caring which file or property it came from.

```xml
<configs>
	<append xpath="/Sounds">
		<SoundDataNode name="myModBlast">
			<AudioSource name="@:Sounds/Prefabs/AudioSource_Explosion.prefab" />
			<AudioClip ClipName="#@modfolder(MyMod):Resources/mymod.unity3d?myModBlastNear.wav" />
			<DistantClip ClipName="#@modfolder(MyMod):Resources/mymod.unity3d?myModBlastDistant.wav" />
			<DistantFadeStart value="120" />
			<DistantFadeEnd value="200" />
		</SoundDataNode>
	</append>
</configs>
```

`Config/sounds.xml` is patched like any other config: the root is `<Sounds>`,
and `SoundsFromXml.ParseNode` reads every `SoundDataNode` child. Per node it
accepts, matched case-insensitively and read from the element's *first*
attribute:

| Element | What it sets |
|---|---|
| `AudioSource name=` | the node's default source prefab — a bundle URI or a vanilla `@:Sounds/Prefabs/AudioSource_*.prefab`; the installed `sounds.xml` uses the full `@:` form every time (`UI_Item`, `Footsteps`, `UseAction`, `Reloads`, `Impact`, `Interact`, `Explosion`, … are the common suffixes) |
| `AudioClip ClipName=` | the clip; also takes `AudioSourceName`, `Loop`, `DistantClip`, `DistantSource`, `AltSound` |
| `DistantFadeStart` / `DistantFadeEnd` | the crossover distances — **the first defaults to −1, meaning never** |
| `Noise` | reports the sound to the AI director (`ID`, `range`, `volumeScale`, `heardBy`) |
| `MaxVoices`, `MaxVoicesPerEntity`, `MaxRepeatRate` | concurrency limits |
| `LowestPitch`, `HighestPitch` | per-play pitch variation |
| `LocalCrouchVolumeScale`, `CrouchNoiseScale`, `NoiseScale` | stealth scaling |
| `Channel`, `Priority` | mixer routing and eviction order |

`SoundsFromXml` calls `DataLoader.PreloadBundle` on those names at parse time,
so a mod bundle referenced from a sound node is opened during config load
rather than at the first play.

**Do not add `<Noise>` reflexively.** It reports the sound to the AI director's
heat map. A mod sound layered *on top of* a vanilla event that already reports
its own noise calls the horde twice for one event. `shamway generate sound sounds-xml`
therefore omits it unless you pass `--noise`.

## The three ways a loaded clip stays silent

Each of these is a real engine behaviour, decompiled from V 3.1.0 b14 (see
[research-provenance.md](research-provenance.md)). All three pass every offline
gate.

**1. `maxDistance` on the AudioSource prefab.** `LoadAudio` plays nothing at
all beyond the AudioSource prefab's `maxDistance`. Vanilla's explosion source
rolls off over a few hundred metres, so a kilometre-scale event referencing it
is simply silent out there — before any distant clip or fade setting gets a
say. Two ways out, and the choice is a real design decision:

- **Ship a mod-owned AudioSource prefab** in the bundle with a large
  `maxDistance`, and name it in the sound group. `GeneratedAsset.AudioSourcePrefab(...)`
  builds one with 3D spatial blend and logarithmic rolloff.
- **Play the sound near the listener, in the direction of the event, and apply
  the attenuation yourself.** The source project chose this: the hook plays the
  blast 40 m from the listener toward the detonation and scales the volume by
  real distance. The direction stays honest, vanilla mixer routing and the
  player's volume options still apply, and no second prefab has to be
  maintained. It needs a C# hook, which the first option does not.

**2. `DistantFadeStart` defaults to −1, meaning never.** `Audio.Manager.Play`
switches to a node's `DistantClip` only past `DistantFadeStart` metres, and
stops the near clip past `DistantFadeEnd`. Authoring a beautiful distant
variant and leaving the defaults alone means it never plays.

**3. The sound group name never resolves.** An unknown group does not error —
it simply never plays. `validate` proves the *clip* is in the bundle under the
right stem; it cannot prove the group name a block or item property references
matches the group you declared.

A fourth, which is not the engine's fault: **automated playtest launchers
commonly mute the client** at the OS audio layer, because a test run should not
make noise. Neither 7DTD nor Unity has a mute launch argument, so harnesses
mute the process's PipeWire/Pulse sink input instead — and that mute can
persist for normal play, since WirePlumber saves per-application stream state.
If a sound "does not play", confirm the client is actually unmuted before
believing any of the three above.

The mechanics, which `shamway client` wraps:

- `shamway client launch --mute --run-seconds 120` — a non-listening run
- `shamway client mute` — the running client only
- `shamway client unmute` — and report the saved state

```bash
shamway client launch --mute --run-seconds 120
shamway client mute
shamway client unmute
```

`mute` polls `pactl -f json list sink-inputs` for a stream whose
`application.name` or `application.process.binary` contains `7DaysToDie`
(the stream exists only once the game has initialised audio, hence the poll),
then `pactl set-sink-input-mute <index> 1`. It never touches GamePrefs, the
in-game sliders, or the registry. `unmute` does the reverse and then reads
`~/.local/state/wireplumber/stream-properties`: if the
`Output/Audio:application.name:7DaysToDie…` entry still says `"mute":true`,
the next launch starts silent, and the game has to be running for the unmute
to be written back — or edit that file and `systemctl --user restart
wireplumber`.

Two rules follow. **A listening run is never muted**, and a harness that
accepts a sound must refuse an explicit mute rather than quietly honour it — a
green run nobody could hear is worse than none. And **every run report names
its audio state**, so a later reader can tell a listening run from a loading
run.

## Two clips, one event

A large event heard near and far is not two sounds; it is one event and two
distances, and they differ predictably:

| | Near | Distant |
|---|---|---|
| Transient | broadband crack, milliseconds | none — air absorbs it |
| Body | sub-bass pressure sweep | slow swell |
| Tail | rolling rumble | longer, more low-passed rumble |
| Arrival | immediate | delayed by the real travel time of sound |

`shamway generate sound blast` generates both from one seed, which is what keeps them
recognisably the same event:

```bash
shamway generate sound blast assets-src/audio/blast-near.wav --seed 7
shamway generate sound blast assets-src/audio/blast-far.wav  --seed 7 --distant
```

If the mod plays the distant clip from code, delay it by `distance / 343`
seconds. A nuclear blast heard instantly two kilometres away reads as a bug
even to a player who could not say why.

Four more facts from the same large-event work, each decompiled or measured
on V 3.1.0 b14:

- **The vanilla explosion keeps playing underneath.** `GameManager.ExplosionClient`
  instantiates `WorldStaticData.prefabExplosions[ParticleIndex]` *including
  the `AudioPlayer` that prefab carries* — index 13 is a grenade-scale bang
  under two seconds. A mod sound for the same event **layers on top** unless
  the mod suppresses it, and suppress-versus-layer, volume scale, and
  `MaxVoices` are first-listen decisions. It is also why a second `<Noise>`
  reports the event to the AI director twice.
- **Heard further than seen.** Sound carries to 6,000 m while the detailed
  cloud is culled past 2,500 m; schedule the audio **before** the visual LOD
  decision, never inside it, or the far player hears nothing. At the edge,
  fade to roughly a quarter volume rather than to nothing — silence at the
  boundary reads as a cut, not as distance.
- **Play through the engine, not an AudioSource.** `Audio.Manager.Play(Vector3
  position, string group, int entityId = -1, bool, float volumeScale)` keeps
  the game's own AudioSource prefab, mixer routing, and the player's volume
  options; nothing a mod writes should construct an `AudioSource`. Positions
  are world coordinates minus `Origin.position` (7DTD re-bases its floating
  origin), as the stock code does. When the clip is delayed, recompute the
  direction at arrival, not at firing: the player moves during a six-second
  flight.
- **Local, non-positional cues.** `Audio.Manager.PlayInsidePlayerHead(group)`
  plays a sound group at the listener, and vanilla groups are reusable by
  name — `buff_geiger_counter` (three clips in the installed
  `Data/Config/sounds.xml`) is the stock hazard-feedback cue. For an
  intensity-driven cue, bound the repeat interval (the source project used
  4.0 s down to 0.18 s) so it stays readable rather than becoming a tone.

## The generator

`shamway generate sound` is standard-library only, so the audio lane
works on a bare host. Each subcommand is a **designed voice** rather than a
generic oscillator, because "explosion" and "sine with noise" are not the same
request:

| Voice | What it is | Typical use |
|---|---|---|
| `blast` | crack + sub-bass sweep + rolling rumble + debris, or the distant swell | explosions, large impacts |
| `tick` | one dry escapement click, under 90 ms | an item's `SoundTick` countdown |
| `whoosh` | filtered noise sweeping up and back down | a thrown object, a passing shell |
| `hum` | mains fundamental with harmonics and grit, optionally seamless | machinery, ambience |
| `beep` | short electronic cue, repeatable | UI, warnings |
| `sounds-xml` | prints the `Config/sounds.xml` entry | wiring |

The script is the clip's provenance, the way a prompt is a generated image's:
nothing is recorded or downloaded, the noise generator is seeded, and
re-running reproduces the file byte-for-byte. Record the exact command and
`--seed` in `assets-src/README.md`. A diff then means someone changed the
design, not that the tool is nondeterministic.

Anything a sound group loops must be generated with `--loop`, which crossfades
the tail over the head. A click at the loop point is the most recognisable
sign of mod-made ambience there is.

## The offline gate

- `shamway check-sound clip.wav --json` — for CI and agents

```bash
shamway check-sound assets-src/audio/blast-near.wav
shamway check-sound clip.wav --json
```

It fails on the format mistakes a listener cannot fix afterwards: not mono, an
unexpected sample rate, digital silence, a clip so quiet it is inaudible beside
vanilla content, samples at full scale, and DC offset. It notes leading silence
(a one-shot triggered by a game event sounds late by exactly that much) and a
missing trailing fade.

Mono is the default because 7DTD positions sounds in 3D itself, so a stereo
clip on a 3D AudioSource is downmixed anyway; pass `--allow-stereo` for a
deliberate 2D UI or music cue.

**DC offset deserves its own sentence**, because it is the one that catches
generators. Long low-frequency layers — a filtered random walk, a sub-bass
sweep — reliably leave content below 20 Hz that no player can hear but that
moves the waveform off centre, so the normalizer spends headroom on it and the
clip clicks when playback starts. `shamway generate sound` high-passes every finished
mix at 12 Hz for this reason. This check caught exactly that defect in this
repository's own generator.

`check-sound` needs no configuration, so it runs outside a mod:

```bash
shamway call check_sound --params '{"clip": "clip.wav"}'
```

## Which XML properties name a sound group

`validate` proves the clip; nothing offline proves the *group name* a
property references exists. These are the properties in the installed
V 3.1.0 b14 `items.xml`, `blocks.xml`, and `entityclasses.xml` that take a
sound group, by frequency: blocks `SoundPlace`, `SoundPickup`, `OpenSound`,
`CloseSound`, `UpgradeSound`, `SoundDestroy`, `LockedSound`, `TriggerSound`,
`ActivateSound`; items and actions `Sound_start`, `Sound_end`, `Sound_repeat`,
`Sound_loop`, `Sound_empty`, `Sound_reload`, `Sound_Sight_In`/`Out`,
`SoundHolster`, `SoundUnholster`, `SoundJammed`, `SoundTick`; entities
`SoundHurt`, `SoundDeath`, `SoundAttack`, `SoundAlert`, `SoundRandom`,
`SoundSense`, `SoundGiveUp`, `StartSound`, `StopSound`. A typo in any of them
is silent in game; the in-process check in [validation.md](validation.md)
looks each one up in `Audio.Manager.audioData`.

## Countdown ticks

`ItemClass.Init` parses `SoundTick` as `"<group>[,<delaySeconds>]"`, defaulting
to one second. `ItemClassTimeBomb.OnDroppedUpdate` decrements a timer by 0.05
per call while the item's `Meta` is above zero and, at zero, resets it to
`SoundTickDelay` and plays the group through `Entity.PlayOneShot`. So a timed
item with no `SoundTick` is silent for its entire countdown, and the only cue
is whatever the mesh shows.

## Unity import

Promote only the selected clip into the bundle-membership folder — from the
generator (`--promote`), so the bytes are the recorded design — and commit its
`.meta`. `GeneratedAsset.ImportAudioClip(...)` sets the import the pipeline
wants: Vorbis compression, force-to-mono, `preloadAudioData` off, and streaming
for anything long — a bundle opens lazily, and a multi-megabyte clip
decompressed at load stalls the frame it lands on.

Keep source generators **outside** that folder. The `.wav` that ships is a
copy; the generator and its full-length source stay in `assets-src/audio/`.

## Acceptance

Offline output proves the clip exists, is addressable, and is not malformed. It
proves nothing about the experience. Before calling a sound done, listen:

1. **Near**, at the event, at normal game volume against ambient noise.
2. **Across the fade**, walking out through `DistantFadeStart` — the switch to
   the distant clip must not be audible as a switch.
3. **At maximum range**, where `maxDistance` decides whether it exists at all.
4. **Under simultaneous events**, several at once, checking the voice limit
   does not cut the one that matters.
5. **On loop**, for anything looping, for long enough to hear a seam.

Say which of these you did. "The bundle validates and the clip resolves" is not
"the sound works", and the difference is the whole point of this page.

Keep an **owed-sounds list** in the mod's docs alongside the asset inventory:
every gameplay event that is still silent (a countdown tick, a falling
whistle, an arming click, a zone ambience). A sound that was never authored
produces no error, so the list is the only thing that makes its absence
visible. Reusing a vanilla group on a mod-owned model is legitimate — say so
in the inventory, the way a stand-in mesh is declared.
