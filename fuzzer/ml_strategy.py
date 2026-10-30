"""ML-assisted strategy: an online-trained candidate scorer.

What it does
------------
Each turn the strategy draws ``n_candidates`` mutations (exactly the mutator the baseline uses),
asks a model which one is most likely to produce a *rare* response, and sends only that one.
The model starts with no knowledge: it is trained from scratch, during the run, on the
(payload features -> response rarity) pairs it has observed on this target. Nothing is
pretrained and nothing is shared between runs.

Reward = response rarity
------------------------
Every response is reduced to a client-side *signature* (status + normalised start of the body).
The label of an observation is ``1 / (number of times that signature has been seen)``.
Common rejections get tiny labels; rare responses (a new validation stage, a sink hit, a 500
with a new error class) get large ones. This is novelty search in the sense of AFL's
"keep what is new" (tutorial §4) and AFLFast's rare-path scheduling, and it needs no server-side
information: on a validation chain the deeper stages are reached less often, so their
messages are rarer, which gives the model a gradient toward depth *without* ever seeing depth.

Labels are recomputed from the *current* counts at every retrain, so they stay consistent as
the run progresses.

Fairness properties (asserted in tests)
---------------------------------------
* Until the first fit, payloads are identical to ``BaselineStrategy`` with the same seed.
* Only client-visible data (status, body, payload) is used. Server ground truth never is.
* The model sees the same request budget as the baseline; extra cost is CPU only.
"""
from __future__ import annotations

import random
import re
from collections import Counter

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from .features import extract_features, feature_names
from .mutators import mutate_request

WARMUP = 10          # observations before the first fit (calibration request counts as one)
N_CANDIDATES = 20    # mutations scored per request once a model exists
RETRAIN_EVERY = 10
EPSILON = 0.10       # probability of ignoring the model and sending a random candidate
MAX_TRAIN = 2000     # sliding window cap keeps retrain cost bounded
BODY_PREFIX = 48     # characters of the response body kept in the signature

MODEL_PARAMS = dict(n_estimators=50, max_depth=3, learning_rate=0.1, min_samples_leaf=3, subsample=1.0)

_NORMALISE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}|\d+")


def signature(rec: dict) -> tuple:
    """Client-side response signature: status code + digit/UUID-normalised start of the body."""
    body = _NORMALISE.sub("#", rec.get("body") or "")[:BODY_PREFIX]
    return (rec.get("status"), body)


def rarity_reward(count: int) -> float:
    """Label for a response whose signature has been seen ``count`` times (>=1)."""
    return 1.0 / max(1, count)


class MLStrategy:
    name = "ml"

    def __init__(self, seed_request, words, seed, *, warmup=WARMUP, n_candidates=N_CANDIDATES,
                 retrain_every=RETRAIN_EVERY, epsilon=EPSILON):
        self.seed_request, self.words, self.seed = seed_request, words, seed
        self.warmup, self.n_candidates = warmup, n_candidates
        self.retrain_every, self.epsilon = retrain_every, epsilon
        self.rng = random.Random(seed)       # same stream as BaselineStrategy for the same seed
        self.first = True
        self.model = None
        self._X: list[list[float]] = []
        self._sigs: list[tuple] = []
        self._sig_counts: Counter = Counter()
        self._n_observed = 0
        self._last_payload = None
        self._names = feature_names(seed_request)

    # ---- metadata for reproducibility (saved into each run's JSON) ----------------------
    @property
    def params(self) -> dict:
        return dict(warmup=self.warmup, n_candidates=self.n_candidates,
                    retrain_every=self.retrain_every, epsilon=self.epsilon,
                    max_train=MAX_TRAIN, body_prefix=BODY_PREFIX, model="GradientBoostingRegressor",
                    model_params=MODEL_PARAMS, reward="1/count(response signature)")

    # ---- strategy interface --------------------------------------------------------------
    def next_payload(self) -> dict:
        if self.first:
            self.first = False
            self._last_payload = dict(self.seed_request)     # calibration request
            return self._last_payload
        if self.model is None:                                # warmup: identical to baseline
            self._last_payload = mutate_request(self.seed_request, self.rng, self.words)
            return self._last_payload
        cands = [mutate_request(self.seed_request, self.rng, self.words)
                 for _ in range(self.n_candidates)]
        if self.rng.random() < self.epsilon:                  # exploration
            self._last_payload = cands[0]
            return self._last_payload
        feats = np.array([extract_features(c, self.seed_request) for c in cands])
        scores = self.model.predict(feats)                    # one batched call
        best = scores.max()
        tied = [i for i, s in enumerate(scores) if s >= best - 1e-12]
        self._last_payload = cands[self.rng.choice(tied)]     # random tie-break (constant model = random)
        return self._last_payload

    def observe(self, rec: dict) -> None:
        payload = rec.get("payload", self._last_payload)
        sig = signature(rec)
        self._X.append(extract_features(payload, self.seed_request))
        self._sigs.append(sig)
        self._sig_counts[sig] += 1
        self._n_observed += 1
        if self._n_observed >= self.warmup and self._n_observed % self.retrain_every == 0:
            self._retrain()

    # ---- learning --------------------------------------------------------------------------
    def _retrain(self) -> None:
        X = np.array(self._X[-MAX_TRAIN:])
        y = np.array([rarity_reward(self._sig_counts[s]) for s in self._sigs[-MAX_TRAIN:]])
        model = GradientBoostingRegressor(random_state=self.seed, **MODEL_PARAMS)
        model.fit(X, y)
        self.model = model

    # ---- explainability ------------------------------------------------------------------
    def model_summary(self, top: int = 5) -> dict:
        """Human-readable snapshot of what the model has learned (for the report)."""
        out = dict(n_samples=self._n_observed, n_signatures=len(self._sig_counts),
                   fitted=self.model is not None,
                   rarest_signatures=sorted(self._sig_counts.items(), key=lambda kv: kv[1])[:top])
        if self.model is not None:
            imp = sorted(zip(self._names, self.model.feature_importances_), key=lambda t: -t[1])
            out["top_features"] = [(n, round(float(v), 3)) for n, v in imp[:top]]
        return out
