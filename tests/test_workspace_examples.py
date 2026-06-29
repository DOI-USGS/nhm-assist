from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from assist.workspace import examples


class ResolveExampleSourceTests(unittest.TestCase):
    def test_env_override_takes_precedence_over_repo_domain_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            override_root = Path(tmpdir) / "shared_examples"
            (repo_root / "domain_data" / "Walla_Walla").mkdir(parents=True)
            (override_root / "Walla_Walla").mkdir(parents=True)
            env = {
                "PIXI_PROJECT_ROOT": str(repo_root),
                examples.EXAMPLE_ENV_VAR: str(override_root),
            }

            result = examples.resolve_example_source("Walla_Walla", env=env)

            self.assertEqual(result, (override_root / "Walla_Walla").resolve())

    def test_falls_back_to_repo_domain_data_when_no_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "domain_data" / "Walla_Walla"
            target.mkdir(parents=True)
            env = {"PIXI_PROJECT_ROOT": str(repo_root)}

            result = examples.resolve_example_source("Walla_Walla", env=env)

            self.assertEqual(result, target.resolve())

    def test_missing_example_raises_with_search_paths_and_pull_domain_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True)
            env = {"PIXI_PROJECT_ROOT": str(repo_root)}

            with self.assertRaises(FileNotFoundError) as exc:
                examples.resolve_example_source("Bogus_Example", env=env)

            message = str(exc.exception)
            self.assertIn("Bogus_Example", message)
            self.assertIn(str(repo_root / "domain_data"), message)
            self.assertIn("pull_domain.py", message)
            self.assertIn(examples.EXAMPLE_ENV_VAR, message)


class ListAvailableExampleNamesTests(unittest.TestCase):
    def test_aggregates_from_override_and_repo_domain_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            override_root = Path(tmpdir) / "shared_examples"
            (repo_root / "domain_data" / "Walla_Walla").mkdir(parents=True)
            (repo_root / "domain_data" / "Rogue_River").mkdir(parents=True)
            (override_root / "Custom_Domain").mkdir(parents=True)
            env = {
                "PIXI_PROJECT_ROOT": str(repo_root),
                examples.EXAMPLE_ENV_VAR: str(override_root),
            }

            names = examples.list_available_example_names(env=env)

            self.assertEqual(names, ["Custom_Domain", "Rogue_River", "Walla_Walla"])

    def test_skips_non_directory_children(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            (repo_root / "domain_data").mkdir(parents=True)
            (repo_root / "domain_data" / "Walla_Walla").mkdir()
            (repo_root / "domain_data" / "README.md").write_text(
                "docs\n", encoding="utf-8"
            )
            env = {"PIXI_PROJECT_ROOT": str(repo_root)}

            names = examples.list_available_example_names(env=env)

            self.assertEqual(names, ["Walla_Walla"])


if __name__ == "__main__":
    unittest.main()
