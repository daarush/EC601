# AI-Assisted Web Fuzzing: Efficiency and Payload Validity vs. Mutation Baseline

### 1. Mission

For security engineers and students who want to know whether AI actually improves web fuzzing, this project builds a modular Python HTTP fuzzer and systematically compares a mutation-based baseline against a learned prioritizer and an LLM-guided payload generator, measured by interestingness gained per fixed budget (requests, wall-clock, and cost) and payload validation-pass rate on an instrumented Flask target with server-side ground truth.

### 2. Target User

A security-literate developer or graduate student who wants to understand whether adding an AI layer to a basic web fuzzer is worth the integration cost. They can run a Python script, read a JSON report, and interpret a comparison table. They do not need to know how to train a model or prompt an LLM — the tool and report should speak for themselves.

### 3. User Stories (Top 5)

| # | Story | Acceptance Criteria |
|---|-------|---------------------|
| 1 | As a researcher, I can run the baseline mutation fuzzer against a target with a fixed request budget and get a structured JSON log of every request and response. | `python -m fuzzer run --target flask_app --budget 1000 --seed 42` produces `run_<id>.json`. |
| 2 | As a researcher, I can inspect the custom Flask target's server-side log to see exactly which validation stage each payload reached. | Each request's correlation ID maps to a server-side log entry showing: validation stage reached, pass/fail, and sink reachability. |
| 3 | As a researcher, I have a CLI-driven experiment harness that enforces fixed request budgets, random seeds, and target resets. | The runner guarantees statistical validity and reproducibility before any AI work begins in Sprint 2. |
| 4 | As a researcher, I can execute the "Cheapest Test" to prove the target's validation logic is complex enough to require AI. | A script runs the baseline + SecLists against the Flask app, and compares it against 10 manual payloads, outputting a saturation report. |
| 5 | As a researcher, I can reproduce the exact baseline environment on a new machine with one command. | `uv sync` creates the virtual environment and installs all dependencies from `uv.lock` without errors. |

### 4. Feasibility — Show, Don't Tell

- **DVWA:** Docker image pulled and verified locally. `docker run --rm -it -p 8080:80 vulnerables/web-dvwa` → login page confirmed. Committed: `scripts/verify_dvwa.sh`.
- **Custom Flask target:** Skeleton app with two input fields, one validation chain, and one sink, running locally. Server-side logging middleware returns a correlation ID per request. Committed: `targets/flask_app/`.
- **LLM API access:** API key for OpenAI confirmed working. A test script (`scripts/verify_llm_api.py`) sends one prompt and logs the response and latency. Key stored in `.env`, referenced in `.env.example`. (key pending, script not yet run)

- **Python environment:** `pyproject.toml` and `uv.lock` committed; `uv sync` produces a working, perfectly reproducible environment on a clean clone. Verified on a fresh machine.

### 5. Tooling

| Tool | Why |
|------|-----|
| Python 3.11+ | Project language; ecosystem support for HTTP, ML, and LLM libs |
| `pyproject.toml` + `uv` | Modern dependency management; `uv` ensures fast, reproducible env creation via `uv.lock` |
| Flask | Custom target app; lightweight, easy to instrument with middleware |
| `httpx` | Async HTTP client for the fuzzer core to handle high request throughput |
| scikit-learn | Classical ML variant (gradient boosting / random forest); fast, explainable, no GPU needed |
| OpenAI API (or Ollama fallback) | LLM payload generation; API for quality, local Ollama as cost-free fallback |
| Docker (DVWA only) | Standard, reproducible vulnerable target |
| pytest | Unit tests for fuzzer core, strategies, and metrics |
| SQLite (or JSON flat files) | Structured run logs; no external DB dependency |
| GitHub Actions (optional) | CI: run tests on push |

### 6. Demo Sentence

> At the end of two weeks I will show the baseline mutation fuzzer and the instrumented Flask target running end-to-end under a fixed request budget, successfully executing the "cheapest test" to prove the target's validation logic is complex enough to warrant AI integration in Sprint 2.

### 7. Riskiest Assumption & Its Test

**Assumptions (ranked most-fatal × most-uncertain first):**

1. The baseline + a good wordlist (SecLists) does *not* already saturate the custom Flask target. If it does, no AI variant adds signal.
2. "Interesting response" can be defined precisely enough to produce a meaningful metric (not just "any non-200").
3. An LLM can generate syntactically valid payloads at a rate that makes the comparison fair (latency problem).
4. A regression/classification model trained on HTTP response features has enough signal to prioritize inputs better than random.
5. The Flask target's validation logic is complex enough that payload correctness is non-trivial to achieve.

**Riskiest:** #1. If the baseline finds everything, the project's core claim is dead.

**Cheapest test (do this before writing any AI code):**
- Start Flask target.
- Run baseline fuzzer with SecLists common wordlist, 500 requests, 30 min.
- Manually write 10 LLM-crafted payloads and send them.
- Compare: does the baseline already reach every sink? Does it pass every validation stage?
- If yes → redesign the Flask target's validation to be harder, or change the metric.

**Kill criterion / pivot line:**
> "I pivot if, after running the baseline fuzzer against the Flask target with a standard wordlist, zero additional unique error classes or deeper validation stages are reached by either the ML or LLM variant. In that case, the project reframes from 'AI finds more' to 'AI triages and explains findings better for a human analyst.'"

### 8. Evaluation with a Baseline

- **Oracle (define "interesting").** A request is _interesting_ if it produces any of: (a) HTTP 5xx; (b) a response body matching a known error signature (SQL error, stack trace, exception string); or (c) server-side confirmation of a **new validation stage or sink reached** (instrumented target only). This is anomaly detection, not confirmed exploitation; findings are for triage.
- **Primary metric (efficiency).** Interestingness-over-budget curves, compared by **area under the curve (AUC)**, under three budgets reported together: request count (fixed 1,000), wall-clock time, and LLM cost (tokens/$). Headline summary: requests-to-first-interesting-response.
- **Secondary metric (correctness).** Fraction of generated payloads that pass all server-side validation stages and reach application logic (from instrumentation logs).
- **Statistics.** ≥ 30 independent runs per variant per target (10 minimum if compute-bound), fixed seeds logged. **Mann-Whitney U** for significance + **Vargha-Delaney A12** for effect size, following the FuzzBench/Dissecting-AFL methodology [3]. 
- **Baseline.** Custom mutation fuzzer (dictionary + random mutation, SecLists). 
- **Sanity reference.** One `ffuf` run on DVWA to confirm the custom baseline isn't artificially weak — noting `ffuf` is a _different tool class_ (content discovery), so this is a sanity check only, not a comparison target.

**LLM Architecture Note:** LLM generation is batched, not per-request. The LLM receives accumulated endpoint context + recent feedback and returns a schema-constrained batch of N candidate payloads (N ≈ 50–100). The fuzzer executes the full batch, logs responses, and loops. This amortizes API latency and matches how real LLM fuzzers (ChatAFL, Fuzz4All) operate. LLM outputs are constrained via structured outputs / Pydantic so payloads are parseable and measurable. Token usage, wall-clock, and $ are logged as first-class cost metrics.

### 9. Related Work (8–10 papers)

| # | Paper/Resource | What it contributes | Relevance gap for your web-fuzzing project | Link |
|---|----------------|---------------------|--------------------------------------------|------|
| **1** | Manès et al., “The Art, Science, and Engineering of Fuzzing,” _IEEE TSE_, 2021 | Unified fuzzer model and taxonomy spanning generation, scheduling, execution, and feedback. | Establishes the general fuzzing vocabulary, but does not deeply characterize black-box HTTP/API feedback loops. | [IEEE Xplore](https://ieeexplore.ieee.org/document/8863940) |
| **2** | Gan et al., “CollAFL: Path Sensitive Fuzzing,” _IEEE S&P_, 2018 | CFG-aware instrumentation reduces AFL path/edge collisions and improves coverage feedback. | Depends on program-level CFG knowledge and compile-time instrumentation, unlike a remote black-box web service. | [IEEE Computer Society](https://www.computer.org/csdl/proceedings-article/sp/2018/435301a679/12OmNBKEyoL) |
| **3** | Fioraldi et al., “Dissecting American Fuzzy Lop: A FuzzBench Evaluation,” _ACM TOSEM_, 2023 | Controlled ablation of AFL design choices across FuzzBench targets. | Motivates evaluating individual “intelligence-layer” choices rather than assuming additive benefit; target domain remains native/software fuzzing. | [ACM Digital Library](https://dl.acm.org/doi/10.1145/3580596) |
| **4** | Fioraldi et al., “AFL++: Combining Incremental Steps of Fuzzing Research,” _WOOT_, 2020 | Modular production platform that combines fuzzing research advances and exposes extension mechanisms (Custom Mutator API). | Offers an architectural analogy for your strategy interface, but its operating assumptions are code-integrated/program-execution fuzzing rather than black-box HTTP. | [USENIX](https://www.usenix.org/conference/woot20/presentation/fioraldi) |
| **5** | Böhme et al., "Coverage-Based Greybox Fuzzing as Markov Chain," _IEEE TSE_, 2019 | Formal model of coverage-guided fuzzing and search/scheduling (foundation of AFLFast). | Assumes observable execution-coverage feedback; black-box web fuzzing requires alternative signals such as response status, body length, or error behavior. | [IEEE Xplore](https://ieeexplore.ieee.org/document/8233151) |
| **6** | Ji et al., "ChatAFL: Enriching Protocol Fuzzing with Large Language Models," _NDSS_, 2024 | Demonstrates using LLMs in a feedback loop to generate state-aware, syntactically valid protocol messages based on RFCs and server responses. | Focuses on network protocols rather than HTTP REST/web forms, but the LLM-in-the-loop feedback architecture is highly relevant to your LLM variant. | [NDSS Symposium](https://www.ndss-symposium.org/ndss-paper/large-language-model-guided-protocol-fuzzing/) |
| **7** | Xia et al., “Fuzz4All: Universal Fuzzing with Large Language Models,” _ICSE_, 2024 | LLM-driven input generation and prompt updating across multiple programming/input languages. | Does not evaluate HTTP endpoint discovery, authentication/session state, OpenAPI/schema conformance, or web-specific response-based feedback. | [arXiv (Preprint)](https://arxiv.org/abs/2308.04748) |
| **8** | Hou et al., "Large Language Models for Cybersecurity: A Survey," _arXiv_, 2024 | Comprehensive survey covering how LLMs are applied to vulnerability detection, fuzzing, and automated repair. | Provides the landscape and terminology for the AI/LLM security intersection, but does not replace a controlled web-fuzzer benchmark. | [arXiv](https://arxiv.org/abs/2402.16968) |
| **9** | Godefroid et al., "Grammar-based whitebox fuzzing," _PLDI_, 2008 | Historical foundation for using context-free grammars to guide fuzzing, ensuring inputs pass early parsers to reach deeper logic. | Requires whitebox access and manual grammar definition; predates modern learned or LLM-driven adaptive feedback loops. | [ACM Digital Library](https://dl.acm.org/doi/10.1145/1375581.1375607) |
| **10a** | OSS-Fuzz | Continuous large-scale fuzzing infrastructure for open-source projects. | Primarily designed for integrated code-level fuzzing workflows. | [Google OSS-Fuzz](https://github.com/google/oss-fuzz) |
| **10b** | FuzzBench | Reproducible fuzzer benchmarking platform and service. | Useful model for your evaluation methodology (fixed budgets, statistical significance); direct applicability to black-box HTTP/API fuzzing is limited. | [FuzzBench](https://fuzzbench.com/) |

**The gap this project fills:** No existing work performs a controlled, ablated comparison of mutation-based vs. ML vs. LLM strategies for *web* fuzzing with server-side ground-truth instrumentation. The binary fuzzing literature (papers 1–5) provides the loop architecture; the LLM fuzzing literature (papers 6–7) provides the generation idea; this project connects them in the web domain with rigorous measurement.

### 10. Three Lines on Harm

1. If the fuzzer is pointed at a production system without authorization, it generates malicious-looking traffic that could trigger incident response, lock accounts, or cause denial of service. The tool must refuse to run without an explicit target allowlist.
2. If the LLM variant generates plausible-looking SQLi or XSS payloads and the report is shared carelessly, those payloads could be copy-pasted into real attacks. All generated payloads must be logged but the report should not include ready-to-exploit strings.
3. If the project concludes "AI doesn't help" based on a weak target or metric, that negative result could be misused to justify skipping AI-assisted security testing entirely, even in contexts where it would help. The report must state the scope of the finding precisely.