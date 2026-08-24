# Bundles — where the `.unity3d` comes from

The artifact this pipeline exists to produce, and the paths that can produce
it.

Read them in this order — the first is the default, the second is the opt-in.

- [no-unity.md](no-unity.md) — the three sources that need no editor, including
  the default: a bundle this tool writes itself (textures, clips, text files,
  and a mesh becoming a prefab with its material and shader), a bundle built
  elsewhere and staged here, or no bundle at all — with what each one's gates
  are actually worth.
- [bundle-generation.md](bundle-generation.md) — the opt-in editor build path
  end to end: the Unity project, `BundleBuilder.cs`, the build log, and the
  gates the artifact has to pass before it is staged. Take it when the bundle
  needs lit, transparent, normal-mapped or multi-pass shading, particles, or
  rigging.

The design record for the editorless writer is
[ADR 0001](../adrs/0001-synthesize-bundles-without-an-editor.md); the gates
themselves are catalogued in [validation.md](../validation.md).
