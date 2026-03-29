"""Guardrail validation pipeline orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from app.guardrails.patch_parser import PatchParser
from app.guardrails.file_validator import FileValidator
from app.guardrails.secret_scanner import SecretScanner
from app.guardrails.syntax_validator import SyntaxValidator

logger = logging.getLogger(__name__)


class GuardrailPipeline:
    """Orchestrate all guardrail validation checks."""

    def __init__(self):
        self.patch_parser = PatchParser()
        self.file_validator = FileValidator()
        self.secret_scanner = SecretScanner()
        self.syntax_validator = SyntaxValidator()

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

        # Check 1: Parse patch
        logger.info("Step 1/4: Parsing patch for %s", file_path)
        patch_result = self.patch_parser.parse_patch(proposed_patch, file_path)
        patch_valid = patch_result.get("is_valid_format", False)

        if not patch_valid:
            errors.append("Patch format is invalid")
            logger.error("Patch parsing failed for %s", file_path)
        
        # Check 2: Validate file path
        logger.info("Step 2/4: Validating file path %s", file_path)
        file_result = self.file_validator.validate_file_path(repo_root, file_path)
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
        logger.info("Step 3/4: Scanning for secrets")
        added_lines = []
        for hunk in patch_result.get("hunks", []):
            added_lines.extend(hunk.get("added_lines", []))

        secret_result = self.secret_scanner.scan_patch_for_secrets(added_lines)
        no_secrets = not secret_result.get("has_secrets", False)

        if not no_secrets:
            secret_count = len(secret_result.get("matches", []))
            errors.append(f"Detected {secret_count} potential secret(s) in patch")
            logger.error("Secret detection failed for %s", file_path)

        # Check 4: Validate syntax (simulate patched code)
        logger.info("Step 4/4: Validating syntax")
        syntax_valid = True

        if file_exists and patch_valid and file_safe:
            try:
                full_path = Path(file_result.get("full_path", ""))
                original_code = full_path.read_text(encoding="utf-8", errors="replace")
                
                # Simple simulation: append added lines (not a real patch apply)
                # For a real implementation, use a patch library
                simulated_code = original_code
                for hunk in patch_result.get("hunks", []):
                    for line in hunk.get("added_lines", []):
                        simulated_code += "\n" + line.lstrip("+")

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
                "patch_valid": patch_valid,
                "file_safe": file_safe,
                "no_secrets": no_secrets,
                "syntax_valid": syntax_valid,
            },
            "errors": errors,
            "warnings": warnings,
        }
