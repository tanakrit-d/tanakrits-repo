from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--repository",
        help="Mirror repository in owner/name form (defaults to GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate local configuration and source JSON without calling GitHub",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_config(config: dict[str, Any]) -> None:
    for key in ("source", "retention", "apps"):
        if key not in config:
            raise ValueError(f"Missing top-level config key: {key}")

    if not isinstance(config["source"], dict):
        raise ValueError("source must be an object")
    for key in ("name", "json_file"):
        if not isinstance(config["source"].get(key), str) or not config["source"][key]:
            raise ValueError(f"source.{key} must be a non-empty string")

    if not isinstance(config["apps"], dict) or not config["apps"]:
        raise ValueError("Config must contain at least one app")

    required = {
        "repo_url",
        "app_id",
        "app_name",
        "developer_name",
        "subtitle",
        "localized_description",
        "caption",
        "tint_colour",
        "image_url",
        "icon_url",
        "mirror_tag_prefix",
        "mirror_asset_regex",
    }
    prefixes: set[str] = set()
    app_ids: set[str] = set()

    for key, app in config["apps"].items():
        missing = required - app.keys()
        if missing:
            raise ValueError(
                f"{key} is missing config keys: {', '.join(sorted(missing))}"
            )
        re.compile(app["mirror_asset_regex"])
        if app["mirror_tag_prefix"] in prefixes:
            raise ValueError(f"Duplicate mirror_tag_prefix: {app['mirror_tag_prefix']}")
        if app["app_id"] in app_ids:
            raise ValueError(f"Duplicate app_id: {app['app_id']}")
        prefixes.add(app["mirror_tag_prefix"])
        app_ids.add(app["app_id"])

    for key in ("versions_per_app", "news_per_app"):
        if (
            not isinstance(config["retention"].get(key), int)
            or config["retention"][key] < 1
        ):
            raise ValueError(f"retention.{key} must be a positive integer")


def github_releases(repository: str) -> list[dict[str, Any]]:
    import requests

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sideload-repo-source-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        response = requests.get(
            f"https://api.github.com/repos/{repository}/releases",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            return releases
        releases.extend(batch)
        page += 1


def clean_description(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return text.replace("**", "").replace("`", '"').strip()


def version_from_tag(tag: str, prefix: str) -> str:
    version = tag.removeprefix(prefix).lstrip("vV")
    if not re.fullmatch(r"\d+(?:\.\d+)+", version):
        raise ValueError(f"Invalid mirrored release tag: {tag}")
    return version


def matching_asset(release: dict[str, Any], pattern: str) -> dict[str, Any] | None:
    regex = re.compile(pattern)
    return next(
        (
            asset
            for asset in release.get("assets", [])
            if regex.fullmatch(asset["name"])
        ),
        None,
    )


def app_releases(
    releases: list[dict[str, Any]], app: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if not release.get("tag_name", "").startswith(app["mirror_tag_prefix"]):
            continue
        asset = matching_asset(release, app["mirror_asset_regex"])
        if asset:
            result.append((release, asset))
    return sorted(
        result, key=lambda item: item[0].get("published_at", ""), reverse=True
    )


def version_entry(
    release: dict[str, Any], asset: dict[str, Any], app: dict[str, Any]
) -> dict[str, Any]:
    version = version_from_tag(release["tag_name"], app["mirror_tag_prefix"])
    return {
        "version": version,
        "buildVersion": version,
        "date": release["published_at"],
        "localizedDescription": clean_description(release.get("body")),
        "downloadURL": asset["browser_download_url"],
        "size": asset.get("size", 0),
    }


def news_entry(release: dict[str, Any], app: dict[str, Any]) -> dict[str, Any]:
    version = version_from_tag(release["tag_name"], app["mirror_tag_prefix"])
    date = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
    return {
        "appID": app["app_id"],
        "title": f"{version} - {date.strftime('%d %b')}",
        "identifier": f"{app['app_id']}-release-{version}",
        "caption": app["caption"],
        "date": release["published_at"],
        "tintColor": app["tint_colour"],
        "imageURL": app["image_url"],
        "notify": True,
        "url": release["html_url"],
    }


def update_app(
    existing: dict[str, Any] | None,
    app: dict[str, Any],
    releases: list[tuple[dict[str, Any], dict[str, Any]]],
    limit: int,
) -> dict[str, Any]:
    result = dict(existing or {})
    result.update(
        {
            "name": app["app_name"],
            "bundleIdentifier": app["app_id"],
            "developerName": app["developer_name"],
            "subtitle": app["subtitle"],
            "localizedDescription": app["localized_description"],
            "iconURL": app["icon_url"],
            "tintColor": app["tint_colour"],
        }
    )
    optional_metadata = {
        "category": "category",
        "screenshots": "screenshots",
        "app_permissions": "appPermissions",
    }
    for config_key, source_key in optional_metadata.items():
        if config_key in app:
            result[source_key] = app[config_key]
        else:
            result.pop(source_key, None)

    versions = [
        version_entry(release, asset, app) for release, asset in releases[:limit]
    ]
    result["versions"] = versions
    if versions:
        latest = versions[0]
        result.update(
            {
                "version": latest["version"],
                "buildVersion": latest["buildVersion"],
                "versionDate": latest["date"],
                "versionDescription": latest["localizedDescription"],
                "downloadURL": latest["downloadURL"],
                "size": latest["size"],
            }
        )
    else:
        for key in (
            "version",
            "buildVersion",
            "versionDate",
            "versionDescription",
            "downloadURL",
            "size",
        ):
            result.pop(key, None)
    return result


def update_source(config: dict[str, Any], releases: list[dict[str, Any]]) -> None:
    source_path = Path(config["source"]["json_file"])
    data = (
        load_json(source_path)
        if source_path.exists() and source_path.stat().st_size
        else {}
    )
    source_metadata = (
        "name",
        "subtitle",
        "description",
        "iconURL",
        "headerURL",
        "website",
        "fediUsername",
    )
    for key in source_metadata:
        if key in config["source"]:
            data[key] = config["source"][key]
        else:
            data.pop(key, None)
    data.pop("identifier", None)

    configured_ids = {app["app_id"] for app in config["apps"].values()}
    existing_apps = {
        app.get("bundleIdentifier"): app
        for app in data.get("apps", [])
        if isinstance(app, dict)
    }
    untouched_apps = [
        app
        for app in data.get("apps", [])
        if app.get("bundleIdentifier") not in configured_ids
    ]
    generated_apps = []
    generated_news = []

    for key, app in config["apps"].items():
        mirrored = app_releases(releases, app)
        print(f"{key}: found {len(mirrored)} mirrored stable release(s)")
        generated_apps.append(
            update_app(
                existing_apps.get(app["app_id"]),
                app,
                mirrored,
                config["retention"]["versions_per_app"],
            )
        )
        generated_news.extend(
            news_entry(release, app)
            for release, _ in mirrored[: config["retention"]["news_per_app"]]
        )

    untouched_news = [
        item for item in data.get("news", []) if item.get("appID") not in configured_ids
    ]
    data["apps"] = untouched_apps + generated_apps
    data["news"] = sorted(
        untouched_news + generated_news,
        key=lambda item: item.get("date", ""),
        reverse=True,
    )

    with source_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main() -> int:
    args = parse_args()
    config = load_json(Path(args.config))
    validate_config(config)

    source_path = Path(config["source"]["json_file"])
    if source_path.exists() and source_path.stat().st_size:
        load_json(source_path)

    if args.validate_only:
        print(f"Validated {args.config} and {source_path}")
        return 0

    repository = args.repository or os.getenv("GITHUB_REPOSITORY")
    if not repository:
        raise ValueError("Set --repository or GITHUB_REPOSITORY")
    update_source(config, github_releases(repository))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
