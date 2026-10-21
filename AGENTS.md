# ci

The shared release machinery of the Haltia repositories (ADR 0002 and 0004,
and `docs/plans/desktop-packages.md`, in
[haltia-de/haltia](https://github.com/haltia-de/haltia)). On a `vX.Y.Z` tag
of a calling repository it checks that the versions in its files are the
tag's, builds the packages and puts them with their checksums into the
GitHub release of the tag. [haltia-de/packages](https://github.com/haltia-de/packages)
then files them into the signed package repositories. This repository is
not a program and has no program id.

## Layout

- `.github/workflows/apk.yml`: reusable workflow; checks `pkgver`/`pkgrel=0`
  in `packaging/alpine/APKBUILD`, the release in `data/*.metainfo.xml`, the
  version in `pyproject.toml`, and the metainfo against `NEWS.md`; builds
  the Alpine 3.24 package (`noarch`, or `armv7`, `aarch64`, `x86_64`)
  without secrets, signs it in a separate job that runs only this
  repository, and uploads it with `SHA256SUMS`. Needs the organization
  secret `B8K_APK_PRIVKEY`.
- `.github/workflows/deb.yml`: builds `debian/` in Ubuntu noble, Ubuntu
  resolute and Debian trixie, checks `debian/changelog` against the tag,
  runs lintian, uploads with `SHA256SUMS.deb`.
- `.github/workflows/flatpak.yml`: builds a Flatpak manifest in Flathub's
  GNOME image, uploads the bundle with `SHA256SUMS.flatpak`.
- `build-apk.sh`: the Alpine build inside an `alpine:3.24` container; the
  header shows how to run it by hand with `docker run`. It signs with a
  throwaway key: the build runs the caller's code.
- `sign-apk.sh`: replaces that signature with the organization key's,
  inside an `alpine:3.24` container, without running anything of the
  package.
- `news.py`: `NEWS.md` (Russian and English) to the metainfo `<releases>`;
  `python3 news.py metainfo NEWS.md data/X.metainfo.xml [--check]` and
  `python3 news.py bootstrap data/X.metainfo.xml > NEWS.md`.
- `keys/`: the public key the packages are signed with.

The header comment of each workflow shows how a repository calls it from
its own `.github/workflows/release.yml`; `README.md` (Russian) has the
version policy and the `NEWS.md` format.

## How callers use it

Callers use the workflows by the moving tag `v1`
(`uses: haltia-de/ci/.github/workflows/apk.yml@v1`), and `apk.yml` checks
out this repository at `v1` for `build-apk.sh`, `news.py` and `keys/`. A
change here reaches the callers only when `v1` moves.

## Releases

Moving `v1` is a release: it changes the release of every Haltia
repository at once, and it needs the user's approval. Never move or create
tags without it.

## Conventions

Follow the shared rules in
[docs/conventions.md](https://github.com/haltia-de/haltia/blob/main/docs/conventions.md)
in haltia-de/haltia. Here: workflow logic and comments in English,
`README.md` in Russian, `*.sh` and `*.py` with LF line endings, commit
subjects as full English sentences.
