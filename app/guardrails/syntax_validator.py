"""Syntax validation for patched code."""

from __future__ import annotations

import ast
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class SyntaxValidator:
    """Validate syntax of code after applying a patch."""

    def validate_python_syntax(self, patched_code: str, file_path: str) -> Dict[str, object]:
        """Validate Python syntax of patched code.

        Args:
            patched_code: The complete code after applying patch.
            file_path: File path for logging context.

        Returns:
            Validation result with syntax errors if any.
        """
        errors: List[str] = []

        try:
            ast.parse(patched_code)
            logger.info("Syntax validation passed for %s", file_path)
            return {
                "valid": True,
                "errors": [],
            }
        except SyntaxError as exc:
            error_msg = f"Line {exc.lineno}: {exc.msg}"
            errors.append(error_msg)
            logger.warning("Syntax error in %s: %s", file_path, error_msg)
            return {
                "valid": False,
                "errors": errors,
            }
        except Exception as exc:
            error_msg = f"Validation failed: {str(exc)}"
            errors.append(error_msg)
            logger.warning("Validation error in %s: %s", file_path, exc)
            return {
                "valid": False,
                "errors": errors,
            }

    def validate_syntax(self, patched_code: str, file_path: str, language: str) -> Dict[str, object]:
        """Validate syntax based on file type.

        Args:
            patched_code: The complete code after applying patch.
            file_path: File path for context.
            language: Language type (python, javascript, etc.).

        Returns:
            Validation result.
        """
        if language == "python" or file_path.endswith(".py"):
            return self.validate_python_syntax(patched_code, file_path)
        
        # For non-Python files, skip syntax validation for now
        logger.info("Skipping syntax validation for non-Python file: %s", file_path)
        return {
            "valid": True,
            "errors": [],
        }
