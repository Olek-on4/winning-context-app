"""The corpus's own vocabulary, embedded.

A stopword list is English knowledge; this is corpus knowledge. `cli index` embeds every
entity key and every predicate gloss once, and a question resolves to anchors by cosine
against that set. Nothing here decides truth: a returned term is only a candidate, and
the caller keeps it only if the graph actually has that key.
"""

from __future__ import annotations

from collections.abc import Callable

from neo4j import Driver

from settings import PREDICATE_GLOSSES, VOCAB_K, VOCAB_MIN_SCORE

VOCAB_INDEX = "vocab_embedding"

# `id` is source:term because Community edition has no node-key constraints.
UPSERT = """
UNWIND $vocab AS v
MERGE (t:Vocab {id: v.id})
SET t.term = v.term, t.kind = v.kind, t.source = v.source, t.embedding = v.embedding
"""

RESOLVE = """
CALL db.index.vector.queryNodes($index, $k, $vector) YIELD node, score
WHERE score >= $min_score
RETURN node.term AS term, node.kind AS kind, node.source AS source, score
ORDER BY score DESC
"""

ENTITIES = "MATCH (e:Entity) RETURN DISTINCT e.key AS key, e.kind AS kind ORDER BY key"


def build(driver: Driver, embed: Callable[[str], list[float] | None]) -> int:
    """(Re)write every vocabulary vector. One MERGE per term, so re-running is free."""
    rows = [dict(record) for record in driver.execute_query(ENTITIES).records]
    terms = [
        {"id": f"entity:{row['key']}", "term": row["key"], "kind": row["kind"] or "ANY",
         "source": "entity", "text": row["key"]}
        for row in rows
    ]
    terms += [
        {"id": f"predicate:{name}", "term": name, "kind": "PREDICATE", "source": "predicate",
         "text": gloss}
        for name, gloss in PREDICATE_GLOSSES.items()
    ]
    vocab = []
    for term in terms:
        vector = embed(term["text"])
        if vector:
            vocab.append({key: value for key, value in term.items() if key != "text"} | {"embedding": vector})
    if vocab:
        driver.execute_query(UPSERT, vocab=vocab)
    return len(vocab)


def resolve(
    driver: Driver, question: str, embed: Callable[[str], list[float] | None]
) -> tuple[list[str], list[str]] | None:
    """(entity keys, predicates) the question is close to, or None when it cannot be embedded.

    None is the signal to fall back to the deterministic plan: a corpus with no vocabulary
    index yet, or a machine with no embedding model, must still answer.
    """
    try:
        vector = embed(question)
    except Exception:  # no model, no network: fall back to the deterministic plan
        return None
    if not vector:
        return None
    try:
        rows = driver.execute_query(
            RESOLVE, index=VOCAB_INDEX, k=VOCAB_K, vector=vector, min_score=VOCAB_MIN_SCORE
        ).records
    except Exception:  # no index yet is a supported state, not an error
        return None
    # A bare name ("accounts") is an anchor about the thing; a path is an anchor about one
    # document that mentions it, which narrows the answer to that file. Names first.
    keys = sorted(
        (row["term"] for row in rows if row["source"] == "entity"),
        key=lambda term: ("/" in term, term),
    )
    predicates = [row["term"] for row in rows if row["source"] == "predicate"]
    if not keys and not predicates:
        return None
    return keys, predicates
