# Graph Report - agentic pr reviewer  (2026-11-11)

## Corpus Check
- Corpus is ~27,099 words - fits in a single context window. You may not need a graph.

## Summary
- 745 nodes · 1994 edges · 29 communities (19 shown, 10 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 273 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- LLM Provider Adapters
- Frontend Review Page
- Specialist Reviewers
- Persistence and Review Jobs
- AST Security Checks
- Settings and Config
- Dependency Manifests
- Frontend App Shell
- Prompt Construction
- REST API Routes
- Docker Compose Config
- Diff Model Types
- Input Validation
- TypeScript Config
- Eval Harness
- Diff Parser Tests
- Diff Parser Core
- AST Check Tests
- Fixture Builder
- ESLint Config
- Next.js Config
- Paste Request Schema
- PostCSS Config

## God Nodes (most connected - your core abstractions)
1. `Finding` - 38 edges
2. `parse_diff()` - 38 edges
3. `ReviewService` - 38 edges
4. `SQLiteReviewRepository` - 28 edges
5. `run_static_analysis()` - 27 edges
6. `Settings` - 25 edges
7. `JobStatus` - 24 edges
8. `ParsedDiff` - 24 edges
9. `ReviewJobView` - 23 edges
10. `validate_diff_text()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `Verification status` --conceptually_related_to--> `pytest 8.3.4`  [AMBIGUOUS]
  README.md → backend/requirements-dev.txt
- `Technology stack` --references--> `httpx 0.28.1`  [EXTRACTED]
  README.md → backend/requirements.txt
- `render_changed_python()` --uses--> `ParsedDiff`  [INFERRED]
  backend/app/agents/prompts.py → backend/app/services/diff_parser.py
- `run_reviewer()` --uses--> `LLMError`  [INFERRED]
  backend/app/agents/reviewers.py → backend/app/agents/providers.py
- `_NullProvider` --uses--> `LLMResponse`  [INFERRED]
  backend/eval/run_eval.py → backend/app/agents/providers.py

## Import Cycles
- None detected.

## Communities (29 total, 10 thin omitted)

### Community 0 - "LLM Provider Adapters"
Cohesion: 0.05
Nodes (51): AnthropicProvider, build_provider(), _HTTPProviderBase, LLMError, LLMProvider, LLMRequest, LLMResponse, _mock_findings() (+43 more)

### Community 1 - "Frontend Review Page"
Cohesion: 0.06
Nodes (70): Home(), cancelActive(), startReview(), tick(), messageOf(), RunDetails(), TERMINAL, View (+62 more)

### Community 2 - "Specialist Reviewers"
Cohesion: 0.08
Nodes (48): _added_lines(), parse_review_response(), strip_code_fences(), Category, Severity, SourceType, TestStatus, VerificationStatus (+40 more)

### Community 3 - "Persistence and Review Jobs"
Cohesion: 0.07
Nodes (25): _iso(), ReviewRepository, SQLiteReviewRepository, StageName, StageStatus, ErrorInfo, FileSummary, ReviewerRun (+17 more)

### Community 4 - "AST Security Checks"
Cohesion: 0.07
Nodes (27): _call_name(), _is_constant_string(), _is_dynamic_sql(), _literal_text(), run_ast_checks(), emit(), RawDiagnostic, PythonContext (+19 more)

### Community 5 - "Settings and Config"
Cohesion: 0.07
Nodes (15): _env_float(), _env_int(), _env_str(), Settings, configure_logging(), get_logger(), JsonFormatter, redact() (+7 more)

### Community 6 - "Dependency Manifests"
Cohesion: 0.07
Nodes (27): bandit 1.8.0, pytest 8.3.4, pytest-asyncio 0.24.0, fastapi 0.115.6, httpx 0.28.1, langgraph 0.2.60, pydantic 2.10.4, python-multipart 0.0.20 (+19 more)

### Community 7 - "Frontend App Shell"
Cohesion: 0.06
Nodes (35): metadata, dependencies, next@14.2.20, react-dom@18.3.1, devDependencies, autoprefixer@10.4.20, eslint@8.57.1, eslint-config-next@14.2.20 (+27 more)

### Community 8 - "Prompt Construction"
Cohesion: 0.14
Nodes (20): _escape_fence(), render_changed_python(), repair_prompt(), review_user_prompt(), ReviewerOutcome, run_reviewer(), build_review_graph(), _dedup() (+12 more)

### Community 9 - "REST API Routes"
Cohesion: 0.17
Nodes (17): cancel_review(), create_review(), get_findings(), get_report(), get_review(), health(), _input_error(), list_reviews() (+9 more)

### Community 10 - "Docker Compose Config"
Cohesion: 0.10
Nodes (21): NEXT_PUBLIC_API_BASE_URL, build, env_file, environment, ports, volumes, args, context (+13 more)

### Community 11 - "Diff Model Types"
Cohesion: 0.15
Nodes (6): FileDiff, start_file(), build_python_context(), build_snippet(), is_python_candidate(), PythonContextTests

### Community 12 - "Input Validation"
Cohesion: 0.17
Nodes (4): InputValidationError, sanitize_display_name(), validate_diff_text(), InputValidationTests

### Community 13 - "TypeScript Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 14 - "Eval Harness"
Cohesion: 0.28
Nodes (9): CaseResult, _diff_text(), load_cases(), main(), _NullProvider, Prediction, run_ast_mode(), run_full_mode() (+1 more)

### Community 15 - "Diff Parser Tests"
Cohesion: 0.29
Nodes (3): parse_diff(), DiffParserTests, read()

### Community 16 - "Diff Parser Core"
Cohesion: 0.20
Nodes (6): DiffParseError, Hunk, HunkLine, _parse_git_header(), _strip_prefix(), _validated_path()

### Community 17 - "AST Check Tests"
Cohesion: 0.32
Nodes (3): AstChecksTests, diagnostics_for(), single_file_diff()

### Community 18 - "Fixture Builder"
Cohesion: 0.48
Nodes (3): main(), unified(), write_benchmark()

## Ambiguous Edges - Review These
- `pytest 8.3.4` → `Verification status`  [AMBIGUOUS]
  README.md · relation: conceptually_related_to

## Knowledge Gaps
- **7 isolated node(s):** `next/core-web-vitals`, `uvicorn[standard] 0.32.1`, `python-multipart 0.0.20`, `pytest-asyncio 0.24.0`, `Features` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 218 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_diff()` connect `Diff Parser Tests` to `LLM Provider Adapters`, `Specialist Reviewers`, `AST Security Checks`, `Diff Model Types`, `Input Validation`, `Eval Harness`, `Diff Parser Core`, `AST Check Tests`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `Finding` (e.g. with `suggest_test()` and `suggest_tests()`) actually correct?**
  _`Finding` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `next/core-web-vitals`, `uvicorn[standard] 0.32.1`, `python-multipart 0.0.20` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `LLM Provider Adapters` be split into smaller, more focused modules?**
  _Cohesion score 0.051096491228070175 - nodes in this community are weakly interconnected._
- **Why does `ReviewService` connect `Persistence and Review Jobs` to `LLM Provider Adapters`, `Specialist Reviewers`, `AST Security Checks`, `Settings and Config`, `Prompt Construction`, `REST API Routes`, `Eval Harness`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `ReviewService` (e.g. with `_service()` and `LLMProvider`) actually correct?**
  _`ReviewService` has 18 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `pytest 8.3.4` and `Verification status`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._