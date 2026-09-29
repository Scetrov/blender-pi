"""The release setting gate fails closed when approval protections change."""

import unittest

from scripts.verify_release_environment import ROOT, verify


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "name": "release",
            "protection_rules": [{"type": "required_reviewers", "prevent_self_review": True,
                                  "reviewers": [{"type": "User", "reviewer": {"id": 630786}}]}],
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
        self.policies = {"branch_policies": [{"name": "v*", "type": "tag"}]}

    def check(self):
        return verify(lambda path: self.environment if path == ROOT else self.policies)

    def test_approved_settings(self):
        self.assertIn("verified", self.check())

    def test_missing_reviewer(self):
        self.environment["protection_rules"] = []
        with self.assertRaises(ValueError):
            self.check()

    def test_self_review_allowed(self):
        self.environment["protection_rules"][0]["prevent_self_review"] = False
        with self.assertRaises(ValueError):
            self.check()

    def test_extra_branch_policy(self):
        self.policies["branch_policies"].append({"name": "main", "type": "branch"})
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_reviewer(self):
        self.environment["protection_rules"][0]["reviewers"][0]["reviewer"]["id"] = 5
        with self.assertRaises(ValueError):
            self.check()


if __name__ == "__main__":
    unittest.main()
