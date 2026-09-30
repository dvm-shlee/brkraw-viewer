from __future__ import annotations

import logging
from typing import Any, List, Protocol, Optional

from brkraw.core.entrypoints import list_entry_points

logger = logging.getLogger("brkraw.viewer")

HOOK_GROUP = "brkraw.viewer.hook"


class ViewerHook(Protocol):
    name: str

    def build_tab(self, parent: Any, app: Any) -> Optional[Any]:
        ...


def load_viewer_hooks() -> List[Any]:
    hooks: List[Any] = []
    for ep in list_entry_points(HOOK_GROUP):
        try:
            loaded = ep.load()
        except Exception as exc:
            logger.warning("Failed to load viewer hook %s: %s", ep.name, exc)
            continue
        hook = loaded() if callable(loaded) else loaded
        if hook is None:
            continue
        hooks.append(hook)
    return hooks
