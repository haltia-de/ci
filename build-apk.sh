#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Build and sign one repository's Alpine package, inside an alpine:3.24
# container (the release workflow runs it; by hand:
#   docker run --rm -v "$PWD:/src" -v /path/to/b8k-ci:/ci -e B8K_APK_PRIVKEY="$(cat key)" \
#     alpine:3.24 sh /ci/build-apk.sh
# ). /src is the repository at its tag, /ci this repository. The package's
# own b8k dependencies (py3-b8k-compat, ...) come from their latest GitHub
# release, the rest from Alpine. Output: /src/out/*.apk.
set -eu
KEYNAME=trudenboy-b8k-6ad4bb12
apk add -q --no-cache alpine-sdk wget
mkdir -p /root/.abuild /src/out
printf '%s\n' "${B8K_APK_PRIVKEY:?the signing key}" >/root/.abuild/$KEYNAME.rsa
chmod 600 /root/.abuild/$KEYNAME.rsa
cp /ci/keys/$KEYNAME.rsa.pub /root/.abuild/
cp /ci/keys/$KEYNAME.rsa.pub /etc/apk/keys/
echo "PACKAGER_PRIVKEY=/root/.abuild/$KEYNAME.rsa" >/root/.abuild/abuild.conf
echo 'PACKAGER="trudenboy b8k <noreply@github.com>"' >>/root/.abuild/abuild.conf

work=/tmp/pkg/packaging
mkdir -p "$work"
cp -r /src/packaging/alpine/. "$work/"
cd "$work"
# Everything the package needs to build and test: Alpine's packages one by
# one (a missing one is reported), ours from their releases.
deps=$( set +u; srcdir=/tmp/src pkgdir=/tmp/pkgdir startdir=$PWD; . ./APKBUILD; echo $depends $makedepends $checkdepends )
for d in $deps; do
	case $d in
		py3-b8k-*|b8k-*)
			repo=${d#py3-}
			url=$(wget -qO- "https://api.github.com/repos/trudenboy/$repo/releases/latest" |
				sed -n 's/.*"browser_download_url": *"\([^"]*\.apk\)".*/\1/p' | head -1)
			if [ -n "$url" ]; then
				wget -q -O "/tmp/${url##*/}" "$url" && apk add -q "/tmp/${url##*/}"
			else
				echo "build-apk: no release of $repo for $d" >&2
			fi ;;
		*)
			apk add -q --no-cache "$d" || echo "build-apk: $d not in Alpine" >&2 ;;
	esac
done
abuild -F checksum
abuild -F -d -P /tmp/repo
find /tmp/repo -name '*.apk' -exec cp {} /src/out/ \;
cd /src/out
sha256sum ./*.apk | sed 's| \./| |' >SHA256SUMS
cat SHA256SUMS
