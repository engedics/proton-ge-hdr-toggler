# GitHub publishing

The workflow checks GE releases and PCGamingWiki daily, rebuilds when inputs
change, publishes a signed Flatpak repository through Pages, and commits the
updated manifest/catalog. Source pushes and manual dispatch also build it.

The display name is **Proton-GE HDR**. Its Flatpak ID is
`com.valvesoftware.Steam.CompatibilityTool.Proton-GE-HDR`; the existing repository
URL, remote name, Steam tool ID and runtime data paths remain unchanged.
Existing users migrate using the reinstall commands in the README. Publish the
new ID before running those commands; the rename is not an automatic rebase.

`data/release-notes.json` retains the five most recent distinct versions.
The updater compares the catalog with the last committed published catalog and
records added/removed AppIDs, HDR support changes and title changes. Proton-GE
updates include the latest upstream release body's notes and a link to that
release. Skipped upstream releases are available through upstream's release
history. Unchanged refreshes preserve existing notes and do not trigger builds.
When successive catalog changes share a version, that version's notes describe
the latest update. Keep manual packaging notes in the current entry's
`paragraphs` when publishing a source-only change.

The installer converts this history to AppStream release descriptions and
escapes upstream text. Flatpak Builder must be at least 1.3.4 so extension
metadata is composed into `share/app-info/xmls`; its host must also have the
AppStream compose tools installed. Publication generates the repository's
AppStream branch for software stores. The workflow checks the composed catalog
before deploying, including its name, component ID and release notes.

Versions use `PROTON_VERSION-YYYYMMDD`, taking the date from the HDR list page's
latest MediaWiki revision, not the download date. Game article edits can change
the catalog without changing that date; catalog changes still trigger a build.
The version appears in Flatpak's AppStream metadata, Steam's display name, the
build/deploy job and artifact names, and the repository's `build-info.json`.
Steam's internal tool ID and Flatpak's `stable` branch stay fixed across updates.
The Pages environment remains `github-pages`; unchanged scheduled checks do not
create deployment entries. The workflow summary explains whether it built or skipped.

1. Push to a GitHub repository whose default branch is `main`.
2. Set **Settings → Pages → Source** to **GitHub Actions**.
3. Generate a dedicated unattended signing key and keep a backup:

   ```sh
   gpg --batch --passphrase '' --quick-generate-key 'proton-ge-hdr-toggler repository <you@example.com>' rsa3072 sign 0
   gpg --list-secret-keys --keyid-format long
   gpg --armor --export-secret-keys YOUR_FULL_FINGERPRINT > /tmp/flatpak-signing-key.asc
   ```

4. Add repository secrets `FLATPAK_GPG_PRIVATE_KEY` (the exported text) and
   `FLATPAK_GPG_KEY_ID` (the full fingerprint). Remove the temporary export.
5. Allow the workflow to write contents and deploy to the `github-pages`
   environment. Branch protection must permit its automated commit.
6. Run **Update and publish proton-ge-hdr-toggler** manually once. Then use
   the Pages URL in the README's install commands.

Public repositories can use standard hosted runners for free. GitHub Free
Pages hosting requires a public repository. For a dedicated self-hosted Linux
runner, set repository variable `FLATPAK_RUNNER` to its label and preinstall
Flatpak, flatpak-builder, Python 3, PyGObject and GnuPG. Other runners need the
equivalent dependencies; the workflow's automatic package installation uses APT.

The signing key remains stable across releases. Pages permits a 1 GB site;
the workflow checks size before deployment and retains the previous deployment
on failure. The initial repository is about 556 MB. Deployment artifacts have
one-day retention; artifact storage has its own quota. Enable automatic Flatpak
updates on client machines. GitHub can disable schedules after 60 inactive days.

## Repository layout

- `src/`: installed Python entry point, supervision, display client and journal.
- `steam/`: installed Steam compatibility-tool manifests.
- `data/`: installed HDR catalog and its attribution.
- `flatpak/`: canonical Flatpak Builder manifest; upstream archive URL/checksum.
- `scripts/`: build-only updater, installer and publication support.
- `tests/`: tests using fake displays and a fake Proton payload.

Only the Proton distribution and explicitly selected runtime files are
installed. The installation prefix uses `lib/proton-ge-hdr-toggler` for Python
modules, `share/proton-ge-hdr-toggler` for catalog data and
`share/licenses/proton-ge-hdr-toggler` for catalog attribution. Build scripts,
source downloads, tests and workflow files stay outside the extension.

The entry point excludes Steam's prerequisite evaluator from HDR activation.
The installer moves GE's conflicting xkbcommon libraries outside its loader
path, allowing Flatpak's matching SDL3/xkbcommon pair to handle controllers.
Upstream manifests and moved libraries remain available for reference. The
legacy state-journal directory is retained so older sessions remain recoverable.

Run checks with `python3 -m unittest discover -s tests -v`; they do not change
the physical display. Controller and actual HDR presentation need desktop tests.
Game overrides remain `AUTOHDR=0 %command%`, `AUTOHDR=1 %command%`, and
`AUTOHDR_MONITOR=DP-3 %command%`. Mod-only catalog entries require explicit opt-in.
