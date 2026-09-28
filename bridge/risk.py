# SPDX-License-Identifier: GPL-3.0-only
"""Pre-execution declaration checks; not a Python sandbox or effect mediation."""

import ast

from .wire.validate import ValidationError, validate

TARGETED_EFFECTS = frozenset({"file_overwrite", "process_launch", "network_disclosure",
                              "installation_change", "other_external"})


def validate_declarations(request):
    """Reject missing/vague metadata before approval or any Blender work."""
    validate(request, "execution")
    for text in (request["summary"], *(effect["description"] for effect in request["expectedEffects"])):
        if not text.strip() or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValidationError("INVALID_PARAMS")
    for effect in request["expectedEffects"]:
        target = effect.get("target")
        if effect["category"] in TARGETED_EFFECTS:
            if not isinstance(target, str) or not target.strip() or any(ord(char) < 32 or ord(char) == 127 for char in target):
                raise ValidationError("INVALID_PARAMS")
        elif effect["category"] == "unknown" and target is not None:
            # Unknown effects have no established target; do not invent approval scope.
            raise ValidationError("INVALID_PARAMS")
    return request


def _qualified_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value)
        return f"{owner}.{node.attr}" if owner else None
    return None


def _literal_target(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        if value.strip() and len(value) <= 4096 and not any(ord(char) < 32 for char in value):
            return value
    return None


def calculate_effective_risk(request):
    """Advisory escalation, never proof of safety or a Python sandbox.

    Known literal hazards are flagged; dynamic/aliased/indirect effects may be
    missed. Full trust normally runs without blanket unknown-effect prompts.
    """
    validate_declarations(request)
    declared = request["declaredRisk"]
    hazards = [{"category": effect["category"], "target": effect.get("target"), "source": "declared"}
               for effect in request["expectedEffects"] if effect["category"] in TARGETED_EFFECTS]
    broad_scene_change = False
    try:
        tree = ast.parse(request["code"])
    except SyntaxError:
        # Compilation rejects the code later. A parse error grants no permission.
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _qualified_name(node.func)
            if name in {"subprocess.run", "subprocess.Popen", "subprocess.call", "os.system",
                        "shutil.rmtree", "os.remove", "os.unlink", "requests.post",
                        "urllib.request.urlopen"}:
                category = ("network_disclosure" if name in {"requests.post", "urllib.request.urlopen"}
                            else "other_external" if name in {"shutil.rmtree", "os.remove", "os.unlink"}
                            else "process_launch")
                target = _literal_target(node.args[0]) if node.args else None
                hazards.append({"category": category, "target": target, "source": "detected"})
            elif name in {"bpy.ops.wm.read_factory_settings", "bpy.ops.wm.open_mainfile"}:
                broad_scene_change = True
    # Do not treat an unknown declaration as permission to erase a high-risk
    # declaration or a known external hazard. Dimensions remain explicit.
    checkpoint = declared == "high" or broad_scene_change
    approval = bool(hazards)
    effective = ("external_effect" if approval else "high" if checkpoint else declared)
    return {"declaredRisk": declared, "effectiveRisk": effective,
            "checkpointRequired": checkpoint, "approvalRequired": approval,
            "hazards": hazards[:32], "hazardsTruncated": len(hazards) > 32,
            "uncertain": declared == "unknown" or any(effect["category"] == "unknown"
                                                        for effect in request["expectedEffects"])}
