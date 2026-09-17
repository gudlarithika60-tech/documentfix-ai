import os
import re
import json
from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from google import genai
import fitz
from PyPDF2 import PdfReader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Always load the .env that belongs to this project, even if Flask is started
# from a different working directory.
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "studentfix.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "studentfix-dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)


class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(80), nullable=False)
    input_text = db.Column(db.Text, default="")
    result = db.Column(db.Text, default="")


with app.app_context():
    db.create_all()


def get_gemini_client():
    # Re-read the project's .env every time so a newly-added key is picked up
    # after a normal Flask restart, regardless of the terminal working folder.
    load_dotenv(dotenv_path=ENV_FILE, override=True)
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip("\'").strip("\"")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def ask_ai(prompt):
    client = get_gemini_client()
    if not client:
        return (
            "ERROR: GEMINI_API_KEY is missing or invalid.\n\n"
            "Put your real Gemini API key in StudentFix_AI/.env as "
            "GEMINI_API_KEY=YOUR_REAL_KEY, save the file, stop Flask with Ctrl+C, "
            "then run python app.py again."
        )
    try:
        response = client.models.generate_content(
            model=(os.getenv("GEMINI_MODEL") or "gemini-3.6-flash").strip(),
            contents=prompt
        )
        return response.text or "No response received from AI."
    except Exception as e:
        return f"AI ERROR: {str(e)}"


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required_json():
    if current_user() is None and not session.get("guest"):
        return jsonify({
            "success": False,
            "auth_required": True,
            "message": "Please login or continue as guest."
        }), 401
    return None


def save_record(module, input_text, result):

    try:
        record = Record(
            module=module,
            input_text=(input_text or "")[:10000],
            result=(result or "")[:30000]
        )
        db.session.add(record)
        db.session.commit()
    except Exception:
        db.session.rollback()


def safe_filename(filename):
    """Keep uploads inside the project uploads folder."""
    return os.path.basename(filename)


def read_uploaded_file(file):
    """Read PDF/DOCX/TXT content for AI modules."""
    if not file or not file.filename:
        return ""

    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            pdf = fitz.open(stream=file.read(), filetype="pdf")
            text = "\n".join(page.get_text() for page in pdf)
            pdf.close()
            return text

        if filename.endswith(".docx"):
            from docx import Document
            document = Document(file)
            return "\n".join(p.text for p in document.paragraphs)

        return file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[Could not read {file.filename}: {e}]"


# =========================================================
# AUTHENTICATION
# =========================================================

@app.route("/auth/status", methods=["GET"])
def auth_status():
    user = current_user()
    if user:
        return jsonify({
            "authenticated": True,
            "guest": False,
            "name": user.name,
            "email": user.email
        })
    if session.get("guest"):
        return jsonify({
            "authenticated": False,
            "guest": True,
            "name": "Guest"
        })
    return jsonify({"authenticated": False, "guest": False})


@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"success": False, "message": "Name, email and password are required."}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"success": False, "message": "Please enter a valid email address."}), 400
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "An account with this email already exists."}), 409

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password)
    )
    db.session.add(user)
    db.session.commit()

    session.clear()
    session["user_id"] = user.id
    return jsonify({
        "success": True,
        "name": user.name,
        "email": user.email,
        "message": "Account created successfully."
    })


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"success": False, "message": "Incorrect email or password."}), 401

    session.clear()
    session["user_id"] = user.id
    return jsonify({
        "success": True,
        "name": user.name,
        "email": user.email,
        "message": "Login successful."
    })


@app.route("/auth/guest", methods=["POST"])
def guest_login():
    session.clear()
    session["guest"] = True
    return jsonify({"success": True, "guest": True, "name": "Guest"})


@app.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


# =========================================================
# DOCUMENTFIX - imported/adapted from df1
# =========================================================

def extract_pdf_text(file_path):
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception:
        return ""


def detect_requirements(text):
    """Extract requirements from the ACTUAL uploaded application using Gemini.
    No hard-coded/default document list is used. If the document does not state a
    requirement, the AI is instructed to return an empty list instead of guessing.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return {"documents": [], "deadline": None, "eligibility": [], "conditions": [], "raw_text": ""}

    # Keep the prompt bounded so very large PDFs do not overwhelm the model.
    source = clean_text[:18000]
    prompt = f"""
You are StudentFix AI's Requirement Intelligence engine.

Read ONLY the application/requirements document below. Extract information that is
explicitly stated in that document. NEVER invent, assume, or use a generic list of
student documents.

Return ONLY valid JSON with exactly these keys:
{{
  "documents": ["document 1", "document 2"],
  "eligibility": ["eligibility rule 1", "eligibility rule 2"],
  "deadline": "exact deadline text or null",
  "conditions": ["important condition 1", "condition 2"]
}}

Rules:
- "documents" must contain only documents/proofs explicitly required for submission.
- Do not add Aadhaar, income certificate, bonafide, passport photo, etc. unless the
  uploaded document explicitly requires them.
- "eligibility" should contain explicit eligibility rules such as age, marks,
  course/year, income, domicile, category, citizenship, etc.
- "deadline" must be copied as a short exact phrase/date from the document when present.
- "conditions" should contain other explicit application conditions/instructions.
- If something is not stated, return an empty list or null.

UPLOADED DOCUMENT:
---
{source}
---
"""

    raw = ask_ai(prompt)
    if raw.startswith("ERROR:") or raw.startswith("AI ERROR:"):
        raise RuntimeError(raw)

    # Gemini may wrap JSON in markdown fences; strip those safely.
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Recover the first JSON object if the model added a short explanation.
        match = re.search(r"\{.*\}", candidate, flags=re.S)
        if not match:
            raise RuntimeError("AI returned an invalid requirements response. Please try again.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise RuntimeError("AI returned an invalid requirements response. Please try again.")

    documents = data.get("documents") or []
    eligibility = data.get("eligibility") or []
    conditions = data.get("conditions") or []
    deadline = data.get("deadline")

    # Normalize to clean strings and remove duplicates while preserving order.
    def clean_list(values):
        out = []
        for value in values if isinstance(values, list) else []:
            value = str(value).strip()
            if value and value not in out:
                out.append(value)
        return out

    return {
        "documents": clean_list(documents),
        "deadline": str(deadline).strip() if deadline not in (None, "", "null") else None,
        "eligibility": clean_list(eligibility),
        "conditions": clean_list(conditions),
        "raw_text": clean_text[:5000]
    }


@app.route("/analyze-requirements", methods=["POST"])
def analyze_requirements():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded."})

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "message": "Please select a PDF."})

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "message": "Only PDF files are supported."})

    filename = safe_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        file.save(file_path)
        text = extract_pdf_text(file_path)

        if not text:
            return jsonify({
                "success": False,
                "message": "Could not extract text from this PDF. Try a text-based PDF."
            })

        result = detect_requirements(text)
        save_record(
            "DocumentFix - Requirements",
            text,
            json_safe_result(result)
        )
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e) or "Could not process PDF."})


@app.route("/check-documents", methods=["POST"])
def check_documents():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    files = request.files.getlist("documents")
    required_documents = request.form.get("required_documents", "")
    application_name = request.form.get("application_name", "")
    application_dob = request.form.get("application_dob", "")

    if not files:
        return jsonify({
            "success": False,
            "message": "Please upload at least one document."
        })

    required_list = [
        item.strip()
        for item in required_documents.split(",")
        if item.strip()
    ]

    uploaded_names = []

    for file in files:
        if not file.filename:
            continue

        filename = safe_filename(file.filename)
        uploaded_names.append(filename.lower())

        try:
            file.save(os.path.join(UPLOAD_FOLDER, filename))
        except Exception:
            pass

    if not uploaded_names:
        return jsonify({
            "success": False,
            "message": "No valid documents were selected."
        })

    missing_documents = []

    for required in required_list:
        found = False
        required_words = required.lower().split()

        for uploaded in uploaded_names:
            matches = sum(
                1 for word in required_words
                if len(word) > 3 and word in uploaded
            )
            if matches >= 1:
                found = True
                break

        if not found:
            missing_documents.append(required)

    format_issues = []
    allowed = (".pdf", ".jpg", ".jpeg", ".png")

    for uploaded in uploaded_names:
        if not uploaded.endswith(allowed):
            format_issues.append(
                f"{uploaded} has an unsupported format."
            )

    mismatches = []

    if application_name:
        important_words = [
            word.lower()
            for word in application_name.split()
            if len(word) > 3
        ]

        for filename in uploaded_names:
            filename_clean = re.sub(r"[^a-zA-Z]", "", filename).lower()

            if important_words and not any(
                word in filename_clean for word in important_words
            ):
                mismatches.append(
                    f"Possible name mismatch detected in {filename}"
                )

    if application_dob:
        dob_numbers = re.sub(r"[^0-9]", "", application_dob)

        for filename in uploaded_names:
            filename_numbers = re.sub(r"[^0-9]", "", filename)

            if dob_numbers and len(dob_numbers) >= 4:
                if dob_numbers[:4] not in filename_numbers:
                    mismatches.append(
                        f"Please verify DOB in {filename}"
                    )

    total_requirements = len(required_list)

    if total_requirements == 0:
        document_score = 100
    else:
        completed = total_requirements - len(missing_documents)
        document_score = int((completed / total_requirements) * 100)

    mismatch_penalty = min(len(mismatches) * 10, 30)
    format_penalty = min(len(format_issues) * 5, 20)
    readiness = max(0, document_score - mismatch_penalty - format_penalty)

    high_priority = [
        f"Missing mandatory document: {item}"
        for item in missing_documents
    ]
    medium_priority = list(mismatches)
    low_priority = list(format_issues)

    fixes = [f"Upload {item}" for item in missing_documents]

    if mismatches:
        fixes.append("Verify personal information across your documents")

    if format_issues:
        fixes.append("Convert unsupported files to PDF, JPG or PNG")

    if not fixes:
        fixes.append("Perform a final manual review before submission.")

    if readiness >= 90:
        status = "Ready to Submit"
    elif readiness >= 70:
        status = "Needs Attention"
    else:
        status = "Incomplete"

    result = {
        "readiness": readiness,
        "status": status,
        "missing_documents": missing_documents,
        "mismatches": mismatches,
        "format_issues": format_issues,
        "high_priority": high_priority,
        "medium_priority": medium_priority,
        "low_priority": low_priority,
        "fixes": fixes,
        "uploaded_count": len(uploaded_names),
        "required_count": total_requirements
    }

    save_record(
        "DocumentFix - Application Check",
        ", ".join(uploaded_names),
        json_safe_result(result)
    )

    return jsonify({"success": True, "result": result})


def json_safe_result(data):
    import json
    return json.dumps(data, indent=2)


# =========================================================
# RESUMEFIX - kept from StudentFix
# =========================================================

@app.route("/resumefix", methods=["POST"])
def resumefix():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    job = request.form.get("job", "")
    resume = request.files.get("resume")
    text = read_uploaded_file(resume)

    if not text:
        return jsonify({"result": "Please upload a resume."})

    prompt = f"""
You are ResumeFix AI.

RESUME:
{text}

JOB DESCRIPTION:
{job}

Analyze the resume for:
- ATS friendliness
- Job match
- Skills
- Projects
- Keywords
- Weak points
- Grammar/clarity
- Missing skills or evidence

Do not invent experience.

Return:
ATS SCORE: XX/100
JOB MATCH: XX%

STRENGTHS:
- ...

PROBLEMS:
- ...

MISSING/RECOMMENDED SKILLS:
- ...

IMPROVEMENTS:
- ...

BETTER SUMMARY:
...
"""
    result = ask_ai(prompt)
    save_record("ResumeFix", text + "\nJOB:\n" + job, result)
    return jsonify({"result": result})


# =========================================================
# CAREERMATE - kept from StudentFix
# =========================================================

@app.route("/careermate", methods=["POST"])
def careermate():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    goal = request.form.get("goal", "")
    skills = request.form.get("skills", "")

    if not goal:
        return jsonify({"result": "Please enter your career goal."})

    prompt = f"""
You are CareerMate AI for college students.

CAREER GOAL:
{goal}

CURRENT SKILLS:
{skills}

Create a realistic beginner-friendly roadmap.

Return:
CURRENT LEVEL:
...

SKILL GAPS:
- ...

3-MONTH ROADMAP:

MONTH 1:
- ...

MONTH 2:
- ...

MONTH 3:
- ...

PROJECTS TO BUILD:
- ...

INTERVIEW TOPICS:
- ...

NEXT 5 ACTIONS:
1. ...
2. ...
3. ...
4. ...
5. ...
"""
    result = ask_ai(prompt)
    save_record("CareerMate", goal + "\n" + skills, result)
    return jsonify({"result": result})


# =========================================================
# INTERVIEWMATE - kept from StudentFix
# =========================================================

@app.route("/interview/question", methods=["POST"])
def interview_question():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    role = request.form.get("role", "Software Developer")

    prompt = f"""
You are InterviewMate.
Generate ONE interview question for a fresher applying for:
{role}

Ask only one question. Do not give the answer.
"""
    result = ask_ai(prompt)
    return jsonify({"question": result})


@app.route("/interview/evaluate", methods=["POST"])
def evaluate_interview():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    question = request.form.get("question", "")
    answer = request.form.get("answer", "")

    prompt = f"""
You are InterviewMate, an AI interviewer.

QUESTION:
{question}

CANDIDATE ANSWER:
{answer}

Evaluate fairly. If the question is technical, assess technical correctness.
For behavioral questions, assess relevance and communication.

Return:
OVERALL SCORE: X/10
TECHNICAL/CONTENT: X/10
COMMUNICATION: X/10
CLARITY: X/10

WHAT WAS GOOD:
- ...

WHAT TO IMPROVE:
- ...

BETTER ANSWER:
...
"""
    result = ask_ai(prompt)
    save_record("InterviewMate", answer, result)
    return jsonify({"result": result})


# =========================================================
# HISTORY
# =========================================================

@app.route("/history", methods=["GET"])
def history():
    auth_error = login_required_json()
    if auth_error:
        return auth_error

    records = Record.query.order_by(Record.id.desc()).limit(30).all()
    return jsonify([
        {
            "id": r.id,
            "module": r.module,
            "result": r.result,
        }
        for r in records
    ])


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "gemini_configured": bool(get_gemini_client())
    })


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
