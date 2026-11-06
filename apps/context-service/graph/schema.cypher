// Schema for the frozen scope (ADR-0006): Community-safe — uniqueness only.
// Non-null is enforced by ClaimRecord validation and by loader.assert_loadable().
// Property existence constraints are Enterprise-only and are deliberately absent.

CREATE CONSTRAINT source_path IF NOT EXISTS
  FOR (s:Source) REQUIRE s.path IS UNIQUE;

CREATE CONSTRAINT claim_id IF NOT EXISTS
  FOR (c:Claim) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT service_key IF NOT EXISTS
  FOR (s:Service) REQUIRE s.key IS UNIQUE;

CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
  FOR (c:Chunk) ON c.embedding
  OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }};

CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS
  FOR (c:Chunk) ON EACH [c.text];

CREATE INDEX claim_validity IF NOT EXISTS
  FOR (c:Claim) ON (c.valid_from, c.valid_to);
