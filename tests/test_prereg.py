import subprocess

from cri import prereg


def test_signed_only_with_the_tag(monkeypatch):
    class Out:
        def __init__(self, text):
            self.stdout = text

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Out("prereg-v1\n"))
    assert prereg.is_signed()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Out(""))
    assert not prereg.is_signed() and not prereg.require_signed("x")


def test_not_signed_outside_a_git_repository(monkeypatch):
    def fail(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", fail)
    assert not prereg.is_signed()
