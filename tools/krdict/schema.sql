PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    lexical_unit TEXT NOT NULL,
    homonym_number INTEGER,
    part_of_speech TEXT,
    vocabulary_level TEXT,
    origin TEXT,
    annotation TEXT
);

CREATE TABLE lemmas (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    written_form TEXT NOT NULL,
    variant TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE TABLE senses (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    source_sense_id INTEGER NOT NULL,
    sense_order INTEGER NOT NULL,
    korean_definition TEXT NOT NULL,
    annotation TEXT,
    syntactic_annotation TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    UNIQUE (entry_id, source_sense_id),
    UNIQUE (entry_id, sense_order)
);

CREATE TABLE translations (
    id INTEGER PRIMARY KEY,
    sense_id INTEGER NOT NULL,
    language TEXT NOT NULL,
    lemma TEXT NOT NULL,
    definition TEXT NOT NULL,
    FOREIGN KEY (sense_id) REFERENCES senses(id) ON DELETE CASCADE
);

CREATE TABLE examples (
    id INTEGER PRIMARY KEY,
    sense_id INTEGER NOT NULL,
    example_group INTEGER NOT NULL,
    example_order INTEGER NOT NULL,
    type TEXT,
    text TEXT NOT NULL,
    FOREIGN KEY (sense_id) REFERENCES senses(id) ON DELETE CASCADE,
    UNIQUE (sense_id, example_group, example_order)
);

CREATE TABLE word_forms (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    written_form TEXT,
    pronunciation TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    value TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE TABLE related_forms (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    written_form TEXT NOT NULL,
    target_source_id INTEGER,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE TABLE syntactic_patterns (
    id INTEGER PRIMARY KEY,
    sense_id INTEGER NOT NULL,
    pattern_order INTEGER NOT NULL,
    pattern TEXT NOT NULL,
    FOREIGN KEY (sense_id) REFERENCES senses(id) ON DELETE CASCADE,
    UNIQUE (sense_id, pattern_order)
);

CREATE TABLE sense_relations (
    id INTEGER PRIMARY KEY,
    sense_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    target_lemma TEXT NOT NULL,
    target_source_id INTEGER,
    target_homonym_number INTEGER,
    FOREIGN KEY (sense_id) REFERENCES senses(id) ON DELETE CASCADE
);

CREATE TABLE resource_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
