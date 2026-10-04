from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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
        raise TypeError(f"{path} must contain a JSON object")
    return value


def compile_pattern(pattern: str) -> re.Pattern[str]:
    # Accept the named-group spelling used by the previous jq-based workflow.
    return re.compile(re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", pattern))


def require_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def require_url(value: Any, label: str) -> None:
    require_string(value, label)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS URL")


def require_date(value: Any, label: str) -> None:
    require_string(value, label)
    try:
        date = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp") from error
    if date.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")


def validate_source(data: dict[str, Any]) -> None:
    require_string(data.get("name"), "source.name")
    if not isinstance(data.get("apps"), list) or not data["apps"]:
        raise ValueError("source.apps must be a non-empty array")
    app_ids = set()
    for app in data["apps"]:
        if not isinstance(app, dict):
            raise ValueError("Each source app must be an object")
        for field in ("name", "bundleIdentifier", "developerName"):
            require_string(app.get(field), f"app.{field}")
        app_id = app["bundleIdentifier"]
        if app_id in app_ids:
            raise ValueError(f"Duplicate source app: {app_id}")
        app_ids.add(app_id)
        require_url(app.get("iconURL"), f"{app_id}.iconURL")
        if not isinstance(app.get("versions"), list) or not app["versions"]:
            raise ValueError(f"{app_id}.versions must be a non-empty array")
        builds = set()
        for version in app["versions"]:
            if not isinstance(version, dict):
                raise ValueError(f"{app_id}: each version must be an object")
            require_string(version.get("version"), f"{app_id}.version")
            require_string(version.get("buildVersion"), f"{app_id}.buildVersion")
            if version["buildVersion"] in builds:
                raise ValueError(f"{app_id}: duplicate buildVersion")
            builds.add(version["buildVersion"])
            require_url(version.get("downloadURL"), f"{app_id}.downloadURL")
            require_date(version.get("date"), f"{app_id}.date")
            if type(version.get("size")) is not int or version["size"] <= 0:
                raise ValueError(f"{app_id}.size must be a positive integer")
        latest = app["versions"][0]
        for field, version_field in (
            ("version", "version"),
            ("buildVersion", "buildVersion"),
            ("downloadURL", "downloadURL"),
            ("size", "size"),
            ("versionDate", "date"),
        ):
            if field in app and app[field] != latest[version_field]:
                raise ValueError(f"{app_id}.{field} disagrees with latest version")
    if not isinstance(data.get("news", []), list):
        raise ValueError("source.news must be an array")
    identifiers = set()
    for item in data.get("news", []):
        if not isinstance(item, dict):
            raise ValueError("Each news entry must be an object")
        for field in ("identifier", "title", "appID"):
            require_string(item.get(field), f"news.{field}")
        if item["appID"] not in app_ids or item["identifier"] in identifiers:
            raise ValueError(
                "News must reference an existing app and have a unique identifier"
            )
        identifiers.add(item["identifier"])
        require_date(item.get("date"), "news.date")
        require_url(item.get("url"), "news.url")
        require_url(item.get("imageURL"), "news.imageURL")


def validate_config(config: dict[str, Any]) -> None:
    for key in ("source", "retention", "apps"):
        if key not in config:
            raise ValueError(f"Missing top-level config key: {key}")

    if not isinstance(config["source"], dict):
        raise TypeError("source must be an object")
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
        "upstream_asset_regex",
        "version_regex",
        "output_name",
        "transformation",
        "runner",
    }
    prefixes: set[str] = set()
    app_ids: set[str] = set()

    for key, app in config["apps"].items():
        if not isinstance(app, dict):
            raise ValueError(f"{key} must be an object")
        missing = required - app.keys()
        if missing:
            raise ValueError(
                f"{key} is missing config keys: {', '.join(sorted(missing))}"
            )
        for field in required:
            require_string(app.get(field), f"{key}.{field}")
        for field in (
            "upstream_asset_regex",
            "mirror_asset_regex",
            "version_regex",
            "preferred_upstream_asset_regex",
            "display_version_regex",
        ):
            if field in app:
                require_string(app[field], f"{key}.{field}")
                regex = compile_pattern(app[field])
                if (
                    field in ("version_regex", "display_version_regex")
                    and "version" not in regex.groupindex
                ):
                    raise ValueError(
                        f"{key}.{field} must contain a named version group"
                    )
        if app["transformation"] not in ("none", "apollo_bundle_versions"):
            raise ValueError(f"{key}: unknown transformation {app['transformation']}")
        if app["transformation"] == "apollo_bundle_versions" and not app[
            "runner"
        ].startswith("macos-"):
            raise ValueError(f"{key}: Apollo transformation requires a macOS runner")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", app["repo_url"]):
            raise ValueError(f"{key}.repo_url must use owner/name form")
        for field in ("icon_url", "image_url"):
            require_url(app[field], f"{key}.{field}")
        template = app["output_name"]
        if re.search(r"\{(?!version\}|asset_name\})", template):
            raise ValueError(f"{key}: unknown output_name placeholder")
        if (
            Path(template).name != template
            or "\\" in template
            or (template != "{asset_name}" and not template.endswith(".ipa"))
        ):
            raise ValueError(f"{key}.output_name must be an IPA filename")
        if app["mirror_tag_prefix"] in prefixes:
            raise ValueError(f"Duplicate mirror_tag_prefix: {app['mirror_tag_prefix']}")
        if app["app_id"] in app_ids:
            raise ValueError(f"Duplicate app_id: {app['app_id']}")
        prefixes.add(app["mirror_tag_prefix"])
        app_ids.add(app["app_id"])

    if not isinstance(config["retention"], dict):
        raise ValueError("retention must be an object")
    for key in ("versions_per_app", "news_per_app"):
        if (
            type(config["retention"].get(key)) is not int
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
    if not re.fullmatch(r"\d+(?:\.\d+)+(?:-\d+(?:\.\d+)+)?", version):
        raise ValueError(f"Invalid mirrored release tag: {tag}")
    return version


def display_version(
    release: dict[str, Any], asset: dict[str, Any], app: dict[str, Any]
) -> str:
    build_version = version_from_tag(release["tag_name"], app["mirror_tag_prefix"])
    pattern = app.get("display_version_regex")
    if not pattern:
        return build_version

    candidates = [asset["name"]]
    candidates.extend(re.findall(r"`([^`]+)`", release.get("body") or ""))
    for candidate in candidates:
        match = compile_pattern(pattern).fullmatch(candidate)
        if match:
            return match.group("version")
    raise ValueError(
        f"Could not extract display version for release: {release['tag_name']}"
    )


def matching_asset(release: dict[str, Any], pattern: str) -> dict[str, Any] | None:
    regex = compile_pattern(pattern)
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
    version = display_version(release, asset, app)
    build_version = version_from_tag(release["tag_name"], app["mirror_tag_prefix"])
    return {
        "version": version,
        "buildVersion": build_version,
        "date": release["published_at"],
        "localizedDescription": clean_description(release.get("body")),
        "downloadURL": asset["browser_download_url"],
        "size": asset.get("size", 0),
    }


def news_entry(
    release: dict[str, Any], asset: dict[str, Any], app: dict[str, Any]
) -> dict[str, Any]:
    version = display_version(release, asset, app)
    build_version = version_from_tag(release["tag_name"], app["mirror_tag_prefix"])
    date = datetime.fromisoformat(release["published_at"])
    return {
        "appID": app["app_id"],
        "title": f"{version} - {date.strftime('%d %b')}",
        "identifier": f"{app['app_id']}-release-{build_version}",
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
    if not releases:
        raise ValueError(
            f"{app['app_name']}: no matching stable mirrored releases; source unchanged"
        )
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
            news_entry(release, asset, app)
            for release, asset in mirrored[: config["retention"]["news_per_app"]]
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

    validate_source(data)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=source_path.parent,
            prefix=f".{source_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.chmod(
            source_path.stat().st_mode & 0o777 if source_path.exists() else 0o644
        )
        temporary_path.replace(source_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    config = load_json(Path(args.config))
    validate_config(config)

    source_path = Path(config["source"]["json_file"])
    if source_path.exists():
        validate_source(load_json(source_path))
    elif args.validate_only:
        raise ValueError(f"Source file does not exist: {source_path}")

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
