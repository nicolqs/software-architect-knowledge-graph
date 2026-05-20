-- Runs once on first container boot.
-- Creates the pgvector extension and a separate schema for Langfuse so it
-- doesn't collide with our app tables.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS langfuse;
