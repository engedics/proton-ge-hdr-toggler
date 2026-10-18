#!/usr/bin/env python3
"""Refresh pinned GE release and complete PCGamingWiki HDR catalog atomically."""
import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
NAME = 'proton-ge-hdr-toggler'
MANIFEST = ROOT / 'flatpak' / ('com.valvesoftware.Steam.CompatibilityTool.' + NAME + '.yml')
CATALOG = ROOT / 'data/hdr-games.json'
API = 'https://www.pcgamingwiki.com/w/api.php'
SOURCE = 'https://www.pcgamingwiki.com/wiki/List_of_games_that_support_high_dynamic_range_display_(HDR)'
STATES = ('true', 'limited', 'always on', 'hackable')


def get_json(url):
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'proton-ge-hdr-toggler/1.0 (build-time catalog updater)'})
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
            if 'error' in data:
                raise ValueError(str(data['error']))
            return data
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


class CargoTable(HTMLParser):
    """Read Cargo's named cells; unrelated page text cannot become a game."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.parts = [], None, None, []
        self.tables, self.cargo_depth = 0, None
        self.found = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'table':
            self.tables += 1
            if 'cargoTable' in attrs.get('class', '').split():
                self.cargo_depth = self.tables
                self.found = True
        if self.cargo_depth is None:
            return
        if tag == 'tr':
            self.row = {}
        if tag == 'td' and self.row is not None:
            self.cell = attrs.get('class', '')
            self.parts = []

    def handle_data(self, data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            self.row[self.cell] = ''.join(self.parts).strip()
            self.cell = None
        if tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        if tag == 'table':
            if self.tables == self.cargo_depth:
                self.cargo_depth = None
            self.tables -= 1


def fetch_catalog(fetch=get_json, limit=100):
    games, seen, count = {}, set(), 0
    for offset in range(0, 10000, limit):
        query = ('{{#cargo_query:tables=Game,Video|join on=Game._pageID=Video._pageID'
                 '|fields=Game._pageName,Video.HDR,Game.Steam_AppID|where=' +
                 ' OR '.join(f"Video.HDR='{state}'" for state in STATES) +
                 f'|order by=Game._pageName|limit={limit}|offset={offset}|format=table}}}}')
        data = fetch(API + '?' + urlencode(dict(action='parse', text=query,
                     contentmodel='wikitext', prop='text', format='json')))
        table = CargoTable()
        table.feed(data['parse']['text']['*'])
        if not table.found:
            raise ValueError('PCGamingWiki did not return the expected Cargo table')
        for row in table.rows:
            title, hdr = row['field__pageName'], row['field_HDR']
            if not title or title in seen or hdr not in STATES:
                raise ValueError('Repeated page or invalid HDR value; refusing partial catalog')
            seen.add(title)
            count += 1
            ids = row['field_Steam_AppID']
            if ids and re.search(r'[^0-9\s,;•]', ids):
                raise ValueError(f'Invalid Steam IDs for {title}: {ids}')
            for appid in re.findall(r'\d+', ids):
                if not 0 < int(appid) < 2**32:
                    raise ValueError(f'Invalid Steam ID: {appid}')
                # Shared AppIDs for separate games/remasters must not silently
                # inherit support from just one of their wiki pages.
                entry = {'title': title, 'hdr': hdr}
                if appid in games and games[appid] != entry:
                    entry = {'title': games[appid]['title'] + ' / ' + title, 'hdr': 'ambiguous'}
                games[appid] = entry
        if len(table.rows) < limit:
            break
    else:
        raise ValueError('Catalog pagination did not terminate')
    return {'version': 1, 'source': SOURCE, 'license': 'CC-BY-NC-SA-3.0',
            'license_url': 'https://creativecommons.org/licenses/by-nc-sa/3.0/',
            'source_rows': count, 'games': dict(sorted(games.items(), key=lambda item: int(item[0])))}


def fetch_release(fetch=get_json):
    release = fetch('https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest')
    tag = release['tag_name']
    if not re.fullmatch(r'GE-Proton[0-9]+(?:-[0-9]+)+', tag):
        raise ValueError(f'Unexpected GE tag: {tag}')
    assets = [item for item in release['assets'] if item['name'] == tag + '-x86_64.tar.gz']
    if len(assets) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', assets[0].get('digest') or ''):
        raise ValueError('Release must have one x86_64 archive with a SHA256 digest')
    asset = assets[0]
    expected = f'https://github.com/GloriousEggroll/proton-ge-custom/releases/download/{tag}/{tag}-x86_64.tar.gz'
    if asset['browser_download_url'] != expected:
        raise ValueError('Unexpected Proton-GE release download URL')
    return {'version': tag, 'url': asset['browser_download_url'],
            'sha256': asset['digest'].split(':', 1)[1]}


def manifest(release):
    return f'''# Generated by scripts/update.py. Build support is never installed.
id: com.valvesoftware.Steam.CompatibilityTool.{NAME}
default-branch: stable
runtime: com.valvesoftware.Steam
runtime-version: stable
sdk: org.freedesktop.Sdk//26.08
build-extension: true
separate-locales: false
build-options:
  no-debuginfo: true
modules:
  - name: {NAME}
    buildsystem: simple
    sources:
      - type: archive
        url: {release['url']}
        sha256: {release['sha256']}
        dest: payload
      - type: dir
        path: ../src
        dest: src
      - type: dir
        path: ../steam
        dest: steam
      - type: dir
        path: ../data
        dest: data
      - type: file
        path: ../scripts/install.py
        dest: build-support
      - type: file
        path: ../LICENSE
        dest: build-support
    build-commands:
      - python3 build-support/install.py --proton payload --source src --steam steam --data data --destination "$FLATPAK_DEST" --license build-support/LICENSE
'''


def write_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        return False
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-large-catalog-change', action='store_true')
    args = parser.parse_args()
    # Fetch and validate both before replacing either checked-in input.
    release, catalog = fetch_release(), fetch_catalog()
    if catalog['source_rows'] < 100 or len(catalog['games']) < 100:
        raise ValueError('Unexpectedly small catalog; retaining previous inputs')
    previous = CATALOG
    if previous.exists() and not args.allow_large_catalog_change:
        old = json.loads(previous.read_text())
        if catalog['source_rows'] < old['source_rows'] * 0.75 or len(catalog['games']) < len(old['games']) * 0.75:
            raise ValueError('Catalog shrank by over 25%; inspect before overriding')
    files = {MANIFEST: manifest(release),
             CATALOG: json.dumps(catalog, indent=2, ensure_ascii=False) + '\n'}
    changed = False
    for path, contents in files.items():
        changed |= write_changed(path, contents.encode())
    print(f"{release['version']}: {catalog['source_rows']} wiki games, {len(catalog['games'])} Steam IDs; changed={changed}")


if __name__ == '__main__':
    main()
