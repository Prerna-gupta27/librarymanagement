-- Library Management System schema
-- Target: MySQL 8.x (InnoDB)

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- Drop order respects FK dependencies
DROP TABLE IF EXISTS fines;
DROP TABLE IF EXISTS book_issues;
DROP TABLE IF EXISTS book_copies;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS member_types;

CREATE TABLE member_types (
  member_type_id INT NOT NULL AUTO_INCREMENT,
  type_name VARCHAR(20) NOT NULL, -- STUDENT | FACULTY
  max_active_issues INT NOT NULL,
  max_issue_days INT NOT NULL,
  PRIMARY KEY (member_type_id),
  UNIQUE KEY uq_member_types_type_name (type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE members (
  member_id INT NOT NULL AUTO_INCREMENT,
  member_type_id INT NOT NULL,
  full_name VARCHAR(200) NOT NULL,
  email VARCHAR(254) NULL,
  phone VARCHAR(30) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (member_id),
  UNIQUE KEY uq_members_email (email),
  KEY ix_members_member_type (member_type_id),
  CONSTRAINT fk_members_member_types
    FOREIGN KEY (member_type_id) REFERENCES member_types(member_type_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE books (
  book_id INT NOT NULL AUTO_INCREMENT,
  title VARCHAR(255) NOT NULL,
  author VARCHAR(255) NOT NULL,
  publisher VARCHAR(255) NULL,
  isbn VARCHAR(20) NULL,
  published_year INT NULL,
  PRIMARY KEY (book_id),
  KEY ix_books_title (title),
  KEY ix_books_author (author)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Each physical copy has its own ID even if title/author are same.
CREATE TABLE book_copies (
  copy_id INT NOT NULL AUTO_INCREMENT,
  book_id INT NOT NULL,
  accession_no VARCHAR(50) NOT NULL, -- library-specific unique copy identifier
  status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE', -- AVAILABLE | ISSUED | LOST | DAMAGED
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (copy_id),
  UNIQUE KEY uq_book_copies_accession_no (accession_no),
  KEY ix_book_copies_book (book_id),
  CONSTRAINT fk_book_copies_books
    FOREIGN KEY (book_id) REFERENCES books(book_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Issue/return entry: who issued what, when, and for how long (due_date)
CREATE TABLE book_issues (
  issue_id INT NOT NULL AUTO_INCREMENT,
  copy_id INT NOT NULL,
  member_id INT NOT NULL,
  issue_date DATE NOT NULL,
  due_date DATE NOT NULL,
  return_date DATE NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (issue_id),
  KEY ix_book_issues_copy (copy_id),
  KEY ix_book_issues_member (member_id),
  KEY ix_book_issues_due (due_date),
  CONSTRAINT fk_book_issues_copy
    FOREIGN KEY (copy_id) REFERENCES book_copies(copy_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT,
  CONSTRAINT fk_book_issues_member
    FOREIGN KEY (member_id) REFERENCES members(member_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT,
  CONSTRAINT ck_book_issues_dates
    CHECK (due_date >= issue_date AND (return_date IS NULL OR return_date >= issue_date))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Fine details when the book is not returned on time
CREATE TABLE fines (
  fine_id INT NOT NULL AUTO_INCREMENT,
  issue_id INT NOT NULL,
  assessed_date DATE NOT NULL,
  days_overdue INT NOT NULL,
  fine_amount DECIMAL(10,2) NOT NULL,
  is_paid TINYINT(1) NOT NULL DEFAULT 0,
  paid_date DATE NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (fine_id),
  UNIQUE KEY uq_fines_issue (issue_id),
  KEY ix_fines_paid (is_paid),
  CONSTRAINT fk_fines_issue
    FOREIGN KEY (issue_id) REFERENCES book_issues(issue_id)
      ON UPDATE RESTRICT ON DELETE CASCADE,
  CONSTRAINT ck_fines_paid_date
    CHECK ((is_paid = 0 AND paid_date IS NULL) OR (is_paid = 1 AND paid_date IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed member types (adjust limits/days as needed)
INSERT INTO member_types (type_name, max_active_issues, max_issue_days) VALUES
  ('STUDENT', 3, 14),
  ('FACULTY', 10, 30);
