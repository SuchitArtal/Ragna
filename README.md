# Ragna

**AI-Powered Repository Analysis and Safe Coding Assistant**

A final-year engineering project that provides repository-level code understanding using large language models, retrieval systems, and agent-based reasoning.

---

## 🎯 Project Goals

- **Repository-level code understanding** — Intelligent analysis of entire codebases
- **Retrieval-augmented reasoning** — Semantic search over code with vector embeddings
- **Agent-based reasoning** — Multi-step code analysis and decision making (future)
- **Safe code modification** — Guardrails for secure code changes (future)
- **Isolated execution** — Sandbox environment for code validation (future)

---

## 📦 Phase 1: Repository Intelligence Engine (Current)

A repository-level code understanding assistant that:

- Indexes a codebase structure-aware
- Performs semantic search over code
- Retrieves relevant functions, classes, and methods
- Answers questions about repository code

### ✅ Implemented Features

- **Repository Loader** — Recursively scans code repositories (`.py`, `.js`, `.ts`, `.java`, `.cpp`, `.c`, `.go`)
- **Structure-Aware Parser** — Extracts functions, classes, and methods using AST parsing
- **Embeddings Pipeline** — Converts code chunks to vector embeddings using SentenceTransformers
- **Vector Store** — FAISS-backed semantic search over code
- **FastAPI Backend** — RESTful API foundation (minimal)

---

## 🛠 Tech Stack

| Component        | Technology                                |
| ---------------- | ----------------------------------------- |
| **Backend**      | Python, FastAPI                           |
| **Vector Store** | FAISS (CPU)                               |
| **Embeddings**   | SentenceTransformers (`all-MiniLM-L6-v2`) |
| **Code Parsing** | Python AST, Tree-sitter (planned)         |
| **Server**       | Uvicorn                                   |
| **LLM**          | OpenAI / Local LLM (planned)              |

---

## 📁 Project Structure

```

---

## 🚩 Phase 2: Deterministic Agent Loop (Added)

This repository now contains a prototype deterministic agent loop that performs
repeatable, safe analysis of the repository and can produce structured edit
proposals (it does not apply edits automatically).

What was implemented
- `app/retrieval/agent_loop.py` — the AgentLoop class and `EditProposal` dataclass
   - Tools implemented: `search_file(query)`, `read_file(path)`,
      `analyze_dependencies(path)`, `propose_edit(file_path, modification_description)`
   - Deterministic loop logic (think → choose tool → observe → update plan)
   - Logging of every step via `agent.log` and Python `logging`
   - Safety: `max_steps` and `max_recursion` to prevent infinite loops
   - Returns structured `EditProposal` objects (with `to_json()`)

Files added for the demo and testing
- `scripts/run_agent_demo.py` — creates a temporary workspace, runs the agent,
   prints the proposal JSON and agent logs (safe, read-only)
- `test_agent_loop.py` — pytest unit test that verifies a proposal is created

How the agent behaves (simple summary)
- The agent turns the task description into search tokens.
- It searches files deterministically for tokens, reads the first match,
   and inspects it for TODO/FIXME or missing local imports.
- If it finds a decisive issue, it returns an `EditProposal` describing what
   to change; otherwise it rotates tokens and repeats until `max_steps`.

Run the demo (safe, read-only)

1. Ensure your virtual environment is active (see Setup above).

2. Run the demo script:

```bash
python3 scripts/run_agent_demo.py
```

You should see a printed JSON edit proposal and a short agent log showing
what tools were invoked.

Programmatic usage example

```python
from app.retrieval.agent_loop import AgentLoop

agent = AgentLoop(workspace_root='path/to/workspace', max_steps=20)
result = agent.run_task('describe task here')
if result.get('solved'):
      proposal = result['proposal']  # EditProposal instance
      print(proposal.to_json())
else:
      print('No proposal; task not solved.')
```

Testing (unit tests)

Run the new test that exercises the agent loop:

```bash
pytest -q test_agent_loop.py
```

The test creates a temp workspace with a file containing `TODO` and ensures the
agent returns a proposal.

Notes and next steps
- The current `analyze_dependencies` is a simple regex scanner; for robust
   dependency analysis we can switch to Python's AST parsing.
- `propose_edit` currently builds a minimal append suggestion. If you want
   line-level patches or an apply helper (with backups/dry-run), I can add it.
- The loop is intentionally deterministic and conservative — it's a safe,
   review-first prototype.

If you want me to: I can implement an `apply_proposal()` helper that writes
changes to disk (with backup) and add tests for rollback and idempotency.

Ragna/
├── app/
│   └── retrieval/
│       ├── repo_loader.py      # Repository scanning
│       ├── parser.py            # AST-based code parsing
│       ├── embeddings.py        # Vector embedding generation
│       └── vector_store.py      # FAISS search engine
├── src/
│   └── ragna/
│       ├── api/                 # FastAPI routes
│       ├── config/              # Configuration
│       ├── core/                # Core modules
│       ├── agents/              # Agent logic (future)
│       ├── guardrails/          # Safety checks (future)
│       └── sandbox/             # Execution sandbox (future)
├── tests/                       # Unit tests
├── test_*.py                    # Integration tests
├── test_config.py               # Test configuration
├── requirements.txt             # Dependencies
└── README.md                    # This file
```

---


## 🚀 Quickstart (for absolute beginners)

Follow these steps to set up the project locally and run the safe agent + sandbox demo.

1) Clone the repository and open a terminal in the project root

```bash
git clone <repo-url>
cd Ragna
```

2) Create and activate a Python virtual environment

macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

3) Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

4) Run the demo agent (safe, read-only)

This script runs a deterministic demo agent that scans a temporary workspace and prints a proposed edit (it does not modify files on disk):

```bash
python3 scripts/run_agent_demo.py
```

5) Run the sandbox flow smoke test (CI-friendly, does not require Docker)

This test validates the full flow: agent proposal -> validation -> in-memory patch application. The test uses a mocked Docker manager so you can run it without Docker.

```bash
pytest -q tests/test_sandbox_flow.py
```

6) (Optional) Run the full test suite

Some tests require additional system-level dependencies (Docker, sentence-transformers). If you installed those, run:

```bash
pytest -q
```

## � Docker & sandbox execution

The sandbox executes validated proposals inside a Docker container to produce a true runtime validation. If Docker is not running or available the executor will still apply the patch in memory and return the validation results along with a helpful Docker error.

To enable Docker-backed execution on macOS:

1. Install Docker Desktop: https://www.docker.com/products/docker-desktop
2. Start Docker Desktop (open the app or run `open -a Docker`).
3. Wait until Docker indicates it is "running" (whale icon status).
4. Optionally pre-pull the Python image used by tests:

```bash
docker pull python:3.11
```

Quick check commands:

```bash
docker info
docker run --rm hello-world
```

If Docker can't be reached, you'll see an error like: "Cannot connect to the Docker daemon". The code handles this gracefully and surfaces the error in the executor output.

## ✅ How the pieces fit together (high-level flow)

1. Agent produces a proposal (JSON) with keys: `action`, `file_path`, `proposed_patch`, `reasoning`, `confidence`.
2. `app/agents/agent_output.parse_agent_output(...)` validates the JSON schema and that `proposed_patch` is a unified-diff using `PatchParser`.
3. `GuardrailPipeline.validate_edit(...)` performs patch parsing, file-path safety checks, secret scanning, and syntax simulation.
4. `SandboxExecutor.execute_edit(repo_root, validated_proposal)` applies the patch in memory with `PatchApplier`. If guardrails allow, it attempts to run a container using `DockerManager` to execute a runtime command; it captures stdout/stderr and returns a structured result.

## 🔧 Troubleshooting

- If `pytest` fails due to missing `sentence_transformers`, either install the extra dependencies listed in `requirements.txt` or run only the focused sandbox test:

```bash
pytest -q tests/test_sandbox_flow.py
```

- If Docker commands fail with "Cannot connect to the Docker daemon": make sure Docker Desktop is running and you have necessary permissions. Restart Docker Desktop if required.

- If you accidentally commit caches, add the following to `.gitignore`:

```
__pycache__/
*.pyc
.DS_Store
```

## 🧪 Developer commands (summary)

Run demo (read-only):

```bash
python3 scripts/run_agent_demo.py
```

Run the sandbox smoke test (no Docker required):

```bash
pytest -q tests/test_sandbox_flow.py
```

Run the full suite (may require extra deps):

```bash
pytest -q
```

---

## 🏃 Run FastAPI Server

```bash
uvicorn ragna.api.main:app --reload --app-dir src
```

Access health check:

```
http://localhost:8000/health
```

---

## 🗺 Roadmap

### Phase 2: Agent-Based Reasoning

- Multi-step code analysis agent
- Context-aware question answering
- Code recommendation system

### Phase 3: Safe Code Modification

- Guardrails for code edits
- Static analysis integration
- Diff generation and validation

### Phase 4: Sandbox Execution

- Isolated code execution environment
- Test execution and validation
- Security boundary enforcement

---

## 📝 Example Workflow

```python
from app.retrieval.repo_loader import load_repository
from app.retrieval.parser import parse_repository
from app.retrieval.embeddings import embed_chunks
from app.retrieval.vector_store import VectorStore

# Load repository
repo = load_repository("/path/to/repo")

# Parse into chunks
chunks = parse_repository(repo)

# Generate embeddings
vectors, metadata = embed_chunks(chunks)

# Initialize search
store = VectorStore(dim=len(vectors[0]))
store.add_embeddings(vectors, metadata)

# Semantic search
query_vec, _ = embed_chunks([{"code": "database connection"}])
results = store.search(query_vec[0], top_k=5)

for result in results:
    print(result["name"], result["file_path"])
```

---

## 🧑‍💻 Development

### Code Style

- Clean, modular architecture
- Production-like structure
- Clear separation of components
- Comprehensive docstrings

### Logging

All modules include structured logging for debugging and monitoring.

---

## 📄 License

This is a final-year engineering project.

---

## 🙏 Acknowledgments

- **FastAPI** — Modern Python web framework
- **FAISS** — Efficient similarity search
- **SentenceTransformers** — State-of-the-art embeddings
- **Hugging Face** — Model hosting and ecosystem

---

## 📧 Contact

For questions or feedback about this project, please reach out to the development team.
