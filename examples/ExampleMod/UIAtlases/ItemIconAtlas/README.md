# Item icons go here

One 160 x 160 RGBA PNG per icon, named exactly as the `CustomIcon` value that
references it. `ModManager.LoadUiAtlases` packs each immediate subfolder of
`UIAtlases/` at runtime, so the folder name is the atlas name and each file
stem is a key.

These never enter the asset bundle, which is why `7dtd-assets validate` cannot
see them and `7dtd-assets check-icons` exists.

```bash
7dtd-assets generate cutout key ../../assets-src/icons/thing-src.png \
    exampleModThing.png --size 160 --pad 0.9 --trim
7dtd-assets check-icons
```

Art direction and the prompt patterns: `docs/art-direction.md` in the pipeline.
