#!/usr/bin/env python3
"""Build-time installation into the Steam compatibility-tool extension prefix."""
import argparse
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

NAME = 'proton-ge-hdr-toggler'
APP_ID = 'com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR'
LIB = Path('lib') / NAME
SHARE = Path('share') / NAME


def install_file(source, target, *, executable=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755 if executable else 0o644)


def install_metainfo(template, target, info, notes):
    tree = ET.parse(template)
    releases = tree.find('releases')
    if not notes or notes[0]['version'] != info['version']:
        raise ValueError('Release notes do not match the bundled version')
    for entry in notes:
        release = ET.SubElement(releases, 'release', version=entry['version'], date=entry['date'])
        description = ET.SubElement(release, 'description')
        for paragraph in entry['paragraphs']:
            ET.SubElement(description, 'p').text = paragraph
        ET.SubElement(description, 'p').text = 'HDR game list changes:'
        changes = ET.SubElement(description, 'ul')
        for change in entry['catalog_changes']:
            ET.SubElement(changes, 'li').text = change
        if entry.get('proton_notes'):
            ET.SubElement(description, 'p').text = 'Proton-GE upstream release notes:'
            changes = ET.SubElement(description, 'ul')
            # Upstream notes are Markdown. Convert to plain text, then let the
            # XML writer escape it; upstream markup is never injected as XML.
            for line in entry['proton_notes'].splitlines():
                text = re.sub(r'^\s*(?:#+\s*|[-*+]\s+)', '', line).strip()
                text = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', text)
                text = text.replace('**', '').replace('`', '')
                if text:
                    ET.SubElement(changes, 'li').text = text
        ET.SubElement(release, 'url', type='details').text = entry['url']
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space='  ')
    tree.write(target, encoding='utf-8', xml_declaration=True)
    target.chmod(0o644)


def install(proton, source, steam, data, destination, license_file):
    if not (proton / 'proton').is_file() or not (proton / 'files').is_dir():
        raise ValueError('Not a Proton distribution')
    catalog = json.loads((data / 'hdr-games.json').read_text())
    if catalog.get('version') != 1 or not catalog.get('games'):
        raise ValueError('Missing or invalid HDR catalog')
    info = json.loads((data / 'build-info.json').read_text())
    notes = json.loads((data / 'release-notes.json').read_text())
    # Flatpak Builder creates the extension prefix before build-commands run.
    shutil.copytree(proton, destination, dirs_exist_ok=True, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    (destination / 'proton').rename(destination / 'proton-real')
    for name in ('compatibilitytool.vdf', 'toolmanifest.vdf'):
        (destination / name).rename(destination / (name + '.upstream'))
        install_file(steam / name, destination / name)
    compatibility = destination / 'compatibilitytool.vdf'
    compatibility.write_text(compatibility.read_text().replace('@VERSION@', info['version']))
    install_file(source / 'proton.py', destination / 'proton', executable=True)
    for name in ('runner.py', 'sessions.py', 'mutter.py'):
        install_file(source / name, destination / LIB / name)
    install_file(data / 'hdr-games.json', destination / SHARE / 'hdr-games.json')
    install_file(data / 'build-info.json', destination / SHARE / 'build-info.json')
    install_file(data / 'release-notes.json', destination / SHARE / 'release-notes.json')
    metainfo = destination / 'share/metainfo' / (APP_ID + '.metainfo.xml')
    install_metainfo(steam / metainfo.name, metainfo, info, notes)
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
