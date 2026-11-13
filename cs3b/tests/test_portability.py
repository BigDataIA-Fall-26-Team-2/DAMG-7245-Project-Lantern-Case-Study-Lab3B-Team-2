"""Regression coverage for Windows ordering, newline translation and file handles."""
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sqlite3
import sys
import pytest
from creditwatch import skills, memory

ROOT = Path(__file__).resolve().parents[1]


def test_skill_hash_is_independent_of_windows_path_order(monkeypatch):
    root = ROOT / 'agent/skills/bdc-quarter-review'
    expected = skills.folder_hash(root)
    files = [p for p in root.rglob('*') if p.is_file()]
    class WindowsFile:
        def __init__(self, path): self.path = path
        @property
        def parts(self): return self.path.parts
        def is_file(self): return True
        def relative_to(self, directory): return PureWindowsPath(self.path.relative_to(directory))
        def read_bytes(self): return self.path.read_bytes()
        def __lt__(self, other): return PureWindowsPath(self.path) < PureWindowsPath(other.path)
    class Directory:
        def rglob(self, pattern): return [WindowsFile(p) for p in files]
    monkeypatch.setattr(skills, 'Path', lambda value: Directory())
    assert skills.folder_hash(root) == expected


def test_fixture_bytes_survive_windows_default_newline_translation(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('fixture_portability', ROOT/'tools/make_fixture.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original = Path.write_text
    def windows_default(self, data, *args, **kwargs):
        kwargs.setdefault('newline', '\r\n')
        return original(self, data, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', windows_default)
    monkeypatch.setattr(sys, 'argv', ['make_fixture.py', '--out', str(tmp_path)])
    module.main()
    fixture = ROOT/'data/fixture'
    for path in fixture.rglob('*'):
        if path.is_file(): assert (tmp_path/path.relative_to(fixture)).read_bytes() == path.read_bytes(), path.name


def test_store_context_releases_connection_even_after_error(tmp_path):
    with pytest.raises(ValueError):
        with memory.MandateStore(tmp_path, 'mandate_a') as store:
            store.add('Saved evidence', 'log/1')
            raise ValueError('Interrupted use')
    with pytest.raises(sqlite3.ProgrammingError): store.db.execute('SELECT 1')
    with memory.MandateStore(tmp_path, 'mandate_a') as reopened:
        assert reopened.search('evidence')
    (tmp_path/'mandate_a/memory.sqlite').unlink()


def test_working_and_starter_locks_are_current():
    for relative in ['agent/skills', 'agent_seed/skills']:
        root = ROOT/relative
        skills.verify(root, json.loads((root/'skills.lock').read_text(encoding='utf-8')))
