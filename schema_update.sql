-- One-time schema updates for requested enhancements
-- Run this against your existing database (example: DB_NAME=world)

-- 1) Update member type rules
UPDATE member_types
SET max_active_issues = 2, max_issue_days = 7
WHERE type_name = 'STUDENT';

UPDATE member_types
SET max_active_issues = 5, max_issue_days = 14
WHERE type_name = 'FACULTY';

-- 2) Add status column to book_issues (issued/returned)
-- If you already have this column, MySQL will error; run only once.
ALTER TABLE book_issues
  ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ISSUED';

-- Backfill status based on return_date
UPDATE book_issues
SET status = CASE WHEN return_date IS NULL THEN 'ISSUED' ELSE 'RETURNED' END;

-- Optional: keep status consistent (recommended to enforce in application logic)
-- MySQL CHECK constraints are parsed but enforcement can vary by version/config.
