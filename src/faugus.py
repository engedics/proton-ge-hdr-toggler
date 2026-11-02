#!/usr/bin/env python3
"""UMU host-layer adapter: supervise the real UMU/Proton runtime from Faugus."""
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'lib/proton-ge-hdr-toggler'))
from policy import HELPERS, wants_hdr
from runner import log, main as recovery_main, supervise

CONFIG = '.protongehdr-faugus.json'
KIND = 'protongehdr-faugus-v1'


def source_root(config):
    """Resolve active once per launch; never substitute a downloadable runner."""
    root = Path(config['source']).resolve(strict=True)
    for name in ('proton-real', 'toolmanifest.vdf.upstream', 'files/bin/wine', 'protonfixes'):
        if not (root / name).exists():
            raise RuntimeError(f'Shared Proton-GE is incomplete or unavailable: {root / name}')
    if not os.access(root / 'proton-real', os.X_OK):
        raise RuntimeError(f'Shared Proton-GE is not executable: {root / "proton-real"}')
    return root


def prepare_backend(destination, source):
    """Build only symlinks, pinned to this Flatpak deployment for this launch."""
    backends = destination / '.backends'
    backends.mkdir(exist_ok=True)
    # Each deployment gets its own linked view, so preparing a new version
    # cannot replace the runner used by a game that is already running.
    backend = backends / sha256(os.fsencode(source)).hexdigest()[:20]
    with (backends / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backend.mkdir(exist_ok=True)
        links = {path.name: path for path in source.iterdir()
                 if path.name not in ('proton', 'proton-real', 'toolmanifest.vdf', 'compatibilitytool.vdf')}
        links['proton'] = source / 'proton-real'
        # Steam's manifest intentionally omits the runtime. UMU needs GE's
        # original require_tool_appid, use_sessions and layer name instead.
        links['toolmanifest.vdf'] = source / 'toolmanifest.vdf.upstream'
        for name, target in links.items():
            link = backend / name
            if not link.is_symlink():
                link.symlink_to(target)
    return backend


def is_game(arguments):
    if len(arguments) < 2 or arguments[0] not in ('run', 'waitforexitandrun', 'runinprefix'):
        return False
    target = arguments[1].replace('\\', '/').rsplit('/', 1)[-1].lower()
    return bool(target) and target not in HELPERS | {
        'createprefix', 'winetricks', 'winecfg', 'winecfg.exe', 'regedit', 'regedit.exe',
        'explorer.exe', 'cmd', 'cmd.exe',
    }


def hdr_enabled(arguments, source, environment):
    if not is_game(arguments):
        return False
    override = environment.get('AUTOHDR')
    if override in ('0', '1'):
        return override == '1'
    # Choosing this runner opts a non-Steam game into HDR. A Steam catalog ID
    # is optional and must not replace UMU's GAMEID, STORE or prefix identity.
    appid = environment.get('AUTOHDR_APPID')
    if not appid:
        return True
    with (source / 'share/proton-ge-hdr-toggler/hdr-games.json').open() as stream:
        return wants_hdr(appid, json.load(stream), environment)


def inner_command(arguments, backend, source, environment):
    env = dict(environment)
    data_home = Path(env.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    umu = Path(env.get('AUTOHDR_UMU', str(data_home / 'faugus-launcher/umu-run')))
    if not umu.is_file() or not os.access(umu, os.X_OK):
        raise RuntimeError(f'Faugus UMU launcher unavailable: {umu}; launch Faugus once to install its components')
    if not arguments or arguments[0] not in ('run', 'waitforexitandrun', 'runinprefix'):
        raise RuntimeError('The Faugus adapter expects a UMU Proton launch verb')
    env['PROTONPATH'] = str(backend)
    env['PROTON_VERB'] = arguments[0]
    # Expose symlink targets to the inner pressure-vessel as well as to the
    # outer Flatpak. Preserve the user's other library mounts.
    mounts = [value for value in env.get('STEAM_COMPAT_LIBRARY_PATHS', '').split(':') if value]
    if str(source) not in mounts:
        mounts.append(str(source))
    env['STEAM_COMPAT_LIBRARY_PATHS'] = ':'.join(mounts)
    return [str(umu), *arguments[1:]], env


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments in (['--status'], ['--recover']):
        return recovery_main(arguments)
    try:
        config = json.loads((ROOT / CONFIG).read_text())
        if config.get('kind') != KIND:
            raise RuntimeError('Unsupported Faugus adapter configuration; reinstall the adapter')
        source = source_root(config)
        backend = prepare_backend(ROOT, source)
        command, environment = inner_command(arguments, backend, source, os.environ)
        try:
            enabled = hdr_enabled(arguments, source, environment)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log(f'Faugus HDR catalog unavailable: {exc}; launching without HDR switching')
            enabled = False
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        log(f'Faugus runner unavailable: {exc}')
        return 127
    if enabled:
        return supervise(command, monitor=environment.get('AUTOHDR_MONITOR'), environment=environment)
    os.execve(command[0], command, environment)


if __name__ == '__main__':
    raise SystemExit(main())
