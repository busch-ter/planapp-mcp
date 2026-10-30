from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class BuilderState:
    workspace: Path
    code_root: Path
    project_name: str
    project_root: Path
    data_root: Path
    nodes_path: Path
    scenario_path: Path
    compiler: Any
    nodes_ready: bool = False
    preparation_report: dict | None = None
    agent: Any = None
    conversation_session: Any = None
    validated_rows: list = field(default_factory=list)
