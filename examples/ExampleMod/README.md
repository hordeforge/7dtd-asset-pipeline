# Example consumer

This directory illustrates the files a mod owns after `7dtd-assets init`.
The full Unity template is omitted here because the CLI creates it.

```bash
7dtd-assets init /path/to/real/ExampleMod \
  --game-dir "/path/to/7 Days To Die"
cd /path/to/real/ExampleMod
7dtd-assets doctor
7dtd-assets build --probe
```

After importing a prefab named `exampleModWorkbench` below the generated
Unity project's `Assets/ModAssets/Bundle/`, build the real bundle before using
the sample XML reference.
