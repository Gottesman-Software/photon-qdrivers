"""Lightweight plugin registry and placeholder integration points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginInfo:
    """Metadata exposed by optional extension modules."""

    name: str
    role: str
    description: str


class PluginRegistry:
    """In-process registry for optional simulators, decoders, and adapters."""

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}

    def register(self, plugin: Any, *, replace: bool = False) -> Any:
        name = _normalize_plugin_name(getattr(plugin, "name", None))
        if name in self._plugins and not replace:
            raise ValueError(
                f"Plugin '{name}' is already registered. Pass replace=True to override it."
            )

        self._plugins[name] = plugin
        return plugin

    def get(self, name: str) -> Any:
        normalized_name = _normalize_plugin_name(name)
        try:
            return self._plugins[normalized_name]
        except KeyError as exc:
            raise KeyError(f"Plugin '{normalized_name}' is not registered.") from exc

    def list(self) -> list[str]:
        return sorted(self._plugins)

    def describe(self) -> list[dict[str, str]]:
        descriptions: list[dict[str, str]] = []
        for name in self.list():
            plugin = self._plugins[name]
            descriptions.append(
                {
                    "name": name,
                    "role": str(getattr(plugin, "role", "extension")),
                    "description": str(getattr(plugin, "description", "")),
                }
            )
        return descriptions


def _normalize_plugin_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("Plugins must expose a non-empty string 'name'.")

    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Plugins must expose a non-empty string 'name'.")
    return normalized


class SchroSIMPlugin:
    """Placeholder for a future SchroSIM photonic simulation adapter."""

    name = "schrosim"
    role = "simulator"
    description = "Optional SchroSIM bridge for symbolic and numeric photonic simulation."

    def compile(self, circuit: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "SchroSIM integration is a placeholder. Install and wire the real "
            "SchroSIM adapter before using this plugin for compilation."
        )


class LiDMaSPlugin:
    """Placeholder for a future LiDMaS+ decoder adapter."""

    name = "lidmas"
    role = "decoder"
    description = "Optional LiDMaS+ bridge for photonic measurement decoding workflows."

    def decode(self, measurements: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "LiDMaS+ integration is a placeholder. Install and wire the real "
            "LiDMaS+ adapter before using this plugin for decoding."
        )
