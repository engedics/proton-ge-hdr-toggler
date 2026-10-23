"""Probe pass-through, catalog policy and staging without touching a display."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load('proton_hdr', 'src/proton.py')
updater = load('hdr_update', 'scripts/update.py')
staging = load('hdr_install', 'scripts/install.py')
publisher = load('hdr_publish', 'scripts/publish.py')


def release(tag='GE-Proton11-11'):
    return {'version': tag, 'published_at': '2026-10-19T18:20:53Z',
            'url': f'https://github.com/GloriousEggroll/proton-ge-custom/releases/download/{tag}/{tag}-x86_64.tar.gz',
            'sha256': 'a' * 64}


def revision(timestamp='2026-08-25T16:22:25Z'):
    return {'id': 1795896, 'timestamp': timestamp}


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.env = {'SteamAppId': '275850', 'STEAM_COMPAT_DATA_PATH': '/steam/compatdata/275850'}
        self.catalog = {'games': {'275850': {'title': 'No Man\'s Sky', 'hdr': 'limited'}}}

    def test_real_game_and_non_game_invocations(self):
        self.assertEqual(wrapper.game_id(['waitforexitandrun', 'game.exe'], self.env), '275850')
        for verb in ('getcompatpath', 'getnativepath', 'waitforexit', 'destroyprefix'):
            self.assertIsNone(wrapper.game_id([verb, 'game.exe'], self.env))
        self.assertIsNone(wrapper.game_id([], self.env))

    def test_startup_probes_never_enable_even_with_force_and_real_id(self):
        self.env['AUTOHDR'] = '1'
        for target in ('/bin/d3ddriverquery64.exe', r'C:\bin\d3ddriverquery.exe',
                       '/Steam/legacycompat/iscriptevaluator.exe',
                       r'C:\Steam\legacycompat\IScriptEvaluator.exe'):
            self.assertIsNone(wrapper.game_id(['run', target, '-d3d12'], self.env))
        for appid, prefix in [('0', '/steam/compatdata/0'), ('275850', '/steam/compatdata/0'),
                              ('275850', '')]:
            with self.subTest(appid=appid, prefix=prefix):
                env = dict(self.env, SteamAppId=appid, STEAM_COMPAT_DATA_PATH=prefix)
                self.assertIsNone(wrapper.game_id(['run', 'game.exe'], env))

    def test_invalid_conflicting_and_non_steam_ids_are_skipped(self):
        for appid in ('', '0', '-1', 'abc', str(2**63), '２７５８５０'):
            env = dict(self.env, SteamAppId=appid)
            self.assertIsNone(wrapper.game_id(['run', 'game.exe'], env))
        env = dict(self.env, STEAM_COMPAT_APP_ID='123')
        self.assertIsNone(wrapper.game_id(['run', 'game.exe'], env))

    def test_policy_overrides_and_fix_required_games(self):
        self.assertTrue(wrapper.wants_hdr('275850', self.catalog, {}))
        self.assertFalse(wrapper.wants_hdr('123', self.catalog, {}))
        for state in ('hackable', 'ambiguous', 'false'):
            self.catalog['games']['275850']['hdr'] = state
            self.assertFalse(wrapper.wants_hdr('275850', self.catalog, {}))
        self.assertTrue(wrapper.wants_hdr('123', self.catalog, {'AUTOHDR': '1'}))
        self.assertFalse(wrapper.wants_hdr('275850', self.catalog, {'AUTOHDR': '0'}))

    def test_matching_game_supervises_exact_bundled_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'share/proton-ge-hdr-toggler').mkdir(parents=True)
            (root / 'share/proton-ge-hdr-toggler/hdr-games.json').write_text(json.dumps(self.catalog))
            with patch.object(wrapper, 'ROOT', root), patch.dict(os.environ, self.env, clear=True), \
                 patch('runner.supervise', return_value=23) as supervise:
                self.assertEqual(wrapper.main(['waitforexitandrun', 'some game.exe', '--flag']), 23)
                supervise.assert_called_once_with([str(root / 'proton-real'), 'waitforexitandrun',
                                                   'some game.exe', '--flag'], monitor=None)

    def test_missing_catalog_passes_through_without_display_access(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(wrapper, 'ROOT', Path(temp)), \
             patch.dict(os.environ, self.env, clear=True), patch.object(wrapper.os, 'execv') as execute:
            wrapper.main(['run', 'game.exe'])
            execute.assert_called_once_with(str(Path(temp) / 'proton-real'),
                                           [str(Path(temp) / 'proton-real'), 'run', 'game.exe'])


def table(rows):
    content = '<table class="cargoTable"><tbody>'
    for title, state, appids in rows:
        content += '<tr>' + ''.join(f'<td class="{field}">{value}</td>' for field, value in
                    zip(('field__pageName', 'field_HDR', 'field_Steam_AppID'), (title, state, appids))) + '</tr>'
    return {'parse': {'text': {'*': content + '</tbody></table>'}}}


class CatalogTests(unittest.TestCase):
    def test_pagination_secondary_ids_and_mod_support_are_retained(self):
        offsets = []
        def fetch(url):
            text = parse_qs(urlparse(url).query)['text'][0]
            offsets.append(text)
            return table([('First &amp; Second', 'true', '10 <span>•</span> 11'),
                          ('Mod game', 'hackable', '12')] if len(offsets) == 1 else
                         [('Last game', 'limited', '13')])
        result = updater.fetch_catalog(fetch, limit=2)
        self.assertIn('offset=2', offsets[1])
        self.assertEqual(result['source_rows'], 3)
        self.assertEqual(result['games']['10']['title'], 'First & Second')
        self.assertEqual(result['games']['11']['hdr'], 'true')
        self.assertEqual(result['games']['12']['hdr'], 'hackable')

    def test_shared_ids_are_ambiguous(self):
        result = updater.fetch_catalog(lambda url: table([('Old', 'true', '10'), ('New', 'limited', '10')]))
        self.assertEqual(result['games']['10']['hdr'], 'ambiguous')

    def test_duplicate_joined_rows_are_deduplicated_but_conflicts_are_rejected(self):
        row = ('BeamNG.drive', 'true', '284160')
        result = updater.fetch_catalog(lambda url: table([row, row]))
        self.assertEqual(result['source_rows'], 1)
        self.assertEqual(result['games']['284160']['hdr'], 'true')
        with self.assertRaises(ValueError):
            updater.fetch_catalog(lambda url: table([row, ('BeamNG.drive', 'limited', '284160')]))

    def test_repeated_pages_and_error_pages_are_rejected(self):
        for response in (table([('Same', 'true', '10')]), {'parse': {'text': {'*': '<p>Permission denied</p>'}}}):
            with self.assertRaises(ValueError):
                updater.fetch_catalog(lambda url: response, limit=1)

    def test_release_requires_checksum_and_correct_architecture(self):
        data = {'tag_name': 'GE-Proton11-9', 'published_at': '2026-10-17T18:00:00Z', 'assets': [
            {'name': 'GE-Proton11-9-x86_64.tar.gz', 'browser_download_url':
             'https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton11-9/GE-Proton11-9-x86_64.tar.gz',
             'digest': 'sha256:' + 'a' * 64}]}
        self.assertEqual(updater.fetch_release(lambda url: data)['sha256'], 'a' * 64)
        data['assets'][0]['digest'] = None
        with self.assertRaises((ValueError, TypeError)):
            updater.fetch_release(lambda url: data)


class VersionTests(unittest.TestCase):
    def test_version_uses_page_edit_date_and_proton_version(self):
        info = updater.build_info(release(), revision())
        self.assertEqual(info['version'], '11-11-20260825')
        self.assertEqual(info['release_date'], '2026-10-19')
        self.assertEqual(info['hdr_page_revision'], 1795896)
        self.assertEqual(updater.build_info(release('GE-Proton11-1'),
                         revision('2026-10-23T23:59:59Z'))['version'], '11-1-20261023')

    def test_revision_query_and_invalid_revision(self):
        def fetch(url):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query['titles'], [updater.PAGE])
            self.assertEqual(query['rvlimit'], ['1'])
            return {'query': {'pages': [{'revisions': [{'revid': 1795896,
                                      'timestamp': '2026-08-25T16:22:25Z'}]}]}}
        self.assertEqual(updater.fetch_page_revision(fetch), revision())
        for page in ({'missing': True}, {'revisions': [{'revid': 0, 'timestamp': 'bad'}]},
                     {'revisions': [{'revid': 1, 'timestamp': '2026-02-30T00:00:00Z'}]}):
            with self.subTest(page=page), self.assertRaises(ValueError):
                updater.fetch_page_revision(lambda url: {'query': {'pages': [page]}})

    def test_refresh_detects_release_catalog_and_page_changes_without_daily_rebuilds(self):
        catalog = {'version': 1, 'source_rows': 100,
                   'games': {str(n): {'hdr': 'true'} for n in range(1, 101)}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'output'
            with patch.object(updater, 'MANIFEST', root / 'manifest.yml'), \
                 patch.object(updater, 'CATALOG', root / 'catalog.json'), \
                 patch.object(updater, 'BUILD_INFO', root / 'build-info.json'), \
                 patch.object(updater, 'fetch_release', return_value=release()) as ge, \
                 patch.object(updater, 'fetch_catalog', return_value=catalog), \
                 patch.object(updater, 'fetch_page_revision', return_value=revision()) as page, \
                 patch.dict(os.environ, GITHUB_OUTPUT=str(output)), patch.object(sys, 'argv', ['update.py']):
                def refresh(expected):
                    output.write_text('')
                    updater.main()
                    self.assertIn(f'changed={expected}\n', output.read_text())
                refresh('true')
                refresh('false')
                self.assertIn('version=11-11-20260825\n', output.read_text())
                ge.return_value = release('GE-Proton11-12')
                refresh('true')
                self.assertIn('version=11-12-20260825\n', output.read_text())
                catalog['games']['1']['hdr'] = 'limited'
                refresh('true')  # Game articles can change without editing the list page.
                refresh('false')
                page.return_value = revision('2026-10-23T12:00:00Z')
                refresh('true')
                self.assertIn('version=11-12-20261023\n', output.read_text())


class PackageTests(unittest.TestCase):
    def test_staged_tool_delegates_probe_preserving_argv_cwd_env_and_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original, destination = base / 'original', base / 'staged'
            original.mkdir()
            (original / 'files').mkdir()
            for arch in ('x86_64-linux-gnu', 'i386-linux-gnu'):
                libs = original / 'files/lib' / arch
                libs.mkdir(parents=True)
                (libs / 'libxkbcommon.so.0.9.2').write_bytes(b'upstream library fixture')
                (libs / 'libxkbcommon.so.0').symlink_to('libxkbcommon.so.0.9.2')
            (original / 'proton').write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_text(json.dumps([sys.argv[1:], os.getcwd(), os.environ['TEST_FLAG']]))
raise SystemExit(23)
''')
            (original / 'proton').chmod(0o755)
            for name in ('compatibilitytool.vdf', 'toolmanifest.vdf'):
                (original / name).write_text('upstream metadata')
            data = base / 'data'
            data.mkdir()
            (data / 'CATALOG-LICENSE.txt').write_text('PCGamingWiki attribution fixture')
            info = updater.build_info(release(), revision())
            (data / 'build-info.json').write_text(json.dumps(info))
            catalog = data / 'hdr-games.json'
            catalog.write_text(json.dumps({'version': 1, 'games': {'10': {'hdr': 'true'}},
                                           'source': updater.SOURCE, 'license_url': 'license'}))
            destination.mkdir()  # Flatpak Builder creates FLATPAK_DEST.
            staging.install(original, ROOT / 'src', ROOT / 'steam', data, destination, ROOT / 'LICENSE')
            for arch in ('x86_64-linux-gnu', 'i386-linux-gnu'):
                self.assertFalse((destination / 'files/lib' / arch / 'libxkbcommon.so.0').exists())
                self.assertEqual((destination / 'share/proton-ge-hdr-toggler/upstream-libs' / arch / 'libxkbcommon.so.0').read_bytes(),
                                 b'upstream library fixture')
                self.assertTrue((original / 'files/lib' / arch / 'libxkbcommon.so.0').exists())
            self.assertEqual((destination / 'toolmanifest.vdf.upstream').read_text(), 'upstream metadata')
            self.assertIn('proton-ge-hdr-toggler', (destination / 'compatibilitytool.vdf').read_text())
            self.assertIn('"proton-ge-hdr-toggler"', (destination / 'compatibilitytool.vdf').read_text())
            self.assertIn('"display_name" "proton-ge-hdr-toggler 11-11-20260825"',
                          (destination / 'compatibilitytool.vdf').read_text())
            metainfo = ET.parse(destination / 'share/metainfo' /
                                'com.valvesoftware.Steam.CompatibilityTool.proton-ge-hdr-toggler.metainfo.xml')
            self.assertEqual(metainfo.find('releases/release').attrib,
                             {'version': '11-11-20260825', 'date': '2026-10-19'})
            self.assertEqual(json.loads((destination / 'share/proton-ge-hdr-toggler/build-info.json').read_text()), info)
            installed = {str(path.relative_to(destination)) for path in destination.rglob('*') if path.is_file()}
            self.assertIn('lib/proton-ge-hdr-toggler/runner.py', installed)
            self.assertIn('share/proton-ge-hdr-toggler/hdr-games.json', installed)
            self.assertIn('share/licenses/proton-ge-hdr-toggler/PCGamingWiki.txt', installed)
            self.assertEqual((destination / 'share/licenses/proton-ge-hdr-toggler/LICENSE').read_bytes(),
                             (ROOT / 'LICENSE').read_bytes())
            self.assertFalse(any(path.endswith(('install.py', 'update.py', 'publish.py')) for path in installed))
            self.assertFalse(any(path.startswith(('scripts/', 'tests/', 'build-support/')) for path in installed))
            capture = base / 'capture.json'
            env = dict(os.environ, CAPTURE=str(capture), TEST_FLAG='preserved', AUTOHDR='1',
                       SteamAppId='275850', STEAM_COMPAT_DATA_PATH='/steam/compatdata/275850')
            args = ['run', '/bin/d3ddriverquery64.exe', 'argument with spaces', '"quoted"']
            result = subprocess.run([str(destination / 'proton'), *args], cwd=base, env=env, capture_output=True)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(json.loads(capture.read_text()), [args, str(base), 'preserved'])
            self.assertNotIn(b'HDR session', result.stderr)
            # Exercise the installed import paths and real supervisor with only
            # its display/session boundary replaced. Never call the desktop.
            (destination / 'lib/proton-ge-hdr-toggler/sessions.py').write_text(
                'class Sessions:\n'
                '    def acquire(self, monitor): return ("DP-test", {})\n'
                '    def release(self, lease): pass\n')
            result = subprocess.run([str(destination / 'proton'), 'waitforexitandrun', 'game.exe'],
                                    cwd=base, env=env, capture_output=True)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn(b'HDR session acquired for DP-test', result.stderr)
            self.assertIn(b'HDR session released', result.stderr)

    def test_repository_exposes_published_version_and_generates_appstream(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = root / 'repo'
            repository.mkdir()
            info = updater.build_info(release(), revision())
            source = root / 'build-info.json'
            source.write_text(json.dumps(info))
            arguments = ['publish.py', '--repository', str(repository), '--url', 'https://example.com/repo',
                         '--gpg-key', 'test-key', '--build-info', str(source)]
            with patch.object(sys, 'argv', arguments), patch.object(publisher.subprocess, 'run') as run, \
                 patch.object(publisher.subprocess, 'check_output', return_value=b'public-key'):
                publisher.main()
            self.assertNotIn('--no-update-appstream', run.call_args.args[0])
            self.assertEqual(json.loads((repository / 'build-info.json').read_text()), info)
            self.assertIn('DefaultBranch=stable', (repository / 'proton-ge-hdr-toggler.flatpakrepo').read_text())


if __name__ == '__main__':
    unittest.main()
