# ADR 0006 — Render an icon from the mesh with Blender when there is no editor

## Status

Accepted.

## Context

An item icon has two honest sources: art drawn or generated for it, and a
photograph of the item itself. The second exists so the icon cannot drift from
the geometry — regenerate the mesh, regenerate the icon —
and [authoring/art-direction.md](../authoring/art-direction.md) treats both as
first-class.

Until now the photograph lane was `shamway render-icon`, which drives a Unity
editor over a **bundle prefab**. [ADR 0001](0001-synthesize-bundles-without-an-editor.md)
removed the editor from the bundle for textures, clips, text files and, as of
2026-08-24, meshes — so the lane was closed to exactly the mods that had just
stopped needing Unity. A synthesized mod has no prefab to photograph and no
editor to photograph it with.

Three alternatives were considered:

1. **Leave it closed.** A bundle-free or synthesized mod draws or generates its
   icons. Workable, and it is what the documentation said; it just means the
   one lane whose whole point is *not drifting from the mesh* is unavailable
   precisely where the mesh is now cheapest to change.
2. **Render the mesh in a Unity runtime without a project.** Still an editor,
   still several gigabytes, and `verify-bundle` already occupies the "an editor
   that happens to exist is a checker" niche. It buys materials only if there
   *are* materials, and on this path there are not.
3. **Render the mesh in Blender.** Already a declared capability, already
   driven headlessly by `shamway generate mesh`, and it reads every format the
   mesh lane accepts because both sit on interchange files.

The measured constraint behind the honest downside: a material needs a shader,
a shader in a bundle is compiled platform bytecode, and both routes to
borrowing one from the game are closed — the shipped player's `unity default
resources` carries six shaders and all are internal, and the game's own bundles
embed theirs with `m_Shader.m_FileID: 0`. Measured with UnityPy against the
installed game, 2026-08-24; see
[research/research-provenance.md](../research/research-provenance.md), "Why a
material cannot follow the mesh". So on this path there is no material to
render, and no amount of renderer choice changes that.

## Decision

`shamway generate mesh-icon MESH PNG` renders the mesh file into an atlas cell
through headless Blender on Cycles, with the camera defaults, supersample and
Lanczos downscale that `render-icon` and `icon_render.py` already use, and it
reports in its own output that what it produced is a clay render.

`render-icon` is unchanged and stays the better answer wherever an editor and a
prefab exist, because it photographs the thing the player actually sees.

## Consequences

Easy now: a mod on the synthesized path gets a mesh-accurate icon with no
editor, from the same file that became the bundle's `Mesh`, and the two icon
lanes frame an object identically so a mod can move between them without a
visible jump.

The honest downside: **the icon is not what the player sees.** An interchange
file carries no Unity material, so the render reports silhouette, proportion
and framing over neutral clay. Treated as finished art it ships an item whose
icon is grey and whose in-game model is not. The generator says so on every
run and [art-direction.md](../authoring/art-direction.md) calls it a base coat,
but nothing mechanical can catch a person ignoring both — which is the same
shape as every other gate here: the offline half is necessary, the look is not
optional.

Two failure modes are designed out rather than documented, and both are in the
gate table's spirit even though neither is a listed gate. Cycles on the CPU is
deliberate: Blender's realtime engines want a GL context and a headless host
without one renders a blank frame **and exits zero**, the same silence
`render-icon` avoids by refusing `-nographics`. The alpha-coverage floor is the
second guard, and it earned its place immediately — during development it
caught a stale `matrix_world` that aimed the camera at nothing and produced a
transparent cell no other check would have failed.

What would justify revisiting this: an offline path to a valid material, which
means either a shader the writer can emit or a shader in the shipped player
that a mod's material may legally reference. Both were measured closed on
2026-08-24. If either changes, the right move is a real prefab render, not a
better clay one.
