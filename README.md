# Library Management System (Flask + MySQL)

Beginner-friendly Flask app for library operations with role-based login.

## Roles and Features

### Admin
- Full dashboard and library operations
- Manage books, members, issues, returns, and fines
- Reset any student/faculty password

### Faculty and Student
- Login to personal portal
- View own dashboard, active issues, and fines
- Browse catalog
- Reset own password

## Default Credentials

- Admin:
  - Username: `admin`
  - Password: `admin123`

- Faculty/Student:
  - Username pattern: `faculty<member_id>` or `student<member_id>`
  - Default password: `user123`

Examples:
- `student1 / user123`
- `faculty3 / user123`

## Project Structure

- `app.py` - Flask routes and auth logic
- `db.py` - MySQL connection helper
- `config.py` - App/database configuration
- `schema.sql` - Database schema
- `demodata.sql` - Optional demo data script
- `templates/` - Jinja templates
- `static/` - CSS

## Setup

1. Create and activate virtual environment.
2. Install dependencies.
3. Create MySQL database.
4. Run `schema.sql`.
5. (Optional) Run `demodata.sql`.
6. Configure `.env`.
7. Start app with `python app.py`.

## Required Environment Variables

- `DB_HOST`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `DB_PORT` (default `3306`)
- `FLASK_SECRET_KEY`
- `DAILY_FINE_RATE` (default `5`)

`.env.example` can be used as template.

## Main Routes

- `/login` - Login page
- `/dashboard` - Admin dashboard
- `/my/dashboard` - Faculty/Student dashboard
- `/books` - Catalog
- `/members` - Admin member management
- `/issues` - Admin active issues
- `/return` - Admin returns
- `/fines` - Admin fines
- `/my/issues` - Faculty/Student issue view
- `/my/fines` - Faculty/Student fines view
- `/reset-password` - Logged-in user password reset
