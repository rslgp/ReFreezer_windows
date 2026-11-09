"""Tests for the collapsible panels (library, track list, queue)."""

import time
import unittest


class PanelDockTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()  # one root per test: no stale poll of an earlier window
        except Exception:
            self.skipTest("Tkinter not available")
        from rfw import app as app_mod

        self.win = app_mod.MainWindow(self.root)
        self.pump(0.3)

    def tearDown(self):
        self.root.destroy()

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.02)

    def slots(self):
        """Pane names in order: the panel name when shown, 'strip:<name>' when collapsed."""
        dock = self.win.panels
        out = []
        for w in dock.pane.panes():
            p = next(p for p in dock._panels if str(w) in (str(p["frame"]), str(p["strip"])))
            out.append(p["name"] if str(w) == str(p["frame"]) else f"strip:{p['name']}")
        return out

    def test_each_panel_collapses_in_place_and_comes_back(self):
        dock = self.win.panels
        self.assertEqual(self.slots(), ["Library", "Tracks", "Queue"])
        for name in ("Library", "Tracks", "Queue"):
            dock.collapse(name)
            expected = ["Library", "Tracks", "Queue"]
            expected[expected.index(name)] = f"strip:{name}"
            self.assertEqual(self.slots(), expected)
            self.assertTrue(dock.is_collapsed(name))
            dock.expand(name)
            self.assertEqual(self.slots(), ["Library", "Tracks", "Queue"])

    def test_several_collapsed_and_repeat_calls_are_harmless(self):
        dock = self.win.panels
        dock.collapse("Library")
        dock.collapse("Queue")
        dock.collapse("Queue")
        self.assertEqual(self.slots(), ["strip:Library", "Tracks", "strip:Queue"])
        self.assertFalse(dock.all_expanded())
        dock.toggle("Library")
        dock.toggle("Queue")
        self.assertEqual(self.slots(), ["Library", "Tracks", "Queue"])

    def test_strip_is_narrow_and_dividers_return_when_all_shown(self):
        dock = self.win.panels
        dock.collapse("Queue")
        self.pump(0.3)
        strip = dock._panel("Queue")["strip"]
        self.assertLess(strip.winfo_width(), 60)
        dock.expand("Queue")
        self.pump(0.3)
        width = dock.pane.winfo_width()
        self.assertEqual(dock.pane.sashpos(1), width - max(340, width // 4))

    def test_collapse_buttons_sit_in_each_header(self):
        for view, arrow in ((self.win.nav_view, "‹"), (self.win.track_view, "‹"), (self.win.queue_view, "›")):
            texts = [w.cget("text") for w in view.header.winfo_children() if w.winfo_class() == "TButton"]
            self.assertIn(arrow, texts)


if __name__ == "__main__":
    unittest.main()
