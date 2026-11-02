#!/usr/bin/env python3
"""Opt-in Faugus/UMU smoke test; temporary runner/prefix, HDR disabled."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from faugus import APP_ID, find_source, install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proton', type=Path, help='Override the shared deployment path')
    args = parser.parse_args()
    source = args.proton or find_source()
    grant = source.parent.parent if source.parent.name == 'active' else source
    # UMU debug logging can print the entire inherited environment. This probe
    # does not need application credentials or coding-agent environment values.
    env = {key: value for key, value in os.environ.items() if key in {
        'PATH', 'HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
        'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LANG', 'LC_ALL',
        'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP',
    }}
    with tempfile.TemporaryDirectory(prefix='protongehdr-faugus-smoke-') as temp:
        root = Path(temp)
        runner = root / 'Steam/compatibilitytools.d/ProtonGEHDR'
        install(source, runner)
        discovery = root / 'discovery.py'
        discovery.write_text('''from faugus import utils
from faugus.path_manager import find_compatibilitytool
utils._ = lambda text: text
class Combo:
    def __init__(self): self.ids = []
    def append(self, key, *args): self.ids.append(key)
    def set_active(self, *args): pass
    def configure_ellipsize(self, *args): pass
combo = Combo()
utils.populate_combobox_with_runners(combo)
assert 'ProtonGEHDR' in combo.ids
assert find_compatibilitytool('ProtonGEHDR').name == 'ProtonGEHDR'
print('PROTONGEHDR_DISCOVERY_OK')
''')
        base = ['flatpak', 'run', f'--filesystem={root}', f'--filesystem={grant}:ro']
        result = subprocess.run([*base, f'--env=HOST_XDG_DATA_HOME={root}',
                                 f'--env=HOST_HOME={root / "home"}',
                                 f'--env=XDG_DATA_HOME={root / "faugus-data"}',
                                 f'--env=XDG_CONFIG_HOME={root / "config"}',
                                 f'--env=XDG_STATE_HOME={root / "state"}',
                                 '--command=python3', APP_ID, str(discovery)],
                                env=env, capture_output=True, text=True, timeout=30)
        if result.returncode or 'PROTONGEHDR_DISCOVERY_OK' not in result.stdout:
            parser.exit(1, 'Installed Faugus did not discover the temporary ProtonGEHDR runner.\n'
                        + result.stderr[-1500:] + '\n')
        print('PASS: installed Faugus lists and resolves ProtonGEHDR.')
        batch = root / 'probe.cmd'
        marker = root / 'game-result.txt'
        windows_batch = 'Z:' + str(batch).replace('/', '\\')
        windows_marker = 'Z:' + str(marker).replace('/', '\\')
        batch.write_text('@echo off\nping -n 3 127.0.0.1 > nul\n> "' + windows_marker +
                         '" echo PROTONGEHDR_SMOKE_OK_%PROTONGEHDR_TEST_VALUE%\nexit /b 23\n')
        executable = source.resolve() / 'files/lib/wine/x86_64-windows/cmd.exe'
        # Only a built-in Windows command is executed. No existing game/prefix
        # or display configuration is changed.
        launch = [*base, f'--env=PROTONPATH={runner}',
                                 f'--env=WINEPREFIX={root / "prefix"}', '--env=GAMEID=0',
                                 '--env=AUTOHDR=0', '--env=UMU_RUNTIME_UPDATE=0',
                                 '--env=UMU_USE_STEAM=1', '--env=UMU_CONTAINER_NSENTER=1',
                                 '--env=UMU_LOG=error', '--env=WINEDEBUG=-all',
                                 '--env=PROTONGEHDR_TEST_VALUE=ENV_PRESERVED',
                                 f'--env=PROTONGEHDR_SMOKE_EXE={executable}',
                                 f'--env=PROTONGEHDR_SMOKE_BATCH={windows_batch}',
                                 '--command=sh', APP_ID, '-c',
                                 'exec "$XDG_DATA_HOME/faugus-launcher/umu-run" '
                                 '"$PROTONGEHDR_SMOKE_EXE" /c "$PROTONGEHDR_SMOKE_BATCH"']
        for verb, exits in (('waitforexitandrun', (0, 23)), ('runinprefix', (23,))):
            marker.unlink(missing_ok=True)
            result = subprocess.run([*launch[:2], f'--env=PROTON_VERB={verb}', *launch[2:]],
                                    env=env, capture_output=True, text=True, timeout=180)
            # GE's Steam command-launcher service currently reports 0 even
            # when cmd.exe exits 23. runinprefix directly preserves code 23.
            # A delayed marker verifies that UMU waited for the game to finish.
            if (result.returncode not in exits or not marker.exists()
                    or 'PROTONGEHDR_SMOKE_OK_ENV_PRESERVED' not in marker.read_text()):
                parser.exit(1, f'UMU/shared-GE {verb} launch failed (exit {result.returncode}).\n'
                            + f'Game marker present: {marker.exists()}\n' + result.stderr[-4000:] + '\n')
            print(f'PASS: real UMU/shared GE {verb} waits for cmd.exe; environment preserved; exit {result.returncode}.')
        if not (root / 'prefix/drive_c').is_dir():
            parser.exit(1, 'UMU did not initialize the temporary prefix as expected.\n')
        print('PASS: UMU initialized the temporary prefix.')
    print('Temporary runner and prefix removed; no HDR or persistent permissions changed.')


if __name__ == '__main__':
    main()
