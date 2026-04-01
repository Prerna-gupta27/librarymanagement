-- Demo data for Library Management System
-- MySQL 8.x
--
-- WARNING:
-- This script CLEARS existing data in these tables:
--   fines, book_issues, book_copies, books, members
-- It does NOT drop or recreate tables.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

START TRANSACTION;

-- Make the script re-runnable
SET FOREIGN_KEY_CHECKS = 0;
DELETE FROM fines;
DELETE FROM book_issues;
DELETE FROM book_copies;
DELETE FROM books;
DELETE FROM members;
SET FOREIGN_KEY_CHECKS = 1;

-- Optional: reset auto-increment counters
ALTER TABLE fines AUTO_INCREMENT = 1;
ALTER TABLE book_issues AUTO_INCREMENT = 1;
ALTER TABLE book_copies AUTO_INCREMENT = 1;
ALTER TABLE books AUTO_INCREMENT = 1;
ALTER TABLE members AUTO_INCREMENT = 1;

-- Ensure member types exist (schema.sql already inserts these)
INSERT INTO member_types (member_type_id, type_name, max_active_issues, max_issue_days)
VALUES
  (1, 'STUDENT', 3, 14),
  (2, 'FACULTY', 10, 30)
ON DUPLICATE KEY UPDATE
  type_name = VALUES(type_name),
  max_active_issues = VALUES(max_active_issues),
  max_issue_days = VALUES(max_issue_days);

-- Members
INSERT INTO members (member_id, member_type_id, full_name, email, phone, is_active)
VALUES
  (1, 1, 'Aarav Sharma', 'aarav.student@example.com', '9990001111', 1),
  (2, 1, 'Diya Patel',   'diya.student@example.com',  '9990002222', 1),
  (3, 2, 'Prof. Meera Rao', 'meera.faculty@example.com', '9990003333', 1),
  (4, 2, 'Dr. Vikram Singh', 'vikram.faculty@example.com', '9990004444', 1);

-- Books
INSERT INTO books (book_id, title, author, publisher, isbn, published_year)
VALUES
  (1, 'Clean Code', 'Robert C. Martin', 'Prentice Hall', '9780132350884', 2008),
  (2, 'Introduction to Algorithms', 'Thomas H. Cormen', 'MIT Press', '9780262046305', 2022),
  (3, 'Database System Concepts', 'Abraham Silberschatz', 'McGraw-Hill', '9780078022159', 2019);

-- Book copies (each copy has a unique accession number)
INSERT INTO book_copies (copy_id, book_id, accession_no, status)
VALUES
  (1, 1, 'ACC-CC-001', 'AVAILABLE'),
  (2, 1, 'ACC-CC-002', 'AVAILABLE'),
  (3, 2, 'ACC-ALGO-001', 'AVAILABLE'),
  (4, 2, 'ACC-ALGO-002', 'AVAILABLE'),
  (5, 3, 'ACC-DB-001', 'AVAILABLE');

-- Issues
-- Issue #1: student issues a copy, returns late -> fine
INSERT INTO book_issues (issue_id, copy_id, member_id, issue_date, due_date, return_date)
VALUES
  (1, 1, 1, DATE_SUB(CURDATE(), INTERVAL 20 DAY), DATE_SUB(CURDATE(), INTERVAL 6 DAY), CURDATE());

-- Mark copy available after return
UPDATE book_copies SET status = 'AVAILABLE' WHERE copy_id = 1;

-- Create fine for issue #1 (days overdue = 6, amount = 6 * 5 = 30)
INSERT INTO fines (fine_id, issue_id, assessed_date, days_overdue, fine_amount, is_paid, paid_date)
VALUES
  (1, 1, CURDATE(), 6, 30.00, 0, NULL);

-- Issue #2: faculty issues a copy, not returned yet
INSERT INTO book_issues (issue_id, copy_id, member_id, issue_date, due_date, return_date)
VALUES
  (2, 3, 3, DATE_SUB(CURDATE(), INTERVAL 5 DAY), DATE_ADD(CURDATE(), INTERVAL 25 DAY), NULL);

-- Mark copy issued
UPDATE book_copies SET status = 'ISSUED' WHERE copy_id = 3;

COMMIT;

-- End
