CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS color_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  color1_hex TEXT,
  color1_pct REAL,
  color2_hex TEXT,
  color2_pct REAL,
  color3_hex TEXT,
  color3_pct REAL,
  color4_hex TEXT,
  color4_pct REAL,
  color5_hex TEXT,
  color5_pct REAL,
  dominant_hex TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_session ON color_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_captured ON color_snapshots(captured_at DESC);
