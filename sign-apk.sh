#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Sign the packages of build-apk.sh with the organisation key, inside an
# alpine:3.24 container that already has abuild, tar and python3 (the
# release workflow runs it; by hand:
#   docker run --name b8k-sign alpine:3.24@sha256:71e9b7bae160ba167fa17414401b94cbcdaf3c32feeab9298bd794a2a0614c35 apk add -q --no-cache abuild tar python3
#   docker commit b8k-sign b8k-sign
#   docker run --rm --network none -v "$PWD/unsigned:/in" -v "$PWD/out:/out" \
#     -v /path/to/b8k-ci:/ci -e B8K_APK_PRIVKEY="$(cat key)" b8k-sign sh /ci/sign-apk.sh
# ). The tools are installed before the key is there: nothing from the
# network runs next to it. It runs nothing of the packages: an apk is
# three gzip streams, the signature, the control (.PKGINFO) and the data,
# and abuild signs the control stream. This drops the build's throwaway
# signature, signs the control stream with abuild-sign as abuild does and
# joins the three again. Output: /out/*.apk, under the names of /in.
set -eu
KEYNAME=trudenboy-b8k-6ad4bb12
for t in abuild-sign python3 tar; do
	command -v $t >/dev/null || { echo "sign-apk: no $t: install abuild tar python3 first, without the key" >&2; exit 1; }
done
mkdir -p /root/.abuild /out
(umask 077; printf '%s\n' "${B8K_APK_PRIVKEY:?the signing key}" >/root/.abuild/$KEYNAME.rsa)
cp /ci/keys/$KEYNAME.rsa.pub /root/.abuild/
cp /ci/keys/$KEYNAME.rsa.pub /etc/apk/keys/
work=/tmp/sign
for f in /in/*.apk; do
	[ -e "$f" ] || { echo "sign-apk: no packages in /in" >&2; exit 1; }
	rm -rf "$work"
	mkdir -p "$work"
	python3 -I - "$f" "$work" <<'EOF'
import sys, zlib

src, work = sys.argv[1], sys.argv[2]
data = open(src, "rb").read()


def stream(start):
    """The unpacked gzip stream at start and where it ends."""
    z = zlib.decompressobj(31)
    text = z.decompress(data[start:])
    if not z.eof:
        sys.exit(f"sign-apk: {src}: a broken gzip stream")
    return text, len(data) - len(z.unused_data)


sig, control_start = stream(0)
control, data_start = stream(control_start)
# abuild's tar writes a PaxHeaders entry before each file.
if b".SIGN." not in sig[:1024] or b".PKGINFO" not in control[:1024]:
    sys.exit(f"sign-apk: {src} is not a signed apk (signature, control, data)")
with open(f"{work}/control.tar.gz", "wb") as out:
    out.write(data[control_start:data_start])
with open(f"{work}/data.tar.gz", "wb") as out:
    out.write(data[data_start:])
EOF
	abuild-sign -q -k /root/.abuild/$KEYNAME.rsa "$work/control.tar.gz"
	cat "$work/control.tar.gz" "$work/data.tar.gz" >"/out/${f##*/}"
	apk verify -q "/out/${f##*/}"
done
rm -f /root/.abuild/$KEYNAME.rsa
ls -l /out
