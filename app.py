from __future__ import annotations

from datetime import date, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

from config import Config
from db import db_error_message, get_conn


def create_app() -> Flask:
    # Load variables from .env (if present) so beginners don't have to set env vars manually.
    # This must happen BEFORE reading Config.
    load_dotenv(override=False)

    app = Flask(__name__)
    app.config.from_object(Config)

    @app.get("/")
    def index():
        return redirect(url_for("books"))

    @app.get("/books")
    def books():
        """View all books."""
        sql = """
            SELECT
              b.book_id,
              b.title,
              b.author,
              b.publisher,
              b.isbn,
              b.published_year,
                            COUNT(c.copy_id) AS total_copies,
                            IFNULL(SUM(CASE WHEN c.status = 'AVAILABLE' THEN 1 ELSE 0 END), 0) AS available_copies
            FROM books b
            LEFT JOIN book_copies c ON c.book_id = b.book_id
            GROUP BY b.book_id, b.title, b.author, b.publisher, b.isbn, b.published_year
            ORDER BY b.book_id DESC
        """
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql)
                rows = cur.fetchall()
            return render_template("books.html", title="All Books", books=rows)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("books.html", title="All Books", books=[])

    @app.route("/books/new", methods=["GET", "POST"])
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

    @app.route("/members/new", methods=["GET", "POST"])
    def register_member():
        """Register new member."""
        try:
            with get_conn(app) as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT member_type_id, type_name, max_active_issues, max_issue_days FROM member_types ORDER BY member_type_id"
                )
                member_types = cur.fetchall()
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

        try:
            with get_conn(app) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO members (member_type_id, full_name, email, phone, is_active)
                    VALUES (%s, %s, %s, %s, 1)
                    """,
                    (member_type_id, form["full_name"], form["email"], form["phone"]),
                )
                conn.commit()

            flash("Member registered successfully.", "success")
            return redirect(url_for("register_member"))
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template(
                "register_member.html",
                title="Register Member",
                member_types=member_types,
                form=form,
            )

    @app.route("/issue", methods=["GET", "POST"])
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
    def return_book():
        """Return a book and calculate fine based on days_overdue."""
        if request.method == "GET":
            return render_template("return_book.html", title="Return Book", form={}, result=None)

        form = {"issue_id": (request.form.get("issue_id") or "").strip()}

        try:
            issue_id = int(form["issue_id"])
        except ValueError:
            flash("Issue ID must be a number.", "error")
            return render_template("return_book.html", title="Return Book", form=form, result=None)

        return_date = date.today()

        try:
            with get_conn(app) as conn:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)

                # Lock the issue row
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
                    flash("Issue record not found.", "error")
                    return render_template("return_book.html", title="Return Book", form=form, result=None)

                if issue["return_date"] is not None:
                    conn.rollback()
                    flash("This book has already been returned.", "error")
                    return render_template("return_book.html", title="Return Book", form=form, result=None)

                # Update issue return_date
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE book_issues SET return_date = %s WHERE issue_id = %s",
                    (return_date, issue_id),
                )

                # Mark copy as available
                cur2.execute(
                    "UPDATE book_copies SET status = 'AVAILABLE' WHERE copy_id = %s",
                    (issue["copy_id"],),
                )

                # Fine calculation
                due_date = issue["due_date"]
                days_overdue = (return_date - due_date).days
                if days_overdue < 0:
                    days_overdue = 0

                fine_amount = round(days_overdue * float(app.config["DAILY_FINE_RATE"]), 2)

                if days_overdue > 0:
                    # Insert or update fine for this issue (unique issue_id)
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

            flash("Book returned successfully.", "success")
            return render_template("return_book.html", title="Return Book", form={}, result=result)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("return_book.html", title="Return Book", form=form, result=None)

    @app.get("/fines")
    def view_fines():
        """View all fines and payment status."""
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
                cur.execute(sql)
                rows = cur.fetchall()
            return render_template("fines.html", title="Fines", fines=rows)
        except Exception as exc:
            flash(db_error_message(exc), "error")
            return render_template("fines.html", title="Fines", fines=[])

    return app


app = create_app()

if __name__ == "__main__":
    # Beginner-friendly way to run without using the Flask CLI
    app.run(debug=True)
