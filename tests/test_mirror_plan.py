import json
import subprocess
import unittest
from unittest.mock import patch

import mirror


class MirrorPlanTests(unittest.TestCase):
    def setUp(self):
        self.app = {
            "app_name": "Example",
            "repo_url": "example/upstream",
            "runner": "macos-latest",
            "version_regex": r"v(?P<version>\d+\.\d+)",
            "mirror_tag_prefix": "example-v",
            "upstream_asset_regex": r"Example\.ipa",
            "output_name": "example-{version}.ipa",
            "mirror_asset_regex": r"example-.*\.ipa",
        }
        self.release = {
            "tag_name": "v1.0",
            "assets": [
                {
                    "name": "Example.ipa",
                    "browser_download_url": "https://example.com/a.ipa",
                }
            ],
        }

    def response(self, value, returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, json.dumps(value), stderr)

    def plan(self):
        return mirror.plan_mirrors({"apps": {"example": self.app}}, "example/mirror")

    @patch("mirror.subprocess.run")
    def test_complete_mirror_allocates_no_runner(self, run):
        run.side_effect = [
            self.response(self.release),
            self.response(
                {
                    "assets": [
                        {"name": "example-1.0.ipa", "size": 123, "state": "uploaded"}
                    ]
                }
            ),
        ]
        self.assertEqual(self.plan(), [])

    @patch("mirror.subprocess.run")
    def test_missing_and_incomplete_mirrors_allocate_configured_runner(self, run):
        for response in (
            self.response({}, 1, "Not Found (HTTP 404)"),
            self.response({"assets": []}),
            self.response(
                {
                    "assets": [
                        {"name": "example-1.0.ipa", "size": 0, "state": "uploaded"}
                    ]
                }
            ),
        ):
            with self.subTest(response=response):
                run.side_effect = [self.response(self.release), response]
                self.assertEqual(self.plan(), [{**self.app, "key": "example"}])

    @patch("mirror.subprocess.run")
    def test_archived_app_is_not_checked(self, run):
        self.app["updates_enabled"] = False
        self.assertEqual(self.plan(), [])
        run.assert_not_called()

    @patch("mirror.subprocess.run")
    def test_allowed_missing_stream_allocates_no_runner(self, run):
        self.app.update(upstream_tag_regex=r"v.*", allow_missing_release=True)
        run.return_value = self.response([[]])
        self.assertEqual(self.plan(), [])
        self.assertEqual(run.call_count, 1)

    @patch("mirror.subprocess.run")
    def test_stream_selection_reads_all_pages(self, run):
        self.app["upstream_tag_regex"] = r"v.*"
        run.side_effect = [
            self.response([[], [self.release]]),
            self.response({}, 1, "Not Found (HTTP 404)"),
        ]
        self.assertEqual(self.plan(), [{**self.app, "key": "example"}])
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                "repos/example/upstream/releases?per_page=100",
            ],
        )

    @patch("mirror.subprocess.run")
    def test_api_failure_is_not_treated_as_missing_mirror(self, run):
        run.side_effect = [
            self.response(self.release),
            self.response({}, 1, "Server error (HTTP 503)"),
        ]
        with self.assertRaisesRegex(RuntimeError, "Could not check mirrored release"):
            self.plan()

    @patch("mirror.subprocess.run")
    def test_upstream_failure_stops_planning(self, run):
        run.return_value = self.response({}, 1, "gh: Server error (HTTP 503)")
        with self.assertRaisesRegex(
            RuntimeError, r"repos/example/upstream/releases/latest: .*HTTP 503"
        ):
            self.plan()
        run.assert_called_once()
