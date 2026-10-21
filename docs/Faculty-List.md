# Faculty Who Can Help

Both entries were checked against current public pages (linked), not just the Research Areas handout.

## 1. Prof. Manuel Egele: ECE, co-director of the Secure Systems Lab (SeclaBU)

**Why relevant.** His group works on fuzzing systems interfaces. One example is **HySe: Hypervisor Security through Component-Wise Fuzzing**, a Red Hat Collaboratory project that fuzzes the many interfaces a hypervisor exposes ([project page](https://research.redhat.com/blog/research_project/hyse-hypervisor-security-through-component-wise-fuzzing)). His Red Hat Research profile also lists **"No Grammar, No Problem: Towards Fuzzing the Linux Kernel without System-Call Descriptions"** ([profile](https://research.redhat.com/blog/project_member/manuel-egele/)). My Site A target has the same difficulty: the fuzzer must discover an input format (`SEARCH:<argument>`) with no grammar, only by reacting to what the server says.

**Question.** "When fuzzing without input descriptions, which feedback signal did you find most reliable for learning input structure? In black-box web fuzzing there is no coverage, so I plan to treat server error messages ('which validation stage rejected me') as a stand-in. Would you trust that as a coverage substitute, or is it too easy to saturate or mislead?"

## 2. Prof. Gianluca Stringhini: ECE, BU Security Lab (SeclaBU)

**Why relevant.** He is a senior author of **CVE-Genie**, an LLM multi-agent framework that reproduces real CVEs end to end. It reproduced 428 of 841 CVEs at an average cost of about $2.77 per CVE, and the authors point to fuzzer evaluation as a use for the resulting benchmark ([arXiv:2509.01835](https://arxiv.org/abs/2509.01835); a CCS 2026 version is hosted on the [lab site](https://seclab.bu.edu/people/gianluca/papers/cvegenie-ccs2026.pdf)). This bears directly on my LLM variant, which has to turn server feedback into better payloads under a cost limit.

**Question.** "My LLM variant generates batches of 50 to 100 payloads and gets about 10 to 20 feedback rounds under a 1,000-request budget. In CVE-Genie, how many refinement rounds did agents typically need before an exploit was verified, and would you budget my comparison by tokens or dollars (as you report cost per CVE) rather than by request count?"

---
*Optional next step: each question can be sent as an email under 150 words after reading the professor's latest abstract.*
