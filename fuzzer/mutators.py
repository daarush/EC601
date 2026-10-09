import random, string

BOUNDARY = ["", " ", "0", "-1", "2147483648", "A" * 256, "A" * 5000,
            "null", "true", "\x00", "../../etc/passwd", "%s%s%s", "😀"]

def mutate_string(s: str, rng: random.Random, words: list[str]) -> str:
    op = rng.choice(["insert", "delete", "flip", "dup", "dict_insert",
                     "dict_replace", "boundary", "truncate"])
    if op == "boundary" or not s:
        return rng.choice(BOUNDARY)
    i = rng.randrange(len(s))
    if op == "insert":       return s[:i] + rng.choice(string.printable) + s[i:]
    if op == "delete":       return s[:i] + s[i + 1:]
    if op == "flip":         return s[:i] + rng.choice(string.printable) + s[i + 1:]
    if op == "dup":          return s[:i] + s[i:] * 2
    if op == "truncate":     return s[:i]
    if not words:            return s
    w = rng.choice(words)
    return s[:i] + w + s[i:] if op == "dict_insert" else w

def mutate_request(seed: dict, rng: random.Random, words: list[str]) -> dict:
    req = dict(seed)
    for _ in range(rng.randint(1, 3)):          # stack 1-3 mutations
        key = rng.choice(list(seed))
        r = rng.random()
        if r < 0.05:   req.pop(key, None)                                   # drop field
        elif r < 0.10: req[key] = rng.choice([None, 0, 1, True, [], {}, 3.14])  # type confusion
        else:          req[key] = mutate_string(str(req.get(key, "")), rng, words)
    return req