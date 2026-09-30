import types
from typing import cast
from brkraw import BrukerLoader

def test_ensure_hook_state_sets_enabled_flag(monkeypatch) -> None:
    from brkraw_viewer.app.workers import convert_worker

    class Scan:
        _hook_resolved = False

    scan = Scan()

    class Loader:
        def __init__(self) -> None:
            self.reset_calls = 0

        def get_scan(self, scan_id: int):
            assert scan_id == 1
            return scan

        def reset_converter(self, scan_obj) -> None:
            self.reset_calls += 1

    loader = Loader()

    def fake_hook_resolver(scan_obj, *_args, **_kwargs) -> None:
        scan_obj._hook_resolved = True

    monkeypatch.setattr(convert_worker.brkapi, "hook_resolver", fake_hook_resolver)
    fake_config = types.SimpleNamespace(
        resolve_root=lambda _root: None,
        affine_decimals=lambda root=None: 0,
    )
    monkeypatch.setattr(convert_worker.brkapi, "config", fake_config)

    convert_worker._ensure_hook_state(cast(BrukerLoader, loader), 1, enable_hook=True)
    assert getattr(scan, "_hook_enabled_state", None) is True
    assert scan._hook_resolved is True
    assert loader.reset_calls == 0


def test_ensure_hook_state_disable_resets_when_resolved(monkeypatch) -> None:
    from brkraw_viewer.app.workers import convert_worker

    class Scan:
        _hook_resolved = True

    scan = Scan()

    class Loader:
        def __init__(self) -> None:
            self.reset_calls = 0

        def get_scan(self, scan_id: int):
            assert scan_id == 1
            return scan

        def reset_converter(self, scan_obj) -> None:
            self.reset_calls += 1

    loader = Loader()

    # Disable path should not require hook resolver/config.
    convert_worker._ensure_hook_state(cast(BrukerLoader, loader), 1, enable_hook=False)
    assert getattr(scan, "_hook_enabled_state", None) is False
    assert scan._hook_resolved is False
    assert loader.reset_calls == 1
