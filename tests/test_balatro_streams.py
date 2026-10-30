import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import cleanup
import mirror
import update

ROOT = Path(__file__).resolve().parents[1]


class BalatroStreamsTests(unittest.TestCase):
    def setUp(self):
        self.config = update.load_json(ROOT / "config.json")
        self.source = update.load_json(ROOT / "app.json")
        self.legacy = self.config["apps"]["balatro-multiplayer-legacy"]
        self.pvp = self.config["apps"]["balatro-multiplayer"]

    def release(self, tag, version="1.0.1", **flags):
        return {
            "tag_name": tag,
            "published_at": "2026-10-30T00:00:00Z",
            "draft": False,
            "prerelease": False,
            "html_url": "https://example.com/release/" + tag,
            "assets": [
                {
                    "name": f"b-multiplayer.{version}.ipa",
                    "browser_download_url": "https://example.com/" + tag + ".ipa",
                    "size": 123,
                }
            ],
            **flags,
        }

    def test_existing_download_and_bundle_id_stay_with_legacy(self):
        existing = next(
            a
            for a in self.source["apps"]
            if a["bundleIdentifier"] == self.legacy["app_id"]
        )
        self.assertFalse(self.legacy["updates_enabled"])
        self.assertEqual(self.legacy["app_id"], "mod.balatro.multiplayer")
        self.assertIn("(Legacy)", existing["name"])
        self.assertEqual(existing["version"], "0.5.5")
        self.assertIn("/balatro-multiplayer-v0.5.5/", existing["downloadURL"])
        self.assertNotEqual(self.legacy["app_id"], self.pvp["app_id"])
        self.assertNotEqual(
            self.legacy["mirror_tag_prefix"], self.pvp["mirror_tag_prefix"]
        )
        with self.assertRaisesRegex(ValueError, "disconnected"):
            mirror.select_release(
                self.release("multiplayer-0.5.5", "0.5.5"), self.legacy
            )

    def test_pvp_accepts_experimental_1x_and_rejects_legacy_and_drafts(self):
        old = self.release("multiplayer-0.5.5", "0.5.5")
        new = self.release("multiplayer-1.0.1", prerelease=True)
        draft = self.release("multiplayer-2.0.0", "2.0.0", draft=True)
        selected = mirror.select_latest_release([old, new, draft], self.pvp)
        self.assertEqual(selected["mirror_tag"], "balatro-multiplayer-pvp-v1.0.1")
        self.assertEqual(selected["output_name"], "b-multiplayer.1.0.1.ipa")
        self.assertEqual(
            mirror.select_latest_release([old], self.pvp), {"available": "false"}
        )
        with self.assertRaises(ValueError):
            mirror.select_release(old, self.pvp)
        for app in self.config["apps"].values():
            if app is not self.pvp and app.get("updates_enabled", True):
                self.assertFalse(app.get("include_prereleases", False))

    def test_archive_is_frozen_and_new_source_waits_for_real_release(self):
        config = copy.deepcopy(self.config)
        config["apps"] = {
            key: config["apps"][key]
            for key in ("balatro-multiplayer-legacy", "balatro-multiplayer")
        }
        fixture = copy.deepcopy(self.source)
        legacy_before = next(
            a for a in fixture["apps"] if a["bundleIdentifier"] == self.legacy["app_id"]
        )
        # Exercise migration from an older generated source, even after the
        # committed source has been renamed. Only metadata may change.
        legacy_before.update(
            name="Balatro (Multiplayer)",
            subtitle="Balatro with Multiplayer",
            localizedDescription="Original legacy description",
        )
        expected_legacy = dict(
            legacy_before,
            name=self.legacy["app_name"],
            subtitle=self.legacy["subtitle"],
            localizedDescription=self.legacy["localized_description"],
        )
        for release_available in (False, True):
            with (
                self.subTest(release_available=release_available),
                tempfile.TemporaryDirectory() as directory,
            ):
                source_path = Path(directory) / "app.json"
                source_path.write_text(json.dumps(fixture))
                config["source"]["json_file"] = str(source_path)
                mirrored = self.release(
                    "balatro-multiplayer-pvp-v1.0.1", prerelease=True
                )
                releases = [self.release("balatro-multiplayer-v9.0.0", "9.0.0")]
                if release_available:
                    releases.append(mirrored)
                update.update_source(config, releases)
                result = update.load_json(source_path)
                apps = {a["bundleIdentifier"]: a for a in result["apps"]}
                self.assertEqual(apps[self.legacy["app_id"]], expected_legacy)
                self.assertEqual(self.pvp["app_id"] in apps, release_available)
                if release_available:
                    self.assertEqual(apps[self.pvp["app_id"]]["version"], "1.0.1")
                    self.assertEqual(
                        apps[self.pvp["app_id"]]["downloadURL"],
                        mirrored["assets"][0]["browser_download_url"],
                    )
                    self.assertTrue(
                        any(n["appID"] == self.pvp["app_id"] for n in result["news"])
                    )
                self.assertEqual(
                    cleanup.cleanup_plan(
                        config, releases[:1] * 5 + releases[1:], result
                    ),
                    [],
                )

    def test_new_entry_cannot_silently_disappear_after_first_release(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "app.json"
            config = copy.deepcopy(self.config)
            config["apps"] = {"balatro-multiplayer": self.pvp}
            config["source"]["json_file"] = str(source_path)
            release = self.release("balatro-multiplayer-pvp-v1.0.1")
            update.update_source(config, [release])
            before = source_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "no matching"):
                update.update_source(config, [])
            self.assertEqual(source_path.read_bytes(), before)

    def test_legacy_is_excluded_from_workflow_matrix(self):
        expression = "[.apps | to_entries[] | select(.value.updates_enabled != false) | .value + {key: .key}]"
        workflow = (ROOT / ".github/workflows/create_release.yml").read_text()
        self.assertIn(expression, workflow)
        result = subprocess.check_output(
            ["jq", "-c", expression, str(ROOT / "config.json")], text=True
        )
        keys = {app["key"] for app in json.loads(result)}
        self.assertNotIn("balatro-multiplayer-legacy", keys)
        self.assertIn("balatro-multiplayer", keys)

    def test_new_flags_require_booleans(self):
        for field in (
            "updates_enabled",
            "allow_missing_release",
            "include_prereleases",
        ):
            config = copy.deepcopy(self.config)
            config["apps"]["balatro-multiplayer"][field] = "false"
            with self.assertRaisesRegex(ValueError, "boolean"):
                update.validate_config(config)

    def test_pokermon_retains_stable_selection_and_letter_suffix(self):
        app = self.config["apps"]["balatro-pokermon"]
        releases = []
        for version, flags in (("3.9.1a", {}), ("3.9.2", {"prerelease": True})):
            release = self.release("pokermon-" + version, version, **flags)
            release["assets"][0]["name"] = "b-pokermon." + version + ".ipa"
            releases.append(release)
        selected = mirror.select_latest_release(releases, app)
        self.assertEqual(selected["mirror_tag"], "balatro-pokermon-v3.9.1a")
        self.assertEqual(selected["output_name"], "b-pokermon.3.9.1a.ipa")
        mirrored = dict(releases[0], tag_name=selected["mirror_tag"])
        matched = update.app_releases([mirrored], app)
        generated = update.update_app(None, app, matched, 2)
        self.assertEqual(generated["bundleIdentifier"], "mod.balatro.pokermon")
        self.assertEqual(generated["version"], "3.9.1a")
        self.assertEqual(generated["versions"][0]["minOSVersion"], "15.0")
        self.assertEqual(update.news_entry(*matched[0], app)["appID"], app["app_id"])


if __name__ == "__main__":
    unittest.main()
