"""Bandit-assisted strategy: learn WHICH MUTATIONS pay off, online, with Thompson sampling.

How it differs from the other ML variant
----------------------------------------
``MLStrategy``  : generates 20 random candidates and a gradient-boosting model scores the *payloads*.
``BanditStrategy``: keeps a Beta posterior for every ARM = (field, mutation operator) and chooses which
                  mutation to apply by sampling those posteriors. No payload features, no sklearn,
                  very sample-efficient (it works from the first handful of requests).

Both start from zero knowledge, learn only during the run, and rate responses with the same client-side
signature, so they are directly comparable (the reward formulas differ, see below). The bandit is the same idea as MOpt in AFL++ (tutorial §5.2): adapt the
probability of each mutation operator from feedback.

Reward
------
Every response is reduced to the same client-side signature as ``MLStrategy`` (status + normalised start
of body). The reward is BINARY: 1 if the response kind is brand new, or rarer than the average kind seen so
far (``count / n < 1 / K`` with K distinct kinds); otherwise 0. Each arm used for the request gets
``alpha += r``, ``beta += 1 - r`` (a Beta-Bernoulli update).
Why not ``1/count`` like the ML variant? That label is only used by the regressor as a *ranking* signal;
a bandit needs a stable, bounded reward, and ``1/count`` makes a repeatedly-found rare response pay less
every time, so no arm could ever separate from the noise (measured: ~no better than the baseline).
The binary rule is scale-free, needs no tuning, and fades on its own once a "rare" kind stops being rare.

Fairness
--------
* Same mutation primitives, same wordlist, same 1-3 stacked mutations per request as the baseline.
* Only client-visible data (status, body) is used; server ground truth never is.
* Same request budget; extra cost is a few random draws per request.
"""
from __future__ import annotations

import random
import string
from collections import Counter

from .ml_strategy import signature
from .mutators import BOUNDARY

OPS = ("insert", "delete", "flip", "dup", "truncate", "dict_insert", "dict_replace",
       "boundary", "drop", "type")
_TYPE_CONFUSION = [None, 0, 1, True, [], {}, 3.14]


def apply_op(value, op: str, rng: random.Random, words: list[str]) -> str:
    """Apply one string-level operator. Mirrors fuzzer.mutators.mutate_string, but the operator is chosen
    by the caller (the bandit) instead of uniformly at random."""
    s = str(value)
    if op == "boundary" or not s:
        return rng.choice(BOUNDARY)
    i = rng.randrange(len(s))
    if op == "insert":
        return s[:i] + rng.choice(string.printable) + s[i:]
    if op == "delete":
        return s[:i] + s[i + 1:]
    if op == "flip":
        return s[:i] + rng.choice(string.printable) + s[i + 1:]
    if op == "dup":
        return s[:i] + s[i:] * 2
    if op == "truncate":
        return s[:i]
    if not words:
        return s
    w = rng.choice(words)
    return s[:i] + w + s[i:] if op == "dict_insert" else w          # dict_replace


def is_rare(count: int, n: int, n_kinds: int) -> bool:
    """True if a response kind seen ``count`` times (out of ``n`` responses, ``n_kinds`` kinds) is new or
    rarer than the average kind."""
    return count == 1 or count / n < 1.0 / n_kinds


class BanditStrategy:
    name = "bandit"

    def __init__(self, seed_request, words, seed, *, prior_alpha=1.0, prior_beta=1.0):
        self.seed_request, self.words, self.seed = seed_request, words, seed
        self.rng = random.Random(seed)
        self.first = True
        self.arms = [(f, op) for f in sorted(seed_request) for op in OPS]
        self.alpha = {a: float(prior_alpha) for a in self.arms}
        self.beta = {a: float(prior_beta) for a in self.arms}
        self.pulls: Counter = Counter()
        self._sig_counts: Counter = Counter()
        self._n = 0
        self._last_arms: list[tuple] = []
        self.prior = (prior_alpha, prior_beta)

    # ---- reproducibility metadata ----------------------------------------------------------
    @property
    def params(self) -> dict:
        return dict(learner="Thompson sampling, Beta posterior per (field, operator) arm",
                    n_arms=len(self.arms), prior=list(self.prior), stacked_mutations="1-3 (as baseline)",
                    reward="1 if response kind is new or rarer than the average kind, else 0",
                    arm_summary=self.arm_summary(10))

    # ---- strategy interface --------------------------------------------------------------
    def _choose_arm(self) -> tuple:
        # Thompson sampling: draw once from every posterior, play the best draw.
        return max(self.arms, key=lambda a: self.rng.betavariate(self.alpha[a], self.beta[a]))

    def next_payload(self) -> dict:
        if self.first:
            self.first = False
            self._last_arms = []
            return dict(self.seed_request)                    # calibration request
        req = dict(self.seed_request)
        used = []
        for _ in range(self.rng.randint(1, 3)):               # stack 1-3 mutations, like the baseline
            field, op = arm = self._choose_arm()
            used.append(arm)
            if op == "drop":
                req.pop(field, None)
            elif op == "type":
                req[field] = self.rng.choice(_TYPE_CONFUSION)
            else:
                req[field] = apply_op(req.get(field, ""), op, self.rng, self.words)
        self._last_arms = used
        return req

    def observe(self, rec: dict) -> None:
        sig = signature(rec)
        self._sig_counts[sig] += 1
        self._n += 1
        r = 1.0 if is_rare(self._sig_counts[sig], self._n, len(self._sig_counts)) else 0.0
        for arm in self._last_arms:                           # credit every arm used for this request
            self.alpha[arm] += r
            self.beta[arm] += 1.0 - r
            self.pulls[arm] += 1

    # ---- explainability ------------------------------------------------------------------
    def arm_summary(self, top: int = 5) -> list[dict]:
        """Arms ranked by posterior mean reward, with how often each was pulled (for the report)."""
        rows = [dict(field=f, operator=op, pulls=self.pulls[(f, op)],
                     posterior_mean=round(self.alpha[(f, op)] / (self.alpha[(f, op)] + self.beta[(f, op)]), 4))
                for (f, op) in self.arms]
        return sorted(rows, key=lambda r: -r["posterior_mean"])[:top]
