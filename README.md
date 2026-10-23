# proton-ge-hdr-toggler

For **Flatpak Steam on GNOME Wayland**: enables monitor HDR before listed HDR
games start and restores the previous mode on exit. Bundles Proton-GE and a
[PCGamingWiki HDR catalog](<https://www.pcgamingwiki.com/wiki/List_of_games_that_support_high_dynamic_range_display_(HDR)>),
updated through GitHub Actions. It toggles desktop HDR; games still need HDR enabled.

## Install

```sh
flatpak remote-add --user --if-not-exists proton-ge-hdr-toggler https://engedics.github.io/proton-ge-hdr-toggler/proton-ge-hdr-toggler.flatpakrepo
flatpak install --user proton-ge-hdr-toggler com.valvesoftware.Steam.CompatibilityTool.proton-ge-hdr-toggler
```

## After installation

Run once:

```sh
flatpak override --user --talk-name=org.gnome.Mutter.DisplayConfig com.valvesoftware.Steam
```

Restart Steam and select **proton-ge-hdr-toggler** under the game's
**Properties → Compatibility**, or as your default tool. No launch options are
required. Receive updates through your software manager or `flatpak update --user`.
The displayed version combines Proton-GE and the HDR list page's last edit date,
for example `11-11-20260825`.

Optional per-game **Launch Options**:

- `AUTOHDR=1 %command%`: enable HDR regardless of the catalog.
- `AUTOHDR=0 %command%`: disable automatic HDR switching; leave the monitor's current mode unchanged.

Remove the override to use the catalog again.

[GitHub publishing setup](docs/PUBLISHING.md)

Original project code is licensed under [CC BY-NC-SA 3.0](LICENSE).
The HDR catalog credits PCGamingWiki under the same license; bundled Proton-GE
and its components retain their upstream licenses.
