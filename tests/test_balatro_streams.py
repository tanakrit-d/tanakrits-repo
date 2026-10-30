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
                    "name": f"b-{'multiplayer-legacy' if 'multiplayer-legacy' in tag else 'multiplayer'}.{version}.ipa",
                    "browser_download_url": "https://example.com/" + tag + ".ipa",
                    "size": 123,
                }
            ],
            **flags,
        }

    def test_legacy_and_pvp_select_only_their_own_stable_releases(self):
        releases = [
            self.release("multiplayer-0.5.5", "0.5.5"),
            self.release("multiplayer-legacy-0.5.5", "0.5.5"),
            self.release("multiplayer-1.0.3", "1.0.3"),
            self.release("multiplayer-2.0.0", "2.0.0", prerelease=True),
            self.release("multiplayer-legacy-0.5.6", "0.5.6", draft=True),
        ]
        for app, tag, asset in [
            (
                self.legacy,
                "balatro-multiplayer-legacy-v0.5.5",
                "b-multiplayer-legacy.0.5.5.ipa",
            ),
            (self.pvp, "balatro-multiplayer-pvp-v1.0.3", "b-multiplayer.1.0.3.ipa"),
        ]:
            selected = mirror.select_latest_release(releases, app)
            self.assertEqual(selected["mirror_tag"], tag)
            self.assertEqual(selected["output_name"], asset)
            self.assertTrue(app.get("updates_enabled", True))
            self.assertFalse(app.get("include_prereleases", False))
        self.assertEqual(self.legacy["app_id"], "mod.balatro.multiplayer")
        self.assertEqual(self.pvp["app_id"], "mod.balatro.multiplayer.pvp")
        self.assertNotEqual(
            self.legacy["mirror_tag_prefix"], self.pvp["mirror_tag_prefix"]
        )
        for app in (self.legacy, self.pvp):
            with self.assertRaises(ValueError):
                mirror.select_release(releases[0], app)

    def test_both_entries_repopulate_independently_from_an_empty_source(self):
        config = copy.deepcopy(self.config)
        config["apps"] = {
            key: config["apps"][key]
            for key in ("balatro-multiplayer-legacy", "balatro-multiplayer")
        }
        ids = {self.legacy["app_id"], self.pvp["app_id"]}
        fixture = copy.deepcopy(self.source)
        fixture["apps"] = [
            a for a in fixture["apps"] if a["bundleIdentifier"] not in ids
        ]
        fixture["news"] = [n for n in fixture["news"] if n["appID"] not in ids]
        legacy = self.release("balatro-multiplayer-legacy-v0.5.5", "0.5.5")
        pvp = self.release("balatro-multiplayer-pvp-v1.0.3", "1.0.3")
        stale = self.release("balatro-multiplayer-v9.0.0", "9.0.0")
        for releases in ([], [legacy], [pvp], [legacy, pvp]):
            with (
                self.subTest(tags=[r["tag_name"] for r in releases]),
                tempfile.TemporaryDirectory() as directory,
            ):
                source_path = Path(directory) / "app.json"
                source_path.write_text(json.dumps(fixture))
                config["source"]["json_file"] = str(source_path)
                update.update_source(config, releases + [stale])
                result = update.load_json(source_path)
                apps = {a["bundleIdentifier"]: a for a in result["apps"]}
                for app, release in ((self.legacy, legacy), (self.pvp, pvp)):
                    self.assertEqual(app["app_id"] in apps, release in releases)
                    news = [n for n in result["news"] if n["appID"] == app["app_id"]]
                    self.assertEqual(len(news), int(release in releases))
                    if release in releases:
                        self.assertEqual(
                            apps[app["app_id"]]["downloadURL"],
                            release["assets"][0]["browser_download_url"],
                        )
                        self.assertEqual(news[0]["url"], release["html_url"])
                self.assertEqual(
                    [a for a in result["apps"] if a["bundleIdentifier"] not in ids],
                    fixture["apps"],
                )
                self.assertEqual(
                    [n for n in result["news"] if n["appID"] not in ids],
                    fixture["news"],
                )

    def test_cleanup_retains_each_multiplayer_stream_separately(self):
        config = copy.deepcopy(self.config)
        config["apps"] = {"legacy": self.legacy, "pvp": self.pvp}
        releases = [
            self.release(app["mirror_tag_prefix"] + "1.0." + str(i), "1.0." + str(i))
            for app in (self.legacy, self.pvp)
            for i in range(1, 6)
        ]
        for release in releases:
            release["published_at"] = (
                "2026-10-0" + release["tag_name"][-1] + "T00:00:00Z"
            )
        fixture = copy.deepcopy(self.source)
        ids = {self.legacy["app_id"], self.pvp["app_id"]}
        fixture["apps"] = [
            a for a in fixture["apps"] if a["bundleIdentifier"] not in ids
        ]
        fixture["news"] = [n for n in fixture["news"] if n["appID"] not in ids]
        expected = {
            app["mirror_tag_prefix"] + "1.0." + str(i)
            for app in (self.legacy, self.pvp)
            for i in (1, 2)
        }
        self.assertEqual(set(cleanup.cleanup_plan(config, releases, fixture)), expected)

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

    def test_both_multiplayer_streams_are_in_workflow_matrix(self):
        expression = "[.apps | to_entries[] | select(.value.updates_enabled != false) | .value + {key: .key}]"
        workflow = (ROOT / ".github/workflows/create_release.yml").read_text()
        self.assertIn(expression, workflow)
        result = subprocess.check_output(
            ["jq", "-c", expression, str(ROOT / "config.json")], text=True
        )
        keys = {app["key"] for app in json.loads(result)}
        self.assertIn("balatro-multiplayer-legacy", keys)
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
