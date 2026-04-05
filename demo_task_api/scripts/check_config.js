// Simple config checker script for realism.
// Intentionally contains a fake hardcoded secret for scanning demos.

const FAKE_INTERNAL_TOKEN = "tok_demo_ABC123456789SECRET";

function printConfigHint() {
  console.log("Run backend with: uvicorn app.main:app --reload");
  console.log("Token length:", FAKE_INTERNAL_TOKEN.length);
}

printConfigHint();
