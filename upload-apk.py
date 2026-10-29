#!/usr/bin/env python3
"""Upload immutable packages; only the APK aggregate checksum may change."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote


def gh(*args):
    return subprocess.check_output(['gh', *args])


def api(path):
    return json.loads(gh('api', path))


def pages(path):
    result = []
    for page in range(1, 1001):
        batch = api(f'{path}?per_page=100&page={page}')
        if not isinstance(batch, list):
            raise ValueError('Incomplete API list')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError('API pagination did not finish')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def assets(repo, release):
    found = {}
    for asset in pages(f'repos/{repo}/releases/{release}/assets'):
        name = asset['name']
        sha = asset['digest']
        if (not isinstance(name, str) or not name or name in found
                or asset['state'] != 'uploaded'
                or not isinstance(sha, str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', sha)):
            raise ValueError('Incomplete or conflicting asset metadata')
        found[name] = (sha[7:], asset['id'])
    return found


def sums(data):
    result = {}
    for line in data.decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\\s]+)', line)
        if not match or match[2] in result:
            raise ValueError('Invalid SHA256SUMS')
        result[match[2]] = match[1]
    return result


def upload(tag, name):
    args = ['release', 'upload', tag, name]
    if name == 'SHA256SUMS':
        args.append('--clobber')
    try:
        gh(*args)
    except subprocess.CalledProcessError:
        print(f'Upload of {name} answered an error; waiting for visibility')


def run(repo, tag, commit, append, format="apk"):
    if format not in ("apk", "deb", "flatpak") or (append and format != "apk"):
        raise ValueError("Only APK supports architecture append")
    checksum = "SHA256SUMS" if format == "apk" else f"SHA256SUMS.{format}"
    suffix = f".{format}"
    # Resolve annotated as well as lightweight tags to the actual source commit.
    actual = api(f'repos/{repo}/commits/{quote(tag, safe="")}')['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or actual != commit:
        raise ValueError('Release tag does not match the build commit')
    releases = pages(f'repos/{repo}/releases')
    matches = [r for r in releases if r['tag_name'] == tag]
    if len(matches) > 1:
        raise ValueError('Duplicate release metadata')
    if not matches:
        if append:
            raise ValueError('Append requires an existing release')
        gh('release', 'create', tag, '--verify-tag', '--title', tag, '--generate-notes')
        release = api(f'repos/{repo}/releases/tags/{quote(tag, safe="")}')['id']
    else:
        release = matches[0]['id']
    have = assets(repo, release)
    old = {}
    if checksum in have:
        sha, asset_id = have[checksum]
        data = gh('api', '-H', 'Accept: application/octet-stream',
                  f'repos/{repo}/releases/assets/{asset_id}')
        if digest(data) != sha:
            raise ValueError('SHA256SUMS download does not match its digest')
        old = sums(data)
    for name, sha in old.items():
        if name not in have or have[name][0] != sha:
            raise ValueError(f'Existing checksum disagrees with asset: {name}')
    local = {p.name: digest(p.read_bytes()) for p in sorted(Path('.').glob(f'*{suffix}'))
             if p.name != checksum}
    if not local:
        raise ValueError('No packages to upload')
    if format != 'apk':
        existing = {n for n in have if n.endswith(suffix) and n != checksum}
        if existing and existing != set(local):
            raise ValueError('Existing package set differs; append is APK-only')
    # Complete every consistency check before the first package write.
    for name, sha in local.items():
        if name in have and have[name][0] != sha:
            raise ValueError(f'Immutable package differs: {name}')
        if name in old and old[name] != sha:
            raise ValueError(f'Existing checksum differs: {name}')
    if format == 'apk':
        merged = dict(old)
        # Retain APK digests even if an earlier run never wrote its sums.
        merged.update({n: v[0] for n, v in have.items() if n.endswith('.apk')})
        merged.update(local)
    else:
        merged = local
    Path(checksum).write_text(''.join(f'{merged[n]}  {n}\n' for n in sorted(merged)))
    expected = dict(local)
    expected[checksum] = digest(Path(checksum).read_bytes())
    if format != 'apk' and checksum in have and have[checksum][0] != expected[checksum]:
        raise ValueError(f'Immutable checksum differs: {checksum}')
    pending = {n: sha for n, sha in expected.items()
               if n not in have or have[n][0] != sha}
    for name in pending:
        upload(tag, name)
    for attempt in range(1, 41):
        try:
            visible = assets(repo, release)
        except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
            # A failed/incomplete response never authorizes a retry upload.
            visible = None
        if visible is not None:
            missing = [n for n, sha in expected.items()
                       if n not in visible or visible[n][0] != sha]
            if not missing:
                return
            for name in missing:
                if name in visible and name != 'SHA256SUMS':
                    raise ValueError(f'Immutable asset differs after upload: {name}')
                if attempt in (10, 20) and name not in visible:
                    upload(tag, name)
        time.sleep(15)
    raise ValueError('Release digests not verified after 10 minutes')


if __name__ == '__main__':
    run(os.environ['GH_REPO'], os.environ['TAG'], os.environ['BUILD_COMMIT'],
        os.environ.get('APPEND') == 'true', os.environ.get('PACKAGE_FORMAT', 'apk'))
