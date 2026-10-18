#!/usr/bin/env python3
"""Finish a signed Flatpak repository for GitHub Pages."""
import argparse
import base64
from pathlib import Path
import subprocess

NAME = 'proton-ge-hdr-toggler'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--gpg-key', required=True)
    args = parser.parse_args()
    if not args.url.startswith('https://') or any(char in args.url for char in '\r\n'):
        parser.error('repository URL must use HTTPS')
    subprocess.run(['flatpak', 'build-update-repo', '--no-update-appstream', '--prune',
                    '--prune-depth=0', '--title=' + NAME, '--gpg-sign=' + args.gpg_key,
                    str(args.repository)], check=True)
    public_key = subprocess.check_output(['gpg', '--export', args.gpg_key])
    if not public_key:
        raise ValueError('Signing key has no public key')
    (args.repository / (NAME + '.flatpakrepo')).write_text(
        '[Flatpak Repo]\nTitle=' + NAME + '\nUrl=' + args.url.rstrip('/') +
        '\nDefaultBranch=stable\nGPGKey=' + base64.b64encode(public_key).decode() + '\n')
    (args.repository / '.nojekyll').touch()
    size = sum(path.stat().st_size for path in args.repository.rglob('*') if path.is_file())
    if size >= 1_000_000_000:
        raise ValueError('Repository exceeds GitHub Pages capacity; retaining previous deployment')
    print(f'Repository: {size / 1_000_000:.1f} MB')


if __name__ == '__main__':
    main()
