"""Keep the latest configured mirrored releases per app; preview by default."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from update import (
    app_releases,
    github_releases,
    load_json,
    validate_config,
    validate_source,
)


def cleanup_plan(
    config: dict[str, Any],
    releases: list[dict[str, Any]],
    source: dict[str, Any],
) -> list[str]:
    validate_config(config)
    validate_source(source)
    limit = config["retention"]["github_releases_per_app"]
    referenced_urls = {
        version["downloadURL"] for app in source["apps"] for version in app["versions"]
    }
    referenced_urls.update(item["url"] for item in source.get("news", []))
    tags = []
    for app in config["apps"].values():
        if not app.get("updates_enabled", True):
            continue
        for release, _ in app_releases(releases, app)[limit:]:
            urls = {release["html_url"]}
            urls.update(asset["browser_download_url"] for asset in release["assets"])
            if urls & referenced_urls:
                raise ValueError(
                    f"Release {release['tag_name']} is still referenced by the source; "
                    "update the source before cleanup"
                )
            tags.append(release["tag_name"])
    return list(dict.fromkeys(tags))


def delete_releases(repository: str, tags: list[str]) -> None:
    for tag in tags:
        subprocess.run(
            ["gh", "release", "delete", tag, "--repo", repository, "--yes"],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--apply", action="store_true", help="Delete planned releases")
    args = parser.parse_args()
    config = load_json(Path(args.config))
    validate_config(config)
    source = load_json(Path(config["source"]["json_file"]))
    validate_source(source)
    tags = cleanup_plan(config, github_releases(args.repository), source)
    print(f"{'Deleting' if args.apply else 'Would delete'} {len(tags)} release(s)")
    for tag in tags:
        print(tag)
    if args.apply:
        delete_releases(args.repository, tags)


if __name__ == "__main__":
    main()
