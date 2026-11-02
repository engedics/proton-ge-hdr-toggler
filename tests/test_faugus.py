"""Faugus adapter contracts; no desktop changes, downloads or real prefixes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load('faugus_adapter', 'src/faugus.py')
installer = load('faugus_installer', 'scripts/faugus.py')
from runner import supervise
from sessions import Sessions


def distribution(path):
    (path / 'files/bin').mkdir(parents=True)
    (path / 'files/bin/wine').write_text('shared binary fixture')
    (path / 'protonfixes').mkdir()
    (path / 'proton-real').write_text('#!/bin/sh\nexit 0\n')
    (path / 'proton-real').chmod(0o755)
    (path / 'toolmanifest.vdf.upstream').write_text('"manifest"\n{\n'
        '"commandline" "/proton %verb%"\n"require_tool_appid" "4183110"\n'
        '"compatmanager_layer_name" "proton"\n}\n')
    (path / 'toolmanifest.vdf').write_text('Steam-only manifest')
    data = path / 'share/proton-ge-hdr-toggler'
    data.mkdir(parents=True)
    (data / 'hdr-games.json').write_text(json.dumps({'games': {
        '10': {'hdr': 'true'}, '11': {'hdr': 'hackable'}}}))
    return path


class Display:
    def __init__(self, path, color=0):
        self.path, self.color = path, color

    def snapshot(self, connector=None):
        return {'connector': connector or 'DP-test', 'original_color': self.color, 'changed': self.color != 1}

    def enable(self, saved):
        self.color = 1
        self.path.write_text('HDR')

    def restore(self, saved):
        self.color = saved['original_color']
        self.path.write_text('HDR' if self.color == 1 else 'SDR')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = distribution(self.root / 'deployments/commit-one/files')
        self.active = self.root / 'deployments/active'
        self.active.symlink_to('commit-one', target_is_directory=True)
        self.destination = self.root / 'Steam/compatibilitytools.d/ProtonGEHDR'
        installer.install(self.active / 'files', self.destination)
        self.umu = self.root / 'umu-run'
        self.umu.write_text('''#!/usr/bin/env python3
import json, os, signal, sys
from pathlib import Path
if os.environ.get('CHECK_HDR'):
    assert Path(os.environ['CHECK_HDR']).read_text() == 'HDR'
Path(os.environ['CAPTURE']).write_text(json.dumps({
    'args': sys.argv[1:], 'cwd': os.getcwd(),
    'env': {key: os.environ.get(key) for key in (
        'WINEPREFIX', 'GAMEID', 'STORE', 'PROTONPATH', 'PROTON_VERB',
        'STEAM_COMPAT_APP_ID', 'SteamAppId', 'FAUGUSID', 'TEST_FLAG', 'STEAM_COMPAT_LIBRARY_PATHS')}}))
if os.environ.get('CRASH'): os.kill(os.getpid(), signal.SIGTERM)
raise SystemExit(23)
''')
        self.umu.chmod(0o755)
        self.env = dict(os.environ, AUTOHDR_UMU=str(self.umu), CAPTURE=str(self.root / 'capture'),
                        WINEPREFIX=str(self.root / 'game prefix'), GAMEID='umu-example', STORE='gog',
                        STEAM_COMPAT_APP_ID='prefix-hash', SteamAppId='0', FAUGUSID='custom-game',
                        TEST_FLAG='preserved', STEAM_COMPAT_LIBRARY_PATHS='/keep/mounted')
        for key in ('AUTOHDR', 'AUTOHDR_APPID', 'CHECK_HDR', 'CRASH'):
            self.env.pop(key, None)

    def test_backend_links_original_proton_and_manifest_and_pins_updates(self):
        backend = adapter.prepare_backend(self.destination, self.source)
        self.assertEqual((backend / 'proton').resolve(), self.source / 'proton-real')
        self.assertEqual((backend / 'toolmanifest.vdf').read_text(),
                         (self.source / 'toolmanifest.vdf.upstream').read_text())
        self.assertTrue((backend / 'files').is_symlink())
        self.assertEqual(adapter.prepare_backend(self.destination, self.source), backend)
        second = distribution(self.root / 'deployments/commit-two/files')
        self.active.unlink()
        self.active.symlink_to('commit-two', target_is_directory=True)
        config = json.loads((self.destination / adapter.CONFIG).read_text())
        self.assertEqual(adapter.source_root(config), second)
        new_backend = adapter.prepare_backend(self.destination, adapter.source_root(config))
        self.assertNotEqual(new_backend, backend)
        self.assertEqual((backend / 'proton').resolve(), self.source / 'proton-real')

    def test_umu_environment_arguments_working_directory_and_exit_are_preserved(self):
        result = subprocess.run([sys.executable, str(self.destination / 'proton'), 'runinprefix',
                                 'game.exe', 'argument with spaces', '"quoted"'],
                                env=dict(self.env, AUTOHDR='0'), cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 23, result.stderr)
        captured = json.loads((self.root / 'capture').read_text())
        self.assertEqual(captured['args'], ['game.exe', 'argument with spaces', '"quoted"'])
        self.assertEqual(captured['cwd'], str(self.root))
        for key in ('WINEPREFIX', 'GAMEID', 'STORE', 'STEAM_COMPAT_APP_ID', 'SteamAppId', 'FAUGUSID', 'TEST_FLAG'):
            self.assertEqual(captured['env'][key], self.env[key])
        self.assertEqual(captured['env']['PROTON_VERB'], 'runinprefix')
        self.assertIn('/keep/mounted:', captured['env']['STEAM_COMPAT_LIBRARY_PATHS'])
        self.assertNotEqual(captured['env']['PROTONPATH'], 'GE-Proton')

    def test_hdr_precedes_inner_umu_and_restores_after_exit_or_child_signal(self):
        display = Display(self.root / 'display')
        sessions = Sessions(self.root / 'state', display)
        for crash, expected in (('', 23), ('1', 143)):
            with self.subTest(crash=crash), patch.object(adapter, 'ROOT', self.destination), \
                 patch.dict(os.environ, dict(self.env, CHECK_HDR=str(display.path), CRASH=crash), clear=True), \
                 patch.object(adapter, 'supervise', side_effect=lambda command, **kw:
                              supervise(command, sessions=sessions, **kw)):
                self.assertEqual(adapter.main(['waitforexitandrun', 'game.exe']), expected)
                self.assertEqual(display.path.read_text(), 'SDR')
                self.assertEqual(json.loads(sessions.path.read_text())['monitors'], {})

    def test_hdr_policy_supports_zero_appid_catalog_and_tool_exclusions(self):
        args = ['waitforexitandrun', 'game.exe']
        self.assertTrue(adapter.hdr_enabled(args, self.source, {'SteamAppId': '0'}))
        self.assertFalse(adapter.hdr_enabled(args, self.source, {'AUTOHDR': '0'}))
        self.assertTrue(adapter.hdr_enabled(args, self.source, {'AUTOHDR_APPID': '10'}))
        self.assertFalse(adapter.hdr_enabled(args, self.source, {'AUTOHDR_APPID': '11'}))
        self.assertFalse(adapter.hdr_enabled(args, self.source, {'AUTOHDR_APPID': 'unknown'}))
        for target in ('', 'createprefix', 'winetricks', r'C:\windows\system32\wineboot.exe', 'd3ddriverquery64.exe'):
            self.assertFalse(adapter.hdr_enabled(['run', target], self.source, {'AUTOHDR': '1'}))

    def test_unavailable_proton_or_umu_never_enables_hdr_or_downloads_a_runner(self):
        with patch.object(adapter, 'ROOT', self.destination), patch.dict(os.environ, self.env, clear=True), \
             patch.object(adapter, 'supervise') as supervise_mock:
            self.umu.unlink()
            self.assertEqual(adapter.main(['run', 'game.exe']), 127)
            (self.source / 'files/bin/wine').unlink()
            self.assertEqual(adapter.main(['run', 'game.exe']), 127)
            supervise_mock.assert_not_called()
        self.assertFalse((self.root / 'capture').exists())

    def test_install_and_removal_are_idempotent_and_do_not_touch_proton(self):
        original = (self.source / 'proton-real').read_bytes()
        installer.install(self.active / 'files', self.destination)
        self.assertEqual((self.source / 'proton-real').read_bytes(), original)
        self.assertFalse((self.destination / 'files').exists())
        self.assertIn('umu-passthrough', (self.destination / 'toolmanifest.vdf').read_text())
        self.assertNotIn('require_tool_appid', (self.destination / 'toolmanifest.vdf').read_text())
        self.assertIsNotNone(installer.remove(self.destination))
        self.assertIsNone(installer.remove(self.destination))
        self.destination.mkdir()
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            installer.remove(self.destination)
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            installer.install(self.source, self.destination)

    def test_permissions_cover_only_runner_deployment_and_mutter(self):
        command = installer.permission_commands(self.active / 'files', self.destination)
        self.assertIn(f'--filesystem={self.active.parent}:ro', command)
        self.assertIn(f'--filesystem={self.destination}', command)
        self.assertIn('--talk-name=org.gnome.Mutter.DisplayConfig', command)
        self.assertNotIn('--filesystem=home', command)
        self.assertNotIn('--talk-name=org.freedesktop.Flatpak', command)

    def test_default_destination_matches_faugus_without_changing_its_steam_preference(self):
        home = self.root / 'home'
        flatpak = home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        flatpak.mkdir(parents=True)
        with patch.object(installer.Path, 'home', return_value=home), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(installer.default_destination(), flatpak / 'compatibilitytools.d/ProtonGEHDR')
            native = home / '.local/share/Steam'
            native.mkdir(parents=True)
            self.assertEqual(installer.default_destination(), native / 'compatibilitytools.d/ProtonGEHDR')

    def test_bundled_installer_contains_only_adapter_sources_and_documentation(self):
        target = self.root / 'adapter.tar.gz'
        installer.bundle(target)
        with tarfile.open(target) as archive:
            names = archive.getnames()
            archive.extractall(self.root / 'extracted', filter='data')
        self.assertIn('ProtonGEHDR-faugus/src/sessions.py', names)
        self.assertIn('ProtonGEHDR-faugus/docs/FAUGUS.md', names)
        self.assertFalse(any('/files/' in name or '/.backends/' in name for name in names))
        script = self.root / 'extracted/ProtonGEHDR-faugus/scripts/faugus.py'
        destination = self.root / 'from-bundle'
        result = subprocess.run([sys.executable, str(script), 'install', '--proton', str(self.source),
                                 '--destination', str(destination)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(destination / 'proton'), 'run', 'game.exe'],
                                env=dict(self.env, AUTOHDR='0'), capture_output=True)
        self.assertEqual(result.returncode, 23, result.stderr)


if __name__ == '__main__':
    unittest.main()
