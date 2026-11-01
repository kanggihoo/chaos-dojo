CREATE TABLE orders (
  id          BIGSERIAL PRIMARY KEY,
  request_id  UUID        NOT NULL UNIQUE,
  cohort      TEXT        NOT NULL,
  product_id  TEXT        NOT NULL,
  quantity    INTEGER     NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  unit_price  BIGINT      NOT NULL,
  total       BIGINT      NOT NULL,
  currency    CHAR(3)     NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
