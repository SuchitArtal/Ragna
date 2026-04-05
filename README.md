# Ragna

Ragna is a CLI-based AI coding assistant for safe repository analysis, edit proposal validation, and isolated execution.

It is designed as a safety-first workflow for AI-assisted code changes:

1. Understand repository context
2. Generate structured edit proposals
3. Validate proposals with guardrails
4. Execute in a sandbox before real application

---

## 1) Project Description

Ragna combines retrieval, agent reasoning, validation guardrails, and sandboxed execution to support safer AI-driven code modification workflows.

---

## 2) Key Features

- Repository-level retrieval with embeddings + FAISS
- Agent-based reasoning for structured edit proposals
- Guardrail validation pipeline:
  - patch format checks
  - syntax checks
  - secret detection
  - path safety and repo-boundary enforcement
- Sandbox execution workflow with Docker isolation
- Interactive CLI built with Typer + Rich

---

## 3) System Architecture

High-level flow:

CLI -> RAG -> Agent -> Guardrails -> Sandbox -> Docker

```text
+------+   +-----+   +-------+   +------------+   +---------+   +--------+
| CLI  |-> | RAG |-> | Agent |-> | Guardrails |-> | Sandbox |-> | Docker |
+------+   +-----+   +-------+   +------------+   +---------+   +--------+
```

---

## 4) Installation

### Python setup

```bash
python -m venv venv
source venv/Scripts/activate   # Git Bash on Windows
```

### Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Docker requirement

Install Docker Desktop (or compatible Docker engine) and verify:

```bash
docker info
```

### Install Ragna as CLI

```bash
pip install -e .
```

---

## 5) Usage

### Commands

```bash
ragna analyze <path>
ragna ask "<query>"
ragna apply
ragna run "<command>"
ragna status
```

### Interactive mode

```bash
ragna
```

Example:

```text
ragna> analyze .
ragna> ask "where is auth logic"
ragna> fix login bug
ragna> apply
ragna> run "python --version"
ragna> status
ragna> exit
```

---

## 6) Example Workflow

1. Analyze repository:

```text
ragna> analyze .
```

2. Ask repository question:

```text
ragna> where is authentication logic
```

3. Generate and apply fix safely:

```text
ragna> fix insecure print
ragna> apply
```

4. Run sandbox command:

```text
ragna> run "python --version"
```

---

## 7) Edit Proposal Contract

```json
{
  "action": "edit_file",
  "file_path": "relative/path/to/file.py",
  "proposed_patch": "unified diff text",
  "reasoning": "why this change is proposed",
  "confidence": 0.0
}
```

Contract notes:
- `file_path` must be repository-relative
- `proposed_patch` must be unified diff
- `confidence` is expected in `[0.0, 1.0]`

---

## 8) Guardrails

Before execution, proposals are checked for:

- Patch validity and hunk parsing
- Safe file targeting within repository root
- Secret leakage in added lines
- Syntax validity of simulated result

If critical checks fail, the proposal is rejected.

---

## 9) Sandbox and Docker

Ragna executes approved proposals in a sandbox flow:

- Patch application occurs in memory
- Runtime execution is performed in Docker
- CLI surfaces stdout, stderr, and status

This reduces risk before any real repository write workflow.

---

## 10) Project Structure

```text
Ragna/
├── app/
│   ├── retrieval/      # repo loading, parsing, embeddings, vector store, agent helpers
│   ├── guardrails/     # validators and guardrail pipeline
│   └── sandbox/        # patch applier, sandbox executor, docker manager
├── src/ragna/          # installable package source (CLI entrypoint)
├── ragna/              # local/dev CLI source copy
├── tests/              # test suite
├── scripts/            # demo and utility scripts
├── pyproject.toml      # packaging + console entrypoint
└── requirements.txt    # dependencies
```

---

## 11) Development Notes

- Install in editable mode during development:

```bash
pip install -e .
```

- Run CLI help:

```bash
ragna --help
```

- Prefer modular components and independent testability.

---

## 12) Limitations

- Some RAG/agent logic is intentionally placeholder-level
- Multi-language syntax validation is not complete
- Sandbox workflow is still evolving for production hardening
- Session state is currently in-memory

---

## 13) Future Work

- Stronger agent planning and proposal quality controls
- Broader language support
- Persistent indexing and retrieval state
- Richer patch simulation and conflict diagnostics
- Policy-driven guardrail configuration
- Improved sandbox orchestration profiles

---

## 14) License

TBD
