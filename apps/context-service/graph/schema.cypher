// Schema for the frozen scope (ADR-0006): Community-safe — uniqueness only.
// Non-null is enforced by ClaimRecord validation and by loader.assert_loadable().
// Property existence constraints are Enterprise-only and are deliberately absent.

CREATE CONSTRAINT source_path IF NOT EXISTS
  FOR (s:Source) REQUIRE s.path IS UNIQUE;

CREATE CONSTRAINT claim_id IF NOT EXISTS
  FOR (c:Claim) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT entity_key IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.key IS UNIQUE;

CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
  FOR (c:Chunk) ON c.embedding
  OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }};

CREATE CONSTRAINT vocab_id IF NOT EXISTS
  FOR (v:Vocab) REQUIRE v.id IS UNIQUE;

CREATE VECTOR INDEX vocab_embedding IF NOT EXISTS
  FOR (v:Vocab) ON v.embedding
  OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }};

CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS
  FOR (c:Chunk) ON EACH [c.text];

// Span identity: a line span is (path, start_line, end_line); a region span adds the four
// pixel fields, so two reads of one image are two nodes. No uniqueness constraint exists —
// property existence is Enterprise-only and MERGE already deduplicates on the same key.
CREATE INDEX span_path IF NOT EXISTS
  FOR (s:Span) ON (s.path);

CREATE INDEX claim_validity IF NOT EXISTS
  FOR (c:Claim) ON (c.valid_from, c.valid_to);

CREATE VECTOR INDEX claim_embedding IF NOT EXISTS
FOR (c:Claim) ON c.embedding
OPTIONS {indexConfig: {
`vector.dimensions`: 768,
`vector.similarity_function`: 'cosine'
}};
