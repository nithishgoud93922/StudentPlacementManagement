import os
import re
import time
from datetime import date
from functools import wraps
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename
import csv
from io import StringIO

from flask import make_response
import csv
from io import StringIO
import random


# --------------------------------------------------
#1. LOAD ENVIRONMENT VARIABLES, GEMINI CONFIGURATION - OPTIMIZED
# --------------------------------------------------

load_dotenv("app.env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

gemini_client = None

if GEMINI_API_KEY:
    gemini_client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=45000,
            retry_options=types.HttpRetryOptions(
                attempts=1
            )
        )
    )

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "development-only-change-this-secret"
)

db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_NAME", "placement_db")
db_user = os.getenv("DB_USER", "root")
db_password = os.getenv("DB_PASSWORD", "")

encoded_password = quote_plus(db_password)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{db_user}:{encoded_password}"
    f"@{db_host}:{db_port}/{db_name}"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --------------------------------------------------
# 2. DATABASE MODELS
# --------------------------------------------------

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum("student", "recruiter", "officer"),
        nullable=False,
        default="student",
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=func.now()
    )


class StudentProfile(db.Model):
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False
    )
    roll_number = db.Column(db.String(50), unique=True, nullable=True)
    branch = db.Column(db.String(100), nullable=True)
    graduation_year = db.Column(db.Integer, nullable=True)
    cgpa = db.Column(db.Float, nullable=True)
    skills = db.Column(db.Text, nullable=True)
    resume_path = db.Column(db.String(255), nullable=True)

    user = db.relationship("User", backref="student_profile")


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    website = db.Column(db.String(255), nullable=True)
    industry = db.Column(db.String(100), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=func.now()
    )


class RecruiterProfile(db.Model):
    __tablename__ = "recruiter_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False
    )
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id"), nullable=True
    )
    designation = db.Column(db.String(100), nullable=True)

    user = db.relationship("User", backref="recruiter_profile")
    company = db.relationship("Company", backref="recruiters")


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id"), nullable=False
    )
    posted_by = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(150), nullable=True)
    minimum_cgpa = db.Column(db.Float, nullable=True)
    package_lpa = db.Column(db.Float, nullable=True)
    application_deadline = db.Column(db.Date, nullable=True)
    status = db.Column(
        db.Enum("draft", "open", "closed"),
        nullable=False,
        default="open",
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=func.now()
    )

    company = db.relationship("Company", backref="jobs")
    recruiter = db.relationship("User", backref="posted_jobs")


class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id"), nullable=False
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    status = db.Column(
        db.Enum(
            "applied",
            "shortlisted",
            "interview",
            "offered",
            "rejected",
            "withdrawn",
        ),
        nullable=False,
        default="applied",
    )
    applied_at = db.Column(
        db.DateTime, nullable=False, server_default=func.now()
    )

    job = db.relationship("Job", backref="applications")
    student = db.relationship("User", backref="applications")

    __table_args__ = (
        db.UniqueConstraint(
            "job_id", "student_id", name="uq_job_student_application"
        ),
    )


# --------------------------------------------------
# 3. ROLE-BASED ACCESS CONTROL
# --------------------------------------------------

def role_required(*allowed_roles):
    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))

            if session.get("user_role") not in allowed_roles:
                flash("You are not authorized to access that page.", "danger")
                return redirect(url_for("dashboard"))

            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


# --------------------------------------------------
# 4. HOME, HEALTH AND DATABASE CHECKS
# --------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/db-check")
def db_check():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({
            "database": "connected",
            "name": db_name,
        })
    except Exception:
        app.logger.exception("Database connection check failed")
        return jsonify({
            "database": "disconnected",
            "message": "Check your app.env settings and MySQL service.",
        }), 500


# --------------------------------------------------
# 5. REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "student").strip().lower()

        # Public registration must not create officer accounts.
        if role not in ("student", "recruiter"):
            flash("Please select a valid account type.", "danger")
            return render_template("register.html")

        if not full_name or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template("register.html")

        user = User.query.filter_by(email=email).first()

        if user:
            flash("An account with this email already exists.", "danger")
            return render_template("register.html")

        new_user = User(
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=True,
        )

        try:
            db.session.add(new_user)
            db.session.flush()

            if role == "student":
                db.session.add(StudentProfile(user_id=new_user.id))
            elif role == "recruiter":
                db.session.add(RecruiterProfile(user_id=new_user.id))

            db.session.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        except IntegrityError:
            db.session.rollback()
            flash(
                "Registration could not be completed. "
                "The email or another unique value may already exist.",
                "danger",
            )
        except Exception:
            db.session.rollback()
            app.logger.exception("Registration failed")
            flash("Registration failed. Please try again.", "danger")

    return render_template("register.html")


# --------------------------------------------------
# 6. LOGIN AND LOGOUT
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if (
            user
            and user.is_active
            and check_password_hash(user.password_hash, password)
        ):
            session.clear()
            session["user_id"] = user.id
            session["user_role"] = user.role
            session["user_name"] = user.full_name

            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password, or account is inactive.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))



# --------------------------------------------------
# 7. DASHBOARD REDIRECTION
# --------------------------------------------------

@app.route("/dashboard")
@app.route("/student/dashboard", endpoint="student_dashboard")
def dashboard():

    # Check whether user is logged in
    if "user_id" not in session:
        flash("Please log in to continue.", "warning")
        return redirect(url_for("login"))

    # --------------------------------------------------
    # STUDENT DASHBOARD
    # --------------------------------------------------

    if session.get("user_role") == "student":

        user_id = session["user_id"]
        today = date.today()

        # Get student profile
        profile = StudentProfile.query.filter_by(
            user_id=user_id
        ).first()

        # --------------------------------------------------
        # 1. TOTAL AVAILABLE JOBS
        # --------------------------------------------------

        total_jobs = Job.query.filter(
            Job.status == "open"
        ).filter(
            (Job.application_deadline.is_(None)) |
            (Job.application_deadline >= today)
        ).count()

        # --------------------------------------------------
        # 2. TOTAL APPLICATIONS
        # --------------------------------------------------

        total_applications = Application.query.filter_by(
            student_id=user_id
        ).count()

        # --------------------------------------------------
        # 3. SHORTLISTED APPLICATIONS
        # --------------------------------------------------

        shortlisted_applications = Application.query.filter_by(
            student_id=user_id,
            status="shortlisted"
        ).count()

        # --------------------------------------------------
        # 4. SELECTED APPLICATIONS
        # --------------------------------------------------

        selected_applications = Application.query.filter_by(
            student_id=user_id,
            status="offered"
        ).count()

        # --------------------------------------------------
        # 5. RECENT FIVE APPLICATIONS
        # --------------------------------------------------

        recent_applications = (
            db.session.query(Application, Job, Company)
            .join(
                Job,
                Application.job_id == Job.id
            )
            .join(
                Company,
                Job.company_id == Company.id
            )
            .filter(
                Application.student_id == user_id
            )
            .order_by(
                Application.applied_at.desc()
            )
            .limit(5)
            .all()
        )

        # --------------------------------------------------
        # 6. PROFILE COMPLETION
        # --------------------------------------------------

        profile_fields = [

            profile.roll_number if profile else None,

            profile.branch if profile else None,

            profile.graduation_year if profile else None,

            profile.cgpa if profile else None,

            profile.skills if profile else None,

            profile.resume_path if profile else None

        ]

        # Count completed profile fields
        completed_fields = sum(
            1
            for field in profile_fields
            if field is not None and str(field).strip()
        )

        # Calculate profile completion percentage
        profile_completion = int(
            (completed_fields / len(profile_fields)) * 100
        )

        # --------------------------------------------------
        # 7. RENDER STUDENT DASHBOARD
        # --------------------------------------------------

        return render_template(
            "dashboard.html",

            total_jobs=total_jobs,

            total_applications=total_applications,

            shortlisted_applications=shortlisted_applications,

            selected_applications=selected_applications,

            recent_applications=recent_applications,

            profile_completion=profile_completion
        )

    # --------------------------------------------------
    # RECRUITER AND PLACEMENT OFFICER DASHBOARDS
    # --------------------------------------------------

    return render_template("dashboard.html")


# --------------------------------------------------
# 8. STUDENT PROFILE
# --------------------------------------------------

@app.route("/student/profile", methods=["GET", "POST"])
@role_required("student")
def student_profile():

    profile = StudentProfile.query.filter_by(
        user_id=session["user_id"]
    ).first()

    if not profile:
        profile = StudentProfile(user_id=session["user_id"])
        db.session.add(profile)
        db.session.commit()

    # Resume storage settings
    upload_folder = os.path.join(
        app.root_path, "static", "uploads", "resumes"
    )

    static_folder = os.path.abspath(
        os.path.join(app.root_path, "static")
    )

    allowed_extensions = {".pdf", ".doc", ".docx"}
    max_file_size = 5 * 1024 * 1024  # 5 MB

    def delete_resume_file(relative_path):
        """Delete a stored resume only if it is inside static/."""

        if not relative_path:
            return

        old_path = os.path.abspath(
            os.path.join(static_folder, relative_path)
        )

        try:
            if os.path.commonpath(
                [static_folder, old_path]
            ) == static_folder and os.path.isfile(old_path):
                os.remove(old_path)

        except (ValueError, OSError):
            app.logger.exception("Could not delete old resume")

    if request.method == "POST":

        # Delete existing resume
        if request.form.get("action") == "delete_resume":

            if profile.resume_path:
                old_resume = profile.resume_path

                profile.resume_path = None
                db.session.commit()

                delete_resume_file(old_resume)

                flash("Resume deleted successfully.", "success")
            else:
                flash("No resume is available to delete.", "warning")

            return redirect(url_for("student_profile"))

        new_file_path = None

        try:
            roll_number = request.form.get(
                "roll_number", ""
            ).strip()

            branch = request.form.get(
                "branch", ""
            ).strip()

            skills = request.form.get(
                "skills", ""
            ).strip()

            graduation_year_text = request.form.get(
                "graduation_year", ""
            ).strip()

            cgpa_text = request.form.get(
                "cgpa", ""
            ).strip()

            graduation_year = (
                int(graduation_year_text)
                if graduation_year_text else None
            )

            cgpa = (
                float(cgpa_text)
                if cgpa_text else None
            )

            # Validate graduation year
            if graduation_year is not None and not (
                2000 <= graduation_year <= 2100
            ):
                raise ValueError(
                    "Enter a valid graduation year."
                )

            # Validate CGPA
            if cgpa is not None and not (0 <= cgpa <= 10):
                raise ValueError(
                    "CGPA must be between 0 and 10."
                )

            # Get uploaded resume, if provided
            uploaded_file = request.files.get("resume")

            old_resume = profile.resume_path

            if uploaded_file and uploaded_file.filename:

                original_filename = secure_filename(
                    uploaded_file.filename
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if extension not in allowed_extensions:
                    raise ValueError(
                        "Only PDF, DOC and DOCX files are allowed."
                    )

                # Check file size
                file_data = uploaded_file.read(
                    max_file_size + 1
                )

                if len(file_data) > max_file_size:
                    raise ValueError(
                        "Resume size must not exceed 5 MB."
                    )

                uploaded_file.seek(0)

                # Create upload directory
                os.makedirs(
                    upload_folder,
                    exist_ok=True
                )

                # Generate a unique filename
                filename = (
                    f"student_{session['user_id']}_"
                    f"{time.time_ns()}{extension}"
                )

                new_file_path = os.path.join(
                    upload_folder,
                    filename
                )

                uploaded_file.save(new_file_path)

                # Store path relative to static/
                profile.resume_path = (
                    "uploads/resumes/" + filename
                )

            # Update profile information
            profile.roll_number = roll_number or None
            profile.branch = branch or None
            profile.skills = skills or None
            profile.graduation_year = graduation_year
            profile.cgpa = cgpa

            db.session.commit()

            # Delete previous resume after successful update
            if new_file_path and old_resume:
                delete_resume_file(old_resume)

            flash(
                "Student profile updated successfully.",
                "success"
            )

            return redirect(url_for("student_profile"))

        except ValueError as error:
            db.session.rollback()

            if new_file_path and os.path.isfile(new_file_path):
                os.remove(new_file_path)

            flash(str(error), "danger")

        except IntegrityError:
            db.session.rollback()

            if new_file_path and os.path.isfile(new_file_path):
                os.remove(new_file_path)

            flash(
                "That roll number is already registered.",
                "danger"
            )

        except Exception:
            db.session.rollback()

            if new_file_path and os.path.isfile(new_file_path):
                os.remove(new_file_path)

            app.logger.exception(
                "Student profile update failed"
            )

            flash(
                "Could not update your profile.",
                "danger"
            )

    return render_template(
        "profile.html",
        profile=profile
    )


# --------------------------------------------------
# 9. JOB LISTINGS
# --------------------------------------------------

@app.route("/jobs")
@role_required("student", "officer")
def jobs():

    today = date.today()

    # Get search and filter values
    search_query = request.args.get("q", "").strip()
    location_filter = request.args.get("location", "").strip()
    eligible_only = request.args.get("eligible_only") == "on"

    # Get student profile
    student_profile = None

    if session.get("user_role") == "student":
        student_profile = StudentProfile.query.filter_by(
            user_id=session["user_id"]
        ).first()

    # Start with currently available jobs
    jobs_query = Job.query.filter(
        Job.status == "open",
        db.or_(
            Job.application_deadline.is_(None),
            Job.application_deadline >= today
        )
    )

    # Search by title, company, description or location
    if search_query:

        search_pattern = f"%{search_query}%"

        jobs_query = jobs_query.filter(
            db.or_(
                Job.title.ilike(search_pattern),
                Job.description.ilike(search_pattern),
                Job.location.ilike(search_pattern),
                Job.company.has(
                    Company.company_name.ilike(search_pattern)
                )
            )
        )

    # Filter by location
    if location_filter:

        jobs_query = jobs_query.filter(
            Job.location.ilike(f"%{location_filter}%")
        )

    # Show only jobs matching student's CGPA
    if eligible_only and student_profile and student_profile.cgpa is not None:

        jobs_query = jobs_query.filter(
            db.or_(
                Job.minimum_cgpa.is_(None),
                Job.minimum_cgpa <= student_profile.cgpa
            )
        )

    # Latest jobs first
    available_jobs = jobs_query.order_by(
        Job.created_at.desc()
    ).all()

    # Find jobs the student has already applied for
    applied_job_ids = set()

    if session.get("user_role") == "student":

        applications = Application.query.filter_by(
            student_id=session["user_id"]
        ).all()

        applied_job_ids = {
            application.job_id
            for application in applications
        }

    return render_template(
        "jobs.html",
        jobs=available_jobs,
        profile=student_profile,
        applied_job_ids=applied_job_ids,
        search_query=search_query,
        location_filter=location_filter,
        eligible_only=eligible_only
    )

# --------------------------------------------------
# 10. APPLY FOR A JOB
# --------------------------------------------------

@app.route("/apply/<int:job_id>", methods=["POST"])
@role_required("student")
def apply(job_id):
    job = db.session.get(Job, job_id)

    if not job or job.status != "open":
        flash("This job is not currently available.", "danger")
        return redirect(url_for("jobs"))

    if (
        job.application_deadline
        and job.application_deadline < date.today()
    ):
        flash("The application deadline has passed.", "danger")
        return redirect(url_for("jobs"))

    profile = StudentProfile.query.filter_by(
        user_id=session["user_id"]
    ).first()

    if not profile or profile.cgpa is None:
        flash("Please complete your profile and CGPA first.", "warning")
        return redirect(url_for("student_profile"))

    if (
        job.minimum_cgpa is not None
        and profile.cgpa < job.minimum_cgpa
    ):
        flash("Your CGPA does not meet this job's requirement.", "danger")
        return redirect(url_for("jobs"))

    existing_application = Application.query.filter_by(
        job_id=job.id,
        student_id=session["user_id"],
    ).first()

    if existing_application:
        flash("You have already applied for this job.", "warning")
        return redirect(url_for("jobs"))

    application = Application(
        job_id=job.id,
        student_id=session["user_id"],
        status="applied",
    )

    try:
        db.session.add(application)
        db.session.commit()
        flash("Your application has been submitted.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("You have already applied for this job.", "warning")
    except Exception:
        db.session.rollback()
        app.logger.exception("Job application failed")
        flash("Could not submit your application.", "danger")

    return redirect(url_for("my_applications"))



# --------------------------------------------------
# 11. STUDENT APPLICATION MANAGEMENT
# --------------------------------------------------

@app.route("/my-applications")
@role_required("student")
def my_applications():

    user_id = session["user_id"]

    # Allowed application status filters
    valid_statuses = [
        "applied",
        "shortlisted",
        "interview",
        "offered",
        "rejected",
        "withdrawn"
    ]

    selected_status = request.args.get("status", "").strip().lower()

    if selected_status not in valid_statuses:
        selected_status = ""

    # Base query for the logged-in student's applications
    applications_query = (
        db.session.query(Application, Job, Company)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .filter(Application.student_id == user_id)
    )

    # Apply status filter
    if selected_status:
        applications_query = applications_query.filter(
            Application.status == selected_status
        )

    applications = (
        applications_query
        .order_by(Application.applied_at.desc())
        .all()
    )

    # Count all applications by status
    status_counts = {}

    for status in valid_statuses:
        status_counts[status] = Application.query.filter_by(
            student_id=user_id,
            status=status
        ).count()

    total_applications = sum(status_counts.values())

    return render_template(
        "applications.html",
        applications=applications,
        status_counts=status_counts,
        total_applications=total_applications,
        selected_status=selected_status
    )


# --------------------------------------------------
# 11A. WITHDRAW APPLICATION
# --------------------------------------------------

@app.route(
    "/application/<int:application_id>/withdraw",
    methods=["POST"]
)
@role_required("student")
def withdraw_application(application_id):

    application = Application.query.filter_by(
        id=application_id,
        student_id=session["user_id"]
    ).first()

    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("my_applications"))

    # Only applications with applied status can be withdrawn
    if application.status != "applied":
        flash(
            "Only applications with Applied status can be withdrawn.",
            "warning"
        )
        return redirect(url_for("my_applications"))

    try:
        application.status = "withdrawn"
        db.session.commit()

        flash(
            "Your application has been withdrawn successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Application withdrawal failed")

        flash(
            "Could not withdraw your application.",
            "danger"
        )

    return redirect(url_for("my_applications"))


# --------------------------------------------------
# 12. RECRUITER JOB MANAGEMENT
# --------------------------------------------------

@app.route("/recruiter/jobs", methods=["GET", "POST"])
@role_required("recruiter")
def recruiter_jobs():

    recruiter_id = session["user_id"]

    recruiter_profile = RecruiterProfile.query.filter_by(
        user_id=recruiter_id
    ).first()

    if not recruiter_profile:
        recruiter_profile = RecruiterProfile(
            user_id=recruiter_id
        )
        db.session.add(recruiter_profile)
        db.session.commit()

    if request.method == "POST":

        company_name = request.form.get(
            "company_name", ""
        ).strip()

        title = request.form.get("title", "").strip()

        description = request.form.get(
            "description", ""
        ).strip()

        location = request.form.get(
            "location", ""
        ).strip()

        minimum_cgpa_text = request.form.get(
            "minimum_cgpa", ""
        ).strip()

        package_lpa_text = request.form.get(
            "package_lpa", ""
        ).strip()

        deadline_text = request.form.get(
            "application_deadline", ""
        ).strip()

        if not company_name or not title or not description:
            flash(
                "Company name, job title, and description are required.",
                "danger"
            )
            return redirect(url_for("recruiter_jobs"))

        try:

            minimum_cgpa = (
                float(minimum_cgpa_text)
                if minimum_cgpa_text else None
            )

            package_lpa = (
                float(package_lpa_text)
                if package_lpa_text else None
            )

            deadline = (
                date.fromisoformat(deadline_text)
                if deadline_text else None
            )

            if minimum_cgpa is not None and not (
                0 <= minimum_cgpa <= 10
            ):
                raise ValueError(
                    "Minimum CGPA must be between 0 and 10."
                )

            if package_lpa is not None and package_lpa < 0:
                raise ValueError(
                    "Package cannot be negative."
                )

            if deadline and deadline < date.today():
                raise ValueError(
                    "The deadline cannot be in the past."
                )

            company = Company.query.filter(
                func.lower(Company.company_name)
                == company_name.lower()
            ).first()

            if not company:
                company = Company(
                    company_name=company_name
                )
                db.session.add(company)
                db.session.flush()

            recruiter_profile.company_id = company.id

            new_job = Job(
                company_id=company.id,
                posted_by=recruiter_id,
                title=title,
                description=description,
                location=location or None,
                minimum_cgpa=minimum_cgpa,
                package_lpa=package_lpa,
                application_deadline=deadline,
                status="open"
            )

            db.session.add(new_job)
            db.session.commit()

            flash(
                "Job posted successfully.",
                "success"
            )

            return redirect(url_for("recruiter_jobs"))

        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Job posting failed")

            flash(
                "Could not post the job. Please try again.",
                "danger"
            )

    # Recruiter's own jobs
    recruiter_jobs_list = Job.query.filter_by(
        posted_by=recruiter_id
    ).order_by(
        Job.created_at.desc()
    ).all()

    # Dashboard statistics
    total_jobs = len(recruiter_jobs_list)

    open_jobs = sum(
        1 for job in recruiter_jobs_list
        if job.status == "open"
    )

    closed_jobs = sum(
        1 for job in recruiter_jobs_list
        if job.status == "closed"
    )

    # Applicant count for each job
    job_application_counts = {}

    for job in recruiter_jobs_list:
        job_application_counts[job.id] = (
            Application.query.filter_by(
                job_id=job.id
            ).count()
        )

    total_applicants = sum(
        job_application_counts.values()
    )

    return render_template(
        "recruiter_jobs.html",
        jobs=recruiter_jobs_list,
        recruiter_profile=recruiter_profile,
        total_jobs=total_jobs,
        open_jobs=open_jobs,
        closed_jobs=closed_jobs,
        total_applicants=total_applicants,
        job_application_counts=job_application_counts
    )


# --------------------------------------------------
# 12A. CLOSE / REOPEN JOB
# --------------------------------------------------

@app.route(
    "/recruiter/job/<int:job_id>/toggle",
    methods=["POST"]
)
@role_required("recruiter")
def toggle_recruiter_job(job_id):

    job = Job.query.filter_by(
        id=job_id,
        posted_by=session["user_id"]
    ).first()

    if not job:
        flash(
            "Job not found or you are not authorized.",
            "danger"
        )
        return redirect(url_for("recruiter_jobs"))


    # --------------------------------------------------
# 12B. EDIT RECRUITER JOB
# --------------------------------------------------

@app.route("/recruiter/job/<int:job_id>/edit", methods=["GET", "POST"])
@role_required("recruiter")
def edit_recruiter_job(job_id):

    job = Job.query.filter_by(
        id=job_id,
        posted_by=session["user_id"]
    ).first_or_404()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        minimum_cgpa_text = request.form.get("minimum_cgpa", "").strip()
        package_lpa_text = request.form.get("package_lpa", "").strip()
        deadline_text = request.form.get("application_deadline", "").strip()

        try:
            if not company_name or not title or not description:
                raise ValueError("Company, job title, and description are required.")

            minimum_cgpa = float(minimum_cgpa_text) if minimum_cgpa_text else None
            package_lpa = float(package_lpa_text) if package_lpa_text else None
            deadline = date.fromisoformat(deadline_text) if deadline_text else None

            if minimum_cgpa is not None and not 0 <= minimum_cgpa <= 10:
                raise ValueError("Minimum CGPA must be between 0 and 10.")

            if package_lpa is not None and package_lpa < 0:
                raise ValueError("Package cannot be negative.")

            if deadline and deadline < date.today():
                raise ValueError("Deadline cannot be in the past.")

            company = Company.query.filter(
                func.lower(Company.company_name) == company_name.lower()
            ).first()

            if not company:
                company = Company(company_name=company_name)
                db.session.add(company)
                db.session.flush()

            job.company_id = company.id
            job.title = title
            job.description = description
            job.location = location or None
            job.minimum_cgpa = minimum_cgpa
            job.package_lpa = package_lpa
            job.application_deadline = deadline

            db.session.commit()
            flash("Job updated successfully.", "success")
            return redirect(url_for("recruiter_jobs"))

        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Job editing failed")
            flash("Could not update the job.", "danger")

    return render_template("edit_job.html", job=job)

    if job.status == "open":
        job.status = "closed"
        message = "Job closed successfully."

    elif job.status == "closed":
        job.status = "open"
        message = "Job reopened successfully."

    else:
        flash(
            "Only open or closed jobs can be changed.",
            "warning"
        )
        return redirect(url_for("recruiter_jobs"))

    try:
        db.session.commit()
        flash(message, "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Job status update failed")

        flash(
            "Could not update job status.",
            "danger"
        )

    return redirect(url_for("recruiter_jobs"))


# --------------------------------------------------
# 13. RECRUITER APPLICANT MANAGEMENT
# --------------------------------------------------

@app.route("/recruiter/applicants", methods=["GET", "POST"])
@role_required("recruiter")
def recruiter_applicants():
    allowed_statuses = {
        "shortlisted",
        "interview",
        "offered",
        "rejected",
    }

    if request.method == "POST":
        application_id_text = request.form.get(
            "application_id", ""
        ).strip()
        new_status = request.form.get("status", "").strip().lower()

        if new_status not in allowed_statuses:
            flash("Please select a valid application status.", "danger")
            return redirect(url_for("recruiter_applicants"))

        try:
            application_id = int(application_id_text)
        except (ValueError, TypeError):
            flash("Invalid application selected.", "danger")
            return redirect(url_for("recruiter_applicants"))

        application = (
            db.session.query(Application)
            .join(Job, Application.job_id == Job.id)
            .filter(
                Application.id == application_id,
                Job.posted_by == session["user_id"],
            )
            .first()
        )

        if not application:
            flash(
                "Application not found or you are not authorized to update it.",
                "danger",
            )
            return redirect(url_for("recruiter_applicants"))

        try:
            application.status = new_status
            db.session.commit()
            flash("Application status updated successfully.", "success")
        except Exception:
            db.session.rollback()
            app.logger.exception("Application status update failed")
            flash("Could not update the application status.", "danger")

        return redirect(url_for("recruiter_applicants"))

    applicants = (
        db.session.query(
            Application,
            Job,
            Company,
            User,
            StudentProfile,
        )
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .join(User, Application.student_id == User.id)
        .outerjoin(
            StudentProfile,
            StudentProfile.user_id == User.id,
        )
        .filter(Job.posted_by == session["user_id"])
        .order_by(Application.applied_at.desc())
        .all()
    )

    return render_template(
        "recruiter_applicants.html",
        applicants=applicants,
    )


@app.route("/officer/home")
@role_required("officer")
def officer_home():
    return redirect(url_for("dashboard"))

# --------------------------------------------------
# 14. PLACEMENT OFFICER DASHBOARD
# --------------------------------------------------

@app.route("/officer/dashboard")
@role_required("officer")
def officer_dashboard():

    # 1. MAIN DASHBOARD STATISTICS

    total_students = User.query.filter_by(
        role="student"
    ).count()

    total_recruiters = User.query.filter_by(
        role="recruiter"
    ).count()

    total_jobs = Job.query.count()

    total_applications = Application.query.count()

    total_offers = Application.query.filter_by(
        status="offered"
    ).count()

    # 2. APPLICATION STATUS STATISTICS

    total_applied = Application.query.filter_by(
        status="applied"
    ).count()

    total_shortlisted = Application.query.filter_by(
        status="shortlisted"
    ).count()

    total_interview = Application.query.filter_by(
        status="interview"
    ).count()

    total_rejected = Application.query.filter_by(
        status="rejected"
    ).count()

    # 3. PLACEMENT PERCENTAGE

    placed_students = (
        db.session.query(Application.student_id)
        .filter(Application.status == "offered")
        .distinct()
        .count()
    )

    placement_percentage = (
        (placed_students / total_students) * 100
        if total_students > 0 else 0
    )

    # 4. BRANCH-WISE STUDENT ANALYTICS

    branch_stats = (
        db.session.query(
            StudentProfile.branch,
            func.count(StudentProfile.id)
        )
        .filter(StudentProfile.branch.isnot(None))
        .group_by(StudentProfile.branch)
        .order_by(func.count(StudentProfile.id).desc())
        .all()
    )

    branch_labels = [
        branch for branch, count in branch_stats
    ]

    branch_values = [
        count for branch, count in branch_stats
    ]

    # 5. APPLICATION STATUS CHART DATA

    status_labels = [
        "Applied",
        "Shortlisted",
        "Interview",
        "Offered",
        "Rejected"
    ]

    status_values = [
        total_applied,
        total_shortlisted,
        total_interview,
        total_offers,
        total_rejected
    ]

    # 6. RECENT FIVE STUDENT APPLICATIONS

    recent_applications = (
        db.session.query(
            Application,
            User,
            Job,
            Company
        )
        .join(User, Application.student_id == User.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .order_by(Application.applied_at.desc())
        .limit(5)
        .all()
    )

    # 7. COMPANY-WISE PLACEMENT ANALYTICS

    company_stats = (
        db.session.query(
            Company.company_name,
            func.count(
                func.distinct(Job.id)
            ).label("total_jobs"),
            func.count(
                Application.id
            ).label("total_offers")
        )
        .outerjoin(
            Job,
            Job.company_id == Company.id
        )
        .outerjoin(
            Application,
            (Application.job_id == Job.id) &
            (Application.status == "offered")
        )
        .group_by(
            Company.id,
            Company.company_name
        )
        .order_by(Company.company_name)
        .all()
    )

    # 8. COMPANY CHART DATA

    company_labels = [
        company for company, jobs, offers in company_stats
    ]

    company_offer_values = [
        offers for company, jobs, offers in company_stats
    ]

    # 9. PLACEMENT CHART DATA

    not_placed_students = max(
        total_students - placed_students,
        0
    )

    # 10. SEND ALL DATA TO HTML

    return render_template(
        "officer_dashboard.html",

        total_students=total_students,
        total_recruiters=total_recruiters,
        total_jobs=total_jobs,
        total_applications=total_applications,
        total_offers=total_offers,

        placed_students=placed_students,
        not_placed_students=not_placed_students,
        placement_percentage=round(placement_percentage, 2),

        total_applied=total_applied,
        total_shortlisted=total_shortlisted,
        total_interview=total_interview,
        total_rejected=total_rejected,

        branch_stats=branch_stats,
        branch_labels=branch_labels,
        branch_values=branch_values,

        status_labels=status_labels,
        status_values=status_values,

        recent_applications=recent_applications,

        company_stats=company_stats,
        company_labels=company_labels,
        company_offer_values=company_offer_values
    )

# --------------------------------------------------
# 15. PLACEMENT OFFICER STUDENT MANAGEMENT
# --------------------------------------------------

@app.route("/officer/students")
@role_required("officer")
def officer_students():

    search = request.args.get("search", "").strip()
    branch = request.args.get("branch", "").strip()

    query = (
        db.session.query(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .filter(User.role == "student")
    )

    if search:
        query = query.filter(
            db.or_(
                User.full_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                StudentProfile.roll_number.ilike(f"%{search}%")
            )
        )

    if branch:
        query = query.filter(StudentProfile.branch == branch)

    students = query.order_by(User.full_name).all()

    branches = [
        row[0] for row in
        db.session.query(StudentProfile.branch)
        .filter(StudentProfile.branch.isnot(None))
        .distinct()
        .order_by(StudentProfile.branch)
        .all()
    ]

    return render_template(
        "officer_students.html",
        students=students,
        branches=branches,
        search=search,
        selected_branch=branch
    )


@app.route("/officer/student/<int:user_id>/toggle", methods=["POST"])
@role_required("officer")
def toggle_student(user_id):

    student = User.query.filter_by(
        id=user_id,
        role="student"
    ).first_or_404()

    student.is_active = not student.is_active

    try:
        db.session.commit()
        flash(
            "Student account status updated successfully!",
            "success"
        )
    except Exception:
        db.session.rollback()
        app.logger.exception("Student account status update failed")
        flash("Could not update student account status.", "danger")

    return redirect(url_for("officer_students"))


# --------------------------------------------------
# 15. STUDENT PERFORMANCE ANALYTICS
# --------------------------------------------------

def get_student_analytics_data():

    # Get all students and their profiles
    student_records = (
        db.session.query(User, StudentProfile)
        .outerjoin(
            StudentProfile,
            StudentProfile.user_id == User.id
        )
        .filter(User.role == "student")
        .order_by(User.full_name)
        .all()
    )

    total_students = len(student_records)

    # Students with at least one offer
    placed_student_ids = {
        row[0] for row in
        db.session.query(Application.student_id)
        .filter(Application.status == "offered")
        .distinct()
        .all()
    }

    # Students eligible for at least one open job
    eligible_student_ids = set(
        row[0] for row in
        db.session.query(StudentProfile.user_id)
        .join(
            Job,
            db.or_(
                Job.minimum_cgpa.is_(None),
                StudentProfile.cgpa >= Job.minimum_cgpa
            )
        )
        .filter(
            Job.status == "open",
            StudentProfile.cgpa.isnot(None)
        )
        .distinct()
        .all()
    )

    placed_count = len(placed_student_ids)
    not_placed_count = max(total_students - placed_count, 0)

    # Branch distribution
    branch_stats = (
        db.session.query(
            StudentProfile.branch,
            func.count(StudentProfile.id)
        )
        .join(User, User.id == StudentProfile.user_id)
        .filter(
            User.role == "student",
            StudentProfile.branch.isnot(None)
        )
        .group_by(StudentProfile.branch)
        .order_by(StudentProfile.branch)
        .all()
    )

    # CGPA distribution
    cgpa_ranges = [
        ("Below 5.0", 0, 5),
        ("5.0 - 5.9", 5, 6),
        ("6.0 - 6.9", 6, 7),
        ("7.0 - 7.9", 7, 8),
        ("8.0 - 8.9", 8, 9),
        ("9.0 - 10.0", 9, 10.01)
    ]

    cgpa_stats = []

    for label, lower, upper in cgpa_ranges:
        count = (
            db.session.query(StudentProfile)
            .join(User, User.id == StudentProfile.user_id)
            .filter(
                User.role == "student",
                StudentProfile.cgpa >= lower,
                StudentProfile.cgpa < upper
            )
            .count()
        )

        cgpa_stats.append((label, count))

    return {
        "student_records": student_records,
        "total_students": total_students,
        "placed_count": placed_count,
        "not_placed_count": not_placed_count,
        "eligible_count": len(eligible_student_ids),
        "branch_stats": branch_stats,
        "cgpa_stats": cgpa_stats,
        "placed_student_ids": placed_student_ids,
        "eligible_student_ids": eligible_student_ids
    }


@app.route("/officer/student-analytics")
@role_required("officer")
def student_analytics():

    analytics = get_student_analytics_data()

    return render_template(
        "student_analytics.html",
        **analytics
    )


# --------------------------------------------------
# STUDENT ANALYTICS CSV EXPORT
# --------------------------------------------------

@app.route("/officer/student-analytics/export")
@role_required("officer")
def export_student_analytics():

    analytics = get_student_analytics_data()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Student Name",
        "Email",
        "Roll Number",
        "Branch",
        "CGPA",
        "Graduation Year",
        "Placement Status",
        "Placement Eligible"
    ])

    for user, profile in analytics["student_records"]:

        placed = user.id in analytics["placed_student_ids"]
        eligible = user.id in analytics["eligible_student_ids"]

        writer.writerow([
            user.full_name,
            user.email,
            profile.roll_number if profile else "",
            profile.branch if profile else "",
            profile.cgpa if profile and profile.cgpa is not None else "",
            profile.graduation_year if profile else "",
            "Placed" if placed else "Not Placed",
            "Yes" if eligible else "No"
        ])

    response = make_response(output.getvalue())

    response.headers["Content-Disposition"] = (
        "attachment; filename=student_performance_report.csv"
    )

    response.headers["Content-Type"] = "text/csv; charset=utf-8"

    return response

# --------------------------------------------------
# 15A. ADVANCED PLACEMENT REPORTS
# --------------------------------------------------

def get_advanced_report_data():

    total_students = User.query.filter_by(role="student").count()

    # Get all placed students only once, even if a student
    # receives offers from multiple companies.
    placed_student_ids = {
        row[0]
        for row in (
            db.session.query(Application.student_id)
            .filter(Application.status == "offered")
            .distinct()
            .all()
        )
    }

    placed_students = len(placed_student_ids)
    not_placed_students = max(total_students - placed_students, 0)

    placement_percentage = (
        round((placed_students / total_students) * 100, 2)
        if total_students else 0
    )

    profiles = (
        db.session.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.id)
        .filter(User.role == "student")
        .all()
    )

    # Branch-wise placement report
    branch_data = {}

    # CGPA-wise placement report
    cgpa_ranges = [
        ("Below 5.0", 0, 5),
        ("5.0 - 5.9", 5, 6),
        ("6.0 - 6.9", 6, 7),
        ("7.0 - 7.9", 7, 8),
        ("8.0 - 8.9", 8, 9),
        ("9.0 - 10.0", 9, 10.01),
    ]

    cgpa_data = {
        label: {"total": 0, "placed": 0}
        for label, lower, upper in cgpa_ranges
    }

    # Graduation-year report
    graduation_data = {}

    for profile, user in profiles:

        branch = profile.branch or "Not Provided"

        if branch not in branch_data:
            branch_data[branch] = {"total": 0, "placed": 0}

        branch_data[branch]["total"] += 1

        if user.id in placed_student_ids:
            branch_data[branch]["placed"] += 1

        if profile.cgpa is not None:
            for label, lower, upper in cgpa_ranges:
                if lower <= profile.cgpa < upper:
                    cgpa_data[label]["total"] += 1

                    if user.id in placed_student_ids:
                        cgpa_data[label]["placed"] += 1

                    break

        year = (
            str(profile.graduation_year)
            if profile.graduation_year
            else "Not Provided"
        )

        if year not in graduation_data:
            graduation_data[year] = {"total": 0, "placed": 0}

        graduation_data[year]["total"] += 1

        if user.id in placed_student_ids:
            graduation_data[year]["placed"] += 1

    branch_stats = []

    for branch, counts in sorted(branch_data.items()):
        percentage = (
            round(counts["placed"] / counts["total"] * 100, 2)
            if counts["total"] else 0
        )

        branch_stats.append({
            "branch": branch,
            "total": counts["total"],
            "placed": counts["placed"],
            "not_placed": counts["total"] - counts["placed"],
            "percentage": percentage,
        })

    cgpa_stats = []

    for label, counts in cgpa_data.items():
        percentage = (
            round(counts["placed"] / counts["total"] * 100, 2)
            if counts["total"] else 0
        )

        cgpa_stats.append({
            "range": label,
            "total": counts["total"],
            "placed": counts["placed"],
            "percentage": percentage,
        })

    graduation_stats = []

    for year, counts in sorted(graduation_data.items()):
        percentage = (
            round(counts["placed"] / counts["total"] * 100, 2)
            if counts["total"] else 0
        )

        graduation_stats.append({
            "year": year,
            "total": counts["total"],
            "placed": counts["placed"],
            "percentage": percentage,
        })

    # Company-wise placement report
    company_stats = []

    companies = Company.query.order_by(Company.company_name).all()

    for company in companies:

        company_jobs = Job.query.filter_by(
            company_id=company.id
        ).all()

        job_ids = [job.id for job in company_jobs]

        total_applications = 0
        company_placed_students = 0

        if job_ids:
            total_applications = Application.query.filter(
                Application.job_id.in_(job_ids)
            ).count()

            company_placed_students = (
                db.session.query(Application.student_id)
                .filter(
                    Application.job_id.in_(job_ids),
                    Application.status == "offered"
                )
                .distinct()
                .count()
            )

        company_stats.append({
            "company": company.company_name,
            "jobs": len(company_jobs),
            "applications": total_applications,
            "placed": company_placed_students,
        })

    return {
        "total_students": total_students,
        "placed_students": placed_students,
        "not_placed_students": not_placed_students,
        "placement_percentage": placement_percentage,
        "branch_stats": branch_stats,
        "cgpa_stats": cgpa_stats,
        "graduation_stats": graduation_stats,
        "company_stats": company_stats,
    }


@app.route("/officer/advanced-reports")
@role_required("officer")
def advanced_placement_reports():

    report = get_advanced_report_data()

    return render_template(
        "advanced_reports.html",
        **report
    )


@app.route("/officer/advanced-reports/export")
@role_required("officer")
def export_advanced_reports():

    report = get_advanced_report_data()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["ADVANCED PLACEMENT REPORT"])
    writer.writerow([])

    writer.writerow(["Overall Summary"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Students", report["total_students"]])
    writer.writerow(["Placed Students", report["placed_students"]])
    writer.writerow(["Not Placed Students", report["not_placed_students"]])
    writer.writerow([
        "Placement Percentage",
        f'{report["placement_percentage"]}%'
    ])

    writer.writerow([])
    writer.writerow(["Branch-wise Placement"])
    writer.writerow([
        "Branch", "Total Students", "Placed",
        "Not Placed", "Placement Percentage"
    ])

    for row in report["branch_stats"]:
        writer.writerow([
            row["branch"],
            row["total"],
            row["placed"],
            row["not_placed"],
            f'{row["percentage"]}%'
        ])

    writer.writerow([])
    writer.writerow(["CGPA-wise Placement"])
    writer.writerow([
        "CGPA Range", "Total Students",
        "Placed", "Placement Percentage"
    ])

    for row in report["cgpa_stats"]:
        writer.writerow([
            row["range"],
            row["total"],
            row["placed"],
            f'{row["percentage"]}%'
        ])

    writer.writerow([])
    writer.writerow(["Graduation Year Statistics"])
    writer.writerow([
        "Graduation Year", "Total Students",
        "Placed", "Placement Percentage"
    ])

    for row in report["graduation_stats"]:
        writer.writerow([
            row["year"],
            row["total"],
            row["placed"],
            f'{row["percentage"]}%'
        ])

    writer.writerow([])
    writer.writerow(["Company-wise Placement"])
    writer.writerow([
        "Company", "Total Jobs",
        "Total Applications", "Distinct Students Offered"
    ])

    for row in report["company_stats"]:
        writer.writerow([
            row["company"],
            row["jobs"],
            row["applications"],
            row["placed"]
        ])

    response = app.response_class(
        output.getvalue(),
        mimetype="text/csv"
    )

    response.headers["Content-Disposition"] = (
        "attachment; filename=advanced_placement_report.csv"
    )

    return response

# --------------------------------------------------
# 16. FAST AI RESUME GENERATOR
# --------------------------------------------------

def add_resume_section_lines(resume_text):
    """
    Adds consistent separator lines between resume sections.
    """

    headings = {
        "CAREER OBJECTIVE",
        "PROFESSIONAL SUMMARY",
        "SUMMARY",
        "ABOUT ME",
        "EDUCATION",
        "TECHNICAL SKILLS",
        "SKILLS",
        "PROJECTS",
        "INTERNSHIPS",
        "EXPERIENCE",
        "WORK EXPERIENCE",
        "ACHIEVEMENTS",
        "ACHIEVEMENTS AND CERTIFICATIONS",
        "CERTIFICATIONS",
        "KEY STRENGTHS",
        "STRENGTHS",
        "PERSONAL DETAILS",
        "DECLARATION"
    }

    lines = resume_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    result = []

    for line in lines:

        heading = line.strip().rstrip(":").upper()

        if heading in headings and result:

            while result and not result[-1].strip():
                result.pop()

            if result and result[-1].strip() != "-" * 50:
                result.append("")
                result.append("-" * 50)
                result.append("")

        result.append(line)

    return "\n".join(result).strip()


def generate_fallback_resume(
    student,
    profile,
    education,
    target_role,
    projects,
    achievements
):
    """
    Generates a local resume when Gemini is unavailable.
    Does not invent qualifications or achievements.
    """

    branch = (
        profile.branch
        if profile and profile.branch
        else "Not provided"
    )

    cgpa = (
        profile.cgpa
        if profile and profile.cgpa is not None
        else "Not provided"
    )

    skills = (
        profile.skills
        if profile and profile.skills
        else "Not provided"
    )

    graduation_year = (
        profile.graduation_year
        if profile and profile.graduation_year
        else "Not provided"
    )

    resume = f"""
{student.full_name.upper()}
Email: {student.email}
Target Role: {target_role}

CAREER OBJECTIVE

Motivated fresher seeking an entry-level position as a {target_role}. Eager to apply technical knowledge, programming skills and problem-solving abilities to contribute to software development projects.

EDUCATION

{education}

Branch: {branch}
CGPA: {cgpa}
Graduation Year: {graduation_year}

TECHNICAL SKILLS

{skills}

PROJECTS

{projects if projects else "No projects provided."}

ACHIEVEMENTS AND CERTIFICATIONS

{achievements if achievements else "Not provided."}

KEY STRENGTHS

- Problem-solving and analytical thinking
- Teamwork and collaboration
- Communication skills
- Adaptability and willingness to learn
- Time management
"""

    return add_resume_section_lines(resume)


@app.route("/student/ai-resume", methods=["GET", "POST"])
@role_required("student")
def ai_resume():

    start_time = time.time()

    student = db.session.get(
        User,
        session.get("user_id")
    )

    if not student:
        session.clear()
        flash("Please log in again.", "warning")
        return redirect(url_for("login"))

    profile = StudentProfile.query.filter_by(
        user_id=student.id
    ).first()

    generated_resume = None
    resume_warning = None

    form_data = {
        "education": "",
        "target_role": "",
        "projects": "",
        "achievements": ""
    }

    if request.method == "POST":

        # ------------------------------------------
        # 1. GET STUDENT INPUTS
        # ------------------------------------------

        form_data = {
            "education": request.form.get("education", "").strip(),
            "target_role": request.form.get("target_role", "").strip(),
            "projects": request.form.get("projects", "").strip(),
            "achievements": request.form.get("achievements", "").strip()
        }

        education = form_data["education"]
        target_role = form_data["target_role"]
        projects = form_data["projects"]
        achievements = form_data["achievements"]

        if not education or not target_role:

            flash(
                "Please enter education details and target job role.",
                "danger"
            )

            return render_template(
                "ai_resume.html",
                student=student,
                profile=profile,
                generated_resume=None,
                form_data=form_data,
                resume_warning=None
            )

        # ------------------------------------------
        # 2. GET PROFILE DETAILS
        # ------------------------------------------

        branch = (
            profile.branch
            if profile and profile.branch
            else "Not provided"
        )

        cgpa = (
            profile.cgpa
            if profile and profile.cgpa is not None
            else "Not provided"
        )

        skills = (
            profile.skills
            if profile and profile.skills
            else "Not provided"
        )

        graduation_year = (
            profile.graduation_year
            if profile and profile.graduation_year
            else "Not provided"
        )

        # ------------------------------------------
        # 3. GEMINI PROMPT
        # ------------------------------------------

        prompt = f"""
You are an expert professional resume writer.

Create a complete, professional, ATS-friendly fresher resume.

STUDENT DETAILS:

Name: {student.full_name}
Email: {student.email}
Branch: {branch}
CGPA: {cgpa}
Graduation Year: {graduation_year}
Technical Skills: {skills}

EDUCATION:
{education}

PROJECTS:
{projects if projects else "Not provided"}

ACHIEVEMENTS AND CERTIFICATIONS:
{achievements if achievements else "Not provided"}

TARGET JOB ROLE:
{target_role}


MANDATORY RESUME SECTION ORDER:

1. CAREER OBJECTIVE
2. EDUCATION
3. TECHNICAL SKILLS
4. PROJECTS
5. ACHIEVEMENTS AND CERTIFICATIONS
6. KEY STRENGTHS


IMPORTANT FORMATTING RULES:

1. Every section must have its own separate heading.
2. KEY STRENGTHS must be a separate heading.
3. KEY STRENGTHS must appear immediately below
   ACHIEVEMENTS AND CERTIFICATIONS.
4. Never write "NO KEY STRENGTHS" as a heading.
5. Do not put key strengths inside the achievements section.
6. Write normal paragraphs continuously.
7. Do not manually break sentences into short lines.
8. Do not add separator lines made of hyphens.
9. Use bullet points for projects and achievements where appropriate.
10. Use professional language and correct grammar.
11. Optimize keywords for the target job role.
12. Keep the resume concise and suitable for a fresher.
13. Do not invent experience, certifications, CGPA,
    achievements, phone numbers or addresses.
14. Do not use placeholder information such as Lorem Ipsum.
15. Return only the complete resume text.
"""

        # ------------------------------------------
        # 4. GEMINI GENERATION - ONE REQUEST
        # ------------------------------------------

        if gemini_client:

            try:

                app.logger.info(
                    "Starting Gemini resume generation"
                )

                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=3000
                    )
                )

                generated_resume = (
                    response.text.strip()
                    if response.text
                    else None
                )

                if generated_resume:

                    generated_resume = add_resume_section_lines(
                        generated_resume
                    )

                    app.logger.info(
                        "Gemini resume generated in %.2f seconds",
                        time.time() - start_time
                    )

            except Exception:

                app.logger.exception(
                    "Gemini resume generation failed"
                )

                generated_resume = None

        # ------------------------------------------
        # 5. LOCAL FALLBACK
        # ------------------------------------------

        if not generated_resume:

            generated_resume = generate_fallback_resume(
                student=student,
                profile=profile,
                education=education,
                target_role=target_role,
                projects=projects,
                achievements=achievements
            )

            resume_warning = (
                "Gemini was unavailable or timed out. "
                "Your resume was generated using your submitted details."
            )

            app.logger.info(
                "Fallback resume generated in %.2f seconds",
                time.time() - start_time
            )

    # ------------------------------------------
    # 6. DISPLAY GENERATED RESUME
    # ------------------------------------------

    return render_template(
        "ai_resume.html",
        student=student,
        profile=profile,
        generated_resume=generated_resume,
        form_data=form_data,
        resume_warning=resume_warning
    )


# --------------------------------------------------
# 17. START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        debug=True,
        use_reloader=False
    )
