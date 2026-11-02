# Faugus Launcher Flatpak

ProtonGEHDR can also be selected in Faugus without installing a second Proton-GE.
The adapter uses the existing Steam Flatpak extension as a read-only distribution.
It does not change that extension or Faugus's source, settings or game prefixes.

## Assessment and upstream contracts

The repository has four runtime parts: Steam's `src/proton.py` entry point,
the shared catalog policy, `runner.py`'s subprocess supervisor, and the
`sessions.py`/`mutter.py` journal and display client. Steam's installer deliberately
replaces GE's runtime-requiring manifest so its wrapper runs in Steam's Flatpak
environment. The original GE manifest and Proton entry point are retained as
`toolmanifest.vdf.upstream` and `proton-real`.

| Approach | Assessment |
| --- | --- |
| Use the Steam sandbox's `/app/share/steam/compatibilitytools.d/...` path | This mount belongs to Steam. It is not available in Faugus. |
| Point UMU directly at the host deployment of the Steam extension | Insufficient: its manifest omits GE's required runtime, and the Steam wrapper rejects UMU's zero/non-Steam app IDs even with forced HDR. |
| Copy GE into Faugus's runner directory | Works in principle, but duplicates the distribution and updates. |
| Lightweight host-layer runner with a linked GE backend | Implemented. The HDR supervisor stays in Faugus's Python/GObject environment; the inner UMU selects GE's proper runtime and initializes its prefix. Only adapter code and symlinks are installed. |

The adapter is a UMU **host compatibility layer**, not a fake complete Proton
distribution. Its outer manifest has no runtime dependency and uses the
`umu-passthrough` layer name. UMU calls `proton VERB EXE ARGS`; the adapter acquires
an HDR lease and runs Faugus's existing UMU again with the original verb, executable,
arguments and a concrete linked backend in `PROTONPATH`. The backend's `proton`
points to GE's `proton-real`; its manifest points to GE's original manifest.
UMU then performs its usual Proton prefix and runtime setup. There is no recursive
call to the Steam HDR wrapper, and no Proton download token is used.

This extra UMU process avoids moving the HDR code inside pressure-vessel, whose
Python environment need not contain PyGObject. The adapter preserves `WINEPREFIX`,
`GAMEID`, `STORE`, Faugus IDs, launch arguments and user environment settings.
The inner UMU naturally recalculates its runtime variables. The adapter changes
`PROTONPATH` and `PROTON_VERB` for that inner invocation, and appends the resolved
deployment to `STEAM_COMPAT_LIBRARY_PATHS` so pressure-vessel can see link targets.

Upstream implementations inspected on 2026-10-25:

- [Faugus path discovery and runner lookup](https://github.com/Faugus/faugus-launcher/blob/6d0cb04292d06b2f70dff7bca87d01a0b6b5e4e8/faugus/path_manager.py): searches the host Steam `compatibilitytools.d` directories, including Steam Flatpak's user data. It does not enumerate installed Steam Flatpak extensions.
- [Faugus runner list](https://github.com/Faugus/faugus-launcher/blob/6d0cb04292d06b2f70dff7bca87d01a0b6b5e4e8/faugus/utils.py) and [launch construction](https://github.com/Faugus/faugus-launcher/blob/6d0cb04292d06b2f70dff7bca87d01a0b6b5e4e8/faugus/runner.py): the directory name is selectable, is resolved into `PROTONPATH`, and the configured UMU launches it.
- [UMU compatibility layers](https://github.com/Open-Wine-Components/umu-launcher/blob/e2b203a1fdd2af9f35166f5713cb3f85d72587e2/umu/umu_runtime.py): reads `toolmanifest.vdf`, resolves `require_tool_appid`, substitutes `%verb%`, and supports a host layer with no required runtime.
- [UMU environment, prefixes, process and exit handling](https://github.com/Open-Wine-Components/umu-launcher/blob/e2b203a1fdd2af9f35166f5713cb3f85d72587e2/umu/umu_run.py): resolves concrete `PROTONPATH` values, prepares Proton prefixes, constructs runtime/tool mounts, handles `runinprefix`, forwards signals and waits for its subprocess.
- [Faugus Flatpak packaging](https://github.com/flathub/io.github.Faugus.faugus-launcher/blob/964ac14094f8b9cb04357e95a5b13ad20bf92d17/io.github.Faugus.faugus-launcher.yml): provides Python/GObject and the existing graphics/audio/container permissions; does not grant Mutter DisplayConfig access.

The installed Faugus 2.5.1-1 and its UMU 1.4.4-patch were also inspected and used
for the sandbox smoke tests. Older UMU releases with a different compatibility
layer interface are not supported by this adapter.

## Why this is not a separately mounted Flatpak add-on

Being a Flatpak does not automatically let an application load arbitrary
extensions. The parent must declare an extension point, and its runner discovery
must look in the resulting mount directory. Steam provides a compatibility-tool
extension point; the current Faugus Flatpak does not. Its installed metadata and
the [current Flathub manifest](https://github.com/flathub/io.github.Faugus.faugus-launcher/blob/master/io.github.Faugus.faugus-launcher.yml)
provide graphics/architecture extension points but no custom-runner extension
point. See [Flatpak's extension requirements](https://docs.flatpak.org/en/latest/dependencies.html#extensions).

A native Faugus add-on would therefore need an upstream extension point plus
discovery of runners mounted there, or a separate registration step into its
existing discovery directories. An AppStream `extends` tag alone cannot mount
an add-on. A standalone Flatpak installer application is possible, but would
still have to register a runner and arrange access to the shared GE files; it
would not be an automatically mounted Faugus extension. The small installer
bundle remains the integration that works with the unmodified Faugus package.

## Installation

First install the existing Steam extension normally and start Faugus once so it
has installed its UMU component. Close Faugus and any games before installing or
updating the adapter. Run from this repository, or from the extracted
`ProtonGEHDR-faugus.tar.gz` installer bundle:

```sh
python3 scripts/faugus.py install
```

By default this follows Faugus's directory choice: a small `ProtonGEHDR` directory
under `~/.local/share/Steam/compatibilitytools.d/` (or the host XDG data directory),
or Steam Flatpak's `~/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/`
if only that Steam directory exists. Use the installed path printed by the script
in the status/recovery examples below.
The installer detects user/system Steam extension deployments using
`flatpak info --show-location`, then saves the stable `active/files` path rather
than pinning the adapter configuration to today's commit. It refuses to overwrite
an unrelated runner. Repeating installation updates only its own small files.

The installer prints the **exact permission command** for your paths. Run that
command on the host. For a normal per-user extension installation it resembles:

```sh
flatpak override --user \
  --filesystem="$HOME/.local/share/Steam/compatibilitytools.d/ProtonGEHDR" \
  --filesystem="$HOME/.local/share/flatpak/runtime/com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR/x86_64/stable:ro" \
  --talk-name=org.gnome.Mutter.DisplayConfig \
  io.github.Faugus.faugus-launcher
```

The runner directory is writable because it creates small linked backend views
at launch. The deployment directory is read-only. Granting its `stable` parent
lets the `active` symlink move between sibling commits after updates. A system
extension instead needs its corresponding path under `/var/lib/flatpak/runtime/`.
No broad home access, host command execution permission or new D-Bus service is
needed. Games, prefixes and UMU's existing runtime storage still need their usual
Faugus permissions; these commands only add what the HDR adapter requires.

For a custom Flatpak installation or discovery directory:

```sh
python3 scripts/faugus.py install \
  --proton /actual/installation/runtime/com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR/x86_64/stable/active/files \
  --destination "$HOME/.local/share/Steam/compatibilitytools.d/ProtonGEHDR"
```

Keep `active` in the source path to follow updates. Choose a destination in one of
Faugus's two discovery directories; arbitrary directories are not discovered.
Use `python3 scripts/faugus.py permissions` to print the grants again, supplying
the same custom arguments if used during installation.

## Runner selection and HDR settings

Reopen Faugus, edit a Windows game, and select **ProtonGEHDR** in its normal runner
selection (it may be labeled **ProtonGEHDR (Flatpak)** in the second discovery
directory). Keep UMU enabled. No extra launch-command wrapper is necessary.

Choosing this runner opts that non-Steam game into HDR. The Steam catalog cannot
reliably identify arbitrary Faugus games from their UMU IDs. Put any overrides in
Faugus's environment/launch arguments field, using its normal assignment syntax:

| Setting | Effect |
| --- | --- |
| No override | Enable desktop HDR for games using this runner. |
| `AUTOHDR=0` | Launch through GE/UMU without HDR switching. |
| `AUTOHDR=1` | Explicitly enable HDR for gameplay. |
| `AUTOHDR_APPID=275850` | Use the shared Steam HDR catalog for this known Steam AppID instead of the default opt-in. Does not change the game's UMU identity. |
| `AUTOHDR_MONITOR=DP-3` | Select a display instead of the primary monitor. |
| `AUTOHDR_UMU=/absolute/path/to/umu-run` | Override the normal Faugus UMU component path if your setup differs. |

Prefix creation, winetricks and known maintenance helpers skip HDR switching.
GE's original Proton and protonfixes still handle the game. Missing Proton/UMU
causes a clear launch error, rather than downloading a second runner. Failure to
activate HDR logs an error and lets the game launch in the current display mode,
matching Steam's existing fail-open behavior.

## Updates, restoration and recovery

Update the Steam extension through Flatpak as before. Each launch resolves its
current `active` deployment and creates a few symlinks under `.backends/` for that
deployment. The running game's links remain pinned to its chosen commit. Added
top-level files and changed runtime requirements are picked up on the next
launch. Do not update/uninstall/prune the shared extension while a Faugus game is
running: Flatpak does not track this external use of its deployment.
To update the adapter's own Python code, rerun its installer from the newer
repository checkout or installer bundle; updating Proton alone does not replace
the adapter's files.

Normal exit and catchable termination use the existing HDR supervisor's `finally`
cleanup, journal, monitor identity checks and restoration rules. HDR that was
already enabled stays enabled; a manual change back to SDR is respected. A game
crash is handled when its UMU process returns. Termination that kills the
supervisor itself with SIGKILL, kills the whole Flatpak, or loses the session bus
cannot guarantee immediate restoration. The journal is recovered on the next
HDR launch, or explicitly after games have stopped:

```sh
flatpak run --command=python3 io.github.Faugus.faugus-launcher \
  "$HOME/.local/share/Steam/compatibilitytools.d/ProtonGEHDR/proton" --status
flatpak run --command=python3 io.github.Faugus.faugus-launcher \
  "$HOME/.local/share/Steam/compatibilitytools.d/ProtonGEHDR/proton" --recover
```

The supervisor runs outside pressure-vessel so concurrent games started within one
Faugus instance share one PID namespace and journal. Steam and Faugus have separate Flatpak state roots and
leases; simultaneous HDR games across the two launchers are not coordinated.
Avoid overlapping HDR sessions across launchers. Do not point both apps at the
same `AUTOHDR_STATE_DIR`, since their PID namespaces can differ. Likewise, use one
Faugus instance for overlapping games; independently started Flatpak instances
can have different PID namespaces and cannot safely share process-based leases.

## MangoHud

The HDR adapter preserves MangoHud environment variables. Enable MangoHud using
Faugus's per-game MangoHud option; merely having the runtime extension installed
does not enable it for a game. The extension branch must match the Freedesktop
version used by Faugus's GNOME runtime (26.08 for GNOME 51).

MangoHud's default visibility toggle is **Right Shift + F12**, not Right Ctrl.
If `no_display` is enabled in the active config, the overlay starts hidden.
To use Right Ctrl instead, set this in that config:

```ini
toggle_hud=Control_R+F12
```

See the [upstream keybindings](https://github.com/flightlessmango/MangoHud#keybindings).
The hotkey toggles an already loaded overlay; it cannot inject MangoHud into a
running game. For diagnosis, temporarily set `MANGOHUD_CONFIG=no_display=0` in
the game's Faugus environment/launch arguments and restart it. If the overlay
then appears, loading works and the remaining issue is its toggle/configuration.
If it does not, check the per-game MangoHud option and runtime extension before
changing HDR or Proton settings. Steam uses `MANGOHUD=1 %command%` to enable the
Vulkan overlay, with the same config and keybinding rules.

## Validation

Run the automated suite with `python3 -m unittest discover -s tests -v`.
It covers the unchanged Steam entry point, catalog/probe policy, signal forwarding,
normal/crashed child cleanup, existing-HDR behavior, installer ownership/idempotence,
GE deployment changes and absence, linked manifests, and preserved arguments,
working directory, prefix/store/game IDs and environment. Display tests use fake
backends and do not touch the desktop.

The optional sandbox smoke test needs installed Faugus, its UMU component and the
Steam HDR extension:

```sh
python3 scripts/test_faugus_flatpak.py
```

It uses temporary per-run permissions and a temporary prefix, checks the real
installed Faugus runner discovery, and runs Wine's built-in `cmd.exe` through the
real UMU and shared GE. It verifies delayed completion, environment preservation,
normal command-launcher behavior and direct `runinprefix` exit code 23, with HDR
disabled. GE's Steam command-launcher service can report exit 0 regardless of the
Windows command's exit status; the adapter passes through UMU's status rather
than changing it. The test does not install the runner permanently or alter your games.
UMU may initialize/update its usual runtime if it is missing; the test disables
runtime updates when the required runtime is already installed.

For physical display validation, use `--status` before launching a known HDR game
with this runner, enable HDR inside the game, and compare the status after normal
exit and after Faugus's Stop action. Repeat with HDR already enabled, a manual
SDR change during play, `AUTOHDR=0`, and a selected secondary display. A successful
Wine smoke test does not establish correct HDR presentation in an actual game.

## Removal

Close Faugus and games; recover any abandoned HDR session first. Select another
runner in Faugus, then run:

```sh
python3 scripts/faugus.py remove
```

This removes only the managed adapter, including its symlinks, and prints a command
to revoke its grants. Run that revocation only for permissions added solely for
this adapter. No prefix, game, Proton distribution or Steam extension is removed.
For a custom install, supply the same `--destination`. Repeating removal is safe.
The recovery journal is retained under Faugus's own XDG state directory.

## Packaging

`python3 scripts/faugus.py bundle` creates `dist/ProtonGEHDR-faugus.tar.gz`.
The bundle contains the adapter, the same shared HDR modules and a host installer,
not a Proton distribution or UMU runtime. The existing workflow builds it alongside
the Steam extension and publishes it in the same Pages repository. Catalog data
continues to come from the shared Steam extension at launch, so it is not copied
into the Faugus bundle.
