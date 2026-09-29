"""Require the operator-configured protected GitHub release environment.

A workflow `environment: release` alone can auto-create an unprotected
configuration. Query the API before and after deployment approval instead.
"""

import json
import subprocess

ROOT = "repos/Scetrov/blender-pi/environments/release"
REVIEWER_ID = 630786


def fetch(path):
    result = subprocess.run(["gh", "api", "-X", "GET", path], capture_output=True,
                            check=True, timeout=30)
    return json.loads(result.stdout)


def verify(api=fetch):
    environment = api(ROOT)
    policies = api(ROOT + "/deployment-branch-policies")
    rules = environment.get("protection_rules", [])
    reviewers = [rule for rule in rules if rule.get("type") == "required_reviewers"]
    branch = environment.get("deployment_branch_policy", {})
    entries = policies.get("branch_policies", [])
    if (environment.get("name") != "release" or len(reviewers) != 1
            or reviewers[0].get("prevent_self_review") is not True
            or len(reviewers[0].get("reviewers", [])) != 1
            or reviewers[0]["reviewers"][0].get("type") != "User"
            or reviewers[0]["reviewers"][0].get("reviewer", {}).get("id") != REVIEWER_ID
            or branch.get("protected_branches") is not False
            or branch.get("custom_branch_policies") is not True
            or len(entries) != 1 or entries[0].get("name") != "v*"
            or entries[0].get("type") != "tag"):
        raise ValueError("Protected release environment does not match approved settings")
    return "Protected release environment verified"


if __name__ == "__main__":
    try:
        print(verify())
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise SystemExit("Protected release environment verification failed") from None
