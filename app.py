from __future__ import annotations

from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# Load variables from .env (if present) so beginners don't have to set env vars manually.
# This must happen BEFORE importing Config, because Config reads env vars at import time.
load_dotenv(override=False)

from config import Config
from db import db_error_message, get_conn


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    ADMIN_DEFAULT_USERNAME = "admin"
    ADMIN_DEFAULT_PASSWORD = "admin123"
    MEMBER_DEFAULT_PASSWORD = "user123"

    def role_from_member_type(type_name: str) -> str:
        return "FACULTY" if (type_name or "").upper() == "FACULTY" else "STUDENT"

    def default_member_username(member_id: int, role: str) -> str:
        return f"{role.lower()}{member_id}"

    def verify_password(stored_password_hash: str, raw_password: str) -> bool:
        # Supports generated hashes and keeps compatibility with any legacy plaintext rows.
        if stored_password_hash.startswith(("scrypt:", "pbkdf2:")):
            return check_password_hash(stored_password_hash, raw_password)
        return stored_password_hash == raw_password

    def get_session_user() -> dict | None:
        user = session.get("auth_user")
        return user if isinstance(user, dict) else None

    def home_endpoint_for_role(role: str | None) -> str:
        return "dashboard" if role == "ADMIN" else "member_dashboard"

    def safe_redirect_target(raw_target: str | None) -> str | None:
        if not raw_target:
            return None
        if raw_target.startswith("/") and not raw_target.startswith("//"):
            return raw_target
        return None

    def login_required(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not get_session_user():
                flash("Please login to continue.", "error")
                return redirect(url_for("login", next=request.path))
            return view_func(*args, **kwargs)

        return wrapped

    def roles_required(*allowed_roles: str):
        allowed = set(allowed_roles)

        def decorator(view_func):
            @wraps(view_func)
            def wrapped(*args, **kwargs):
                user = get_session_user()
                if not user:
                    flash("Please login to continue.", "error")
                    return redirect(url_for("login", next=request.path))
                if user.get("role") not in allowed:
                    flash("You are not authorized to access that page.", "error")
                    return redirect(url_for(home_endpoint_for_role(user.get("role"))))
                return view_func(*args, **kwargs)

            return wrapped

        return decorator

    @app.context_processor
    def inject_layout_data():
        auth_user = get_session_user()
        return {
            "daily_fine_rate": float(app.config["DAILY_FINE_RATE"]),
            "current_year": date.today().year,
            "auth_user": auth_user,
            "is_admin": bool(auth_user and auth_user.get("role") == "ADMIN"),
        }

    def get_member_types() -> list[dict]:
        with get_conn(app) as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT member_type_id, type_name, max_active_issues, max_issue_days FROM member_types ORDER BY member_type_id"
            )
            return cur.fetchall()

    def ensure_member_account(
        conn,
        member_id: int,
        role: str,
        is_active: int,
        reset_password: bool = False,
    ) -> str:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT user_id, username FROM user_accounts WHERE member_id = %s FOR UPDATE",
            (member_id,),
        )
        account = cur.fetchone()

        if account:
            cur2 = conn.cursor()
            if reset_password:
                cur2.execute(
                    """
                    UPDATE user_accounts
                    SET password_hash = %s, role = %s, is_active = %s, must_reset_password = 1
                    WHERE user_id = %s
                    """,
                    (
                        generate_password_hash(MEMBER_DEFAULT_PASSWORD),
                        role,
                        is_active,
                        account["user_id"],
                    ),
                )
            else:
                cur2.execute(
                    """
                    UPDATE user_accounts
                    SET role = %s, is_active = %s
                    WHERE user_id = %s
                    """,
                    (role, is_active, account["user_id"]),
                )
            return account["username"]

        username = default_member_username(member_id, role)
        cur.execute("SELECT user_id FROM user_accounts WHERE username = %s", (username,))
        if cur.fetchone():
            username = f"{username}_{member_id}"

        cur2 = conn.cursor()
        cur2.execute(
            """
            INSERT INTO user_accounts (username, password_hash, role, member_id, must_reset_password, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                username,
                generate_password_hash(MEMBER_DEFAULT_PASSWORD),
                role,
                member_id,
                1 if reset_password else 0,
                is_active,
            ),
        )
        return username

    def ensure_auth_setup() -> None:
        with get_conn(app) as conn:
            conn.start_transaction()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_accounts (
                  user_id INT NOT NULL AUTO_INCREMENT,
                  username VARCHAR(100) NOT NULL,
                  password_hash VARCHAR(255) NOT NULL,
                  role VARCHAR(20) NOT NULL,
                  member_id INT NULL,
                  must_reset_password TINYINT(1) NOT NULL DEFAULT 0,
                  is_active TINYINT(1) NOT NULL DEFAULT 1,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (user_id),
                  UNIQUE KEY uq_user_accounts_username (username),
                  UNIQUE KEY uq_user_accounts_member (member_id),
                  KEY ix_user_accounts_role (role),
                  CONSTRAINT fk_user_accounts_member
                    FOREIGN KEY (member_id) REFERENCES members(member_id)
                      ON UPDATE RESTRICT ON DELETE CASCADE,
                  CONSTRAINT ck_user_accounts_role
                    CHECK (role IN ('ADMIN', 'FACULTY', 'STUDENT'))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            cur.execute("SELECT user_id FROM user_accounts WHERE username = %s", (ADMIN_DEFAULT_USERNAME,))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO user_accounts (username, password_hash, role, member_id, must_reset_password, is_active)
                    VALUES (%s, %s, 'ADMIN', NULL, 0, 1)
                    """,
                    (ADMIN_DEFAULT_USERNAME, generate_password_hash(ADMIN_DEFAULT_PASSWORD)),
                )

            cur_dict = conn.cursor(dictionary=True)
            cur_dict.execute(
                """
                SELECT m.member_id, mt.type_name, m.is_active
                FROM members m
                JOIN member_types mt ON mt.member_type_id = m.member_type_id
                LEFT JOIN user_accounts ua ON ua.member_id = m.member_id
                WHERE ua.user_id IS NULL
                ORDER BY m.member_id
                """
            )
            missing_accounts = cur_dict.fetchall()

            for row in missing_accounts:
                ensure_member_account(
                    conn=conn,
                    member_id=int(row["member_id"]),
                    role=role_from_member_type(row["type_name"]),
                    is_active=int(row["is_active"]),
                    reset_password=False,
                )

            # Keep member-linked account role/status in sync with member records.
            cur.execute(
                """
                UPDATE user_accounts ua
                JOIN members m ON m.member_id = ua.member_id
                JOIN member_types mt ON mt.member_type_id = m.member_type_id
                SET
                  ua.role = CASE WHEN UPPER(mt.type_name) = 'FACULTY' THEN 'FACULTY' ELSE 'STUDENT' END,
                  ua.is_active = m.is_active
                WHERE ua.member_id IS NOT NULL
                """
            )

            conn.commit()

    def get_active_issue_rows(status_filter: str = "all", limit: int | None = None) -> list[dict]:
        filters = ["bi.return_date IS NULL"]
        if status_filter == "overdue":
            filters.append("bi.due_date < CURDATE()")
        elif status_filter == "due_soon":
            filters.append("bi.due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 3 DAY)")

        sql = f"""
            SELECT
              bi.issue_id,
              bi.issue_date,
              bi.due_date,
              bi.copy_id,
              m.member_id,
              m.full_name,
              mt.type_name,
              c.accession_no,
              b.title,
              b.author
            FROM book_issues bi
            JOIN members m ON m.member_id = bi.member_id
            JOIN member_types mt ON mt.member_type_id = m.member_type_id
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE {' AND '.join(filters)}
            ORDER BY bi.due_date ASC, bi.issue_id ASC
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)

        with get_conn(app) as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, params)
            rows = cur.fetchall()

        today = date.today()
        for row in rows:
            days_left = (row["due_date"] - today).days
            row["days_left"] = days_left
            row["is_overdue"] = days_left < 0
            row["overdue_days"] = abs(days_left) if days_left < 0 else 0
        return rows

    def process_return(issue_id: int) -> tuple[dict | None, str | None]:
        return_date = date.today()
        with get_conn(app) as conn:
            conn.start_transaction()
            cur = conn.cursor(dictionary=True)

            # Lock the issue row to avoid double-return race conditions.
            cur.execute(
                """
                SELECT bi.issue_id, bi.copy_id, bi.member_id, bi.issue_date, bi.due_date, bi.return_date,
                       m.full_name AS member_name, c.accession_no
                FROM book_issues bi
                JOIN members m ON m.member_id = bi.member_id
                JOIN book_copies c ON c.copy_id = bi.copy_id
                WHERE bi.issue_id = %s
                FOR UPDATE
                """,
                (issue_id,),
            )
            issue = cur.fetchone()

            if not issue:
                conn.rollback()
                return None, "Issue record not found."

            if issue["return_date"] is not None:
                conn.rollback()
                return None, "This book has already been returned."

            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE book_issues SET return_date = %s WHERE issue_id = %s",
                (return_date, issue_id),
            )
            cur2.execute(
                "UPDATE book_copies SET status = 'AVAILABLE' WHERE copy_id = %s",
                (issue["copy_id"],),
            )

            due_date = issue["due_date"]
            days_overdue = max((return_date - due_date).days, 0)
            fine_amount = round(days_overdue * float(app.config["DAILY_FINE_RATE"]), 2)

            if days_overdue > 0:
                cur2.execute(
                    """
                    INSERT INTO fines (issue_id, assessed_date, days_overdue, fine_amount, is_paid, paid_date)
                    VALUES (%s, %s, %s, %s, 0, NULL)
                    ON DUPLICATE KEY UPDATE
                      assessed_date = VALUES(assessed_date),
                      days_overdue = VALUES(days_overdue),
                      fine_amount = VALUES(fine_amount)
                    """,
                    (issue_id, return_date, days_overdue, fine_amount),
                )

            conn.commit()

        result = {
            "issue_id": issue_id,
            "member_name": issue["member_name"],
            "copy_id": issue["copy_id"],
            "accession_no": issue["accession_no"],
            "issue_date": issue["issue_date"],
            "due_date": due_date,
            "return_date": return_date,
            "days_overdue": days_overdue,
            "fine_amount": fine_amount,
        }
        return result, None

    try:
        ensure_auth_setup()
    except Exception as exc:
        app.logger.warning("Authentication setup skipped on startup: %s", db_error_message(exc))

    @app.get("/")
    def index():
        user = get_session_user()
        if not user:
            return redirect(url_for("login"))
        return redirect(url_for(home_endpoint_for_role(user.get("role"))))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            user = get_session_user()
            if user:
                return redirect(url_for(home_endpoint_for_role(user.get("role"))))
            return render_template(
                "login.html",
                title="Login",
                form={},
                next_target=safe_redirect_target(request.args.get("next")),
            )

        form = {
            "role": (request.form.get("role") or "").strip().upper(),
            "username": (request.form.get("username") or "").strip(),
            "password": request.form.get("password") or "",
            "next": safe_redirect_target(request.form.get("next")),
        }

        if form["role"] not in {"ADMIN", "FACULTY", "STUDENT"}:
            flash("Please select a valid account type.", "error")
            return render_template("login.html", title="Login", form=form, next_target=form["next"])

        if not form["username"] or not form["password"]:
            flash("Username and password are required.", "error")
            return render_template("login.html", title="Login", form=form, next_target=form["next"])

        try:
            ensure_auth_setup()
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    """
                    SELECT
                      ua.user_id,
                      ua.username,
                      ua.password_hash,
                      ua.role,
                      ua.member_id,
                      ua.must_reset_password,
                      ua.is_active,
                      m.full_name,
                      m.is_active AS member_is_active,
                      mt.type_name
                    FROM user_accounts ua
                    LEFT JOIN members m ON m.member_id = ua.member_id
                    LEFT JOIN member_types mt ON mt.member_type_id = m.member_type_id
                    WHERE ua.username = %s
                    LIMIT 1
                    """,
                    (form["username"],),
                )
                account = cur.fetchone()

            if not account:
                flash("Invalid credentials.", "error")
                return render_template("login.html", title="Login", form=form, next_target=form["next"])

            if account["role"] != form["role"]:
                flash("Selected account type does not match this username.", "error")
                return render_template("login.html", title="Login", form=form, next_target=form["next"])

            if int(account["is_active"]) != 1:
                flash("This account is inactive. Contact admin.", "error")
                return render_template("login.html", title="Login", form=form, next_target=form["next"])

            if account["role"] in {"FACULTY", "STUDENT"}:
                if not account["member_id"] or int(account.get("member_is_active") or 0) != 1:
                    flash("Member account is inactive. Contact admin.", "error")
                    return render_template("login.html", title="Login", form=form, next_target=form["next"])

            if not verify_password(account["password_hash"], form["password"]):
                flash("Invalid credentials.", "error")
                return render_template("login.html", title="Login", form=form, next_target=form["next"])

            session.clear()
            session["auth_user"] = {
                "user_id": int(account["user_id"]),
                "username": account["username"],
                "role": account["role"],
                "member_id": int(account["member_id"]) if account["member_id"] is not None else None,
                "display_name": account["full_name"] if account["full_name"] else "Administrator",
            }

            if int(account["must_reset_password"]) == 1:
                flash("Please reset your password before continuing.", "error")
                return redirect(url_for("reset_password"))

            next_target = form["next"]
            if next_target:
                return redirect(next_target)
            return redirect(url_for(home_endpoint_for_role(account["role"])))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("login.html", title="Login", form=form, next_target=form["next"])

    @app.route("/logout", methods=["GET", "POST"])
    @login_required
    def logout():
        session.clear()
        flash("Logged out successfully.", "success")
        return redirect(url_for("login"))

    @app.route("/reset-password", methods=["GET", "POST"])
    @login_required
    def reset_password():
        user = get_session_user()
        if request.method == "GET":
            return render_template("reset_password.html", title="Reset Password", form={})

        form = {
            "current_password": request.form.get("current_password") or "",
            "new_password": request.form.get("new_password") or "",
            "confirm_password": request.form.get("confirm_password") or "",
        }

        if not form["current_password"] or not form["new_password"] or not form["confirm_password"]:
            flash("All password fields are required.", "error")
            return render_template("reset_password.html", title="Reset Password", form=form)

        if len(form["new_password"]) < 6:
            flash("New password must be at least 6 characters.", "error")
            return render_template("reset_password.html", title="Reset Password", form=form)

        if form["new_password"] != form["confirm_password"]:
            flash("New password and confirm password do not match.", "error")
            return render_template("reset_password.html", title="Reset Password", form=form)

        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT user_id, password_hash FROM user_accounts WHERE user_id = %s FOR UPDATE",
                    (user["user_id"],),
                )
                account = cur.fetchone()

                if not account:
                    conn.rollback()
                    session.clear()
                    flash("Session expired. Please login again.", "error")
                    return redirect(url_for("login"))

                if not verify_password(account["password_hash"], form["current_password"]):
                    conn.rollback()
                    flash("Current password is incorrect.", "error")
                    return render_template("reset_password.html", title="Reset Password", form=form)

                cur2 = conn.cursor()
                cur2.execute(
                    """
                    UPDATE user_accounts
                    SET password_hash = %s, must_reset_password = 0
                    WHERE user_id = %s
                    """,
                    (generate_password_hash(form["new_password"]), user["user_id"]),
                )
                conn.commit()

            flash("Password updated successfully.", "success")
            return redirect(url_for(home_endpoint_for_role(user.get("role"))))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("reset_password.html", title="Reset Password", form=form)

    @app.get("/dashboard")
    @roles_required("ADMIN")
    def dashboard():
        metrics_sql = """
            SELECT
              (SELECT COUNT(*) FROM books) AS total_titles,
              (SELECT COUNT(*) FROM book_copies) AS total_copies,
              (SELECT COUNT(*) FROM book_copies WHERE status = 'AVAILABLE') AS available_copies,
              (SELECT COUNT(*) FROM members WHERE is_active = 1) AS active_members,
              (SELECT COUNT(*) FROM book_issues WHERE return_date IS NULL) AS active_issues,
              (SELECT COUNT(*) FROM book_issues WHERE return_date IS NULL AND due_date < CURDATE()) AS overdue_issues,
              (SELECT COUNT(*) FROM fines WHERE is_paid = 0) AS unpaid_fines_count,
              (SELECT IFNULL(SUM(fine_amount), 0) FROM fines WHERE is_paid = 0) AS unpaid_fines_amount
        """
        due_soon_sql = """
            SELECT
              bi.issue_id,
              bi.due_date,
              m.full_name,
              c.accession_no,
              b.title
            FROM book_issues bi
            JOIN members m ON m.member_id = bi.member_id
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE bi.return_date IS NULL
            ORDER BY bi.due_date ASC
            LIMIT 8
        """
        recent_issues_sql = """
            SELECT
              bi.issue_id,
              bi.issue_date,
              bi.due_date,
              bi.return_date,
              m.full_name,
              c.accession_no,
              b.title
            FROM book_issues bi
            JOIN members m ON m.member_id = bi.member_id
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            ORDER BY bi.issue_id DESC
            LIMIT 8
        """

        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(metrics_sql)
                metrics = cur.fetchone() or {}

                cur.execute(due_soon_sql)
                due_soon = cur.fetchall()

                cur.execute(recent_issues_sql)
                recent_issues = cur.fetchall()

            today = date.today()
            for row in due_soon:
                row["days_left"] = (row["due_date"] - today).days

            return render_template(
                "dashboard.html",
                title="Library Dashboard",
                metrics=metrics,
                due_soon=due_soon,
                recent_issues=recent_issues,
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "dashboard.html",
                title="Library Dashboard",
                metrics={},
                due_soon=[],
                recent_issues=[],
            )

    @app.get("/my/dashboard")
    @roles_required("FACULTY", "STUDENT")
    def member_dashboard():
        user = get_session_user()
        member_id = int(user["member_id"])

        profile_sql = """
            SELECT
              m.member_id,
              m.full_name,
              m.email,
              m.phone,
              mt.type_name,
              mt.max_active_issues,
              mt.max_issue_days
            FROM members m
            JOIN member_types mt ON mt.member_type_id = m.member_type_id
            WHERE m.member_id = %s AND m.is_active = 1
            LIMIT 1
        """
        summary_sql = """
            SELECT
              (SELECT COUNT(*) FROM book_issues WHERE member_id = %s AND return_date IS NULL) AS active_issues,
              (SELECT COUNT(*) FROM book_issues WHERE member_id = %s AND return_date IS NULL AND due_date < CURDATE()) AS overdue_issues,
              (SELECT COUNT(*) FROM fines f JOIN book_issues bi ON bi.issue_id = f.issue_id WHERE bi.member_id = %s AND f.is_paid = 0) AS unpaid_count,
              (SELECT IFNULL(SUM(f.fine_amount), 0) FROM fines f JOIN book_issues bi ON bi.issue_id = f.issue_id WHERE bi.member_id = %s AND f.is_paid = 0) AS unpaid_amount
        """
        active_sql = """
            SELECT
              bi.issue_id,
              bi.issue_date,
              bi.due_date,
              c.accession_no,
              b.title,
              b.author
            FROM book_issues bi
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE bi.member_id = %s AND bi.return_date IS NULL
            ORDER BY bi.due_date ASC
            LIMIT 8
        """

        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(profile_sql, (member_id,))
                profile = cur.fetchone()
                if not profile:
                    session.clear()
                    flash("Your member account is inactive. Please contact admin.", "error")
                    return redirect(url_for("login"))

                cur.execute(summary_sql, (member_id, member_id, member_id, member_id))
                summary = cur.fetchone() or {}

                cur.execute(active_sql, (member_id,))
                active_rows = cur.fetchall()

            today = date.today()
            for row in active_rows:
                days_left = (row["due_date"] - today).days
                row["days_left"] = days_left
                row["is_overdue"] = days_left < 0
                row["overdue_days"] = abs(days_left) if days_left < 0 else 0

            return render_template(
                "member_dashboard.html",
                title="My Dashboard",
                profile=profile,
                summary=summary,
                active_issues=active_rows,
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "member_dashboard.html",
                title="My Dashboard",
                profile={},
                summary={},
                active_issues=[],
            )

    @app.get("/my/issues")
    @roles_required("FACULTY", "STUDENT")
    def member_issues():
        user = get_session_user()
        member_id = int(user["member_id"])

        active_sql = """
            SELECT
              bi.issue_id,
              bi.issue_date,
              bi.due_date,
              c.accession_no,
              b.title,
              b.author
            FROM book_issues bi
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE bi.member_id = %s AND bi.return_date IS NULL
            ORDER BY bi.due_date ASC, bi.issue_id ASC
        """
        history_sql = """
            SELECT
              bi.issue_id,
              bi.issue_date,
              bi.due_date,
              bi.return_date,
              c.accession_no,
              b.title,
              b.author
            FROM book_issues bi
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE bi.member_id = %s
            ORDER BY bi.issue_id DESC
            LIMIT 20
        """

        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(active_sql, (member_id,))
                active_rows = cur.fetchall()

                cur.execute(history_sql, (member_id,))
                history_rows = cur.fetchall()

            today = date.today()
            for row in active_rows:
                days_left = (row["due_date"] - today).days
                row["days_left"] = days_left
                row["is_overdue"] = days_left < 0
                row["overdue_days"] = abs(days_left) if days_left < 0 else 0

            return render_template(
                "member_issues.html",
                title="My Issues",
                active_issues=active_rows,
                history_issues=history_rows,
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "member_issues.html",
                title="My Issues",
                active_issues=[],
                history_issues=[],
            )

    @app.get("/my/fines")
    @roles_required("FACULTY", "STUDENT")
    def member_fines():
        user = get_session_user()
        member_id = int(user["member_id"])

        summary_sql = """
            SELECT
              COUNT(*) AS total_fines,
              IFNULL(SUM(CASE WHEN f.is_paid = 0 THEN 1 ELSE 0 END), 0) AS unpaid_count,
              IFNULL(SUM(CASE WHEN f.is_paid = 0 THEN f.fine_amount ELSE 0 END), 0) AS unpaid_amount
            FROM fines f
            JOIN book_issues bi ON bi.issue_id = f.issue_id
            WHERE bi.member_id = %s
        """
        rows_sql = """
            SELECT
              f.fine_id,
              f.issue_id,
              f.assessed_date,
              f.days_overdue,
              f.fine_amount,
              f.is_paid,
              f.paid_date,
              b.title,
              b.author,
              c.accession_no
            FROM fines f
            JOIN book_issues bi ON bi.issue_id = f.issue_id
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            WHERE bi.member_id = %s
            ORDER BY f.fine_id DESC
        """

        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(summary_sql, (member_id,))
                summary = cur.fetchone() or {}

                cur.execute(rows_sql, (member_id,))
                rows = cur.fetchall()

            return render_template("member_fines.html", title="My Fines", fines=rows, summary=summary)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("member_fines.html", title="My Fines", fines=[], summary={})

    @app.get("/books")
    @roles_required("ADMIN", "FACULTY", "STUDENT")
    def books():
        """View all books with search and availability filters."""
        query_text = (request.args.get("q") or "").strip()
        availability = (request.args.get("availability") or "all").strip().lower()
        if availability not in {"all", "available", "issued", "no_copies"}:
            availability = "all"

        where_clauses = []
        params: list[str] = []
        if query_text:
            where_clauses.append("(b.title LIKE %s OR b.author LIKE %s OR IFNULL(b.isbn, '') LIKE %s)")
            like = f"%{query_text}%"
            params.extend([like, like, like])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        having_sql = ""
        if availability == "available":
            having_sql = "HAVING available_copies > 0"
        elif availability == "issued":
            having_sql = "HAVING issued_copies > 0"
        elif availability == "no_copies":
            having_sql = "HAVING total_copies = 0"

        sql = """
            SELECT
              b.book_id,
              b.title,
              b.author,
              b.publisher,
              b.isbn,
              b.published_year,
              COUNT(c.copy_id) AS total_copies,
              IFNULL(SUM(CASE WHEN c.status = 'AVAILABLE' THEN 1 ELSE 0 END), 0) AS available_copies,
              IFNULL(SUM(CASE WHEN c.status = 'ISSUED' THEN 1 ELSE 0 END), 0) AS issued_copies,
              IFNULL(SUM(CASE WHEN c.status = 'LOST' THEN 1 ELSE 0 END), 0) AS lost_copies,
              IFNULL(SUM(CASE WHEN c.status = 'DAMAGED' THEN 1 ELSE 0 END), 0) AS damaged_copies
            FROM books b
            LEFT JOIN book_copies c ON c.book_id = b.book_id
            {where_sql}
            GROUP BY b.book_id, b.title, b.author, b.publisher, b.isbn, b.published_year
            {having_sql}
            ORDER BY b.book_id DESC
        """.format(where_sql=where_sql, having_sql=having_sql)
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            return render_template(
                "books.html",
                title="Book Catalog",
                books=rows,
                filters={"q": query_text, "availability": availability},
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "books.html",
                title="Book Catalog",
                books=[],
                filters={"q": query_text, "availability": availability},
            )

    @app.route("/books/new", methods=["GET", "POST"])
    @roles_required("ADMIN")
    def add_book():
        """Add new book (optionally with copies)."""
        if request.method == "GET":
            return render_template("add_book.html", title="Add New Book", form={})

        form = {
            "title": (request.form.get("title") or "").strip(),
            "author": (request.form.get("author") or "").strip(),
            "publisher": (request.form.get("publisher") or "").strip() or None,
            "isbn": (request.form.get("isbn") or "").strip() or None,
            "published_year": (request.form.get("published_year") or "").strip(),
            "accession_numbers": (request.form.get("accession_numbers") or "").strip(),
        }

        if not form["title"] or not form["author"]:
            flash("Title and Author are required.", "error")
            return render_template("add_book.html", title="Add New Book", form=form)

        published_year = None
        if form["published_year"]:
            try:
                published_year = int(form["published_year"])
            except ValueError:
                flash("Published year must be a number.", "error")
                return render_template("add_book.html", title="Add New Book", form=form)

        accession_numbers = []
        if form["accession_numbers"]:
            # One per line, ignore empty lines
            accession_numbers = [
                line.strip()
                for line in form["accession_numbers"].splitlines()
                if line.strip()
            ]

        if len(accession_numbers) != len(set(accession_numbers)):
            flash("Duplicate accession numbers found. Each copy ID must be unique.", "error")
            return render_template("add_book.html", title="Add New Book", form=form)

        try:
            with get_conn(app) as conn:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO books (title, author, publisher, isbn, published_year)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (form["title"], form["author"], form["publisher"], form["isbn"], published_year),
                )
                book_id = cur.lastrowid

                # Optional: create copies for this book
                if accession_numbers:
                    for acc in accession_numbers:
                        cur.execute(
                            """
                            INSERT INTO book_copies (book_id, accession_no, status)
                            VALUES (%s, %s, 'AVAILABLE')
                            """,
                            (book_id, acc),
                        )

                conn.commit()

            flash("Book saved successfully.", "success")
            return redirect(url_for("books"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("add_book.html", title="Add New Book", form=form)

    @app.get("/members")
    @roles_required("ADMIN")
    def members_list():
        sql = """
            SELECT
              m.member_id,
              m.full_name,
              m.email,
              m.phone,
              m.is_active,
              mt.type_name,
              mt.max_active_issues,
              mt.max_issue_days,
              ua.username AS login_username,
              ua.is_active AS login_active,
              IFNULL(ai.active_count, 0) AS active_count,
              IFNULL(uf.unpaid_total, 0) AS unpaid_total
            FROM members m
            JOIN member_types mt ON mt.member_type_id = m.member_type_id
            LEFT JOIN user_accounts ua ON ua.member_id = m.member_id
            LEFT JOIN (
              SELECT member_id, COUNT(*) AS active_count
              FROM book_issues
              WHERE return_date IS NULL
              GROUP BY member_id
            ) ai ON ai.member_id = m.member_id
            LEFT JOIN (
              SELECT bi.member_id, SUM(f.fine_amount) AS unpaid_total
              FROM fines f
              JOIN book_issues bi ON bi.issue_id = f.issue_id
              WHERE f.is_paid = 0
              GROUP BY bi.member_id
            ) uf ON uf.member_id = m.member_id
            ORDER BY m.member_id DESC
        """
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql)
                rows = cur.fetchall()
            return render_template("members.html", title="Members", members=rows)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("members.html", title="Members", members=[])

    @app.post("/members/<int:member_id>/status")
    @roles_required("ADMIN")
    def update_member_status(member_id: int):
        action = (request.form.get("action") or "").strip().lower()
        if action not in {"activate", "deactivate"}:
            flash("Invalid member status action.", "error")
            return redirect(url_for("members_list"))

        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT member_id, is_active FROM members WHERE member_id = %s FOR UPDATE",
                    (member_id,),
                )
                member = cur.fetchone()
                if not member:
                    conn.rollback()
                    flash("Member not found.", "error")
                    return redirect(url_for("members_list"))

                if action == "deactivate":
                    cur.execute(
                        "SELECT COUNT(*) AS active_count FROM book_issues WHERE member_id = %s AND return_date IS NULL",
                        (member_id,),
                    )
                    active_count = int(cur.fetchone()["active_count"])
                    if active_count > 0:
                        conn.rollback()
                        flash("Cannot deactivate member with active issues.", "error")
                        return redirect(url_for("members_list"))
                    target_status = 0
                else:
                    target_status = 1

                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE members SET is_active = %s WHERE member_id = %s",
                    (target_status, member_id),
                )
                cur2.execute(
                    "UPDATE user_accounts SET is_active = %s WHERE member_id = %s",
                    (target_status, member_id),
                )
                conn.commit()

            flash("Member status updated successfully.", "success")
            return redirect(url_for("members_list"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return redirect(url_for("members_list"))

    @app.post("/members/<int:member_id>/reset-password")
    @roles_required("ADMIN")
    def reset_member_password(member_id: int):
        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    """
                    SELECT m.member_id, m.is_active, mt.type_name
                    FROM members m
                    JOIN member_types mt ON mt.member_type_id = m.member_type_id
                    WHERE m.member_id = %s
                    FOR UPDATE
                    """,
                    (member_id,),
                )
                member = cur.fetchone()
                if not member:
                    conn.rollback()
                    flash("Member not found.", "error")
                    return redirect(url_for("members_list"))

                username = ensure_member_account(
                    conn=conn,
                    member_id=int(member["member_id"]),
                    role=role_from_member_type(member["type_name"]),
                    is_active=int(member["is_active"]),
                    reset_password=True,
                )
                conn.commit()

            flash(
                f"Password reset for {username}. Default password is {MEMBER_DEFAULT_PASSWORD}.",
                "success",
            )
            return redirect(url_for("members_list"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return redirect(url_for("members_list"))

    @app.route("/members/new", methods=["GET", "POST"])
    @roles_required("ADMIN")
    def register_member():
        """Register new member."""
        try:
            member_types = get_member_types()
        except Exception as exc:
            flash(db_error_message(exc), "error")
            member_types = []

        if request.method == "GET":
            return render_template(
                "register_member.html",
                title="Register Member",
                member_types=member_types,
                form={},
            )

        form = {
            "member_type_id": (request.form.get("member_type_id") or "").strip(),
            "full_name": (request.form.get("full_name") or "").strip(),
            "email": (request.form.get("email") or "").strip() or None,
            "phone": (request.form.get("phone") or "").strip() or None,
        }

        if not form["member_type_id"] or not form["full_name"]:
            flash("Member Type and Full Name are required.", "error")
            return render_template(
                "register_member.html",
                title="Register Member",
                member_types=member_types,
                form=form,
            )

        try:
            member_type_id = int(form["member_type_id"])
        except ValueError:
            flash("Invalid member type.", "error")
            return render_template(
                "register_member.html",
                title="Register Member",
                member_types=member_types,
                form=form,
            )

        type_lookup = {int(t["member_type_id"]): t["type_name"] for t in member_types}

        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO members (member_type_id, full_name, email, phone, is_active)
                    VALUES (%s, %s, %s, %s, 1)
                    """,
                    (member_type_id, form["full_name"], form["email"], form["phone"]),
                )
                member_id = int(cur.lastrowid)

                username = ensure_member_account(
                    conn=conn,
                    member_id=member_id,
                    role=role_from_member_type(type_lookup.get(member_type_id, "STUDENT")),
                    is_active=1,
                    reset_password=False,
                )
                conn.commit()

            flash(
                f"Member registered successfully. Username: {username}, default password: {MEMBER_DEFAULT_PASSWORD}",
                "success",
            )
            return redirect(url_for("register_member"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "register_member.html",
                title="Register Member",
                member_types=member_types,
                form=form,
            )

    @app.get("/issues")
    @roles_required("ADMIN")
    def active_issues():
        status_filter = (request.args.get("status") or "all").strip().lower()
        if status_filter not in {"all", "overdue", "due_soon"}:
            status_filter = "all"

        summary_sql = """
            SELECT
              COUNT(*) AS active_total,
              IFNULL(SUM(CASE WHEN due_date < CURDATE() THEN 1 ELSE 0 END), 0) AS overdue_total
            FROM book_issues
            WHERE return_date IS NULL
        """

        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(summary_sql)
                summary = cur.fetchone() or {}

            rows = get_active_issue_rows(status_filter=status_filter)
            return render_template(
                "active_issues.html",
                title="Active Issues",
                issues=rows,
                status_filter=status_filter,
                summary=summary,
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "active_issues.html",
                title="Active Issues",
                issues=[],
                status_filter=status_filter,
                summary={},
            )

    @app.post("/issues/<int:issue_id>/return")
    @roles_required("ADMIN")
    def quick_return_issue(issue_id: int):
        try:
            result, error_message = process_return(issue_id)
            if error_message:
                flash(error_message, "error")
            else:
                flash(
                    f"Book copy {result['accession_no']} returned successfully. Fine: {result['fine_amount']}",
                    "success",
                )
        except Exception as exc:
            flash(db_error_message(exc), "error")
        return redirect(url_for("active_issues"))

    @app.route("/issue", methods=["GET", "POST"])
    @roles_required("ADMIN")
    def issue_book():
        """Issue a book copy to a member.

        Rules:
          - Copy must be AVAILABLE
          - Member must be active
          - Member cannot exceed max_active_issues
          - Due date = issue_date + max_issue_days
        """
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)

                cur.execute(
                    """
                    SELECT m.member_id, m.full_name, mt.type_name, mt.max_active_issues, mt.max_issue_days
                    FROM members m
                    JOIN member_types mt ON mt.member_type_id = m.member_type_id
                    WHERE m.is_active = 1
                    ORDER BY m.member_id DESC
                    """
                )
                members = cur.fetchall()

                cur.execute(
                    """
                    SELECT c.copy_id, c.accession_no, b.title, b.author
                    FROM book_copies c
                    JOIN books b ON b.book_id = c.book_id
                    WHERE c.status = 'AVAILABLE'
                    ORDER BY c.copy_id DESC
                    """
                )
                copies = cur.fetchall()
        except Exception as exc:
            flash(db_error_message(exc), "error")
            members, copies = [], []

        if request.method == "GET":
            return render_template(
                "issue_book.html",
                title="Issue Book",
                members=members,
                copies=copies,
                form={},
            )

        form = {
            "member_id": (request.form.get("member_id") or "").strip(),
            "copy_id": (request.form.get("copy_id") or "").strip(),
        }

        try:
            member_id = int(form["member_id"])
            copy_id = int(form["copy_id"])
        except ValueError:
            flash("Please select a valid member and copy.", "error")
            return render_template(
                "issue_book.html",
                title="Issue Book",
                members=members,
                copies=copies,
                form=form,
            )

        issue_date = date.today()

        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)

                # Lock member row and get rules
                cur.execute(
                    """
                    SELECT m.member_id, mt.max_active_issues, mt.max_issue_days
                    FROM members m
                    JOIN member_types mt ON mt.member_type_id = m.member_type_id
                    WHERE m.member_id = %s AND m.is_active = 1
                    FOR UPDATE
                    """,
                    (member_id,),
                )
                member = cur.fetchone()
                if not member:
                    conn.rollback()
                    flash("Member not found or inactive.", "error")
                    return render_template(
                        "issue_book.html",
                        title="Issue Book",
                        members=members,
                        copies=copies,
                        form=form,
                    )

                # Enforce max active issues
                cur.execute(
                    """
                    SELECT COUNT(*) AS active_count
                    FROM book_issues
                    WHERE member_id = %s AND return_date IS NULL
                    """,
                    (member_id,),
                )
                active_count = int(cur.fetchone()["active_count"])
                if active_count >= int(member["max_active_issues"]):
                    conn.rollback()
                    flash("This member has reached the maximum active issues.", "error")
                    return render_template(
                        "issue_book.html",
                        title="Issue Book",
                        members=members,
                        copies=copies,
                        form=form,
                    )

                # Lock copy row and ensure it's available
                cur.execute(
                    """
                    SELECT copy_id, status
                    FROM book_copies
                    WHERE copy_id = %s
                    FOR UPDATE
                    """,
                    (copy_id,),
                )
                copy = cur.fetchone()
                if not copy or copy["status"] != "AVAILABLE":
                    conn.rollback()
                    flash("Copy not available.", "error")
                    return render_template(
                        "issue_book.html",
                        title="Issue Book",
                        members=members,
                        copies=copies,
                        form=form,
                    )

                due_date = issue_date + timedelta(days=int(member["max_issue_days"]))

                # Create issue record
                cur2 = conn.cursor()
                cur2.execute(
                    """
                    INSERT INTO book_issues (copy_id, member_id, issue_date, due_date, return_date)
                    VALUES (%s, %s, %s, %s, NULL)
                    """,
                    (copy_id, member_id, issue_date, due_date),
                )
                issue_id = cur2.lastrowid

                # Mark copy as issued
                cur2.execute(
                    "UPDATE book_copies SET status = 'ISSUED' WHERE copy_id = %s",
                    (copy_id,),
                )

                conn.commit()

            flash(f"Book issued successfully. Issue ID: {issue_id}", "success")
            return redirect(url_for("issue_book"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "issue_book.html",
                title="Issue Book",
                members=members,
                copies=copies,
                form=form,
            )

    @app.route("/return", methods=["GET", "POST"])
    @roles_required("ADMIN")
    def return_book():
        """Return a book and calculate fine based on days_overdue."""
        initial_issue_id = (request.args.get("issue_id") or "").strip()
        if request.method == "GET":
            try:
                active_rows = get_active_issue_rows(limit=20)
            except Exception as exc:
                flash(db_error_message(exc), "error")
                active_rows = []
            return render_template(
                "return_book.html",
                title="Return Book",
                form={"issue_id": initial_issue_id},
                result=None,
                active_issues=active_rows,
            )

        form = {"issue_id": (request.form.get("issue_id") or "").strip()}

        try:
            issue_id = int(form["issue_id"])
        except ValueError:
            flash("Issue ID must be a number.", "error")
            try:
                active_rows = get_active_issue_rows(limit=20)
            except Exception:
                active_rows = []
            return render_template(
                "return_book.html",
                title="Return Book",
                form=form,
                result=None,
                active_issues=active_rows,
            )

        try:
            result, error_message = process_return(issue_id)
            if error_message:
                flash(error_message, "error")
                try:
                    active_rows = get_active_issue_rows(limit=20)
                except Exception:
                    active_rows = []
                return render_template(
                    "return_book.html",
                    title="Return Book",
                    form=form,
                    result=None,
                    active_issues=active_rows,
                )

            flash("Book returned successfully.", "success")
            try:
                active_rows = get_active_issue_rows(limit=20)
            except Exception:
                active_rows = []
            return render_template(
                "return_book.html",
                title="Return Book",
                form={},
                result=result,
                active_issues=active_rows,
            )
        except Exception as exc:
            flash(db_error_message(exc), "error")
            try:
                active_rows = get_active_issue_rows(limit=20)
            except Exception:
                active_rows = []
            return render_template(
                "return_book.html",
                title="Return Book",
                form=form,
                result=None,
                active_issues=active_rows,
            )

    @app.get("/fines")
    @roles_required("ADMIN")
    def view_fines():
        """View all fines and payment status."""
        summary_sql = """
            SELECT
              COUNT(*) AS total_fines,
              IFNULL(SUM(CASE WHEN is_paid = 0 THEN 1 ELSE 0 END), 0) AS unpaid_count,
              IFNULL(SUM(CASE WHEN is_paid = 0 THEN fine_amount ELSE 0 END), 0) AS unpaid_amount
            FROM fines
        """
        sql = """
            SELECT
              f.fine_id,
              f.issue_id,
              f.assessed_date,
              f.days_overdue,
              f.fine_amount,
              f.is_paid,
              f.paid_date,
              m.full_name,
              b.title,
              b.author,
              c.accession_no
            FROM fines f
            JOIN book_issues bi ON bi.issue_id = f.issue_id
            JOIN members m ON m.member_id = bi.member_id
            JOIN book_copies c ON c.copy_id = bi.copy_id
            JOIN books b ON b.book_id = c.book_id
            ORDER BY f.fine_id DESC
        """
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(summary_sql)
                summary = cur.fetchone() or {}

                cur.execute(sql)
                rows = cur.fetchall()
            return render_template("fines.html", title="Fines", fines=rows, summary=summary)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("fines.html", title="Fines", fines=[], summary={})

    @app.post("/fines/<int:fine_id>/pay")
    @roles_required("ADMIN")
    def pay_fine(fine_id: int):
        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT fine_id, is_paid FROM fines WHERE fine_id = %s FOR UPDATE", (fine_id,))
                fine = cur.fetchone()

                if not fine:
                    conn.rollback()
                    flash("Fine record not found.", "error")
                    return redirect(url_for("view_fines"))

                if int(fine["is_paid"]) == 1:
                    conn.rollback()
                    flash("Fine is already marked as paid.", "success")
                    return redirect(url_for("view_fines"))

                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE fines SET is_paid = 1, paid_date = %s WHERE fine_id = %s",
                    (date.today(), fine_id),
                )
                conn.commit()

            flash("Fine payment recorded.", "success")
            return redirect(url_for("view_fines"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return redirect(url_for("view_fines"))

    return app


app = create_app()

if __name__ == "__main__":
    # Beginner-friendly way to run without using the Flask CLI
    app.run(debug=True, use_reloader=False, threaded=True)
