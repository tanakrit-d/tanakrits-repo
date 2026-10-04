"""Select and check mirrored releases using the updater's configuration rules."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from update import (
    compile_pattern,
    display_version,
    load_json,
    validate_config,
    version_from_tag,
)


def select_release(release: dict[str, Any], app: dict[str, Any]) -> dict[str, str]:
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Upstream release must be stable and published")
    tag = release["tag_name"]
    # Version patterns may capture a suffix of a compound upstream tag.
    # Match the previous jq capture behavior and let the config supply anchors.
    match = compile_pattern(app["version_regex"]).search(tag)
    if not match:
        raise ValueError(f"Unsupported upstream tag: {tag}")
    version = match.group("version")
    mirror_tag = app["mirror_tag_prefix"] + version
    version_from_tag(mirror_tag, app["mirror_tag_prefix"])
    pattern = compile_pattern(app["upstream_asset_regex"])
    candidates = [
        asset for asset in release.get("assets", []) if pattern.fullmatch(asset["name"])
    ]
    preferred = app.get("preferred_upstream_asset_regex")
    if preferred:
        preferred_assets = [
            asset
            for asset in candidates
            if compile_pattern(preferred).fullmatch(asset["name"])
        ]
        candidates = preferred_assets or candidates
    if len(candidates) != 1:
        raise ValueError(
            f"Expected exactly one supported IPA for {tag}; found {len(candidates)}"
        )
    asset = candidates[0]
    output = app["output_name"].format(version=version, asset_name=asset["name"])
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.ipa", output):
        raise ValueError(f"Unsafe IPA filename: {output}")
    if not re.fullmatch(app["mirror_asset_regex"], output):
        raise ValueError(
            f"Mirrored filename does not match mirror_asset_regex: {output}"
        )
    # Check the updater can also derive the displayed version before publishing.
    display_version(
        {"tag_name": mirror_tag, "body": f"Upstream asset: `{asset['name']}`"},
        {"name": output},
        app,
    )
    return {
        "tag": tag,
        "version": version,
        "asset_url": asset["browser_download_url"],
        "asset_name": asset["name"],
        "mirror_tag": mirror_tag,
        "output_name": output,
        "notes": release.get("body") or "",
    }


def check_release(repository: str, tag: str, output_name: str) -> dict[str, str]:
    response = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases/tags/{quote(tag, safe='')}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if response.returncode:
        if "(HTTP 404)" in response.stderr:
            return {"release_exists": "false", "should_mirror": "true"}
        raise RuntimeError(
            f"Could not check mirrored release: {response.stderr.strip()}"
        )
    release = json.loads(response.stdout)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError(f"Existing mirror {tag} is not a published stable release")
    complete = any(
        asset["name"] == output_name
        and asset.get("size", 0) > 0
        and asset.get("state") == "uploaded"
        for asset in release.get("assets", [])
    )
    return {"release_exists": "true", "should_mirror": "false" if complete else "true"}


def write_outputs(values: dict[str, str]) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            delimiter = f"OUTPUT_{uuid.uuid4().hex}"
            output.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("select", "check"))
    args = parser.parse_args()
    if args.command == "select":
        config = load_json(Path("config.json"))
        validate_config(config)
        values = select_release(
            json.load(sys.stdin), config["apps"][os.environ["APP_KEY"]]
        )
    else:
        values = check_release(
            os.environ["GITHUB_REPOSITORY"],
            os.environ["MIRROR_TAG"],
            os.environ["OUTPUT_NAME"],
        )
    write_outputs(values)


if __name__ == "__main__":
    main()
