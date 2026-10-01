### 1. Prof. Manuel Egele (ECE / BU Secure Systems Lab)

**Why he is relevant:** 
Prof. Egele’s research focuses heavily on systems security, binary analysis, and automated vulnerability discovery. His recent Red Hat Collaboratory award-winning project, *"HySe: hypervisor security through component-wise fuzzing"* (2024), explores bypassing complex execution states in hypervisors through targeted fuzzing. This directly mirrors my project's challenge of bypassing deep semantic validation in web apps where naive mutation fuzzers get rejected by input filters before ever reaching the vulnerable sink.

**Specific Question:** 
"In my black-box web fuzzer, I instrument a Flask target to log 'validation stages reached' via correlation IDs to prove a payload passed semantic checks (sink reachability) rather than just triggering a superficial HTTP 5xx crash. Real-world web logic flaws often return HTTP 200 upon successful exploitation. When designing feedback loops for component-wise fuzzing in *HySe*, how did you mathematically weight 'state/sink reachability' against 'crash triggering' in your reward function when successful state corruption does not result in a traditional program crash?"

### 2. Prof. Gianluca Stringhini (ECE / BU Security Lab - SeclaBU)

**Why he is relevant:** 
Prof. Stringhini’s research bridges cybersecurity, web security, and the evaluation of AI in adversarial contexts. His 2026 paper, *"CVE-Genie: An LLM-Based Multi-Agent Framework for Reproducing CVEs"*, demonstrates using multi-agent LLMs to iteratively reason about and reproduce vulnerabilities. This directly informs my project's LLM-guided payload generation strategy, specifically how an LLM requires iterative feedback to refine attack vectors based on server responses.

**Specific Question:** 
"I am batching LLM-generated payloads (50–100 per loop) to amortize API latency, but a strict 1,000-request testing budget limits my feedback loop to roughly 10–20 iterations. Based on your multi-agent architecture in *CVE-Genie*, is 10 iterations enough for an LLM to meaningfully refine its payload generation based on black-box HTTP error messages? Or, based on your evaluation of LLM reasoning limits, should I abandon fixed-request budgets in favor of fixed-token or wall-clock budgets to allow the model sufficient iterations to 'think'?"