"""Fitness test for the rfw package layout: each layer imports only the layers below it,
and only the GUI layer touches Tk."""

import ast
import unittest
from pathlib import Path

RFW = Path(__file__).resolve().parents[2] / "rfw"

# Layer -> layers it may import (besides itself)
ALLOWED = {
    "deezer": set(),
    "win": set(),
    "core": {"deezer"},
    "media": {"deezer"},
    "services": {"deezer", "core", "media", "win"},
    "ui": {"deezer", "core", "media", "win", "services"},
    "app": {"deezer", "core", "media", "win", "services", "ui"},
}
TK_LAYERS = {"ui", "app"}


def layer_of(path):
    rel = path.relative_to(RFW).parts
    return rel[0] if len(rel) > 1 else "app"


def imported_layers(path):
    """rfw layers a module imports (relative or absolute), plus whether it imports tkinter."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = list(path.relative_to(RFW.parent).with_suffix("").parts[:-1])
    layers, tk = set(), False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - node.level + 1]
                names = [".".join(base + ([node.module] if node.module else []))]
            else:
                names = [node.module or ""]
        else:
            continue
        for name in names:
            parts = name.split(".")
            tk = tk or parts[0] == "tkinter"
            if parts[0] == "rfw" and len(parts) > 1 and parts[1] in ALLOWED:
                layers.add(parts[1])
            elif parts[0] == "rfw" and len(parts) > 1 and parts[1] == "app":
                layers.add("app")
    return layers, tk


class LayerTests(unittest.TestCase):
    def modules(self):
        return [p for p in RFW.rglob("*.py") if "__pycache__" not in p.parts]

    def test_layers_only_import_downwards(self):
        bad = []
        for p in self.modules():
            own = layer_of(p)
            layers, _ = imported_layers(p)
            for target in layers - {own} - ALLOWED.get(own, set()):
                bad.append(f"{p.relative_to(RFW)} ({own}) imports {target}")
        self.assertEqual(bad, [])

    def test_only_gui_layers_import_tkinter(self):
        bad = [str(p.relative_to(RFW)) for p in self.modules()
               if imported_layers(p)[1] and layer_of(p) not in TK_LAYERS]
        self.assertEqual(bad, [])

    def test_every_module_belongs_to_a_known_layer(self):
        unknown = {layer_of(p) for p in self.modules()} - set(ALLOWED)
        self.assertEqual(unknown, set())


if __name__ == "__main__":
    unittest.main()
