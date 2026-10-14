import copy
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cleanup
import update

ROOT = Path(__file__).resolve().parents[1]


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.config = update.load_json(ROOT / "config.json")
        self.source = update.load_json(ROOT / "app.json")
        self.releases = []
        for app in self.config["apps"].values():
            existing = next(
                item
                for item in self.source["apps"]
                if item["bundleIdentifier"] == app["app_id"]
            )
            name = existing["downloadURL"].rsplit("/", 1)[1]
            for number in range(1, 6):
                tag = app["mirror_tag_prefix"] + f"1.0.{number}"
                self.releases.append(
                    {
                        "tag_name": tag,
                        "published_at": f"2026-10-{number:02d}T00:00:00Z",
                        "html_url": f"https://example.org/releases/tag/{tag}",
                        "assets": [
                            {
                                "name": name,
                                "browser_download_url": f"https://example.org/{tag}/{name}",
                                "size": 100,
                            }
                        ],
                    }
                )

    def test_keeps_three_per_app_and_stream_by_publication_date(self):
        planned = cleanup.cleanup_plan(
            self.config, list(reversed(self.releases)), self.source
        )
        expected = {
            app["mirror_tag_prefix"] + f"1.0.{number}"
            for app in self.config["apps"].values()
            for number in (1, 2)
        }
        self.assertEqual(set(planned), expected)
        self.assertEqual(len(planned), 2 * len(self.config["apps"]))

    def test_preserves_unrelated_draft_prerelease_and_unsupported_assets(self):
        excluded = []
        for tag, changes in (
            ("unrelated-v1.0.0", {}),
            ("draft-v1.0.0", {"draft": True}),
            ("prerelease-v1.0.0", {"prerelease": True}),
            ("missing-asset-v1.0.0", {"assets": []}),
        ):
            release = copy.deepcopy(self.releases[0])
            if changes:
                tag = self.config["apps"]["apollo-reborn"]["mirror_tag_prefix"] + tag
            release.update(tag_name=tag, **changes)
            excluded.append(release)
        self.assertEqual(
            cleanup.cleanup_plan(self.config, self.releases + excluded, self.source),
            cleanup.cleanup_plan(self.config, self.releases, self.source),
        )
        self.assertEqual(cleanup.cleanup_plan(self.config, [], self.source), [])

    def test_refuses_to_delete_download_or_news_referenced_by_source(self):
        for reference in ("download", "news"):
            with self.subTest(reference=reference):
                source = copy.deepcopy(self.source)
                if reference == "download":
                    source["apps"][0]["versions"][-1]["downloadURL"] = self.releases[0][
                        "assets"
                    ][0]["browser_download_url"]
                else:
                    source["news"][0]["url"] = self.releases[0]["html_url"]
                with self.assertRaisesRegex(ValueError, "still referenced"):
                    cleanup.cleanup_plan(self.config, self.releases, source)

    def test_retention_must_cover_the_feed(self):
        for value in (0, True, 1):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["retention"]["github_releases_per_app"] = value
                with self.assertRaises(ValueError):
                    cleanup.cleanup_plan(config, self.releases, self.source)

    def test_preview_does_not_delete_and_apply_uses_checked_commands(self):
        with (
            patch("sys.argv", ["cleanup.py", "--repository", "owner/repo"]),
            patch("cleanup.github_releases", return_value=self.releases),
            patch("cleanup.delete_releases") as delete,
            redirect_stdout(io.StringIO()),
        ):
            cleanup.main()
            delete.assert_not_called()
        with patch("cleanup.subprocess.run") as run:
            cleanup.delete_releases("owner/repo", ["app-v1.0.1"])
            run.assert_called_once_with(
                [
                    "gh",
                    "release",
                    "delete",
                    "app-v1.0.1",
                    "--repo",
                    "owner/repo",
                    "--yes",
                ],
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
