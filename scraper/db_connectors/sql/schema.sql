CREATE TABLE IF NOT EXISTS health_data_points (
    data_type   TEXT        NOT NULL,
    point_id    TEXT        NOT NULL,
    start_time  TIMESTAMPTZ,
    end_time    TIMESTAMPTZ,
    record_date DATE,
    payload     JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (data_type, point_id)
);

CREATE INDEX IF NOT EXISTS idx_health_data_points_type_start
    ON health_data_points (data_type, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_health_data_points_type_date
    ON health_data_points (data_type, record_date DESC);

CREATE TABLE IF NOT EXISTS sync_state (
    data_type      TEXT PRIMARY KEY,
    last_synced_at TIMESTAMPTZ,
    last_status    TEXT,
    last_error     TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
