#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Build and sign one repository's Alpine package, inside an alpine:3.24
# container (the release workflow runs it; by hand:
#   docker run --rm -v "$PWD:/src" -v /path/to/b8k-ci:/ci -e B8K_APK_PRIVKEY="$(cat key)" \
#     alpine:3.24 sh /ci/build-apk.sh
# ). /src is the repository at its tag, /ci this repository. The package's
# own dependencies (py3-haltia-kit, ...) come from the Haltia apk
# repository, the rest from Alpine. Output: /src/out/*.apk.
set -eu
KEYNAME=trudenboy-b8k-6ad4bb12
# The architecture asked for (the workflow's WANT_ARCH) must be the one
# this container runs: a wrong image would build the wrong package.
have=$(apk --print-arch)
case ${WANT_ARCH:-} in
	''|noarch) ;;
	"$have") ;;
	*) echo "build-apk: asked for $WANT_ARCH, the container is $have" >&2; exit 1 ;;
esac
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
# Everything the package needs to build and test, one by one (a missing
# one is reported): Alpine's, and ours from the Haltia apk repository
# (haltia-de/packages), which has every released package for this
# architecture under its plain name.
cp /ci/keys/$KEYNAME.rsa.pub /etc/apk/keys/haltia-de-6ad4bb12.rsa.pub
echo https://haltia-de.github.io/packages/alpine/v3.24 >>/etc/apk/repositories
apk update -q || echo "build-apk: the Haltia repository is not reachable" >&2
deps=$( set +u; srcdir=/tmp/src pkgdir=/tmp/pkgdir startdir=$PWD; . ./APKBUILD; echo $depends $makedepends $checkdepends )
for d in $deps; do
	apk add -q "$d" || echo "build-apk: $d not in Alpine or Haltia" >&2
done
abuild -F checksum
abuild -F -d -P /tmp/repo
# One release holds the packages of several architectures: armv7 and
# noarch keep the plain name, the others carry theirs (name.aarch64.apk),
# so they do not overwrite each other. The apk repository files them
# under the plain name again.
for f in $(find /tmp/repo -name '*.apk'); do
	arch=$(tar -xzOf "$f" .PKGINFO 2>/dev/null | sed -n 's/^arch = //p' | head -1)
	base=${f##*/}
	case $arch in
		armv7|noarch|'') cp "$f" "/src/out/$base" ;;
		*) cp "$f" "/src/out/${base%.apk}.$arch.apk" ;;
	esac
done
cd /src/out
sha256sum ./*.apk | sed 's| \./| |' >SHA256SUMS
cat SHA256SUMS
