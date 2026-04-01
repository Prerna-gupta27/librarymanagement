# Library Management System (Flask + MySQL)

This is a beginner-friendly Flask web app that works with your existing MySQL schema (already created via `schema.sql`).

## Folder structure

- `app.py` — Flask routes (books, members, issue, return, fines)
- `db.py` — MySQL connection helper
- `config.py` — database + fine configuration (reads env vars)
- `templates/` — HTML (Jinja2) templates
- `static/` — CSS
- `requirements.txt` — Python dependencies

## Prerequisites

- Python 3.10+ recommended
- MySQL Server running
- Your database already contains tables:
  `member_types`, `members`, `books`, `book_copies`, `book_issues`, `fines`

## Configure database connection

The app reads these environment variables:


Example values are in `.env.example`.

This project will also auto-load a local `.env` file (if present) on startup.

### Quick way on Windows (PowerShell)

From this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DB_HOST = "localhost"
$env:DB_USER = "root"
$env:DB_PASSWORD = "your_mysql_password"
$env:DB_NAME = "your_database_name"

If you edit `.env`, stop the server (Ctrl+C) and run `python app.py` again.
$env:DB_PORT = "3306"
$env:DAILY_FINE_RATE = "5"

python app.py
```

Then open: http://127.0.0.1:5000

## Features / Pages

- **View all books**: `/books`
- **Add new book** (optionally add accession numbers / copies): `/books/new`
- **Register new member**: `/members/new`
- **Issue a book to a member**: `/issue`
- **Return a book + calculate fine**: `/return`
- **View all fines and payment status**: `/fines`

## Notes

- Issue rules are enforced using the `member_types` table (`max_active_issues`, `max_issue_days`).
- Returning a book inserts/updates a row in `fines` only if `days_overdue > 0`.
