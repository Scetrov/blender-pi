"""Cross-runtime-safe canonical result encoding and bounded failures."""
import math
from pathlib import Path
import sys
import types
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
namespace = types.ModuleType("blender_pi_result_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_result_test.result_serialization import SerializationError, normalize_result  # noqa: E402


class SerializationTests(unittest.TestCase):
    def test_canonical_values_and_independent_snapshot(self):
        original = {"z": [None, True, 1, 0.25], "a": {"s": "héllo"}}
        first = normalize_result(original)
        self.assertEqual(list(first), ["a", "z"])
        original["z"].append(3)
        self.assertEqual(first["z"], [None, True, 1, 0.25])
        self.assertEqual(normalize_result((1, 2)), [1, 2])
        shared = [1]
        self.assertEqual(normalize_result([shared, shared]), [[1], [1]])

    def test_unsupported_cycles_depth_nonfinite_and_size_are_stable(self):
        cycle = []
        cycle.append(cycle)
        for value in (cycle, {"a": cycle}, [1] * 2049, {1: "not a string key"},
                      [math.nan], math.inf, 2**80, [object()], "x" * 65537,
                      ["x" * 40] * 2048):
            with self.subTest(kind=type(value).__name__), self.assertRaises(SerializationError) as raised:
                normalize_result(value)
            self.assertEqual(raised.exception.code, "SERIALIZATION_FAILED")
        nested = []
        for _ in range(26):
            nested = [nested]
        with self.assertRaises(SerializationError):
            normalize_result(nested)

    def test_unsupported_object_is_not_rendered(self):
        class Private:
            def __repr__(self):
                raise AssertionError("Never call repr on an unsupported object")
        with self.assertRaisesRegex(SerializationError, "Unsupported result type: Private"):
            normalize_result(Private())


if __name__ == "__main__":
    unittest.main()
