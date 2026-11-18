-- Runs once, the first time the Postgres volume is created.
-- A separate database for automated tests so they never touch your real data.
CREATE DATABASE rag_test;

-- pgvector adds the "vector" column type and similarity operators.
CREATE EXTENSION IF NOT EXISTS vector;
\connect rag_test
CREATE EXTENSION IF NOT EXISTS vector;
