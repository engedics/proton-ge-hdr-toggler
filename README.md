# Proton-GE HDR

For **Flatpak Steam on GNOME Wayland**: enables monitor HDR before HDR-supported
games start and restores the previous mode on exit. Bundles Proton-GE and works based off of
[PCGamingWiki's HDR catalog](<https://www.pcgamingwiki.com/wiki/List_of_games_that_support_high_dynamic_range_display_(HDR)>).
It toggles desktop HDR; games still need HDR enabled.

## Install

```sh
flatpak remote-add --user --if-not-exists proton-ge-hdr-toggler https://engedics.github.io/proton-ge-hdr-toggler/proton-ge-hdr-toggler.flatpakrepo
flatpak install --user proton-ge-hdr-toggler com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR
flatpak override --user --talk-name=org.gnome.Mutter.DisplayConfig com.valvesoftware.Steam
```

Restart Steam and select **Proton-GE HDR** under the game's
**Properties → Compatibility**, or as your default tool. No launch options are
required. Receive updates through your software manager or `flatpak update --user`.
The displayed version combines Proton-GE and the UTC date when the HDR catalog
snapshot changed, for example `11-11-20261102`. Further catalog updates on the
same day append `.2`, `.3`, and so on. Unchanged daily checks keep the version.

GNOME Software metadata includes release notes with HDR game list additions,
removals and support changes, plus upstream release notes when Proton-GE changes.
If GNOME Software still shows cached metadata, refresh it with
`flatpak update --user --appstream proton-ge-hdr-toggler` and reopen Software.

Optional per-game **Launch Options**:

- `AUTOHDR=1 %command%`: enable HDR regardless of the catalog.
- `AUTOHDR=0 %command%`: disable automatic HDR switching; leave the monitor's current mode unchanged.

Remove the override to use the catalog again.

If MangoHud is missing with Proton's Wayland driver on an older package, GE's
Wayland overlay may have replaced Vulkan's implicit-layer search path. Updated
packages preserve normal layer discovery. Until updating, this per-game launch
option includes Flatpak's layer directory while retaining GE's own additions:

```sh
VK_IMPLICIT_LAYER_PATH=/usr/lib/extensions/vulkan/share/vulkan/implicit_layer.d %command%
```

[Faugus Launcher Flatpak support](docs/FAUGUS.md) reuses this installed Proton-GE
through a lightweight selectable **ProtonGEHDR** runner. It needs no second Proton
download. Install with `python3 scripts/faugus.py install`, then apply the narrowly
scoped permission command it prints. The linked guide covers runner selection,
HDR settings, updates, testing and removal.

[GitHub publishing setup](docs/PUBLISHING.md)

Original project code is licensed under [CC BY-NC-SA 3.0](LICENSE).
The HDR catalog credits PCGamingWiki under the same license; bundled Proton-GE
and its components retain their upstream licenses.
