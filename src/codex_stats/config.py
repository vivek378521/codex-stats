from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    codex_home: Path
    state_db: Path
    logs_db: Path
    sessions_dir: Path

    @classmethod
    def discover(cls) -> "Paths":
        codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
        return cls(
            codex_home=codex_home,
            state_db=codex_home / "state_5.sqlite",
            logs_db=codex_home / "logs_1.sqlite",
            sessions_dir=codex_home / "sessions",
        )
