"""Public-source export checks use disposable repositories and synthetic data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import zlib

import pytest

EXPORT_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/export_public.py'
SPEC = importlib.util.spec_from_file_location('radar_public_export', EXPORT_SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


@pytest.fixture
def source_repo(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    files = {
        'README.md': '# Synthetic public exporter fixture\n',
        '.env.example': 'TYPESAFE_API_KEY=YOUR_KEY_HERE\nBRAVE_SEARCH_API_KEY=\n',
        'requirements.lock': '# Synthetic fixture\n',
        'frontend/package-lock.json': '{}\n',
        'backend/radar/main.py': '# Synthetic fixture\n',
        'scripts/run.sh': '#!/bin/sh\n',
        'scripts/export_public.py': EXPORT_SCRIPT.read_text(),
        'CONTRIBUTING.md': '# Synthetic fixture\n',
        'tests/fixtures/urls.csv': 'url\nhttps://example.com/\n',
    }
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), 'update-index', '--chmod=+x', 'scripts/run.sh'], check=True)
    return root


def test_deterministic_archive_and_manifest(source_repo, tmp_path):
    entries = exporter.collect_files(source_repo)
    first, second = tmp_path / 'one.tar.gz', tmp_path / 'two.tar.gz'
    exporter.write_archive(first, entries, False)
    exporter.write_archive(second, entries, False)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        manifest = json.load(archive.extractfile('Jev-Radar/SOURCE_MANIFEST.json'))
        assert len(archive.getmembers()) == len(entries) + 1
        assert archive.getmember('Jev-Radar/scripts/run.sh').mode == 0o755
        for item in manifest['files']:
            content = archive.extractfile('Jev-Radar/' + item['path']).read()
            assert hashlib.sha256(content).hexdigest() == item['sha256']
            assert len(content) == item['bytes']
        for member in archive.getmembers():
            assert (member.mtime, member.uid, member.gid, member.uname, member.gname) == (0, 0, 0, '', '')


def test_untracked_private_data_and_history_are_not_read(source_repo, tmp_path):
    (source_repo / '.env').write_text('DO_NOT_EXPORT=synthetic-private-marker\n')
    (source_repo / 'data').mkdir()
    (source_repo / 'data' / 'private.json').write_text('{"synthetic_private_marker":true}')
    entries = exporter.collect_files(source_repo)
    output = tmp_path / 'source.tar.gz'
    exporter.write_archive(output, entries, False)
    with tarfile.open(output) as archive:
        for member in archive.getmembers():
            assert not {'.git', '.env', 'data', '.runtime'}.intersection(Path(member.name).parts)
            assert b'synthetic-private-marker' not in archive.extractfile(member).read()


def test_existing_output_requires_explicit_overwrite(source_repo, tmp_path):
    entries = exporter.collect_files(source_repo)
    output = tmp_path / 'source.tar.gz'
    output.write_bytes(b'existing fixture')
    with pytest.raises(exporter.ExportError, match='Output exists'):
        exporter.write_archive(output, entries, False)
    assert output.read_bytes() == b'existing fixture'
    exporter.write_archive(output, entries, True)
    assert tarfile.is_tarfile(output)


def test_tracked_env_is_rejected_without_reading_or_disclosing_contents(source_repo):
    secret = source_repo / '.env'
    secret.write_text('SYNTHETIC_KEY=not-a-real-credential-private-marker\n')
    subprocess.run(['git', '-C', str(source_repo), 'add', '.env'], check=True)
    secret.unlink()  # A rejected path must not need to exist or be opened.
    with pytest.raises(exporter.ExportError) as error:
        exporter.collect_files(source_repo)
    assert '.env: outside the public path policy' in str(error.value)
    assert 'not-a-real-credential-private-marker' not in str(error.value)
    assert '.env: missing' not in str(error.value)


def test_private_home_and_lan_are_redacted_in_errors(source_repo):
    private_home = '/home/' + 'synthetic-operator/research'
    private_lan = '192.168.88.19'
    (source_repo / 'README.md').write_text(f'{private_home} {private_lan}\n')
    with pytest.raises(exporter.ExportError) as error:
        exporter.collect_files(source_repo)
    assert 'README.md' in str(error.value)
    assert private_home not in str(error.value)
    assert private_lan not in str(error.value)


def test_non_placeholder_environment_credentials_are_rejected(source_repo):
    (source_repo / '.env.example').write_text('TYPESAFE_API_KEY=synthetic-secret-not-a-real-key\n')
    with pytest.raises(exporter.ExportError) as error:
        exporter.collect_files(source_repo)
    assert 'non-placeholder credential' in str(error.value)
    assert 'synthetic-secret-not-a-real-key' not in str(error.value)


def test_replaced_working_tree_symlink_is_rejected(source_repo):
    (source_repo / '.env').write_text('synthetic private target')
    target = source_repo / 'README.md'
    target.unlink()
    target.symlink_to(source_repo / '.env')
    with pytest.raises(exporter.ExportError, match='symlink in working-tree path'):
        exporter.collect_files(source_repo)


def test_non_synthetic_fixture_url_is_rejected(source_repo):
    (source_repo / 'tests/fixtures/urls.csv').write_text('url\nhttps://customer.invalid-example.io/private\n')
    with pytest.raises(exporter.ExportError, match='non-synthetic fixture URL'):
        exporter.collect_files(source_repo)


def test_new_required_public_file_must_be_staged(source_repo):
    subprocess.run(['git', '-C', str(source_repo), 'rm', '--cached', '--quiet', 'CONTRIBUTING.md'], check=True)
    assert (source_repo / 'CONTRIBUTING.md').exists()
    with pytest.raises(exporter.ExportError, match='CONTRIBUTING.md: required public file is not tracked'):
        exporter.collect_files(source_repo)


def png_chunk(kind, payload=b''):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


def synthetic_png(extra=b''):
    return (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + extra + png_chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + png_chunk(b'IEND'))


def mp4_box(kind, payload=b''):
    return struct.pack('>I', len(payload) + 8) + kind + payload


def synthetic_mp4(extra=b''):
    # Container fixture only; no real recording or personal data belongs in tests.
    return mp4_box(b'ftyp', b'isom\0\0\x02\0isomiso2avc1mp41') + mp4_box(b'moov', extra) + mp4_box(b'mdat')


def synthetic_gif(extra=b''):
    return (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff' + extra
            + b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b')


def stage_media(root, files, *, reviewed=True):
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if reviewed:
        (root / exporter.MEDIA_REVIEW).write_text(json.dumps({
            'format_version': 1, 'visually_reviewed': True, 'contains_only_public_demo': True,
            'assets': [{'path': name, 'sha256': hashlib.sha256(content).hexdigest()} for name, content in files.items()],
        }))
    subprocess.run(['git', '-C', str(root), 'add', 'docs'], check=True)


@pytest.mark.parametrize('name,content', [
    ('docs/media/radar-home.png', synthetic_png()),
    ('docs/media/radar-live.png', synthetic_png()),
    ('docs/media/radar-results.png', synthetic_png()),
    ('docs/media/radar-demo.mp4', synthetic_mp4()),
    ('docs/media/radar-demo.gif', synthetic_gif()),
])
def test_explicitly_reviewed_media_is_exported_and_hashed(source_repo, tmp_path, name, content):
    stage_media(source_repo, {name: content})
    entries = exporter.collect_files(source_repo)
    output = tmp_path / 'with-media.tar.gz'
    exporter.write_archive(output, entries, False)
    with tarfile.open(output) as archive:
        assert archive.extractfile('Jev-Radar/' + name).read() == content
        manifest = json.load(archive.extractfile('Jev-Radar/SOURCE_MANIFEST.json'))
        item = next(item for item in manifest['files'] if item['path'] == name)
        assert item['sha256'] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize('name', ['docs/media/radar-home.png', 'docs/media/radar-demo.mp4', 'docs/media/radar-demo.gif'])
def test_media_extension_does_not_accept_other_binary_content(source_repo, name):
    stage_media(source_repo, {name: b'PK\x03\x04synthetic archive'})
    with pytest.raises(exporter.ExportError, match='signature|invalid MP4 box'):
        exporter.collect_files(source_repo)


@pytest.mark.parametrize('name,content', [
    ('docs/media/radar-live.png', synthetic_png(png_chunk(b'tEXt', b'Comment\0synthetic private marker'))),
    ('docs/media/radar-demo.mp4', synthetic_mp4(mp4_box(b'udta', mp4_box(b'meta', b'synthetic private marker')))),
    ('docs/media/radar-demo.gif', synthetic_gif(b'\x21\xfe\x07private\x00')),
])
def test_metadata_is_rejected_even_with_visual_review(source_repo, name, content):
    stage_media(source_repo, {name: content})
    with pytest.raises(exporter.ExportError, match='metadata|comments') as error:
        exporter.collect_files(source_repo)
    assert 'synthetic private marker' not in str(error.value)


def test_standard_gif_loop_is_allowed():
    loop = b'\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00'
    assert exporter.media_problems('docs/media/radar-demo.gif', synthetic_gif(loop)) == []


def test_ffmpeg_empty_metadata_envelope_is_allowed_but_values_are_not():
    handler = mp4_box(b'hdlr', b'\0' * 8 + b'mdirappl' + b'\0' * 9)
    empty = mp4_box(b'udta', mp4_box(b'meta', b'\0' * 4 + handler + mp4_box(b'ilst')))
    assert exporter.media_problems('docs/media/radar-demo.mp4', synthetic_mp4(empty)) == []
    populated = mp4_box(b'udta', mp4_box(b'meta', b'\0' * 4 + handler + mp4_box(b'ilst', mp4_box(b'\xa9nam', b'private title'))))
    assert exporter.media_problems('docs/media/radar-demo.mp4', synthetic_mp4(populated))


def test_media_requires_explicit_visual_review(source_repo):
    stage_media(source_repo, {'docs/media/radar-home.png': synthetic_png()}, reviewed=False)
    with pytest.raises(exporter.ExportError, match='missing, incomplete or stale visual review'):
        exporter.collect_files(source_repo)


@pytest.mark.parametrize('change', ['hash', 'flag', 'private_flag', 'duplicate', 'omitted', 'extra', 'wrong_path'])
def test_stale_or_incomplete_media_review_is_rejected(source_repo, change):
    stage_media(source_repo, {'docs/media/radar-home.png': synthetic_png()})
    path = source_repo / exporter.MEDIA_REVIEW
    review = json.loads(path.read_text())
    if change == 'hash':
        review['assets'][0]['sha256'] = '0' * 64
    elif change == 'flag':
        review['visually_reviewed'] = False
    elif change == 'private_flag':
        review['contains_only_public_demo'] = False
    elif change == 'duplicate':
        review['assets'].append(review['assets'][0])
    elif change == 'omitted':
        review['assets'] = []
    elif change == 'extra':
        review['extra'] = 'unsupported freeform field'
    else:
        review['assets'][0]['path'] = '.runtime/screenshots/private.png'
    path.write_text(json.dumps(review))
    with pytest.raises(exporter.ExportError, match='missing, incomplete or stale visual review'):
        exporter.collect_files(source_repo)


@pytest.mark.parametrize('name', ['docs/media/private.png', '.runtime/screenshots/radar-live.png', 'docs/private.mp4'])
def test_media_allowlist_never_opens_other_binaries(source_repo, name):
    target = source_repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(synthetic_png())
    subprocess.run(['git', '-C', str(source_repo), 'add', name], check=True)
    target.unlink()
    with pytest.raises(exporter.ExportError, match='outside the public path policy') as error:
        exporter.collect_files(source_repo)
    assert 'missing or unreadable' not in str(error.value)


@pytest.mark.parametrize('name', list(exporter.PUBLIC_MEDIA))
def test_media_size_limit_is_enforced_before_read(source_repo, name):
    stage_media(source_repo, {name: b''})
    with (source_repo / name).open('wb') as handle:
        handle.truncate(exporter.PUBLIC_MEDIA[name] + 1)
    with pytest.raises(exporter.ExportError, match='oversized file'):
        exporter.collect_files(source_repo)


@pytest.mark.parametrize('name', [
    'docs/media/../media/radar-live.png', 'docs//media/radar-live.png',
    './docs/media/radar-live.png', '/docs/media/radar-live.png',
    'docs/media/radar-live.png/../private.png', 'docs/media/radar-live.png.backup',
    'docs/media/radar-live.PNG',
])
def test_media_paths_must_be_exact(name):
    assert not exporter.permitted_path(name)


@pytest.mark.parametrize('name,content', [
    ('docs/media/radar-home.png', synthetic_png() + b'private'),
    ('docs/media/radar-demo.gif', synthetic_gif() + b'private'),
    ('docs/media/radar-demo.mp4', synthetic_mp4() + b'private'),
])
def test_trailing_binary_data_is_rejected(name, content):
    assert exporter.media_problems(name, content)
