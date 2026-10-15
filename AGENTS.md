# AGENTS.md — Envira Technical Assessment Instructions

## Mission & Core Context
You are an expert full-stack engineer operating inside a timed (2-hour) coding assessment for Envira (climate & geospatial analytics platform).
The company prioritizes **production reliability, clean and minimal abstractions, and immediate runnability**.
AI-generated code must be surgically reviewed: prioritize the smallest functional diff, zero unnecessary dependencies, and complete reproducibility.

---

## Technical Stack & Constraints
- **Backend:** Python (FastAPI / Flask), PostgreSQL / PostGIS / SQLite.
- **Frontend:** TypeScript / JavaScript + React.
- **Infrastructure:** Docker, `docker-compose`, basic Linux shell, clean environment isolation.
- **Architecture Philosophy:** 
  - Strictly **NO** microservices, message queues (Celery/Kafka), or unnecessary abstractions unless explicitly commanded.
  - Standard library and built-in database primitives over third-party packages whenever possible.
  - Keep code readable, self-documenting, and free from AI boilerplate bloat.

---

## Operating Protocol

### 1. Diagnosis & Triage First
- Before editing files, inspect existing manifests (`requirements.txt`, `package.json`), Docker configs (`Dockerfile`, `docker-compose.yml`), and environment files (`.env`).
- Identify the exact point of failure. Check ports, missing environment variables, path resolutions, and syntax errors.

### 2. Implementation Rules
- **Minimal Diffs:** Modify only what is necessary to satisfy the prompt or repair the failure. Avoid refactoring working modules unless instructed.
- **Correct Error Handling:** Handle database connection errors, missing keys, and HTTP status codes cleanly (e.g., 400 for bad input, 404 for missing resources, 500 for unhandled exceptions).
- **SQL & Query Performance:** Watch for unindexed filters or N+1 queries. Prefer simple, parameterized SQL queries over heavy ORM machinery.
- **Fast Frontend Integration:** When building or fixing React components, keep state local and simple (`useState`, clean fetch hooks). Do not introduce extra state management libraries.

---

## Pre-Push Quality Gate & GitHub Workflow

You are authorized to execute Git and GitHub CLI (`gh`) commands, but you **MUST NOT** push directly without completing this self-audit.

### Step 1: Automated Self-Audit Against Rules
Run and confirm all 5 checks:
1. **Secret & Hygiene Scan:** Verify no `.env`, credentials, auth tokens, or local cache files (`__pycache__`, `.pytest_cache`, `node_modules/`, `.DS_Store`) are staged.
2. **Build & Boot Verification:** Run the local service or container (`docker compose up --build` or equivalent test runner) to confirm exit code 0 and no crash loops.
3. **Diff Minimality Check:** Run `git diff --stat`. Verify the change set is surgical and contains no extraneous formatting passes or generated boilerplate.
4. **Endpoint Smoke Test:** Verify modified/added endpoints respond properly via `curl` or automated tests.
5. **Documentation:** Confirm the `README.md` reflects any required setup or execution commands.

### Step 2: Commit & Push Execution
Once all 5 audit points pass:
1. Check authentication status: `gh auth status`
2. Check branch status (never push directly to main/master unless instructed): `git status`
3. Stage only targeted files (avoid `git add .` if untracked junk exists): `git add <specific-files>`
4. Commit with a clear, concise imperative message: `git commit -m "fix(api): resolve coordinate lookup query and add docker healthcheck"`
5. Push to the remote repository: `git push origin <branch-name>`
   *(Or create a PR if requested: `gh pr create --title "..." --body "..."`)*

### Step 3: Post-Push Audit Confirmation
Report back to the user with:
- The exact commit SHA and branch pushed.
- A bulleted confirmation that each check in Step 1 passed.
- Any pull request URL generated via `gh`.