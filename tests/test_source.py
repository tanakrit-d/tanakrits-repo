import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mirror
import update

ROOT = Path(__file__).resolve().parents[1]


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.config = update.load_json(ROOT / "config.json")
        self.source = update.load_json(ROOT / "app.json")

    def release(self, names, tag="v1.1.1"):
        return {
            "tag_name": tag,
            "published_at": "2026-09-01T00:00:00Z",
            "html_url": "https://github.com/example/app/releases/tag/v1.1.1",
            "assets": [
                {
                    "name": name,
                    "browser_download_url": f"https://example.org/{name}",
                    "size": 100,
                    "state": "uploaded",
                }
                for name in names
            ],
        }

    def mirrored_releases(self):
        releases = []
        for app in self.config["apps"].values():
            existing = next(
                item
                for item in self.source["apps"]
                if item["bundleIdentifier"] == app["app_id"]
            )
            for version in existing["versions"]:
                release = self.release(
                    [version["downloadURL"].rsplit("/", 1)[1]],
                    app["mirror_tag_prefix"] + version["buildVersion"],
                )
                release["published_at"] = version["date"]
                release["assets"][0]["size"] = version["size"]
                release["assets"][0]["browser_download_url"] = version["downloadURL"]
                releases.append(release)
        return releases

    def test_committed_config_and_source(self):
        update.validate_config(self.config)
        update.validate_source(self.source)

    def test_invalid_config(self):
        for field, value in [
            ("transformation", "typo"),
            ("upstream_asset_regex", "["),
            ("version_regex", "[0-9]+"),
            ("runner", ""),
            ("output_name", "../app.ipa"),
            ("output_name", "{unknown}.ipa"),
            ("app_name", None),
            ("preferred_upstream_asset_regex", "["),
        ]:
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config["apps"]["youtube"][field] = value
                with self.assertRaises((ValueError, update.re.error)):
                    update.validate_config(config)
        self.config["retention"]["versions_per_app"] = True
        with self.assertRaises(ValueError):
            update.validate_config(self.config)

    def test_apollo_extracts_tweak_version_from_compound_tag(self):
        app = self.config["apps"]["apollo-reborn"]
        for tag in ("v1.15.11_3.8.5", "v3.8.5", "3.8.5"):
            with self.subTest(tag=tag):
                release = self.release(["Apollo-Reborn-3.8.5-GLASS.ipa"], tag)
                selected = mirror.select_release(release, app)
                self.assertEqual(selected["version"], "3.8.5")
                self.assertEqual(selected["mirror_tag"], "apollo-reborn-glass-v3.8.5")
                self.assertEqual(
                    selected["output_name"], "Apollo_with_Apollo-Reborn-3.8.5-GLASS.ipa"
                )
        for tag in ("v1.15.11_3.8.5-beta", "v1.15.11_invalid"):
            with (
                self.subTest(tag=tag),
                self.assertRaisesRegex(ValueError, "Unsupported upstream tag"),
            ):
                mirror.select_release(
                    self.release(["Apollo-Reborn-3.8.5-GLASS.ipa"], tag), app
                )

    def test_youtube_prefers_modern_variant_regardless_of_order(self):
        names = [
            "YTKACE_1.1.1_YouTube_iOS16_21.33.6.ipa",
            "YTKACE_1.1.1_YouTube_21.34.2.ipa",
        ]
        app = self.config["apps"]["youtube"]
        for order in [names, list(reversed(names))]:
            selected = mirror.select_release(self.release(order), app)
            self.assertEqual(selected["asset_name"], names[1])
            self.assertIsNotNone(
                update.matching_asset(
                    {"assets": [{"name": selected["output_name"]}]},
                    app["mirror_asset_regex"],
                )
            )
        selected = mirror.select_release(self.release(names[:1]), app)
        self.assertEqual(selected["asset_name"], names[0])

    def test_unsupported_or_ambiguous_assets_fail_before_publication(self):
        app = self.config["apps"]["youtube"]
        for names in [
            ["YTKACE-1.1.1.ipa"],
            [],
            ["YTKACE_1.1.1_YouTube_21.34.2.ipa", "YTKACE_1.1.1_YouTube_21.35.1.ipa"],
        ]:
            with self.subTest(names=names), self.assertRaises(ValueError):
                mirror.select_release(self.release(names), app)
        app["mirror_asset_regex"] = r"^Different\.ipa$"
        with self.assertRaisesRegex(ValueError, "mirror_asset_regex"):
            mirror.select_release(
                self.release(["YTKACE_1.1.1_YouTube_21.34.2.ipa"]), app
            )

    def test_twitch_separates_app_and_build_versions(self):
        app = self.config["apps"]["twitch-adblock"]
        release = self.release(
            ["tv.twitch-30.7-TwitchAdBlock-0.1.13.ipa"], "v30.7-0.1.13"
        )
        selected = mirror.select_release(release, app)
        release["tag_name"] = selected["mirror_tag"]
        version = update.version_entry(release, release["assets"][0], app)
        self.assertEqual(version["version"], "30.7")
        self.assertEqual(version["buildVersion"], "30.7-0.1.13")

    def test_source_validation_rejects_malformed_feed(self):
        mutations = [
            lambda data: data.update(apps=[]),
            lambda data: data["apps"][0].update(versions=[]),
            lambda data: data["apps"][0]["versions"][0].update(size=0),
            lambda data: data["apps"][0]["versions"][0].update(date="invalid"),
            lambda data: data["apps"][0]["versions"][0].update(
                downloadURL="file:///bad"
            ),
            lambda data: data["apps"][0].update(version="wrong"),
            lambda data: data["news"][0].update(appID="unknown"),
            lambda data: data["apps"].append(data["apps"][0]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = copy.deepcopy(self.source)
                mutate(data)
                with self.assertRaises(ValueError):
                    update.validate_source(data)

    def test_failed_updates_preserve_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.json"
            original = (ROOT / "app.json").read_bytes()
            path.write_bytes(original)
            self.config["source"]["json_file"] = str(path)
            with self.assertRaisesRegex(ValueError, "no matching"):
                update.update_source(self.config, [])
            self.assertEqual(path.read_bytes(), original)
            releases = self.mirrored_releases()
            releases[0]["assets"][0]["size"] = 0
            with self.assertRaisesRegex(ValueError, "size"):
                update.update_source(self.config, releases)
            self.assertEqual(path.read_bytes(), original)
            releases = self.mirrored_releases()
            with patch.object(Path, "replace", side_effect=OSError("failed replace")):
                with self.assertRaises(OSError):
                    update.update_source(self.config, releases)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_successful_update_is_valid_and_respects_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.json"
            self.config["source"]["json_file"] = str(path)
            releases = self.mirrored_releases()
            releases.append(dict(releases[0], draft=True))
            releases.append(dict(releases[0], prerelease=True))
            update.update_source(self.config, releases)
            source = update.load_json(path)
            update.validate_source(source)
            self.assertEqual(len(source["apps"]), 4)
            self.assertEqual(len(source["news"]), 8)
            self.assertTrue(all(len(app["versions"]) == 2 for app in source["apps"]))

    def test_selection_cli_writes_github_outputs(self):
        release = self.release(["YTKACE_1.1.1_YouTube_21.34.2.ipa"])
        release["body"] = "First line\nSecond line with `literal` and $(literal)"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            result = subprocess.run(
                [sys.executable, str(ROOT / "mirror.py"), "select"],
                cwd=ROOT,
                input=json.dumps(release),
                text=True,
                capture_output=True,
                env=dict(os.environ, APP_KEY="youtube", GITHUB_OUTPUT=str(output)),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = iter(output.read_text().splitlines())
            values = {}
            for line in lines:
                key, delimiter = line.split("<<", 1)
                content = []
                for value in lines:
                    if value == delimiter:
                        break
                    content.append(value)
                values[key] = "\n".join(content)
            self.assertEqual(values["mirror_tag"], "ytkace-v1.1.1")
            self.assertEqual(values["notes"], release["body"])

    def test_validation_cli_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            self.config["source"]["json_file"] = str(Path(directory) / "missing.json")
            config_path.write_text(json.dumps(self.config))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "update.py"),
                    "--config",
                    str(config_path),
                    "--validate-only",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source file does not exist", result.stderr)

    def test_mirror_release_check_and_repair_decisions(self):
        name = "App.ipa"
        cases = [
            (
                0,
                {"assets": [{"name": name, "size": 100, "state": "uploaded"}]},
                "",
                "false",
                "true",
            ),
            (0, {"assets": []}, "", "true", "true"),
            (
                0,
                {"assets": [{"name": name, "size": 0, "state": "uploaded"}]},
                "",
                "true",
                "true",
            ),
            (
                0,
                {"assets": [{"name": name, "size": 100, "state": "new"}]},
                "",
                "true",
                "true",
            ),
            (1, {}, "gh: Not Found (HTTP 404)", "true", "false"),
        ]
        for code, data, error, should_mirror, exists in cases:
            with self.subTest(data=data, error=error):
                result = subprocess.CompletedProcess([], code, json.dumps(data), error)
                with patch("mirror.subprocess.run", return_value=result):
                    self.assertEqual(
                        mirror.check_release("owner/repo", "v1.0", name),
                        {"release_exists": exists, "should_mirror": should_mirror},
                    )
        for error in ["gh: Unauthorized (HTTP 401)", "network failure"]:
            result = subprocess.CompletedProcess([], 1, "", error)
            with (
                patch("mirror.subprocess.run", return_value=result),
                self.assertRaises(RuntimeError),
            ):
                mirror.check_release("owner/repo", "v1.0", name)


if __name__ == "__main__":
    unittest.main()
