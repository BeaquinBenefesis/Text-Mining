CREATE TABLE entity(
    id INTEGER PRIMARY KEY,
    accession TEXT NOT NULL UNIQUE,
    primary_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    obsolete INTEGER NOT NULL,
    reference_level TEXT   -- 'family' | 'precursor' | 'mature'; NULL for non-MIR rows
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
