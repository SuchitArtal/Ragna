"""Guardrail validation pipeline orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from app.guardrails.patch_parser import PatchParser
from app.guardrails.file_validator import FileValidator
from app.guardrails.secret_scanner import SecretScanner
from app.guardrails.syntax_validator import SyntaxValidator
from app.sandbox.patch_applier import PatchApplier

logger = logging.getLogger(__name__)


class GuardrailPipeline:
    """Orchestrate all guardrail validation checks."""

    def __init__(self):
        self.patch_parser = PatchParser()
        self.file_validator = FileValidator()
        self.secret_scanner = SecretScanner()
        self.syntax_validator = SyntaxValidator()
        self.patch_applier = PatchApplier()

    def validate_proposal_structure(self, edit_proposal: Dict[str, object]) -> Dict[str, object]:
        """Validate required proposal schema and types."""
        required = {
            "action": str,
            "file_path": str,
            "proposed_patch": str,
            "reasoning": str,
            "confidence": (int, float),
        }
        errors: List[str] = []

        for key, expected_type in required.items():
            if key not in edit_proposal:
                errors.append(f"Missing required field: {key}")
                continue
            if not isinstance(edit_proposal[key], expected_type):
                errors.append(f"Field {key} has invalid type")

        action = str(edit_proposal.get("action", ""))
        if action not in {"edit_file", "delete_file"}:
            errors.append("Unsupported action; only edit_file/delete_file are allowed")

        confidence = float(edit_proposal.get("confidence", 0.0)) if "confidence" in edit_proposal else 0.0
        if confidence < 0.0 or confidence > 1.0:
            errors.append("confidence must be between 0.0 and 1.0")

        return {"valid": not errors, "errors": errors}

    def validate_edit(self, repo_root: str, edit_proposal: Dict[str, object]) -> Dict[str, object]:
        """Run complete guardrail validation pipeline.

        Args:
            repo_root: Absolute path to repository root.
            edit_proposal: Edit proposal containing file_path and proposed_patch.

        Returns:
            Validation result with allowed flag and detailed checks.
        """
        file_path = edit_proposal.get("file_path", "")
        proposed_patch = edit_proposal.get("proposed_patch", "")

        errors: List[str] = []
        warnings: List[str] = []

        # Check 0: Validate proposal schema
        logger.info("Step 0/5: Validating proposal schema")
        schema_result = self.validate_proposal_structure(edit_proposal)
        if not schema_result.get("valid", False):
            errors.extend(schema_result.get("errors", []))
            return {
                "allowed": False,
                "checks": {
                    "schema_valid": False,
                    "patch_valid": False,
                    "file_safe": False,
                    "no_secrets": False,
                    "syntax_valid": False,
                },
                "errors": errors,
                "warnings": warnings,
            }

        # Check 1: Parse patch
        logger.info("Step 1/5: Parsing patch for %s", file_path)
        patch_result = self.patch_parser.parse_patch(proposed_patch, file_path)
        patch_valid = patch_result.get("is_valid_format", False)

        if not patch_valid:
            errors.append("Patch format is invalid")
            logger.error("Patch parsing failed for %s", file_path)

        files_touched = patch_result.get("files_touched", [])
        if patch_valid and not patch_result.get("targets_declared_file", False):
            errors.append("Patch does not target declared file path")
            patch_valid = False
        if patch_valid and patch_result.get("touches_multiple_files", False):
            errors.append("Patch modifies multiple files; only single-file edits allowed")
            patch_valid = False
        if patch_valid and int(patch_result.get("hunk_count", 0)) > 80:
            errors.append("Patch contains too many hunks")
            patch_valid = False
        if patch_valid and int(patch_result.get("added_line_count", 0)) > 500:
            errors.append("Patch is oversized")
            patch_valid = False
        
        # Check 2: Validate file path
        logger.info("Step 2/5: Validating file path %s", file_path)
        allow_protected = bool(edit_proposal.get("allow_protected_edit", False))
        file_result = self.file_validator.validate_file_path(repo_root, file_path, allow_protected=allow_protected)
        file_safe = (
            file_result.get("within_repo", False)
            and file_result.get("is_safe_path", False)
        )
        file_exists = file_result.get("exists", False)

        if not file_safe:
            errors.append(f"File path unsafe: {file_result.get('error', 'unknown')}")
            logger.error("File validation failed for %s", file_path)
        elif not file_exists:
            warnings.append(f"File does not exist: {file_path}")
            logger.warning("File does not exist: %s", file_path)

        # Check 3: Scan for secrets
        logger.info("Step 3/5: Scanning for secrets")
        added_lines = []
        for hunk in patch_result.get("hunks", []):
            added_lines.extend(hunk.get("added_lines", []))

        secret_result = self.secret_scanner.scan_patch_for_secrets(added_lines)
        no_secrets = not secret_result.get("has_secrets", False)

        if not no_secrets:
            secret_count = len(secret_result.get("matches", []))
            errors.append(f"Detected {secret_count} potential secret(s) in patch")
            logger.error("Secret detection failed for %s", file_path)

        # Check 4: Validate syntax (real in-memory patched code)
        logger.info("Step 4/5: Validating syntax")
        syntax_valid = True

        if file_exists and patch_valid and file_safe:
            try:
                full_path = Path(file_result.get("full_path", ""))
                original_code = full_path.read_text(encoding="utf-8", errors="replace")

                simulated_code = self.patch_applier.apply_patch(original_code, proposed_patch)

                syntax_result = self.syntax_validator.validate_syntax(
                    simulated_code, file_path, "python"
                )
                syntax_valid = syntax_result.get("valid", False)

                if not syntax_valid:
                    syntax_errors = syntax_result.get("errors", [])
                    errors.extend([f"Syntax error: {e}" for e in syntax_errors])
                    logger.error("Syntax validation failed for %s", file_path)
            except Exception as exc:
                warnings.append(f"Could not validate syntax: {str(exc)}")
                logger.warning("Syntax check skipped for %s: %s", file_path, exc)
        else:
            warnings.append("Syntax validation skipped (prerequisite checks failed)")

        logger.info("Step 5/5: Final policy checks")
        if str(edit_proposal.get("action", "")) == "delete_file":
            warnings.append("Delete action requires explicit interactive confirmation")

        # Final decision
        allowed = patch_valid and file_safe and no_secrets and syntax_valid

        logger.info(
            "Validation complete for %s: allowed=%s",
            file_path,
            allowed,
        )

        return {
            "allowed": allowed,
            "checks": {
                "schema_valid": schema_result.get("valid", False),
                "patch_valid": patch_valid,
                "file_safe": file_safe,
                "no_secrets": no_secrets,
                "syntax_valid": syntax_valid,
            },
            "files_touched": files_touched,
            "errors": errors,
            "warnings": warnings,
        }
