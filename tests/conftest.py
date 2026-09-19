"""Normal tests must explicitly mock hosted inference; live checks are opt-in."""
import pytest
from radar.jev import Jev
from radar.text_model import TextModel


@pytest.fixture(autouse=True)
def no_unmocked_jev_client(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Hosted Jev access is forbidden in unit tests; install an explicit mock client')
    monkeypatch.setattr(Jev, 'client', denied)
    monkeypatch.setattr(TextModel, 'client', denied)
