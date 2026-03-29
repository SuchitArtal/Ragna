from app.guardrails.secret_scanner import SecretScanner

scanner = SecretScanner()

lines = [
    '+API_KEY="123456abcdef"',
    '+print("hello")',
    '+aws_key="AKIAIOSFODNN7EXAMPLE"',
]

result = scanner.scan_patch_for_secrets(lines)

print(result)
