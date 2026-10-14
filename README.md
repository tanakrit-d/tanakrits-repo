# Tana's Source 🐤

An automatically updated AltStore-compatible source that mirrors selected iOS
apps and community-maintained tweaks from their upstream GitHub releases. This is largely for personal use, but feel to utilise it :^)

## Applications

|      | App | Upstream |
| :---: | --- | --- |
| <img src="images/apollo/icon.png" alt="Apollo icon" width="64" height="64"> | **Apollo** | [Apollo-Reborn/Apollo-Reborn](https://github.com/Apollo-Reborn/Apollo-Reborn) |
| <img src="images/balato_mp/icon.png" alt="Balatro Multiplayer icon" width="64" height="64"> | **Balatro (Multiplayer)** | [balatro-ios-mod-builder](https://github.com/tanakrit-d/balatro-ios-mod-builder) |
| <img src="images/balatro_pk/icon.png" alt="Balatro Pokermon icon" width="64" height="64"> | **Balatro (Pokermon)** | [balatro-ios-mod-builder](https://github.com/tanakrit-d/balatro-ios-mod-builder) |
| <img src="images/plezy/icon.png" alt="Plezy icon" width="64" height="64"> | **Plezy** | [edde746/plezy](https://github.com/edde746/plezy) |
| <img src="images/twitch/icon.png" alt="Twitch icon" width="64" height="64"> | **Twitch** | [gunnerkidBT/TwitchAdBlock](https://github.com/gunnerkidBT/TwitchAdBlock) |
| <img src="images/youtube/icon.png" alt="YouTube icon" width="64" height="64"> | **YouTube** | [itzzace/ytkace](https://github.com/itzzace/ytkace) |

## Adding the source

Use the following source URL with AltStore Classic, SideStore, Feather, etc:

```text
https://raw.githubusercontent.com/tanakrit-d/tanakrits-repo/refs/heads/main/app.json
```

> [!NOTE]  
> Not compatible with AltStore PAL.

## How it works

The scheduled GitHub Actions workflow checks each configured upstream project
daily for its latest stable IPA (per stream where configured), mirrors new
releases, and regenerates
[`app.json`](app.json). The source retains up to two releases and two news
entries per app.

App metadata, upstream asset matching, and mirror transformations are defined
in [`config.json`](config.json). Projects with multiple release streams use
`upstream_tag_regex` to select the latest stable release for each stream, with
separate bundle identifiers and mirror tag prefixes. The initial Balatro entries
link directly to upstream IPAs until the workflow creates their first mirrors.

Validate local changes with:

```sh
uv sync --locked
uv run --locked python update.py --validate-only
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
uv run --locked ruff format --check .
```

The workflow prefers YouTube’s iOS 17+ IPA and falls back to the iOS 16 build
when it is the only supported asset. Existing release tags are checked for the
expected IPA, and missing uploads are repaired. Source generation fails without
changing `app.json` if any configured app has no matching mirrored releases or
the generated feed is invalid. Pull requests run validation, tests, and linting.

## Disclaimer

This repository is an unofficial mirror and is not affiliated with the apps,
services, or upstream projects listed above.
