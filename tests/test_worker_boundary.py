"""Keep process-isolated wire code independent of Blender's Python API."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkerBoundaryTests(unittest.TestCase):
    def test_worker_and_shared_wire_sources_do_not_import_bpy(self):
        for path in (ROOT / "bridge/io_worker.py", ROOT / "protocol/frame.py", ROOT / "protocol/validate.py"):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names.append(node.module)
                self.assertFalse(any(name == "bpy" or name.startswith("bpy.") for name in names))


if __name__ == "__main__":
    unittest.main()
