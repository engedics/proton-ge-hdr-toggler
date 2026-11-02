#!/usr/bin/env python3
"""Install/remove a lightweight Faugus runner, or bundle its installer."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

from install import install_file

ROOT = Path(__file__).resolve().parent.parent
APP_ID = 'io.github.Faugus.faugus-launcher'
EXTENSION_ID = 'com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR'
CONFIG = '.protongehdr-faugus.json'
KIND = 'protongehdr-faugus-v1'
MANIFEST = '''"manifest"
{
    "version" "2"
    "commandline" "/proton %verb%"
    "compatmanager_layer_name" "umu-passthrough"
}
'''


def default_destination():
    data_home = os.environ.get('HOST_XDG_DATA_HOME')
    if not data_home and not os.environ.get('FLATPAK_ID'):
        data_home = os.environ.get('XDG_DATA_HOME')
    native = Path(data_home or Path.home() / '.local/share') / 'Steam'
    flatpak = Path.home() / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
    steam = flatpak if not native.is_dir() and flatpak.is_dir() else native
    return steam / 'compatibilitytools.d/ProtonGEHDR'


def find_source():
    for installation in ('--user', '--system'):
        result = subprocess.run(['flatpak', 'info', installation, '--show-location', EXTENSION_ID],
                                text=True, capture_output=True)
        if result.returncode == 0:
            deployment = Path(result.stdout.strip())
            # Do not save the immutable commit returned by --show-location:
            # follow active on the next launch after a Flatpak update.
            return deployment.parent / 'active/files'
    raise ValueError(f'Install the Steam extension {EXTENSION_ID} first, or specify --proton')


def validate_source(source):
    for name in ('proton-real', 'toolmanifest.vdf.upstream', 'files/bin/wine', 'protonfixes',
                 'share/proton-ge-hdr-toggler/hdr-games.json'):
        if not (source / name).exists():
            raise ValueError(f'Not a complete Proton-GE HDR deployment: {source / name}')


def check_owned(destination):
    if destination.is_symlink():
        raise ValueError(f'Refusing to replace/remove a symlink: {destination}')
    if destination.exists():
        marker = destination / CONFIG
        if not marker.is_file() or json.loads(marker.read_text()).get('kind') != KIND:
            raise ValueError(f'Refusing to replace/remove an unmanaged runner: {destination}')


def install(source, destination, project=ROOT):
    source, destination = source.absolute(), destination.absolute()
    validate_source(source)
    check_owned(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.protongehdr-', dir=destination.parent) as temp:
        staging = Path(temp)
        install_file(project / 'src/faugus.py', staging / 'proton', executable=True)
        for name in ('runner.py', 'sessions.py', 'mutter.py', 'policy.py'):
            install_file(project / 'src' / name, staging / 'lib/proton-ge-hdr-toggler' / name)
        (staging / 'toolmanifest.vdf').write_text(MANIFEST)
        (staging / CONFIG).write_text(json.dumps({'kind': KIND, 'source': str(source)}, indent=2) + '\n')
        install_file(project / 'LICENSE', staging / 'LICENSE')
        destination.mkdir(exist_ok=True)
        files = sorted((path for path in staging.rglob('*') if path.is_file()),
                       key=lambda path: path.name == CONFIG)
        for path in files:
            target = destination / path.relative_to(staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
    return destination


def permission_commands(source, destination, *, revoke=False):
    # active -> COMMIT is a sibling link, so the grant must include the stable
    # directory rather than only the initially resolved files directory.
    source = source.absolute()
    grant = source.parent.parent if source.parent.name == 'active' else source
    arguments = ['flatpak', 'override', '--user']
    if revoke:
        arguments += [f'--nofilesystem={destination}', f'--nofilesystem={grant}',
                      '--no-talk-name=org.gnome.Mutter.DisplayConfig']
    else:
        arguments += [f'--filesystem={destination}', f'--filesystem={grant}:ro',
                      '--talk-name=org.gnome.Mutter.DisplayConfig']
    return shlex.join([*arguments, APP_ID])


def remove(destination):
    check_owned(destination)
    if destination.exists():
        config = json.loads((destination / CONFIG).read_text())
        shutil.rmtree(destination)
        return config
    return None


def bundle(output, project=ROOT):
    output.parent.mkdir(parents=True, exist_ok=True)
    # No distribution, prefix, runtime or per-machine configuration is bundled.
    files = ['scripts/faugus.py', 'scripts/install.py', 'src/faugus.py', 'src/runner.py',
             'src/sessions.py', 'src/mutter.py', 'src/policy.py', 'LICENSE', 'docs/FAUGUS.md']
    with tarfile.open(output, 'w:gz') as archive:
        for name in files:
            archive.add(project / name, arcname='ProtonGEHDR-faugus/' + name, recursive=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'remove', 'permissions', 'bundle'))
    parser.add_argument('--proton', type=Path, help='Host deployment files directory; retain active in the path for updates')
    parser.add_argument('--destination', type=Path, default=default_destination())
    parser.add_argument('--output', type=Path, default=Path('dist/ProtonGEHDR-faugus.tar.gz'))
    args = parser.parse_args(argv)
    destination = args.destination.expanduser().absolute()
    try:
        if args.action == 'bundle':
            bundle(args.output)
            print(args.output)
        elif args.action == 'remove':
            config = remove(destination)
            print(f'Runner removed (or already absent): {destination}')
            if config:
                print('To revoke permissions added solely for this runner:')
                print(permission_commands(Path(config['source']), destination, revoke=True))
        else:
            if args.proton:
                source = args.proton.expanduser()
            elif args.action == 'permissions' and (destination / CONFIG).is_file():
                source = Path(json.loads((destination / CONFIG).read_text())['source'])
            else:
                source = find_source()
            if args.action == 'install':
                install(source, destination)
                print(f'Installed lightweight runner: {destination}')
                print('Close and reopen Faugus, then select ProtonGEHDR in the game runner list.')
            print('Required Faugus permissions (run on the host):')
            print(permission_commands(source, destination))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
