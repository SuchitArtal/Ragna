from app.guardrails.file_validator import FileValidator

repo_root = "D:/Ragna"
validator = FileValidator()

print(validator.validate_file_path(repo_root, "app/main.py"))
print(validator.validate_file_path(repo_root, "../../windows/system32"))
