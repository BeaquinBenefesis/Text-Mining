CREATE TABLE entity(
    id INTEGER PRIMARY KEY,
    accession TEXT NOT NULL UNIQUE,
    primary_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    obsolete INTEGER NOT NULL,
    reference_level TEXT,  -- 'family' | 'precursor' | 'mature'; NULL for non-MIR rows
    organism TEXT          -- miRBase 3-letter prefix ('hsa'); NULL for non-MIR rows
) STRICT;

CREATE TABLE synonym(
    id INTEGER PRIMARY KEY,
    synonym_name TEXT NOT NULL,
    synonym_type TEXT NOT NULL DEFAULT 'STANDARD',
    entity_id INTEGER,
    FOREIGN KEY (entity_id) REFERENCES entity
) STRICT;

CREATE TABLE association(
    id INTEGER PRIMARY KEY,
    mirna_entity_id INTEGER NOT NULL,
    term_entity_id INTEGER NOT NULL,
    term_type TEXT NOT NULL,
    score REAL NOT NULL,
    FOREIGN KEY (mirna_entity_id) REFERENCES entity,
    FOREIGN KEY (term_entity_id) REFERENCES entity,
    UNIQUE (mirna_entity_id, term_entity_id)
) STRICT;

CREATE TABLE ontology_closure(
    ancestor_id INTEGER NOT NULL,
    descendant_id INTEGER NOT NULL,
    FOREIGN KEY (ancestor_id) REFERENCES entity,
    FOREIGN KEY (descendant_id) REFERENCES entity,
    UNIQUE (ancestor_id, descendant_id)
) STRICT;

CREATE TABLE association_evidence(
    id INTEGER PRIMARY KEY,
    association_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    mirna_start INTEGER NOT NULL,
    mirna_end INTEGER NOT NULL,
    term_start INTEGER NOT NULL,
    term_end INTEGER NOT NULL,
    FOREIGN KEY (association_id) REFERENCES association,
    FOREIGN KEY (sentence_id) REFERENCES sentence
) STRICT;

CREATE TABLE article(
    id INTEGER PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    year INTEGER,      -- NULL when PubDate is missing (~13-16% of source rows)
    journal TEXT        -- NULL for a small fraction of PMC rows
) STRICT;

CREATE TABLE sentence(
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL,
    section_num INTEGER NOT NULL,
    sentence_num INTEGER NOT NULL,
    sentence_text TEXT NOT NULL,
    FOREIGN KEY (article_id) REFERENCES article,
    UNIQUE (article_id, section_num, sentence_num)
) STRICT;

-- ============================================================================
-- MENTION LAYER
-- Every miRNA mention in the corpus, not only those that produced an
-- association. Built by loaders/mentions.py from the .norm file via duckdb.
-- ============================================================================

-- mir_key is TEXT and deliberately NOT a foreign key to entity: hits with
-- norm_status = IN_BLACKLIST carry no accession (MirNormalizer._map_to_accession
-- returns normalized_id = None for ambiguous miRBase identifiers), and carrying
-- them is the entire point of this table -- they are invisible everywhere else
-- in the schema. For those rows mir_key is the lowercased surface name.
-- WITHOUT ROWID: a pure junction table whose PRIMARY KEY is its entire identity.
-- On a rowid table the composite PK builds a SEPARATE unique index duplicating
-- both columns, so the data is stored twice -- measured 83.7MB table plus a
-- 90.5MB autoindex, and every query read the index, never the table. WITHOUT
-- ROWID stores the rows once, in the PK b-tree itself.
CREATE TABLE mir_mention_article(
    mir_key     TEXT    NOT NULL,   -- accession, or surface name when blacklisted
    article_id  INTEGER NOT NULL,
    blacklisted INTEGER NOT NULL,
    PRIMARY KEY (mir_key, article_id),
    FOREIGN KEY (article_id) REFERENCES article
) STRICT, WITHOUT ROWID;

-- Denominator for share-of-corpus normalisation. The corpus is 99% post-2010,
-- so a raw mention count per year measures corpus coverage, not research
-- activity; every timeline is divided by this.
CREATE TABLE corpus_year(
    year       INTEGER PRIMARY KEY,
    n_articles INTEGER NOT NULL
) STRICT;

-- ============================================================================
-- miRBASE NAME HISTORY
-- Full per-release record. Two uses: legacy names become searchable synonyms,
-- and names whose accession changed between releases get a disambiguation view
-- instead of being silently resolved.
-- ============================================================================

CREATE TABLE mirna_name_history(
    mirna_name      TEXT    NOT NULL,
    accession       TEXT    NOT NULL,
    version         TEXT    NOT NULL,   -- miRBase release, e.g. 'v9_2', 'v22'
    version_rank    INTEGER NOT NULL,   -- sortable form of version
    dead            INTEGER NOT NULL,
    reference_level TEXT    NOT NULL,   -- 'mature' | 'precursor'
    PRIMARY KEY (mirna_name, accession, version)
) STRICT;

CREATE INDEX ix_nh_accession ON mirna_name_history(accession);
CREATE INDEX ix_nh_name      ON mirna_name_history(lower(mirna_name));

-- ============================================================================
-- SEARCH
-- One row per surface form the user may type. Restricted at build time to
-- entities that are actually reachable: terms with associations or closure
-- ancestry, and miRNAs with mentions. Ontologies contribute far more terms than
-- a corpus ever mentions, so this keeps unhit terms out of the search path.
-- ============================================================================

CREATE TABLE search_name(
    name_lower   TEXT    NOT NULL,
    display_name TEXT    NOT NULL,
    entity_id    INTEGER,             -- NULL when kind = 'conflict'
    kind         TEXT    NOT NULL,    -- 'primary'|'synonym'|'legacy'|'conflict'
    FOREIGN KEY (entity_id) REFERENCES entity
) STRICT;

CREATE INDEX ix_search_name ON search_name(name_lower);

-- ============================================================================
-- INDEXES
-- Without these every UI query is a full scan; the miRNA timeline measured
-- 5.6s and association_evidence lookups scan 17.9M rows.
-- ontology_closure(ancestor_id) is already covered by its UNIQUE autoindex,
-- as is association(mirna_entity_id) by UNIQUE(mirna_entity_id, term_entity_id).
-- ============================================================================

-- (association_id, sentence_id) and not association_id alone: the evidence view
-- pages by DISTINCT sentence, and the largest association has 23,810 evidence rows
-- over 16,228 sentences. A single-column index gives rowids and then needs one
-- random row fetch each to read sentence_id (measured 2.9s per page); with
-- sentence_id in the index the page is a plain ordered range scan.
CREATE INDEX ix_ae_assoc         ON association_evidence(association_id, sentence_id);
CREATE INDEX ix_assoc_mir_score  ON association(mirna_entity_id, score DESC);
CREATE INDEX ix_assoc_term_score ON association(term_entity_id, score DESC);
CREATE INDEX ix_sentence_article ON sentence(article_id);
CREATE INDEX ix_synonym_entity   ON synonym(entity_id);
-- No index on entity(entity_type, organism): it was tried and EXPLAIN QUERY PLAN
-- never chose it (49.9MB wasted). Organism filtering always reaches entity by
-- rowid from association and then tests the column, so the index is never the
-- access path.
