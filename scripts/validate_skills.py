"""Validate bundled Agent Skills and read-only Blender examples."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
EXPECTED = {
    "blender-setup-diagnostics", "blender-scene-workflow", "blender-modeling",
    "blender-materials-nodes", "blender-animation-rigging", "blender-render-review",
    "blender-troubleshooting-recovery",
}
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FENCE = re.compile(r"^```python\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def validate():
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "./skills" in manifest["pi"]["skills"]
    assert "skills/" in manifest["files"]
    found = {path.parent.name for path in SKILLS.glob("*/SKILL.md")}
    assert found == EXPECTED, f"skill discovery differs: {found ^ EXPECTED}"
    examples = []
    for name in sorted(found):
        directory = SKILLS / name
        skill = directory / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        assert match, f"{skill}: missing frontmatter"
        fields = dict(re.findall(r"^([a-z-]+): (.+)$", match.group(1), re.MULTILINE))
        assert fields.get("name") == name and NAME.fullmatch(name), f"{skill}: invalid name"
        assert len(fields.get("description", "")) >= 40, f"{skill}: routing description too short"
        assert len(fields["description"]) <= 1024
        assert "Use for" in fields["description"] or "Use when" in fields["description"]
        assert fields.get("license") == "MIT"
        references = directory / "references" / "examples.md"
        assert references.is_file(), f"{name}: missing examples"
        for document in (skill, references):
            content = document.read_text(encoding="utf-8")
            for destination in LINK.findall(content):
                if destination.startswith("https://"):
                    continue
                assert not destination.startswith(("/", "..")), f"{document}: nonportable link"
                assert (document.parent / destination).is_file(), f"{document}: broken {destination}"
            for index, source in enumerate(FENCE.findall(content)):
                ast.parse(source, filename=f"{document}:{index}")
                examples.append(source)
    return examples


def verify_blender(examples):
    # Used by the CI Blender integration job: run in real Blender, not a mock.
    import bpy
    assert bpy.app.version >= (5, 2, 0), bpy.app.version
    for index, source in enumerate(examples):
        compiled = compile(source, f"skill-example-{index}", "exec")
        exec(compiled, {"__name__": "__skill_example__"})
    print("BLENDER_SKILLS_OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", action="store_true", help="also run read-only examples in Blender")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    snippets = validate()
    if args.blender:
        verify_blender(snippets)
    else:
        print(f"SKILLS_OK: {len(EXPECTED)} skills, {len(snippets)} Python examples")
