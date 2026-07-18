"""Inner drive state — minimal care list (inner-drive-state.md 一期).

A flat, capacity-bounded, FIFO list of things the AI keeps on its mind,
persisted per session as ``data/.inner_drive_state.{session_id}`` (same
per-session file pattern as ``.sleep_state``). The proactive think loop
reads it as Round-1 input and updates it via ``care_updates`` — the only
write action the loop is allowed to have.

Full typed/lifecycle design (priority, surface rules, resolution):
doc/refactor/layer4-agent/inner-drive-state.md
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class InnerDriveState:
    """Minimal care list: flat entries, capacity-bounded, FIFO eviction.

    All failures (missing/corrupt file, write errors) degrade to an empty
    or in-memory-only state — the inner world must never break the main
    flow.
    """

    def __init__(self, session_id: str, max_entries: int = 20,
                 state_dir: str = "data"):
        self._path = Path(state_dir) / f".inner_drive_state.{session_id}"
        try:
            self._max = max(1, int(max_entries))
        except (TypeError, ValueError):
            self._max = 20
        self._lock = threading.Lock()
        self._entries: list[dict] = []
        self._loaded = False

    def entries(self) -> list[str]:
        """Current care items, oldest first."""
        with self._lock:
            self._load_once()
            return [e["content"] for e in self._entries]

    def apply_updates(self, add: list | None = None,
                      remove: list | None = None) -> None:
        """Apply care_updates from the think loop (add/remove by content)."""
        with self._lock:
            self._load_once()
            if remove:
                drop = {str(x).strip() for x in remove}
                before = len(self._entries)
                self._entries = [e for e in self._entries
                                 if e["content"] not in drop]
                if len(self._entries) != before:
                    logger.info(f"[inner_drive_state] removed "
                                f"{before - len(self._entries)} care item(s)")
            for item in add or []:
                content = str(item).strip()
                if not content:
                    continue
                if any(e["content"] == content for e in self._entries):
                    continue
                self._entries.append({
                    "content": content,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                logger.info(f"[inner_drive_state] new care: {content[:60]}")
            # FIFO: capacity full → evict oldest (一期规则；二期改优先级淘汰)
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max:]
            try:
                self._save()
            except Exception as e:
                logger.warning(f"[inner_drive_state] save failed: {e}")

    def _load_once(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            raw = data.get("care_list", [])
            if isinstance(raw, list):
                self._entries = [
                    {"content": str(e.get("content", "")),
                     "created_at": str(e.get("created_at", ""))}
                    for e in raw
                    if isinstance(e, dict) and e.get("content")
                ]
        except FileNotFoundError:
            self._entries = []
        except Exception as e:
            logger.warning(f"[inner_drive_state] load failed "
                           f"({self._path}): {e}")
            self._entries = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"care_list": self._entries},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
