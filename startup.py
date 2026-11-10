"""Start-up helpers shared by main.py, gui.py and net.py (2026-11-10, hub instruction "splash").

Two things make the exe slow to open: PyInstaller unpacking 40 MB, and importing requests
and Pillow (about half a second together on this machine, run from source). The first is
covered by the picture the exe shows while it unpacks (build.bat --splash assets/splash.png);
the second by importing those two libraries only when first used, from a background thread
started once the window is painted. mutagen was measured at a few milliseconds and stays a
normal import in tags.py.
"""
from __future__ import annotations

import importlib
import threading

_LAZY: list[LazyModule] = []


class LazyModule:
    """Stands in for a module until the first attribute is read. Then the real module is
    imported, once, by whichever thread asks first; the others wait on the lock and get the
    same module. Every attribute read afterwards goes to the real module."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._module = None
        self._lock = threading.Lock()
        _LAZY.append(self)

    def load(self):
        module = self._module
        if module is None:
            with self._lock:
                module = self._module
                if module is None:
                    module = importlib.import_module(self._name)
                    self._module = module
        return module

    @property
    def loaded(self) -> bool:
        return self._module is not None

    def __getattr__(self, attr: str):
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)  # copy/pickle/inspect probes must not trigger an import
        return getattr(self.load(), attr)

    def __repr__(self) -> str:
        return f"<LazyModule {self._name} {'loaded' if self.loaded else 'not loaded'}>"


def lazy(name: str) -> LazyModule:
    return LazyModule(name)


def load_heavy() -> None:
    """Import every deferred library now; the caller waits for it."""
    for module in list(_LAZY):
        module.load()


def heavy_loaded() -> bool:
    return all(module.loaded for module in _LAZY)


def preload_heavy(done=None) -> None:
    """For a background thread started once the window is up: import the deferred libraries
    so the first real use does not wait. A failure is left for that first use, which reports
    it; `done` is called only after everything loaded."""
    try:
        load_heavy()
    except Exception:
        return
    if done is not None:
        done()


_splash_closed = False


def close_splash() -> None:
    """Take down the picture the exe shows while unpacking. Run from source there is no
    pyi_splash module and nothing happens; a second call does nothing either."""
    global _splash_closed
    if _splash_closed:
        return
    _splash_closed = True
    try:
        import pyi_splash

        pyi_splash.close()
    except Exception:
        pass
