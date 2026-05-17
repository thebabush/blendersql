"""Env-var override resolver for the addon's listen config.

`_resolve_listen_config` lets headless multi-instance launches override
the saved `bind` / `port` / `autostart` prefs without mutating the .blend
or the Blender user-config. Pure stdlib; no Blender boot needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from blendersql import _resolve_listen_config


@dataclass
class _FakePrefs:
    bind: str = '127.0.0.1'
    port: int = 8174
    autostart: bool = True


def test_defaults_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ('BLENDERSQL_BIND', 'BLENDERSQL_PORT', 'BLENDERSQL_AUTOSTART'):
        monkeypatch.delenv(var, raising=False)
    bind, port, autostart = _resolve_listen_config(_FakePrefs())
    assert (bind, port, autostart) == ('127.0.0.1', 8174, True)


def test_bind_env_overrides_prefs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BLENDERSQL_BIND', '0.0.0.0')
    bind, _, _ = _resolve_listen_config(_FakePrefs(bind='127.0.0.1'))
    assert bind == '0.0.0.0'


def test_port_env_overrides_prefs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BLENDERSQL_PORT', '8200')
    _, port, _ = _resolve_listen_config(_FakePrefs(port=8174))
    assert port == 8200


def test_port_env_bad_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BLENDERSQL_PORT', 'eight-thousand')
    with pytest.raises(ValueError):
        _resolve_listen_config(_FakePrefs())


@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'yes', 'on'])
def test_autostart_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv('BLENDERSQL_AUTOSTART', value)
    _, _, autostart = _resolve_listen_config(_FakePrefs(autostart=False))
    assert autostart is True


@pytest.mark.parametrize('value', ['0', 'false', 'NO', 'off', ''])
def test_autostart_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv('BLENDERSQL_AUTOSTART', value)
    _, _, autostart = _resolve_listen_config(_FakePrefs(autostart=True))
    assert autostart is False


def test_autostart_unknown_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BLENDERSQL_AUTOSTART', 'maybe')
    with pytest.raises(ValueError):
        _resolve_listen_config(_FakePrefs())


def test_env_missing_keeps_pref_autostart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('BLENDERSQL_AUTOSTART', raising=False)
    _, _, autostart = _resolve_listen_config(_FakePrefs(autostart=False))
    assert autostart is False
