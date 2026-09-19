#!/usr/bin/env python3
"""Build a deterministic source archive from reviewed tracked working-tree files.

Never reads .env, local runtime data or historical Git blobs. No network access,
Git-history rewriting or publication. New public files must be staged first.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit
import zlib

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = 'Jev-Radar'
MAX_FILE_BYTES = 4 * 1024 * 1024
ROOT_FILES = {
    '.env.example', '.gitignore', 'README.md', 'BUILD_REPORT.md', 'NEXT_STEPS.md',
    'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'LICENSE', 'LICENSE.md',
    'LICENSE.txt', 'NOTICE', 'NOTICE.md', 'pyproject.toml', 'requirements.in', 'requirements.lock',
}
FRONTEND_FILES = {
    'frontend/index.html', 'frontend/package.json', 'frontend/package-lock.json',
    'frontend/tsconfig.json', 'frontend/vite.config.ts',
}
FIXTURES = {'tests/fixtures/analytics.csv', 'tests/fixtures/search.json', 'tests/fixtures/urls.csv'}
DOC_DATA = {'docs/DEPENDENCY_LICENSES.json', 'docs/lens-example.json'}
MEDIA_REVIEW = 'docs/media-review.json'
# Public media is deliberately an exact list, never a directory-wide exception.
PUBLIC_MEDIA = {
    'docs/media/radar-home.png': 4 * 1024 * 1024,
    'docs/media/radar-live.png': 4 * 1024 * 1024,
    'docs/media/radar-results.png': 4 * 1024 * 1024,
    'docs/media/radar-demo.mp4': 12 * 1024 * 1024,
    'docs/media/radar-demo.gif': 8 * 1024 * 1024,
}
FORBIDDEN_PARTS = {
    '.git', '.runtime', '.venv', '.cache', '.pytest_cache', '__pycache__',
    'node_modules', 'data', 'exports', 'snapshots', 'browser-profiles',
    'test-results', 'playwright-report', 'private-docs', 'dist',
}
CONTENT_PATTERNS = {
    'absolute home directory': re.compile(r'(?:/home/|/Users/)[A-Za-z0-9_.-]+/'),
    'Windows user directory': re.compile(r'[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\'),
    'private key material': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential token': re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b'),
}
PRIVATE_IP = re.compile(r'(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])')


class ExportError(ValueError):
    pass


def permitted_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or name != path.as_posix() or any(part in {'', '.', '..'} for part in path.parts):
        return False
    if any(part in FORBIDDEN_PARTS for part in path.parts):
        return False
    if any(part.startswith('.env') for part in path.parts) and name != '.env.example':
        return False
    if name in ROOT_FILES or name in FRONTEND_FILES or name in FIXTURES or name in DOC_DATA or name == MEDIA_REVIEW or name in PUBLIC_MEDIA:
        return True
    if name.startswith('backend/radar/') and path.suffix in {'.py', '.sql'}:
        return True
    if name.startswith('frontend/src/') and path.suffix in {'.ts', '.tsx', '.css'}:
        return True
    if len(path.parts) == 2 and path.parts[0] == 'scripts' and path.suffix in {'.py', '.sh'}:
        return True
    if len(path.parts) == 2 and path.parts[0] == 'tests' and path.suffix == '.py':
        return True
    if len(path.parts) == 2 and path.parts[0] == 'docs' and path.suffix == '.md':
        return True
    if name.startswith('docs/licenses/') and path.suffix == '.txt':
        return True
    if len(path.parts) == 3 and path.parts[0] == '.github' and path.parts[1] in {'ISSUE_TEMPLATE', 'workflows'} and path.suffix in {'.md', '.yml', '.yaml'}:
        return True
    return name in {'.github/pull_request_template.md', '.github/ISSUE_TEMPLATE/config.yml'}


def _check_png(content: bytes):
    if not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG signature mismatch')
    offset, kinds = 8, []
    # Only image/display chunks. Text, EXIF, timestamps and unknown chunks must
    # be stripped before publication, even when the image looks harmless.
    allowed = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'sRGB', b'gAMA', b'cHRM', b'pHYs', b'bKGD', b'sBIT'}
    while offset < len(content):
        if offset + 12 > len(content):
            raise ValueError('truncated PNG chunk')
        length = int.from_bytes(content[offset:offset + 4], 'big')
        kind = content[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(content) or kind not in allowed:
            raise ValueError('invalid or metadata-bearing PNG chunk')
        if zlib.crc32(content[offset + 4:end - 4]) != int.from_bytes(content[end - 4:end], 'big'):
            raise ValueError('PNG checksum mismatch')
        if not kinds and (kind != b'IHDR' or length != 13):
            raise ValueError('missing PNG image header')
        if kind == b'IHDR':
            width = int.from_bytes(content[offset + 8:offset + 12], 'big')
            height = int.from_bytes(content[offset + 12:offset + 16], 'big')
            if kinds or not 0 < width <= 8192 or not 0 < height <= 8192:
                raise ValueError('invalid PNG dimensions or duplicate header')
        kinds.append(kind)
        offset = end
        if kind == b'IEND':
            if length or offset != len(content):
                raise ValueError('PNG has trailing data')
            break
    if not kinds or kinds[-1] != b'IEND' or b'IDAT' not in kinds:
        raise ValueError('incomplete PNG image')


def _check_gif(content: bytes):
    if content[:6] not in {b'GIF87a', b'GIF89a'} or len(content) < 14:
        raise ValueError('GIF signature mismatch')
    width, height = int.from_bytes(content[6:8], 'little'), int.from_bytes(content[8:10], 'little')
    if not 0 < width <= 8192 or not 0 < height <= 8192:
        raise ValueError('invalid GIF dimensions')
    offset = 13 + (3 * 2 ** ((content[10] & 7) + 1) if content[10] & 128 else 0)
    frames = 0

    def blocks(start):
        while start < len(content):
            length = content[start]
            start += 1
            if not length:
                return start
            start += length
        raise ValueError('truncated GIF data')

    while offset < len(content):
        marker = content[offset]
        if marker == 0x3B:
            if offset + 1 != len(content) or not frames:
                raise ValueError('incomplete GIF or trailing data')
            return
        if marker == 0x2C:
            if offset + 11 > len(content):
                raise ValueError('truncated GIF image descriptor')
            flags = content[offset + 9]
            offset += 10 + (3 * 2 ** ((flags & 7) + 1) if flags & 128 else 0)
            if offset >= len(content) or not 2 <= content[offset] <= 8:
                raise ValueError('invalid GIF image data')
            offset = blocks(offset + 1)
            frames += 1
        elif marker == 0x21 and offset + 2 < len(content):
            label = content[offset + 1]
            if label == 0xF9 and content[offset + 2] == 4 and offset + 8 <= len(content) and content[offset + 7] == 0:
                offset += 8
            elif content[offset:offset + 14] == b'\x21\xff\x0bNETSCAPE2.0' and content[offset + 14:offset + 16] == b'\x03\x01' and offset + 19 <= len(content) and content[offset + 18] == 0:
                offset += 19
            else:
                raise ValueError('GIF contains text, comments or unreviewed application metadata')
        else:
            raise ValueError('invalid GIF structure')
    raise ValueError('incomplete GIF image')


def _check_mp4(content: bytes):
    containers = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'dinf', b'edts'}
    leaves = {b'ftyp', b'mdat', b'free', b'mvhd', b'tkhd', b'mdhd', b'hdlr', b'vmhd', b'smhd',
              b'stsd', b'stts', b'stsc', b'stsz', b'stco', b'co64', b'stss', b'ctts', b'elst', b'dref'}
    seen = []
    # FFmpeg writes this empty QuickTime metadata envelope even with
    # -map_metadata -1 -fflags +bitexact. There are no keys or values here.
    empty_metadata = (b'\x00\x00\x00\x35meta' + b'\0' * 4
                      + b'\x00\x00\x00\x21hdlr' + b'\0' * 8 + b'mdirappl' + b'\0' * 9
                      + b'\x00\x00\x00\x08ilst')

    def boxes(start, end, depth=0):
        if depth > 8:
            raise ValueError('excessive MP4 container nesting')
        while start < end:
            if start + 8 > end:
                raise ValueError('truncated MP4 box')
            length = int.from_bytes(content[start:start + 4], 'big')
            kind = content[start + 4:start + 8]
            if length < 8 or start + length > end:
                raise ValueError('invalid MP4 box length')
            if not depth:
                seen.append(kind)
            if kind in containers:
                boxes(start + 8, start + length, depth + 1)
            elif kind == b'udta' and content[start + 8:start + length] == empty_metadata:
                pass
            elif kind not in leaves:
                raise ValueError('MP4 contains metadata or an unsupported box; strip metadata before export')
            elif kind == b'free' and any(content[start + 8:start + length]):
                raise ValueError('MP4 contains nonempty padding')
            start += length

    boxes(0, len(content))
    if not seen or seen[0] != b'ftyp' or b'moov' not in seen or b'mdat' not in seen or len(content) < 20:
        raise ValueError('MP4 signature or required boxes missing')
    if content[8:12] not in {b'isom', b'iso2', b'iso4', b'iso5', b'iso6', b'avc1', b'mp41', b'mp42'}:
        raise ValueError('unsupported MP4 file brand')


def media_problems(name: str, content: bytes) -> list[str]:
    if len(content) > PUBLIC_MEDIA[name]:
        return ['oversized public media file']
    try:
        {'.png': _check_png, '.gif': _check_gif, '.mp4': _check_mp4}[PurePosixPath(name).suffix](content)
    except ValueError as exc:
        return [str(exc)]
    # This catches exposed plaintext metadata only. It cannot establish that
    # rendered pixels are safe; matching explicit visual-review hashes below
    # are required as a separate release step.
    text = content.decode('latin-1')
    return [label for label, pattern in CONTENT_PATTERNS.items() if pattern.search(text)]


def content_problems(name: str, content: bytes) -> list[str]:
    if name in PUBLIC_MEDIA:
        return media_problems(name, content)
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return ['unexpected binary content']
    reasons = [label for label, pattern in CONTENT_PATTERNS.items() if pattern.search(text)]
    # Security fixtures deliberately contain denied RFC1918 targets. Production
    # examples and docs should use placeholders instead of an operator LAN IP.
    if not name.startswith('tests/') and PRIVATE_IP.search(text):
        reasons.append('literal private network address outside security tests')
    if name == '.env.example':
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, value = stripped.split('=', 1)
            if any(part in key.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                if value.strip().strip('\"\'') not in {'', 'YOUR_KEY_HERE', 'YOUR_API_KEY_HERE', 'CHANGE_ME'}:
                    reasons.append('non-placeholder credential in environment template')
                    break
    if name in FIXTURES:
        for url in re.findall(r'https?://[^\s\"\'<>),]+', text):
            host = (urlsplit(url).hostname or '').lower()
            if host not in {'example.com', 'example.net', 'example.org'} and not host.endswith(('.example.com', '.example.net', '.example.org', '.test', '.invalid')):
                reasons.append('non-synthetic fixture URL')
                break
    return reasons


def media_review_problems(entries: list[tuple[str, int, bytes]]) -> list[str]:
    files = {name: content for name, _mode, content in entries}
    media = {name: content for name, content in files.items() if name in PUBLIC_MEDIA}
    if not media and MEDIA_REVIEW not in files:
        return []
    try:
        review = json.loads(files[MEDIA_REVIEW])
        if set(review) != {'format_version', 'visually_reviewed', 'contains_only_public_demo', 'assets'}:
            raise ValueError
        if review['format_version'] != 1 or review['visually_reviewed'] is not True or review['contains_only_public_demo'] is not True:
            raise ValueError
        assets = review['assets']
        if not isinstance(assets, list) or len(assets) != len(media):
            raise ValueError
        checked = set()
        for item in assets:
            if set(item) != {'path', 'sha256'} or item['path'] not in media or item['path'] in checked:
                raise ValueError
            if item['sha256'] != hashlib.sha256(media[item['path']]).hexdigest():
                raise ValueError
            checked.add(item['path'])
    except (KeyError, TypeError, ValueError):
        return [f'{MEDIA_REVIEW}: missing, incomplete or stale visual review; inspect every public demo asset and record its exact SHA-256']
    return []


def collect_files(root: Path) -> list[tuple[str, int, bytes]]:
    try:
        listing = subprocess.run(['git', '-C', str(root), 'ls-files', '--stage', '-z'],
                                 check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise ExportError('Run this script from its source Git checkout; Git and an index are required.') from None
    entries = []
    problems = []
    seen = set()
    for entry in filter(None, listing.split(b'\0')):
        metadata, raw_name = entry.split(b'\t', 1)
        mode, _blob_id, stage = metadata.decode('ascii').split()
        name = raw_name.decode('utf-8')
        if name in seen:
            problems.append(f'{name}: duplicate or conflicted index entry')
            continue
        seen.add(name)
        if not permitted_path(name):
            problems.append(f'{name}: outside the public path policy')
            continue  # Do not open excluded files, even accidentally tracked ones.
        if stage != '0' or mode not in {'100644', '100755'}:
            problems.append(f'{name}: unresolved, symlink or submodule entry')
            continue
        path = root / name
        # Reject symlinks at every component, including a replaced parent folder.
        if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
            problems.append(f'{name}: symlink in working-tree path')
            continue
        try:
            info = path.stat()
            limit = PUBLIC_MEDIA.get(name, MAX_FILE_BYTES)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                problems.append(f'{name}: non-regular or oversized file')
                continue
            content = path.read_bytes()
        except OSError:
            problems.append(f'{name}: missing or unreadable tracked file')
            continue
        if len(content) > limit:
            problems.append(f'{name}: oversized file')
            continue
        reasons = content_problems(name, content)
        if reasons:
            problems.append(f'{name}: ' + '; '.join(reasons))
            continue
        entries.append((name, 0o755 if mode == '100755' else 0o644, content))
    problems.extend(media_review_problems(entries))
    required = {'README.md', '.env.example', 'requirements.lock', 'frontend/package-lock.json',
                'backend/radar/main.py', 'scripts/run.sh', 'scripts/export_public.py', 'CONTRIBUTING.md'}
    for name in sorted(required - seen):
        problems.append(f'{name}: required public file is not tracked; review and stage it first')
    if problems:
        raise ExportError('Source export stopped; no private content was printed:\n' + '\n'.join(f'- {item}' for item in problems))
    return sorted(entries)


def manifest_bytes(entries: list[tuple[str, int, bytes]]) -> bytes:
    return (json.dumps({
        'format_version': 1,
        'source': 'reviewed tracked working-tree files; no Git history',
        'files': [{'path': name, 'mode': oct(mode), 'bytes': len(content),
                   'sha256': hashlib.sha256(content).hexdigest()} for name, mode, content in entries],
    }, sort_keys=True, indent=2) + '\n').encode('utf-8')


def write_archive(output: Path, entries: list[tuple[str, int, bytes]], overwrite: bool):
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise ExportError('Output exists. Choose another path or pass --force to replace it explicitly.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.radar-export-', delete=False) as raw:
            temporary = Path(raw.name)
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                    for name, mode, content in [*entries, ('SOURCE_MANIFEST.json', 0o644, manifest_bytes(entries))]:
                        member = tarfile.TarInfo(f'{ARCHIVE_ROOT}/{name}')
                        member.size, member.mode, member.mtime = len(content), mode, 0
                        member.uid = member.gid = 0
                        member.uname = member.gname = ''
                        archive.addfile(member, io.BytesIO(content))
        if overwrite:
            os.replace(temporary, output)
        else:
            # Atomic no-clobber publication on the same filesystem.
            try:
                os.link(temporary, output)
            except FileExistsError:
                raise ExportError('Output appeared during export; refusing to overwrite it.') from None
            temporary.unlink()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate tracked public files without creating an archive.')
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime/public-export/jev-radar-source.tar.gz')
    parser.add_argument('--force', action='store_true', help='Explicitly replace an existing output archive.')
    args = parser.parse_args()
    try:
        entries = collect_files(ROOT)
        if args.check:
            print(f'Public source check passed: {len(entries)} files. No archive created.')
            return
        output = args.output.expanduser().absolute()
        if output.suffixes[-2:] != ['.tar', '.gz']:
            raise ExportError('Output must end in .tar.gz.')
        if output.is_symlink():
            raise ExportError('Output must not be a symlink.')
        if output.is_relative_to(ROOT) and output.relative_to(ROOT).as_posix() in {name for name, _, _ in entries}:
            raise ExportError('Output cannot replace a source file.')
        write_archive(output, entries, args.force)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        print(f'Created {output.name}: {len(entries)} source files plus manifest; SHA-256 {digest}')
        print('Review the extracted source before sharing. Git history and local runtime data were not copied.')
    except (ExportError, OSError) as exc:
        print(f'Export failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
