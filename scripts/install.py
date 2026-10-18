#!/usr/bin/env python3
"""Build-time installation into the Steam compatibility-tool extension prefix."""
import argparse
import json
from pathlib import Path
import shutil

NAME = 'proton-ge-hdr-toggler'
LIB = Path('lib') / NAME
SHARE = Path('share') / NAME


def install_file(source, target, *, executable=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755 if executable else 0o644)


def install(proton, source, steam, data, destination, license_file):
    if not (proton / 'proton').is_file() or not (proton / 'files').is_dir():
        raise ValueError('Not a Proton distribution')
    catalog = json.loads((data / 'hdr-games.json').read_text())
    if catalog.get('version') != 1 or not catalog.get('games'):
        raise ValueError('Missing or invalid HDR catalog')
    # Flatpak Builder creates the extension prefix before build-commands run.
    shutil.copytree(proton, destination, dirs_exist_ok=True, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    (destination / 'proton').rename(destination / 'proton-real')
    for name in ('compatibilitytool.vdf', 'toolmanifest.vdf'):
        (destination / name).rename(destination / (name + '.upstream'))
        install_file(steam / name, destination / name)
    install_file(source / 'proton.py', destination / 'proton', executable=True)
    for name in ('runner.py', 'sessions.py', 'mutter.py'):
        install_file(source / name, destination / LIB / name)
    install_file(data / 'hdr-games.json', destination / SHARE / 'hdr-games.json')
    install_file(data / 'CATALOG-LICENSE.txt',
                 destination / 'share/licenses' / NAME / 'PCGamingWiki.txt')
    install_file(license_file, destination / 'share/licenses' / NAME / 'LICENSE')
    # Keep GE's originals outside the loader path. Its old xkbcommon prevents
    # Flatpak SDL3 from loading, which breaks Wine's controller backend.
    for arch in ('x86_64-linux-gnu', 'i386-linux-gnu'):
        for library in sorted((destination / 'files/lib' / arch).glob('libxkbcommon.so*')):
            saved = destination / SHARE / 'upstream-libs' / arch / library.name
            saved.parent.mkdir(parents=True, exist_ok=True)
            library.rename(saved)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('proton', 'source', 'steam', 'data', 'destination', 'license'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    install(args.proton, args.source, args.steam, args.data, args.destination, args.license)
