"""Graphviz can render, so pydot's write_pdf and friends work in notebooks.

On macOS, conda-forge's graphviz ships without its plugin registry and relies
on a post-link script that pixi does not run; the pixi activation script
scripts/register-graphviz-plugins.sh writes it instead. Without the registry,
`dot` fails with 'Format: "pdf" not recognized. No formats found.' On Linux
and Windows the package ships the registry, so this guards against a
regression there too. See "Graphviz on macOS" in AGENTS.md.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest


class GraphvizRendersTest(unittest.TestCase):
    def test_dot_renders_pdf(self):
        dot = shutil.which("dot")
        self.assertIsNotNone(dot, "graphviz `dot` is not on PATH")
        result = subprocess.run(
            [dot, "-Tpdf"],
            input=b"digraph { a -> b }",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(result.stdout.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
