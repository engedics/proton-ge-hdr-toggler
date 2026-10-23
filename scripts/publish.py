#!/usr/bin/env python3
"""Finish a signed Flatpak repository for GitHub Pages."""
import argparse
import base64
import gzip
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

NAME = 'proton-ge-hdr-toggler'
DISPLAY_NAME = 'Proton-GE HDR'
APP_ID = 'com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR'


def check_catalog(build_directory, info):
    """Catch missing or dropped AppStream metadata before deployment."""
    catalog = build_directory / 'files/share/app-info/xmls' / (APP_ID + '.xml.gz')
    if not catalog.is_file():
        raise ValueError('Missing composed AppStream catalog; use Flatpak Builder >= 1.3.4 with AppStream compose installed')
    root = ET.fromstring(gzip.decompress(catalog.read_bytes()))
    component = next((item for item in root.findall('component') if item.findtext('id') == APP_ID), None)
    if component is None or component.findtext('name') != DISPLAY_NAME:
        raise ValueError('Composed AppStream catalog is missing the Proton-GE HDR name or ID')
    release = component.find('releases/release')
    if (release is None or release.get('version') != info['version']
            or not release.findall('description/p') or not release.findall('description/ul/li')):
        raise ValueError('Composed AppStream catalog is missing current release notes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--gpg-key', required=True)
    parser.add_argument('--build-info', type=Path, required=True)
    parser.add_argument('--build-directory', type=Path, required=True)
    args = parser.parse_args()
    info = json.loads(args.build_info.read_text())
    if not args.url.startswith('https://') or any(char in args.url for char in '\r\n'):
        parser.error('repository URL must use HTTPS')
    check_catalog(args.build_directory, info)
    subprocess.run(['flatpak', 'build-update-repo', '--prune',
                    '--prune-depth=0', '--title=' + DISPLAY_NAME, '--gpg-sign=' + args.gpg_key,
                    str(args.repository)], check=True)
    public_key = subprocess.check_output(['gpg', '--export', args.gpg_key])
    if not public_key:
        raise ValueError('Signing key has no public key')
    (args.repository / (NAME + '.flatpakrepo')).write_text(
        '[Flatpak Repo]\nTitle=' + DISPLAY_NAME + '\nUrl=' + args.url.rstrip('/') +
        '\nDefaultBranch=stable\nGPGKey=' + base64.b64encode(public_key).decode() + '\n')
    (args.repository / '.nojekyll').touch()
    (args.repository / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    size = sum(path.stat().st_size for path in args.repository.rglob('*') if path.is_file())
    if size >= 1_000_000_000:
        raise ValueError('Repository exceeds GitHub Pages capacity; retaining previous deployment')
    print(f"Repository {info['version']}: {size / 1_000_000:.1f} MB")


if __name__ == '__main__':
    main()
