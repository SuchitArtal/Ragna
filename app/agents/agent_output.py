"""Agent output helpers enforcing strict JSON contract for edit proposals.

This module provides utilities to build and validate an agent's output that
will be passed to SandboxExecutor.execute_edit(repo_root, agent_output).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Dict, Any, Union

from app.guardrails.patch_parser import PatchParser


@dataclass
class EditProposal:
    action: str
    file_path: str
    proposed_patch: str
    reasoning: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def validate_proposal_shape(obj: Dict[str, Any]) -> None:
    required = {
        "action": str,
        "file_path": str,
        "proposed_patch": str,
        "reasoning": str,
        "confidence": float,
    }
    if not isinstance(obj, dict):
        raise ValueError("Proposal must be a dict")
    for k, t in required.items():
        if k not in obj:
            raise ValueError(f"Missing required key: {k}")
        if not isinstance(obj[k], t):
            if k == "confidence" and isinstance(obj[k], (int, float)):
                continue
            raise ValueError(f"Invalid type for {k}: expected {t}, got {type(obj[k])}")
    if obj.get("action") != "edit_file":
        raise ValueError('action must be "edit_file"')
    if not (0.0 <= float(obj.get("confidence")) <= 1.0):
        raise ValueError("confidence must be between 0.0 and 1.0")


def build_edit_proposal(file_path: str, proposed_patch: str, reasoning: str, confidence: float) -> Dict[str, Any]:
    p = EditProposal(
        action="edit_file",
        file_path=file_path,
        proposed_patch=proposed_patch,
        reasoning=reasoning,
        confidence=float(confidence),
    )
    obj = p.to_dict()
    validate_proposal_shape(obj)
    return obj


def parse_agent_output(agent_output: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(agent_output, str):
        try:
            obj = json.loads(agent_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Agent output is not valid JSON: {exc}") from exc
    elif isinstance(agent_output, dict):
        obj = agent_output
    else:
        raise ValueError("Agent output must be a JSON string or dict")
    validate_proposal_shape(obj)
    parser = PatchParser()
    if not parser.parse_patch(obj.get("proposed_patch", ""), obj.get("file_path", "")).get("is_valid_format", False):
        raise ValueError("proposed_patch is not a valid unified diff")
    fp = obj.get("file_path", "")
    if fp.startswith("/") or ".." in fp.split("/"):
        raise ValueError("file_path must be a relative path inside repository")
    obj["confidence"] = float(obj["confidence"])
    return obj


__all__ = ["EditProposal", "build_edit_proposal", "validate_proposal_shape", "parse_agent_output"]
