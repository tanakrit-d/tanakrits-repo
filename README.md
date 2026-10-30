# Tana's Source 🐤

An automatically updated AltStore-compatible source that mirrors selected iOS
apps and community-maintained tweaks from their upstream GitHub releases. This is largely for personal use, but feel to utilise it :^)

## Applications

|      | App | Upstream |
| :---: | --- | --- |
| <img src="images/apollo/icon.png" alt="Apollo icon" width="64" height="64"> | **Apollo** | [Apollo-Reborn/Apollo-Reborn](https://github.com/Apollo-Reborn/Apollo-Reborn) |
| <img src="images/balato_mp/icon.png" alt="Balatro Multiplayer icon" width="64" height="64"> | **Balatro (Multiplayer)** | [tanakrit-d/balatro-ios-mod-builder](https://github.com/tanakrit-d/balatro-ios-mod-builder) |
| <img src="images/balato_mp_legacy/icon.png" alt="Balatro Multiplayer icon" width="64" height="64"> | **Balatro (Multiplayer) (Legacy)** | [tanakrit-d/balatro-ios-mod-builder](https://github.com/tanakrit-d/balatro-ios-mod-builder) |
| <img src="images/balatro_pk/icon.png" alt="Balatro Pokermon icon" width="64" height="64"> | **Balatro (Pokermon)** | [tanakrit-d/balatro-ios-mod-builder](https://github.com/tanakrit-d/balatro-ios-mod-builder) |
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

## Disclaimer

This repository is an unofficial mirror and is not affiliated with the apps,
services, or upstream projects listed above.

The legacy Multiplayer entry is frozen at its existing downloads and excluded from
mirroring and release cleanup. The new Multiplayer entry tracks PvP 1.x (including
experimental releases) separately and appears in the source after its first real
IPA is mirrored. It uses a separate bundle identifier so both apps can coexist.
