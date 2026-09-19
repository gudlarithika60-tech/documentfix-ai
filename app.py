import os
import re
import json
import time

from flask import Flask, request, jsonify, render_template, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

try:
    from google import genai
except Exception:
    genai = None

try:
    import fitz
except Exception:
    fitz = None


# =====================================================
# APP SETUP
# =====================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "studentfix-ai-local-secret-change-this"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(BASE_DIR, "studentfix.db")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =====================================================
# DATABASE MODEL
# =====================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)


class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)
    module = db.Column(db.String(100), nullable=False)
    result = db.Column(db.Text, nullable=False)


with app.app_context():
    db.create_all()


# =====================================================
# GEMINI
# =====================================================

def get_gemini_client():
    """
    Creates the Gemini client only when a valid-looking
    API key exists.

    The real key stays on the server in .env.
    """

    if genai is None:
        return None

    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        return None

    if len(api_key) < 20:
        return None

    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def ask_ai(prompt):
    """
    Returns AI text when Gemini is available.

    Automatically retries temporary Gemini 429/503 errors
    using exponential backoff: 2s -> 4s -> 8s.

    Returns None when Gemini is unavailable so the
    application can safely use its local fallback.
    """

    client = get_gemini_client()

    if client is None:
        return None

    model_name = os.getenv(
        "GEMINI_MODEL",
        "gemini-3.6-flash"
    )

    # Retry delays: 2 seconds, 4 seconds, 8 seconds
    retry_delays = [2, 4, 8]

    for attempt, delay in enumerate(retry_delays):

        try:

            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            text = getattr(response, "text", None)

            if text and text.strip():
                return text.strip()

            return None

        except Exception as error:

            error_text = str(error).lower()

            temporary_error = any(
                word in error_text
                for word in [
                    "429",
                    "quota",
                    "resource_exhausted",
                    "rate limit",
                    "503",
                    "unavailable",
                    "high demand",
                    "temporarily",
                    "overloaded",
                    "service unavailable"
                ]
            )

            # Retry only temporary Gemini errors.
            if temporary_error and attempt < len(retry_delays) - 1:

                time.sleep(delay)
                continue

            # Never send Gemini's raw error to the browser.
            return None

    return None

# =====================================================
# GENERAL HELPERS
# =====================================================

def clean_lines(text):
    if not text:
        return []

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"^[\s•●○▪▫\-*]+\s*",
            "",
            line
        ).strip()

        line = re.sub(
            r"^\d+[\.\)]\s*",
            "",
            line
        ).strip()

        if line:
            lines.append(line)

    return lines


def safe_json_from_ai(text):
    if not text:
        return None

    text = text.strip()

    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```\s*",
        "",
        text
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL
    )

    if match:

        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    return None


def save_record(module, result):

    user_id = session.get("user_id")

    record = Record(
        user_id=user_id,
        module=module,
        result=str(result)
    )

    db.session.add(record)
    db.session.commit()


def current_user_id():
    return session.get("user_id")


# =====================================================
# LOCAL FALLBACK - REQUIREMENTS
# =====================================================

def fallback_requirements(text):

    text_lower = (text or "").lower()

    documents = []

    possible_documents = [
        (
            "Aadhaar / ID Proof",
            [
                "aadhaar",
                "aadhar",
                "identity proof",
                "id proof"
            ]
        ),
        (
            "10th Marks Memo",
            [
                "10th marks",
                "10th mark",
                "ssc marks",
                "ssc memo",
                "tenth marks"
            ]
        ),
        (
            "Intermediate / 12th Marks Memo",
            [
                "intermediate",
                "12th marks",
                "12th mark",
                "hsc marks"
            ]
        ),
        (
            "Current Academic Marks Memo",
            [
                "current academic",
                "semester marks",
                "academic marks",
                "latest marks"
            ]
        ),
        (
            "Bonafide Certificate",
            [
                "bonafide",
                "bonafide certificate"
            ]
        ),
        (
            "Income Certificate",
            [
                "income certificate",
                "family income"
            ]
        ),
        (
            "Caste Certificate",
            [
                "caste certificate",
                "community certificate"
            ]
        ),
        (
            "Residence Certificate",
            [
                "residence certificate",
                "residential certificate"
            ]
        ),
        (
            "Domicile Certificate",
            [
                "domicile"
            ]
        ),
        (
            "Bank Account Details",
            [
                "bank account",
                "bank details",
                "bank passbook"
            ]
        ),
        (
            "Passport Size Photograph",
            [
                "passport size",
                "passport photograph",
                "passport photo"
            ]
        )
    ]

    for name, keywords in possible_documents:

        if any(keyword in text_lower for keyword in keywords):

            documents.append({
                "name": name,
                "required": "Yes",
                "accepted_format": "PDF / JPG / PNG",
                "special_condition": ""
            })

    if not documents:

        documents = [
            {
                "name": "Identity Proof",
                "required": "Yes",
                "accepted_format": "PDF / JPG / PNG",
                "special_condition": "Check the official application instructions."
            },
            {
                "name": "Educational Certificate / Marks Memo",
                "required": "Yes",
                "accepted_format": "PDF / JPG / PNG",
                "special_condition": "Use the latest applicable certificate."
            },
            {
                "name": "Passport Size Photograph",
                "required": "May be required",
                "accepted_format": "JPG / PNG",
                "special_condition": ""
            }
        ]

    eligibility = []

    eligibility_keywords = [
        "student",
        "education",
        "academic",
        "income",
        "residence",
        "age",
        "merit",
        "scholarship",
        "category"
    ]

    for keyword in eligibility_keywords:

        if keyword in text_lower:
            eligibility.append(
                keyword.capitalize()
            )

    if not eligibility:
        eligibility = [
            "Check applicant eligibility in the official notice.",
            "Verify academic and category conditions."
        ]

    conditions = []

    for line in clean_lines(text):

        lower = line.lower()

        if any(
            word in lower
            for word in [
                "must",
                "should",
                "required",
                "only",
                "valid",
                "original",
                "attested",
                "self attested"
            ]
        ):

            if len(line) <= 250:
                conditions.append(line)

        if len(conditions) >= 6:
            break

    if not conditions:

        conditions = [
            "Verify that uploaded documents are clear and readable.",
            "Submit documents in the format requested by the official application.",
            "Check all personal details before submission."
        ]

    deadline = None

    deadline_patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b"
    ]

    for pattern in deadline_patterns:

        match = re.search(
            pattern,
            text or "",
            flags=re.IGNORECASE
        )

        if match:
            deadline = match.group(0)
            break

    return {
        "documents": documents,
        "eligibility": eligibility,
        "conditions": conditions,
        "deadline": deadline
    }


# =====================================================
# DOCUMENT PDF EXTRACTION
# =====================================================

def extract_pdf_text(file_storage):

    if fitz is None:
        return ""

    try:

        file_bytes = file_storage.read()

        if not file_bytes:
            return ""

        document = fitz.open(
            stream=file_bytes,
            filetype="pdf"
        )

        pages = []

        for page in document:

            text = page.get_text()

            if text:
                pages.append(text)

        document.close()

        return "\n".join(pages)

    except Exception:

        return ""


# =====================================================
# REQUIREMENTS ANALYSIS
# =====================================================

def detect_requirements(text):

    fallback = fallback_requirements(text)

    prompt = f"""
You are StudentFix AI.

Analyze the following official application requirements document.

Return ONLY valid JSON in exactly this structure:

{{
  "documents": [
    {{
      "name": "Document name",
      "required": "Yes / No / May be required",
      "accepted_format": "PDF / JPG / PNG / etc.",
      "special_condition": "condition or empty string"
    }}
  ],
  "eligibility": [
    "eligibility point"
  ],
  "conditions": [
    "important condition"
  ],
  "deadline": "deadline or null"
}}

Do not invent requirements.
If something is not clearly available, use an empty list or null.

DOCUMENT TEXT:
{text[:30000]}
"""

    raw = ask_ai(prompt)

    parsed = safe_json_from_ai(raw)

    if not isinstance(parsed, dict):
        return fallback

    documents = parsed.get("documents")

    if not isinstance(documents, list):
        return fallback

    cleaned_documents = []

    for item in documents:

        if isinstance(item, str):

            cleaned_documents.append({
                "name": item,
                "required": "Yes",
                "accepted_format": "",
                "special_condition": ""
            })

        elif isinstance(item, dict):

            name = str(
                item.get("name", "")
            ).strip()

            if name:

                cleaned_documents.append({
                    "name": name,
                    "required": str(
                        item.get(
                            "required",
                            "Yes"
                        )
                    ),
                    "accepted_format": str(
                        item.get(
                            "accepted_format",
                            ""
                        )
                    ),
                    "special_condition": str(
                        item.get(
                            "special_condition",
                            ""
                        )
                    )
                })

    if not cleaned_documents:
        return fallback

    return {
        "documents": cleaned_documents,
        "eligibility": (
            parsed.get("eligibility")
            if isinstance(
                parsed.get("eligibility"),
                list
            )
            else fallback["eligibility"]
        ),
        "conditions": (
            parsed.get("conditions")
            if isinstance(
                parsed.get("conditions"),
                list
            )
            else fallback["conditions"]
        ),
        "deadline": parsed.get(
            "deadline",
            fallback["deadline"]
        )
    }


# =====================================================
# AUTH
# =====================================================

@app.post("/auth/status")
@app.get("/auth/status")
def auth_status():

    user_id = session.get("user_id")

    if user_id:

        user = db.session.get(
            User,
            user_id
        )

        if user:

            return jsonify({
                "authenticated": True,
                "guest": False,
                "name": user.name,
                "email": user.email
            })

        session.clear()

    return jsonify({
        "authenticated": False,
        "guest": bool(
            session.get("guest")
        ),
        "name": "",
        "email": ""
    })


@app.post("/auth/register")
def register():

    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get("name", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if not name or not email or not password:

        return jsonify({
            "success": False,
            "message": "Please fill all fields."
        }), 400

    if len(password) < 6:

        return jsonify({
            "success": False,
            "message": "Password must be at least 6 characters."
        }), 400

    existing = User.query.filter_by(
        email=email
    ).first()

    if existing:

        return jsonify({
            "success": False,
            "message": "An account with this email already exists."
        }), 409

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(
            password
        )
    )

    db.session.add(user)
    db.session.commit()

    session.clear()

    session["user_id"] = user.id

    return jsonify({
        "success": True,
        "name": user.name,
        "email": user.email,
        "guest": False
    })


@app.post("/auth/login")
def login():

    data = request.get_json(
        silent=True
    ) or {}

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if not email or not password:

        return jsonify({
            "success": False,
            "message": "Please enter your email and password."
        }), 400

    user = User.query.filter_by(
        email=email
    ).first()

    if not user:

        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401

    if not check_password_hash(
        user.password_hash,
        password
    ):

        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401

    session.clear()

    session["user_id"] = user.id

    return jsonify({
        "success": True,
        "name": user.name,
        "email": user.email,
        "guest": False
    })


@app.post("/auth/guest")
def guest():

    session.clear()

    session["guest"] = True

    return jsonify({
        "success": True,
        "guest": True,
        "name": "Guest",
        "email": ""
    })


@app.post("/auth/logout")
def logout():

    session.clear()

    return jsonify({
        "success": True
    })


# =====================================================
# DOCUMENTFIX - ANALYZE REQUIREMENTS
# =====================================================

@app.post("/analyze-requirements")
def analyze_requirements():

    file = request.files.get("file")

    if not file:

        return jsonify({
            "success": False,
            "message": "Please upload the requirements PDF."
        }), 400

    if not file.filename.lower().endswith(".pdf"):

        return jsonify({
            "success": False,
            "message": "Please upload a PDF file."
        }), 400

    text = extract_pdf_text(file)

    if not text.strip():

        return jsonify({
            "success": True,
            "result": fallback_requirements("")
        })

    result = detect_requirements(text)

    return jsonify({
        "success": True,
        "result": result
    })


# =====================================================
# DOCUMENT NAME MATCHING
# =====================================================

def normalize_name(value):

    value = str(value or "").lower()

    replacements = {
        "aadhaar": "id",
        "aadhar": "id",
        "identity": "id",
        "proof": "",
        "certificate": "",
        "cert": "",
        "marks": "mark",
        "memo": "",
        "document": "",
        "photo": "photograph"
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value
    )

    return set(
        word
        for word in value.split()
        if len(word) > 2
    )


def document_matches(
    required_name,
    uploaded_names
):

    required_words = normalize_name(
        required_name
    )

    if not required_words:
        return False

    for filename in uploaded_names:

        filename_words = normalize_name(
            filename
        )

        if not filename_words:
            continue

        common = (
            required_words &
            filename_words
        )

        if len(common) >= 2:
            return True

        for word in required_words:

            if len(word) >= 4:

                if any(
                    word in other
                    or other in word
                    for other in filename_words
                ):
                    return True

    return False


# =====================================================
# DOCUMENTFIX - CHECK DOCUMENTS
# =====================================================

@app.post("/check-documents")
def check_documents():

    uploaded = request.files.getlist(
        "documents"
    )

    if not uploaded:

        return jsonify({
            "success": False,
            "message": "Please upload your documents first."
        }), 400

    required_raw = request.form.get(
        "required_documents",
        "[]"
    )

    try:

        required_data = json.loads(
            required_raw
        )

    except Exception:

        required_data = []

    required_documents = []

    if isinstance(required_data, list):

        for item in required_data:

            if isinstance(item, str):

                name = item.strip()

            elif isinstance(item, dict):

                name = str(
                    item.get("name", "")
                ).strip()

            else:

                name = ""

            if name:
                required_documents.append(name)

    uploaded_names = [
        file.filename or ""
        for file in uploaded
    ]

    missing = []

    matched = []

    for required in required_documents:

        if document_matches(
            required,
            uploaded_names
        ):

            matched.append(required)

        else:

            missing.append(required)

    uploaded_count = len(uploaded)

    total_required = len(
        required_documents
    )

    if total_required == 0:

        readiness = 70

    else:

        readiness = round(
            (
                len(matched) /
                total_required
            ) * 100
        )

    mismatches = []

    if uploaded_count > total_required and total_required > 0:

        mismatches.append(
            "Some uploaded files may not correspond to the listed requirements."
        )

    high_priority = []

    if missing:

        for item in missing[:10]:

            high_priority.append(
                f"Missing or not clearly matched: {item}"
            )

    medium_priority = []

    if mismatches:

        medium_priority.extend(
            mismatches
        )

    low_priority = []

    for filename in uploaded_names:

        extension = os.path.splitext(
            filename
        )[1].lower()

        if extension not in [
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png"
        ]:

            low_priority.append(
                f"Check file format: {filename}"
            )

    fixes = []

    for item in missing[:10]:

        fixes.append(
            f"Upload or verify: {item}"
        )

    if not fixes:

        fixes.append(
            "Review all uploaded documents manually before submission."
        )

    if readiness >= 90:

        status = "Looks Ready"

    elif readiness >= 70:

        status = "Needs a Few Checks"

    else:

        status = "Incomplete"

    result = {
        "readiness": readiness,
        "status": status,
        "uploaded_count": uploaded_count,
        "missing_documents": missing,
        "mismatches": mismatches,
        "high_priority": high_priority,
        "medium_priority": medium_priority,
        "low_priority": low_priority,
        "fixes": fixes
    }

    save_record(
        "DocumentFix",
        json.dumps(
            result,
            indent=2
        )
    )

    return jsonify({
        "success": True,
        "result": result
    })


# =====================================================
# RESUMEFIX FALLBACK
# =====================================================

def fallback_resume(job):

    job = job.strip()

    if not job:

        return """Resume review completed.

Please add:
1. A clear professional summary.
2. Your technical skills.
3. Education details.
4. Projects with your role and technologies.
5. Internship or experience details.
6. Relevant achievements.

Tip: Keep your resume clear, concise and easy to scan."""

    return f"""Resume review completed for the target role:

{job}

Recommended improvements:

1. Add a clear summary matching the target role.
2. Highlight skills that appear in the job description.
3. Add 2–3 relevant academic or personal projects.
4. Describe projects using action + technology + result.
5. Keep education details accurate and concise.
6. Check spelling, grammar and formatting.
7. Put the most relevant skills near the top.
8. Avoid unnecessary personal information.

This is a general review. Compare the final resume with the actual job description before submitting."""


# =====================================================
# RESUMEFIX
# =====================================================

@app.post("/resumefix")
def resume_fix():

    resume = request.files.get(
        "resume"
    )

    job = request.form.get(
        "job",
        ""
    ).strip()

    if not resume:

        return jsonify({
            "success": False,
            "message": "Please upload a resume."
        }), 400

    prompt = f"""
You are StudentFix AI ResumeFix.

Review a student's resume against the supplied job description.

Give practical beginner-friendly feedback.

Include:
- strengths
- missing skills
- formatting improvements
- project improvements
- specific suggestions

Do not invent facts about the student.

JOB DESCRIPTION:
{job[:12000]}

Resume filename:
{resume.filename}
"""

    ai_result = ask_ai(prompt)

    result = (
        ai_result
        if ai_result
        else fallback_resume(job)
    )

    save_record(
        "ResumeFix",
        result
    )

    return jsonify({
        "success": True,
        "result": result
    })


# =====================================================
# CAREERMATE FALLBACK
# =====================================================

def fallback_career(
    goal,
    skills
):

    goal = goal.strip() or "Software Developer"

    skills = skills.strip()

    current = (
        skills
        if skills
        else "Beginner level"
    )

    return f"""Career Roadmap

Goal:
{goal}

Current skills:
{current}

Step 1 — Strengthen basics
• Programming fundamentals
• Problem solving
• Git and GitHub
• Basic SQL

Step 2 — Build technical skills
• Choose the main technologies required for {goal}
• Practice small coding exercises
• Learn through small projects

Step 3 — Build projects
• Create 2–3 practical projects
• Put the projects on GitHub
• Explain what you built and why

Step 4 — Prepare for opportunities
• Improve your resume
• Practice technical questions
• Practice communication and interview questions

Step 5 — Keep improving
• Review weak areas
• Build another project
• Follow current industry requirements

Start with one skill at a time instead of trying to learn everything together."""


# =====================================================
# CAREERMATE
# =====================================================

@app.post("/careermate")
def career_mate():

    goal = request.form.get(
        "goal",
        ""
    ).strip()

    skills = request.form.get(
        "skills",
        ""
    ).strip()

    prompt = f"""
You are StudentFix AI CareerMate.

Create a beginner-friendly career roadmap.

Career goal:
{goal}

Current skills:
{skills}

Include:
1. Skills to learn
2. Suggested project types
3. Practice plan
4. Resume preparation
5. Interview preparation
6. A simple sequence to follow

Do not make unrealistic guarantees.
"""

    ai_result = ask_ai(prompt)

    result = (
        ai_result
        if ai_result
        else fallback_career(
            goal,
            skills
        )
    )

    save_record(
        "CareerMate",
        result
    )

    return jsonify({
        "success": True,
        "result": result
    })


# =====================================================
# INTERVIEW FALLBACK
# =====================================================

def fallback_question(role):

    role = role.strip() or "Software Developer"

    questions = {
        "python": "Explain the difference between a list, tuple and dictionary in Python.",
        "software": "Tell me about a project you have worked on and explain your contribution.",
        "developer": "How would you approach solving a programming problem you have never seen before?",
        "web": "Explain the difference between frontend and backend development."
    }

    lower = role.lower()

    if "python" in lower:
        return questions["python"]

    if "web" in lower:
        return questions["web"]

    if "developer" in lower:
        return questions["developer"]

    return questions["software"]


def fallback_eval(
    question,
    answer
):

    answer = answer.strip()

    word_count = len(
        answer.split()
    )

    if word_count < 10:

        return """Interview feedback:

Your answer is a little short.

Try this structure:
1. Direct answer
2. Short explanation
3. Example
4. Result or conclusion

Practice giving a clear answer in your own words."""

    if word_count < 30:

        return """Interview feedback:

Your answer has a useful starting point.

To improve it:
• Give a little more explanation.
• Add a practical example.
• Clearly explain your own contribution.
• Finish with the result or learning.

Keep your answer natural rather than memorizing it."""

    return """Interview feedback:

Your answer contains enough detail for a basic interview response.

To improve it further:
• Start with the main point.
• Use a specific example.
• Explain your personal contribution.
• Mention the result or what you learned.
• Keep the answer focused on the question.

Continue practicing with different questions."""


# =====================================================
# INTERVIEW QUESTION
# =====================================================

@app.post("/interview/question")
def interview_question():

    role = request.form.get(
        "role",
        "Software Developer"
    ).strip()

    if not role:
        role = "Software Developer"

    prompt = f"""
You are StudentFix AI InterviewMate.

Generate ONE beginner-friendly interview question
for this target role:

{role}

Return only the question.
"""

    ai_result = ask_ai(prompt)

    question = (
        ai_result
        if ai_result
        else fallback_question(role)
    )

    return jsonify({
        "success": True,
        "question": question
    })


# =====================================================
# INTERVIEW EVALUATION
# =====================================================

@app.post("/interview/evaluate")
def interview_evaluate():

    question = request.form.get(
        "question",
        ""
    ).strip()

    answer = request.form.get(
        "answer",
        ""
    ).strip()

    if not answer:

        return jsonify({
            "success": False,
            "message": "Please type your answer first."
        }), 400

    prompt = f"""
You are StudentFix AI InterviewMate.

Evaluate this student's interview answer.

Question:
{question}

Answer:
{answer}

Give beginner-friendly feedback.

Include:
- what was done well
- what can improve
- one specific suggestion

Do not insult or discourage the student.
"""

    ai_result = ask_ai(prompt)

    result = (
        ai_result
        if ai_result
        else fallback_eval(
            question,
            answer
        )
    )

    save_record(
        "InterviewMate",
        result
    )

    return jsonify({
        "success": True,
        "result": result
    })


# =====================================================
# HISTORY
# =====================================================

@app.get("/history")
def history():

    user_id = current_user_id()

    if user_id:

        records = Record.query.filter_by(
            user_id=user_id
        ).order_by(
            Record.id.desc()
        ).limit(20).all()

    else:

        records = Record.query.filter_by(
            user_id=None
        ).order_by(
            Record.id.desc()
        ).limit(20).all()

    return jsonify([
        {
            "module": record.module,
            "result": record.result
        }
        for record in records
    ])


# =====================================================
# HEALTH
# =====================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok",
        "app": "StudentFix AI"
    })


# =====================================================
# HOME
# =====================================================

@app.get("/")
def home():

    return render_template(
        "index.html"
    )


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )