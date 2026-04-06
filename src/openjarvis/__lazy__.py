"""Lazy import utilities for OpenJarvis.

This module provides lazy loading for heavy modules to improve startup time.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class LazyModule:
    """Lazy module proxy that imports on first access.

    Usage:
        openjarvis = LazyModule("openjarvis")
        # Only imports when accessing attributes
        jarvis = openjarvis.Jarvis
    """

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Any = None

    def _ensure_loaded(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure_loaded(), name)

    def __dir__(self) -> list[str]:
        return dir(self._ensure_loaded())


def lazy_import(module_name: str, *attrs: str) -> Any:
    """Create a lazy import for a module or module attribute.

    Args:
        module_name: Full module path (e.g., 'openjarvis.engine.ollama')
        *attrs: Optional attributes to import (if empty, imports the module)

    Returns:
        Lazy proxy or the imported attribute

    Example:
        # Lazy import a class
        OllamaEngine = lazy_import("openjarvis.engine.ollama", "OllamaEngine")

        # Lazy import entire module
        ollama = lazy_import("openjarvis.engine.ollama")
    """
    if attrs:
        # Import specific attributes
        module = importlib.import_module(module_name)
        if len(attrs) == 1:
            return getattr(module, attrs[0])
        return tuple(getattr(module, a) for a in attrs)
    else:
        # Return lazy module proxy
        return LazyModule(module_name)


class LazyLoader:
    """Class decorator for lazy loading class dependencies.

    Usage:
        @LazyLoader("openjarvis.engine")
        class MyEngine:
            def __init__(self):
                self._engine = None

            @property
            def engine(self):
                if self._engine is None:
                    from openjarvis.engine.ollama import OllamaEngine
                    self._engine = OllamaEngine()
                return self._engine
    """

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Any = None

    def __call__(self, cls: type[T]) -> type[T]:
        original_init = cls.__init__

        def lazy_init(self: Any, *args: Any, **kwargs: Any) -> None:
            # Defer import until instance creation
            importlib.import_module(self._module_name)

            # Now call the original init
            original_init(self, *args, **kwargs)

        cls.__init__ = lazy_init
        return cls


def create_getter(module_name: str, attr_name: str) -> Callable[[], Any]:
    """Create a getter function for lazy attribute access.

    Args:
        module_name: Full module path
        attr_name: Attribute name to access

    Returns:
        A function that lazily imports and returns the attribute

    Example:
        get_ollama_engine = create_getter("openjarvis.engine.ollama", "OllamaEngine")
        engine = get_ollama_engine()  # Actual import happens here
    """
    _cached: Any = None

    def getter() -> Any:
        nonlocal _cached
        if _cached is None:
            module = importlib.import_module(module_name)
            _cached = getattr(module, attr_name)
        return _cached

    return getter


def install_lazy_import_hooks() -> None:
    """Install import hooks for even faster lazy loading.

    This is optional and uses importlib.util.find_spec for lazy loading.
    Call this at startup if you want the most aggressive lazy loading.
    """
    pass  # Reserved for future implementation


__all__ = [
    "LazyModule",
    "lazy_import",
    "LazyLoader",
    "create_getter",
    "install_lazy_import_hooks",
]
