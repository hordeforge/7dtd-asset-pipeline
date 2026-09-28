"""The package's dependency direction, as assertions rather than a convention.

A flat layer of modules plus two feature subpackages stays navigable only
while three properties hold, and each of them has been broken at least once
and repaired by hand. Each is cheap to check mechanically, so each is checked
here: an import cycle, a root module reaching up into `generators/`, and the
ubiquitous base modules growing a dependency on a feature they used to be
underneath.

`docs/architecture.md` states the rules; this file is what stops them rotting.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import sevendtd_asset_pipeline as package

SOURCE = Path(package.__file__).parent

# Root modules that name a feature on purpose: the published surface stack,
# whose whole job is to reach every leaf.
SURFACE = frozenset({"", "api", "cli", "operations", "serve"})

# Imported by more than a handful of modules, so anything they pull in is paid
# for by the whole package. Each may only reach another base module, or the
# credential state behind `providers`, which is itself a host capability.
BASE_MODULES = frozenset({"atomic", "capabilities", "errors", "text", "workdir"})
BASE_ALLOWED_EXTRAS = frozenset({"providers", "providers.base"})


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE).parts)
    if parts[-1] == "__init__.py":
        return ".".join(parts[:-1])
    return ".".join([*parts[:-1], parts[-1][: -len(".py")]])


def _modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for path in sorted(SOURCE.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _imports(name: str, path: Path) -> set[str]:
    """Every in-tree module `path` names, spelled as the import wrote it.

    Both spellings count: `from .foo import bar` names the module, and
    `from . import foo` names it through the alias.
    """
    package_parts = name.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                if node.module:
                    found.add(".".join([*base, node.module]))
                else:
                    found.update(".".join([*base, alias.name]) for alias in node.names)
            elif node.module and node.module.startswith(f"{package.__name__}."):
                found.add(node.module[len(package.__name__) + 1 :])
        elif isinstance(node, ast.Import):
            found.update(
                alias.name[len(package.__name__) + 1 :]
                for alias in node.names
                if alias.name.startswith(f"{package.__name__}.")
            )
    found.discard(name)
    return found


def _graph() -> dict[str, set[str]]:
    """The in-tree import graph, each edge resolved to the module that owns it."""
    modules = _modules()
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        resolved: set[str] = set()
        for imported in _imports(name, path):
            target = imported
            while target and target not in modules:
                target = target.rsplit(".", 1)[0] if "." in target else ""
            if target and target != name:
                resolved.add(target)
        graph[name] = resolved
    return graph


class DependencyDirectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = _graph()
        # Every rule below is a statement about modules that exist. A renamed
        # source root, a packaging change or a swallowed walk error would
        # return an empty graph, and an empty graph has no cycle, no offender
        # and no base module: all three would pass having checked nothing.
        self.assertGreater(
            len(self.graph), 50, f"the module walk found {len(self.graph)} modules to check"
        )

    def test_the_import_graph_has_no_cycle(self) -> None:
        """Settle what imports nothing, then what that leaves nothing.

        Whatever cannot be settled this way sits in a cycle, and its members
        are reported by name so the cycle is readable from the failure.
        """
        graph = self.graph
        settled: set[str] = set()
        while True:
            free = {
                name for name, deps in graph.items() if name not in settled and not deps - settled
            }
            if not free:
                break
            settled |= free
        self.assertEqual(sorted(set(graph) - settled), [])

    def test_no_root_module_reaches_into_a_feature_subpackage(self) -> None:
        """`generators/` sits above the flat layer, not inside it.

        A gate or writer that imports a generator has the arrow backwards, and
        the cost is paid by every module that imports the gate.
        """
        offenders = {
            name: sorted(dep for dep in deps if dep.split(".")[0] == "generators")
            for name, deps in self.graph.items()
            if name not in SURFACE and "." not in name
        }
        self.assertEqual({name: deps for name, deps in offenders.items() if deps}, {})

    def test_the_base_modules_depend_on_nothing_but_each_other(self) -> None:
        """These are imported nearly everywhere, so their closure is the package's.

        `capabilities` answering a library question once pulled the whole
        shader compiler in behind it; the probe belongs in the registry.
        """
        graph = self.graph
        allowed = {name for name in graph if name.rsplit(".", 1)[-1] in BASE_MODULES}
        allowed |= BASE_ALLOWED_EXTRAS
        for name in sorted(allowed & set(graph)):
            self.assertLessEqual(graph[name], allowed, f"{name} reaches outside the base layer")

    def test_the_two_edges_repaired_here_stay_repaired(self) -> None:
        """The clip gate owns the WAV reader, and the registry owns the zmol-v probe."""
        graph = self.graph
        self.assertEqual(graph["sound_check"], {"errors"})
        self.assertNotIn("shader_blob", graph["capabilities"])
        # The probe the shader compiler uses is reached through the registry,
        # not by a base module reaching up for the compiler itself. Asserting
        # the edge, not that the name resolves: `callable(...)` holds for any
        # function body and would survive the edge being reversed.
        self.assertIn("capabilities", graph["shader_blob"])
        self.assertNotIn("shader_blob", graph["capabilities"])
        # The arrow points down: the generator converts through the gate's
        # reader, and the gate never reaches back up for it.
        self.assertIn("sound_check", graph["generators.audio"])


if __name__ == "__main__":
    unittest.main()
