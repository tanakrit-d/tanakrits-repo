# Tana's Source 🐤

An automatically updated AltStore-compatible source that mirrors selected iOS
apps and community-maintained tweaks from their upstream GitHub releases. This is largely for personal use, but feel to utilise it :^)

## Apps

| Icon | App | Upstream | Repository changes |
| :---: | --- | --- | --- |
| <img src="https://apolloreborn.app/assets/icon.png" alt="Apollo icon" width="64" height="64"> | **Apollo** | [Apollo-Reborn](https://github.com/Apollo-Reborn/Apollo-Reborn) | Mirrors the `Glass` IPA variant and sets `CFBundleVersion` and `CFBundleShortVersionString` to the Apollo-Reborn release version. |
| <img src="images/icons/plezy/icon.webp" alt="Plezy icon" width="64" height="64"> | **Plezy** | [edde746/plezy](https://github.com/edde746/plezy) | Mirrors the upstream iOS IPA without binary changes and gives the mirrored asset a versioned filename. |
| <img src="images/icons/twitch/icon.png" alt="Twitch icon" width="64" height="64"> | **Twitch** | [gunnerkidBT/TwitchAdBlock](https://github.com/gunnerkidBT/TwitchAdBlock) | Mirrors the upstream Twitch IPA patched with TwitchAdBlock without additional binary changes. The displayed app version is extracted separately from the TwitchAdBlock release version. |

## Add The Source

Use the following source URL with AltStore Classic, SideStore, Feather, or
whatever floats your boat:

```text
https://raw.githubusercontent.com/tanakrit-d/tanakrits-repo/refs/heads/main/app.json
```

> [!NOTE]  
> Not compatible with AltStore PAL.

## How It Works

The scheduled GitHub Actions workflow checks each configured upstream project
daily for its latest stable IPA, mirrors new releases, and regenerates
[`app.json`](app.json). The source retains up to three releases and three news
entries per app.

App metadata, upstream asset matching, and mirror transformations are defined
in [`config.json`](config.json). Validate local changes with:

```sh
uv run python update.py --validate-only
```

## Disclaimer

This repository is an unofficial mirror and is not affiliated with the apps,
services, or upstream projects listed above.
