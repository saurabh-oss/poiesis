-- Schema for {{project_name}}.
--
-- Postgres runs this once, on first start of an empty volume. Every table in
-- backend/app/models.py needs a matching statement here.

CREATE TABLE IF NOT EXISTS example (
    id          SERIAL PRIMARY KEY,
    label       VARCHAR(200) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

