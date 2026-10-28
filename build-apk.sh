#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Build one repository's Alpine package, inside an alpine:3.24 container
# (the release workflow runs it; by hand:
#   docker run --rm -v "$PWD:/src" -v /path/to/b8k-ci:/ci alpine:3.24 sh /ci/build-apk.sh
# ). /src is the repository at its tag, /ci this repository. The package's
# own dependencies (py3-haltia-kit, ...) come from the Haltia apk
# repository, the rest from Alpine. Output: /src/out/*.apk, signed with a
# throwaway key: the build runs the repository's code (APKBUILD, check()),
# so the organisation key never comes near it. sign-apk.sh, in a job that
# runs no repository code, signs them again with the organisation key.
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
echo 'PACKAGER="trudenboy b8k <noreply@github.com>"' >/root/.abuild/abuild.conf
# As root: no doas to install the public key with.
SUDO= abuild-keygen -a -i -n -q

work=/tmp/pkg/packaging
mkdir -p "$work"
cp -r /src/packaging/alpine/. "$work/"
cd "$work"
# Bytecode. A program's Python is installed root-owned (/usr/lib/<name>,
# site-packages, unpacked wheels), so the session user can never write
# its __pycache__, and every start compiled every module again. A package
# that depends on python3 therefore ships its modules compiled: the
# APKBUILD's package() runs as written, then compileall goes over all of
# $pkgdir with this container's python3, which is the target's (Alpine
# 3.24, the architecture built). The .pyc land beside their modules in
# the same package, root-owned like the rest; an APKBUILD with a -pyc
# subpackage (default_pyc) still moves site-packages' into it. They are
# checked-hash: abuild sets every file's mtime to SOURCE_DATE_EPOCH after
# package(), which a timestamp .pyc would never match, and a module edited
# on the device is still noticed (hashing the source costs far less than
# compiling it). -s/-p record the installed path for tracebacks. A module
# that does not compile fails the build. Python never caches the
# extensionless script in /usr/bin it is started by.
if grep -q '^package()' APKBUILD; then
	sed -i 's/^package()/_haltia_package()/' APKBUILD
	cat >>APKBUILD <<'EOF'

# Added by haltia-de/ci's build-apk.sh: the package's Python, compiled.
package() {
	_haltia_package "$@" || return 1
	local _d
	for _d in $depends; do
		case $_d in
		python3|python3[\<\>=~]*)
			msg "Compiling the package's Python modules"
			python3 -m compileall -q -j0 --invalidation-mode checked-hash \
				-s "$pkgdir" -p / "$pkgdir" || return 1
			return 0 ;;
		esac
	done
}
EOF
fi
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
ls -l /src/out
