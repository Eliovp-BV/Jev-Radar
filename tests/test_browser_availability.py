"""Browser readiness follows installed executables, without driver/network I/O."""
import pytest

from radar.api import browser_installed


@pytest.mark.parametrize('relative', [
    'chromium-1200/chrome-linux/chrome',
    'chromium-9999/chrome-linux64/chrome',
    'chromium-9999/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium',
    'chromium-9999/chrome-win64/chrome.exe',
    'chromium_headless_shell-9999/chrome-headless-shell-linux64/chrome-headless-shell',
    'chromium_headless_shell-9999/chrome-headless-shell-win64/chrome-headless-shell.exe',
    'chromium_headless_shell-1200/chrome-linux/headless_shell',
])
def test_downloaded_executable_is_detected_across_revisions_and_layouts(tmp_path, relative):
    executable = tmp_path / relative
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'synthetic browser executable fixture')
    executable.chmod(0o755)
    assert browser_installed(tmp_path)


def test_missing_incomplete_and_nonexecutable_downloads_are_unavailable(tmp_path):
    assert not browser_installed(tmp_path / 'missing')
    revision = tmp_path / 'chromium-9999/chrome-linux64'
    revision.mkdir(parents=True)
    assert not browser_installed(tmp_path)
    executable = revision / 'chrome'
    executable.write_text('incomplete executable fixture')
    executable.chmod(0o644)
    assert not browser_installed(tmp_path)
    executable.unlink()
    executable.mkdir()
    assert not browser_installed(tmp_path)
