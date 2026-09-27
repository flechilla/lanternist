-- Who asked for an invitation, and the film they would make first. One row per address: asking
-- again keeps the latest idea.
CREATE TABLE waitlist (
  email TEXT PRIMARY KEY,
  idea TEXT NOT NULL DEFAULT '',
  lang TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
