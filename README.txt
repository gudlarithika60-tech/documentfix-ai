STUDENTFIX AI

RUN:
1. Create/activate venv.
2. pip install -r requirements.txt
3. Create .env beside app.py:
   GEMINI_API_KEY=YOUR_REAL_KEY
   GEMINI_MODEL=gemini-2.5-flash
   SECRET_KEY=studentfix-dev-secret
4. python app.py
5. Open http://127.0.0.1:5000

IMPORTANT:
- Do not open index.html directly.
- CareerMate, ResumeFix and InterviewMate results are now kept visible after loading.
- If Gemini is unavailable, the result area displays the actual error instead of appearing blank.
- Test Gemini configuration at http://127.0.0.1:5000/health
