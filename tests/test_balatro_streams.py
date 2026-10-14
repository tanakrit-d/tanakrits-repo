import json
import re
import unittest
from pathlib import Path

import update
import mirror


ROOT = Path(__file__).resolve().parents[1]


class BalatroStreamsTests(unittest.TestCase):
    def setUp(self):
        self.config = update.load_json(ROOT / "config.json")

    def release(self, stream, version, date, **flags):
        app = self.config["apps"][f"balatro-{stream}"]
        return {
            "tag_name": app["mirror_tag_prefix"] + version,
            "published_at": date,
            "draft": False,
            "prerelease": False,
            "html_url": "https://example.com/release",
            "assets": [
                {
                    "name": f"b-{stream}.{version}.ipa",
                    "browser_download_url": f"https://example.com/{stream}/{version}.ipa",
                    "size": 123,
                }
            ],
            **flags,
        }

    def test_streams_have_independent_versions_downloads_and_news(self):
        releases = [
            self.release("pokermon", "3.9.1", "2026-10-13T22:24:28Z"),
            self.release("multiplayer", "0.5.5", "2026-10-13T22:24:19Z"),
            self.release(
                "multiplayer", "0.5.6", "2026-10-14T00:00:00Z", prerelease=True
            ),
            self.release("pokermon", "3.9.2", "2026-10-14T00:00:00Z", draft=True),
        ]
        for stream, version in (("multiplayer", "0.5.5"), ("pokermon", "3.9.1")):
            app = self.config["apps"][f"balatro-{stream}"]
            selected = update.app_releases(releases, app)
            self.assertEqual(len(selected), 1)
            generated = update.update_app(None, app, selected, 2)
            self.assertEqual(generated["bundleIdentifier"], f"mod.balatro.{stream}")
            self.assertEqual(generated["version"], version)
            self.assertEqual(generated["versions"][0]["minOSVersion"], "15.0")
            self.assertIn(f"/{stream}/", generated["downloadURL"])
            self.assertEqual(
                update.news_entry(*selected[0], app)["appID"], app["app_id"]
            )

    def test_upstream_matching_and_letter_suffix(self):
        for stream in ("multiplayer", "pokermon"):
            app = self.config["apps"][f"balatro-{stream}"]
            # Python uses a different named-group syntax from jq's capture().
            regex = app["version_regex"].replace("(?<version>", "(?P<version>")
            for version in ("0.5.5", "0.5.5a"):
                tag = f"{stream}-{version}"
                self.assertIsNotNone(re.fullmatch(app["upstream_tag_regex"], tag))
                self.assertEqual(re.fullmatch(regex, tag).group("version"), version)
                release = self.release(stream, version, "2026-10-13T22:24:19Z")
                self.assertEqual(
                    update.version_entry(release, release["assets"][0], app)["version"],
                    version,
                )
                self.assertIsNotNone(
                    update.matching_asset(release, app["upstream_asset_regex"])
                )
            other = "pokermon" if stream == "multiplayer" else "multiplayer"
            self.assertIsNone(re.fullmatch(app["upstream_tag_regex"], f"{other}-3.9.1"))
            self.assertIsNone(
                update.matching_asset(
                    self.release(other, "3.9.1", ""), app["upstream_asset_regex"]
                )
            )

    def test_initial_source_contains_both_streams(self):
        source = json.loads((ROOT / "app.json").read_text())
        apps = {app["bundleIdentifier"]: app for app in source["apps"]}
        for stream in ("multiplayer", "pokermon"):
            app = apps[f"mod.balatro.{stream}"]
            self.assertTrue(app["versions"])
            self.assertIn(f"b-{stream}.", app["downloadURL"])
            self.assertEqual(app["downloadURL"], app["versions"][0]["downloadURL"])

    def test_latest_upstream_release_is_selected_per_stream(self):
        releases = []
        for stream in ("multiplayer", "pokermon"):
            for version, date, flags in (
                ("0.5.4", "2026-10-12T00:00:00Z", {}),
                ("0.5.5a", "2026-10-13T00:00:00Z", {}),
                ("0.5.6", "2026-10-14T00:00:00Z", {"prerelease": True}),
                ("0.5.7", "2026-10-15T00:00:00Z", {"draft": True}),
            ):
                release = self.release(stream, version, date, **flags)
                release["tag_name"] = f"{stream}-{version}"
                releases.append(release)
        for stream in ("multiplayer", "pokermon"):
            app = self.config["apps"][f"balatro-{stream}"]
            selected = mirror.select_latest_release(list(reversed(releases)), app)
            self.assertEqual(selected["tag"], f"{stream}-0.5.5a")
            self.assertEqual(selected["mirror_tag"], f"balatro-{stream}-v0.5.5a")
            self.assertEqual(selected["output_name"], f"b-{stream}.0.5.5a.ipa")
            with self.assertRaisesRegex(ValueError, "No stable upstream release"):
                mirror.select_latest_release([], app)


if __name__ == "__main__":
    unittest.main()
