// =====================================================
// AUTHENTICATION + PROTECTED NAVIGATION
// =====================================================

let pendingSection = null;
let authMode = "login";

function requestSection(id) {
    pendingSection = id;
    fetch("/auth/status")
        .then(r => r.json())
        .then(status => {
            if (status.authenticated || status.guest) {
                showSection(id);
                updateUserArea(status);
            } else {
                openAuthModal("login");
            }
        })
        .catch(() => openAuthModal("login"));
}

function openAuthModal(mode = "login") {
    authMode = mode;
    document.getElementById("authModal").classList.remove("hidden");
    document.getElementById("authModal").setAttribute("aria-hidden", "false");
    if (mode === "register") showRegister();
    else showLogin();
}

function closeAuthModal() {
    document.getElementById("authModal").classList.add("hidden");
    document.getElementById("authModal").setAttribute("aria-hidden", "true");
    document.getElementById("authMessage").textContent = "";
}

function showLogin() {
    authMode = "login";
    document.getElementById("authTitle").textContent = "Login";
    document.getElementById("authSubtitle").textContent = "Login to continue to StudentFix AI.";
    document.getElementById("loginForm").classList.remove("hidden");
    document.getElementById("registerForm").classList.add("hidden");
    document.getElementById("authMessage").textContent = "";
}

function showRegister() {
    authMode = "register";
    document.getElementById("authTitle").textContent = "Create Account";
    document.getElementById("authSubtitle").textContent = "Create your StudentFix AI account.";
    document.getElementById("loginForm").classList.add("hidden");
    document.getElementById("registerForm").classList.remove("hidden");
    document.getElementById("authMessage").textContent = "";
}

function setAuthMessage(message, isError = true) {
    const el = document.getElementById("authMessage");
    el.textContent = message;
    el.className = "auth-message " + (isError ? "error" : "success");
}

async function parseJsonResponse(response) {
    const text = await response.text();
    try {
        return JSON.parse(text);
    } catch {
        throw new Error("Server returned an invalid response. Please restart Flask and try again.");
    }
}

async function loginUser() {
    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;

    if (!email || !password) {
        setAuthMessage("Please enter your email and password.");
        return;
    }

    try {
        const response = await fetch("/auth/login", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({email, password})
        });
        const data = await parseJsonResponse(response);
        if (!response.ok || !data.success) {
            setAuthMessage(data.message || "Login failed.");
            return;
        }
        afterAuth(data);
    } catch (error) {
        setAuthMessage(error.message);
    }
}

async function registerUser() {
    const name = document.getElementById("registerName").value.trim();
    const email = document.getElementById("registerEmail").value.trim();
    const password = document.getElementById("registerPassword").value;

    if (!name || !email || !password) {
        setAuthMessage("Please fill all fields.");
        return;
    }

    try {
        const response = await fetch("/auth/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name, email, password})
        });
        const data = await parseJsonResponse(response);
        if (!response.ok || !data.success) {
            setAuthMessage(data.message || "Account creation failed.");
            return;
        }
        afterAuth(data);
    } catch (error) {
        setAuthMessage(error.message);
    }
}

async function continueAsGuest() {
    try {
        const response = await fetch("/auth/guest", {method: "POST"});
        const data = await parseJsonResponse(response);
        if (!response.ok || !data.success) {
            setAuthMessage(data.message || "Could not continue as guest.");
            return;
        }
        afterAuth(data);
    } catch (error) {
        setAuthMessage(error.message);
    }
}

function afterAuth(data) {
    closeAuthModal();
    updateUserArea({
        authenticated: !!data.email,
        guest: !!data.guest,
        name: data.name,
        email: data.email
    });
    if (pendingSection) {
        const target = pendingSection;
        pendingSection = null;
        showSection(target);
    }
}

function updateUserArea(status) {
    const area = document.getElementById("userArea");
    if (!area) return;

    if (status.authenticated) {
        area.innerHTML = `<span>👤 ${escapeHtml(status.name)}</span><button onclick="logoutUser()">Logout</button>`;
    } else if (status.guest) {
        area.innerHTML = `<span>👤 Guest</span><button onclick="logoutUser()">Exit</button>`;
    } else {
        area.innerHTML = "";
    }
}

function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, ch => ({
        "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;"
    }[ch]));
}

async function logoutUser() {
    await fetch("/auth/logout", {method: "POST"});
    document.getElementById("userArea").innerHTML = "";
    showSection("welcome");
}

async function checkAuthBeforeAction() {
    const response = await fetch("/auth/status");
    const status = await parseJsonResponse(response);
    if (status.authenticated || status.guest) return true;
    openAuthModal("login");
    return false;
}

window.addEventListener("DOMContentLoaded", async () => {
    try {
        const response = await fetch("/auth/status");
        const status = await parseJsonResponse(response);
        updateUserArea(status);
    } catch (e) {}
});

// =====================================================
// NAVIGATION
// =====================================================

function showSection(id) {
    document.querySelectorAll("main > section").forEach(section => {
        section.classList.add("hidden");
    });

    const section = document.getElementById(id);
    if (section) section.classList.remove("hidden");

    if (id === "history") loadHistory();
}


// =====================================================
// HELPERS
// =====================================================

function setLoading(id, message = "AI is analyzing...") {
    const el = document.getElementById(id);
    el.textContent = message;
    el.classList.remove("hidden");
}

function hideLoading(id) {
    document.getElementById(id).classList.add("hidden");
}

function showError(id, message) {
    document.getElementById(id).textContent = message;
}


// =====================================================
// DOCUMENTFIX - REQUIREMENT PDF
// =====================================================

let requiredDocuments = [];

const requirementsFile = document.getElementById("requirementsFile");

requirementsFile.addEventListener("change", function () {
    const file = this.files[0];
    if (file) console.log("Requirement PDF selected:", file.name);
});

document.getElementById("analyzeButton").addEventListener("click", async function () {
    const file = requirementsFile.files[0];

    if (!file) {
        alert("Please upload the application requirements PDF.");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setLoading("requirementsLoading", "Analyzing requirements...");

    try {
        const response = await fetch("/analyze-requirements", {
            method: "POST",
            body: formData
        });

        const data = await parseJsonResponse(response);
        hideLoading("requirementsLoading");

        if (!data.success) {
            alert(data.message);
            return;
        }

        requiredDocuments = data.result.documents || [];
        displayRequirements(data.result);
    } catch (error) {
        hideLoading("requirementsLoading");
        alert("Something went wrong while analyzing the PDF.");
        console.error(error);
    }
});


function displayRequirements(result) {
    const resultBox = document.getElementById("requirementsResult");
    resultBox.classList.remove("hidden");

    const documentList = document.getElementById("requiredDocuments");
    documentList.innerHTML = "";

    if (!result.documents || result.documents.length === 0) {
        const li = document.createElement("li");
        li.textContent = "No specific required documents were explicitly found.";
        documentList.appendChild(li);
    } else {
        (result.documents || []).forEach(documentName => {
            const li = document.createElement("li");
            li.textContent = "✅ " + documentName;
            documentList.appendChild(li);
        });
    }

    const eligibility = document.getElementById("eligibility");
    eligibility.innerHTML = "";

    if (!result.eligibility || result.eligibility.length === 0) {
        eligibility.textContent = "No explicit eligibility rule found in this document.";
    } else {
        result.eligibility.forEach(item => {
            const span = document.createElement("span");
            span.className = "chip";
            span.textContent = item;
            eligibility.appendChild(span);
        });
    }

    const conditions = document.getElementById("conditions");
    conditions.innerHTML = "";
    if (!result.conditions || result.conditions.length === 0) {
        const li = document.createElement("li");
        li.textContent = "No additional conditions found.";
        conditions.appendChild(li);
    } else {
        result.conditions.forEach(item => {
            const li = document.createElement("li");
            li.textContent = "📌 " + item;
            conditions.appendChild(li);
        });
    }

    document.getElementById("deadline").textContent =
        result.deadline || "No deadline stated in this document";

    resultBox.scrollIntoView({ behavior: "smooth" });
}


// =====================================================
// DOCUMENTFIX - USER DOCUMENTS
// =====================================================

const documentsInput = document.getElementById("documents");

documentsInput.addEventListener("change", function () {
    const files = Array.from(this.files);
    const fileList = document.getElementById("selectedFiles");
    fileList.innerHTML = "";

    files.forEach(file => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.textContent = "📄 " + file.name;
        fileList.appendChild(div);
    });
});


document.getElementById("checkButton").addEventListener("click", async function () {
    const files = Array.from(documentsInput.files);

    if (requiredDocuments.length === 0) {
        alert("First upload and analyze the requirements PDF.");
        return;
    }

    if (files.length === 0) {
        alert("Please upload your documents.");
        return;
    }

    const formData = new FormData();

    files.forEach(file => {
        formData.append("documents", file);
    });

    formData.append("required_documents", requiredDocuments.join(","));
    formData.append(
        "application_name",
        document.getElementById("applicationName").value
    );
    formData.append(
        "application_dob",
        document.getElementById("applicationDob").value
    );

    setLoading("checkLoading", "Checking your application...");

    try {
        const response = await fetch("/check-documents", {
            method: "POST",
            body: formData
        });

        const data = await parseJsonResponse(response);
        hideLoading("checkLoading");

        if (!data.success) {
            alert(data.message);
            return;
        }

        displayDashboard(data.result);
    } catch (error) {
        hideLoading("checkLoading");
        alert("Something went wrong while checking your documents.");
        console.error(error);
    }
});


function displayDashboard(result) {
    const dashboard = document.getElementById("dashboard");
    dashboard.classList.remove("hidden");

    document.getElementById("score").textContent = result.readiness + "%";
    document.getElementById("status").textContent = result.status;

    document.getElementById("uploadedCount").textContent = result.uploaded_count;
    document.getElementById("missingCount").textContent =
        result.missing_documents.length;
    document.getElementById("mismatchCount").textContent =
        result.mismatches.length;

    displayIssueList(
        result.high_priority,
        "highPriority",
        "highPrioritySection"
    );

    displayIssueList(
        result.medium_priority,
        "mediumPriority",
        "mediumPrioritySection"
    );

    displayIssueList(
        result.low_priority,
        "lowPriority",
        "lowPrioritySection"
    );

    const fixes = document.getElementById("fixes");
    fixes.innerHTML = "";

    result.fixes.forEach(fix => {
        const li = document.createElement("li");
        li.textContent = "📌 " + fix;
        fixes.appendChild(li);
    });

    const finalMessage = document.getElementById("finalMessage");

    if (result.readiness >= 90) {
        finalMessage.textContent =
            "🟢 Your application looks ready for submission. Still perform a final manual review.";
    } else if (result.readiness >= 70) {
        finalMessage.textContent =
            "🟡 Your application needs a few checks before submission.";
    } else {
        finalMessage.textContent =
            "🔴 Your application is incomplete. Fix the high-priority issues before submission.";
    }

    dashboard.scrollIntoView({ behavior: "smooth" });
}


function displayIssueList(items, listId, sectionId) {
    const section = document.getElementById(sectionId);
    const list = document.getElementById(listId);

    list.innerHTML = "";

    if (!items || items.length === 0) {
        section.classList.add("hidden");
        return;
    }

    section.classList.remove("hidden");

    items.forEach(item => {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
    });
}


// =====================================================
// RESUMEFIX
// =====================================================

async function resumeFix() {
    const file = document.getElementById("resumeFile").files[0];

    if (!file) {
        showError("resumeResult", "Please upload a resume.");
        return;
    }

    const form = new FormData();
    form.append("resume", file);
    form.append("job", document.getElementById("job").value);

    const resultBox = document.getElementById("resumeResult");
    resultBox.classList.remove("hidden");
    resultBox.textContent = "AI is analyzing your resume...";

    try {
        const response = await fetch("/resumefix", {
            method: "POST",
            body: form
        });

        const data = await parseJsonResponse(response);
        if (!response.ok) {
            resultBox.textContent = data.message || data.result || "Resume analysis failed.";
            return;
        }
        resultBox.textContent = data.result || data.message || "No analysis was returned.";
    } catch (error) {
        resultBox.textContent = "Request failed: " + error.message;
    }
}


// =====================================================
// CAREERMATE
// =====================================================

async function careerMate() {
    const form = new FormData();
    form.append("goal", document.getElementById("goal").value);
    form.append("skills", document.getElementById("skills").value);

    const resultBox = document.getElementById("careerResult");
    resultBox.classList.remove("hidden");
    resultBox.textContent = "AI is generating your roadmap...";

    try {
        const response = await fetch("/careermate", {
            method: "POST",
            body: form
        });

        const data = await parseJsonResponse(response);
        if (!response.ok) {
            resultBox.textContent = data.message || data.result || "Career roadmap generation failed.";
            return;
        }
        resultBox.textContent = data.result || data.message || "No roadmap was returned.";
    } catch (error) {
        resultBox.textContent = "Request failed: " + error.message;
    }
}


// =====================================================
// INTERVIEWMATE
// =====================================================

let currentQuestion = "";

async function getQuestion() {
    const role =
        document.getElementById("role").value || "Software Developer";

    const form = new FormData();
    form.append("role", role);

    document.getElementById("question").textContent =
        "Generating question...";
    document.getElementById("questionBox").classList.remove("hidden");

    try {
        const response = await fetch("/interview/question", {
            method: "POST",
            body: form
        });

        const data = await parseJsonResponse(response);

        currentQuestion = data.question;
        document.getElementById("question").textContent = currentQuestion;
        document.getElementById("answer").value = "";
        document.getElementById("interviewResult").textContent = "";
    } catch (error) {
        document.getElementById("question").textContent =
            "Request failed: " + error.message;
    }
}


async function evaluateAnswer() {
    const answer = document.getElementById("answer").value;

    if (!answer.trim()) {
        showError("interviewResult", "Please type your answer first.");
        return;
    }

    const form = new FormData();
    form.append("question", currentQuestion);
    form.append("answer", answer);

    const resultBox = document.getElementById("interviewResult");
    resultBox.classList.remove("hidden");
    resultBox.textContent = "AI is evaluating your answer...";

    try {
        const response = await fetch("/interview/evaluate", {
            method: "POST",
            body: form
        });

        const data = await parseJsonResponse(response);
        if (!response.ok) {
            resultBox.textContent = data.message || data.result || "Interview evaluation failed.";
            return;
        }
        resultBox.textContent = data.result || data.message || "No evaluation was returned.";
    } catch (error) {
        resultBox.textContent = "Request failed: " + error.message;
    }
}


// =====================================================
// HISTORY
// =====================================================

async function loadHistory() {
    const box = document.getElementById("historyResult");
    box.textContent = "Loading history...";

    try {
        const response = await fetch("/history");
        const data = await parseJsonResponse(response);

        if (!data.length) {
            box.textContent = "No history yet.";
            return;
        }

        box.innerHTML = "";

        data.forEach(item => {
            const div = document.createElement("div");
            div.className = "history-item";

            const title = document.createElement("h3");
            title.textContent = item.module;

            const result = document.createElement("div");
            result.style.whiteSpace = "pre-wrap";
            result.textContent = item.result;

            div.appendChild(title);
            div.appendChild(result);
            box.appendChild(div);
        });
    } catch (error) {
        box.textContent = "Could not load history: " + error.message;
    }
}


// Open the welcome screen first. A login is requested when a tool is selected.
showSection("welcome");
