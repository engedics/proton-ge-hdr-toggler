#!/usr/bin/env python3
"""Steam entry point: use the bundled HDR catalog, then delegate to bundled GE."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'lib/proton-ge-hdr-toggler'))


def game_id(arguments, environment):
    # Steam runs d3ddriverquery under appid/prefix 0 during client startup.
    # These checks precede even the manual force override.
    if not arguments or arguments[0] not in ('run', 'waitforexitandrun'):
        return None
    helpers = {'d3ddriverquery.exe', 'd3ddriverquery64.exe', 'iscriptevaluator.exe', 'wineboot.exe',
               'wineserver', 'winedevice.exe', 'steamservice.exe'}
    if any(value.replace('\\', '/').rsplit('/', 1)[-1].lower() in helpers
           for value in arguments[1:]):
        return None
    prefix = environment.get('STEAM_COMPAT_DATA_PATH', '')
    if not prefix or Path(prefix).name == '0':
        return None
    identities = [environment[key] for key in ('SteamAppId', 'STEAM_COMPAT_APP_ID')
                  if environment.get(key)]
    if not identities:
        identities = [environment.get('SteamGameId', '')]
    if any(not value.isascii() or not value.isdecimal() or
           not 0 < int(value) < 2**32 for value in identities):
        return None
    return identities[0] if len(set(identities)) == 1 else None


def wants_hdr(appid, catalog, environment):
    override = environment.get('AUTOHDR')
    if override in ('0', '1'):
        return override == '1'
    entry = catalog['games'].get(appid)
    # Mod-only games require a deliberate per-game opt-in after installing a fix.
    return entry is not None and entry['hdr'] in ('true', 'limited', 'always on')


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    command = [str(ROOT / 'proton-real'), *arguments]
    appid = game_id(arguments, os.environ)
    if appid:
        try:
            catalog = json.loads((ROOT / 'share/proton-ge-hdr-toggler/hdr-games.json').read_text())
            enabled = wants_hdr(appid, catalog, os.environ)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'proton-ge-hdr-toggler: catalog unavailable: {exc}', file=sys.stderr)
            enabled = os.environ.get('AUTOHDR') == '1'
        if enabled:
            from runner import supervise
            return supervise(command, monitor=os.environ.get('AUTOHDR_MONITOR'))
    # Preserve arguments, environment, cwd and status for all other invocations.
    os.execv(command[0], command)


if __name__ == '__main__':
    raise SystemExit(main())
