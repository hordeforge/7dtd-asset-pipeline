# Bundles — where the `.unity3d` comes from

The artifact this pipeline exists to produce, and the paths that can produce
it.

- [bundle-generation.md](bundle-generation.md) — the editor build path end to
  end: the Unity project, `BundleBuilder.cs`, the build log, and the gates the
  artifact has to pass before it is staged.
- [no-unity.md](no-unity.md) — the answers when there is no editor: no bundle
  at all, a bundle built elsewhere and staged here, or one synthesized by
  `shamway pack`, with what each one's gates are actually worth.

The design record for the editorless writer is
[ADR 0001](../adrs/0001-synthesize-bundles-without-an-editor.md); the gates
themselves are catalogued in [validation.md](../validation.md).
