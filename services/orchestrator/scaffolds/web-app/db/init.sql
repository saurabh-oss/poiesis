-- Schema for {{project_name}}.
--
-- Postgres runs this once, on first start of an empty volume. Every table in
-- backend/app/models.py needs a matching statement here.

CREATE TABLE IF NOT EXISTS example (
    id          SERIAL PRIMARY KEY,
    label       VARCHAR(200) NOT NULL,
    status      VARCHAR(40) NOT NULL DEFAULT 'open',   -- open|in_progress|review|done
    owner       VARCHAR(120),
    amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The worked example's own rows, so the reference screen shows what a finished screen looks like.
INSERT INTO example (label, status, owner, amount, created_at) VALUES
  ('Quarterly budget review', 'in_progress', 'Priya Nair', 12400, now() - interval '2 days'),
  ('Renew office lease in Hamburg', 'review', 'Tomasz Kowalski', 86000, now() - interval '5 days'),
  ('Onboard 14 new warehouse staff', 'open', 'Aisha Okafor', 3200, now() - interval '1 day'),
  ('Replace ageing forklift batteries', 'done', 'Diego Ramirez', 18750, now() - interval '12 days'),
  ('Audit software licence seats', 'in_progress', 'Mei Chen', 0, now() - interval '3 days'),
  ('Negotiate freight rates with Maersk', 'open', 'Lars Berg', 240000, now() - interval '6 hours'),
  ('Migrate payroll to the new provider', 'review', 'Fatima Haddad', 15500, now() - interval '8 days'),
  ('Refresh laptops for the sales team', 'done', 'Noah Fischer', 42300, now() - interval '20 days'),
  ('Close Q3 accounts payable', 'done', 'Ines Costa', 0, now() - interval '9 days'),
  ('Pilot route optimisation in Antwerp', 'in_progress', 'Kwame Mensah', 27800, now() - interval '4 days'),
  ('Update the health and safety handbook', 'open', 'Hana Sato', 900, now() - interval '2 hours'),
  ('Consolidate cloud storage accounts', 'review', 'Mateo Rossi', 6100, now() - interval '11 days'),
  ('Tender for the Gdansk cleaning contract', 'open', 'Zara Patel', 31000, now() - interval '13 days'),
  ('Train supervisors on the new WMS', 'in_progress', 'Ivan Petrov', 4800, now() - interval '7 days');

