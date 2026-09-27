/* =========================================================
   ITDEBUGS FRONTEND
   ========================================================= */

const API_BASE = "http://127.0.0.1:8000";


/* =========================================================
   STATE
   ========================================================= */

let selectedRepository = null;
let latestAnalysis = null;

let reactionStartTime = null;
let reactionTimeout = null;

let lastReaction = null;

let bestReaction =
    Number(
        localStorage.getItem(
            "itdebugs_reaction_best"
        )
    ) || null;

let reactionStreak = 0;


/* =========================================================
   HELPERS
   ========================================================= */

function escapeHTML(value) {

    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function setActiveNav(button) {

    document
        .querySelectorAll(".nav-item")
        .forEach(item => {

            item.classList.remove("active");

        });

    if (button) {
        button.classList.add("active");
    }
}


/* =========================================================
   ELEMENTS
   ========================================================= */

const repositoryInput =
    document.getElementById(
        "repositoryInput"
    );

const repositoryName =
    document.getElementById(
        "repositoryName"
    );

const repositoryMeta =
    document.getElementById(
        "repositoryMeta"
    );

const repositoryAnalyze =
    document.getElementById(
        "repositoryAnalyze"
    );

const investigateButton =
    document.getElementById(
        "investigateButton"
    );


/* =========================================================
   DASHBOARD
   ========================================================= */

const navDashboard =
    document.getElementById(
        "navDashboard"
    );


navDashboard.addEventListener(
    "click",
    () => {

        document
            .querySelectorAll(
                ".ui-modal-overlay"
            )
            .forEach(el => el.remove());

        setActiveNav(navDashboard);

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });

    }
);


/* =========================================================
   REPOSITORY SELECT
   ========================================================= */

repositoryInput.addEventListener(
    "change",
    event => {

        const files =
            Array.from(
                event.target.files
            );

        if (!files.length) {
            return;
        }


        const firstPath =
            files[0].webkitRelativePath ||
            files[0].name;


        const parts =
            firstPath.split("/");


        const repoName =
            parts.length > 1
                ? parts[0]
                : "Selected Repository";


        selectedRepository = {

            name: repoName,

            files: files

        };


        repositoryName.textContent =
            repoName;


        repositoryMeta.textContent =
            `${files.length} files selected · Ready for analysis`;


        repositoryAnalyze.disabled =
            false;


        localStorage.setItem(
            "itdebugs_last_repository",
            repoName
        );

    }
);


/* =========================================================
   OPEN FILE PICKER
   ========================================================= */

document
    .querySelector(
        ".repository-button"
    )
    .addEventListener(
        "click",
        () => repositoryInput.click()
    );


investigateButton.addEventListener(
    "click",
    () => {

        if (!selectedRepository) {

            repositoryInput.click();

            return;
        }

        analyzeRepository();

    }
);


/* =========================================================
   ANALYZE REPOSITORY
   ========================================================= */

repositoryAnalyze.addEventListener(
    "click",
    analyzeRepository
);


async function analyzeRepository() {

    if (!selectedRepository) {

        alert(
            "Please select a repository first."
        );

        return;
    }


    repositoryAnalyze.disabled =
        true;


    repositoryAnalyze.textContent =
        "Analyzing...";


    repositoryMeta.textContent =
        "ItDebugs is analyzing the repository...";


    try {

        const formData =
            new FormData();


        selectedRepository.files.forEach(
            file => {

                formData.append(
                    "files",
                    file,
                    file.webkitRelativePath ||
                    file.name
                );

            }
        );


        formData.append(
            "timeout",
            "60"
        );


        const response =
            await fetch(
                `${API_BASE}/api/investigate`,
                {
                    method: "POST",
                    body: formData
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.detail ||
                "Repository analysis failed."
            );

        }


        latestAnalysis =
            data;


        localStorage.setItem(
            "itdebugs_last_repository",
            selectedRepository.name
        );


        updateDashboardResults(
            data
        );


        repositoryMeta.textContent =
            `${data.test_summary.total} tests analyzed · Analysis completed`;


    } catch (error) {

        console.error(error);


        repositoryMeta.textContent =
            "Analysis failed.";


        alert(
            "ItDebugs could not analyze this repository.\n\n" +
            error.message
        );

    } finally {

        repositoryAnalyze.disabled =
            false;

        repositoryAnalyze.textContent =
            "Analyze →";

    }

}


/* =========================================================
   UPDATE RESULTS
   ========================================================= */

function updateDashboardResults(data) {

    const summary =
        data.test_summary;


    document.getElementById(
        "metricTotal"
    ).textContent =
        summary.total;


    document.getElementById(
        "metricPassed"
    ).textContent =
        summary.passed;


    document.getElementById(
        "metricFailed"
    ).textContent =
        summary.failed;


    const passRate =
        summary.total
            ? (
                summary.passed /
                summary.total *
                100
            ).toFixed(1)
            : 0;


    document.getElementById(
        "metricPassRate"
    ).textContent =
        `${passRate}% pass rate`;


    document.getElementById(
        "failureBadge"
    ).textContent =
        `${summary.failed} failures`;


    const resultsSection =
        document.getElementById(
            "resultsSection"
        );


    resultsSection.style.display =
        "grid";


    const container =
        document.getElementById(
            "investigationResults"
        );


    if (!data.reports?.length) {

        container.innerHTML = `

            <div class="empty-result">

                ${
                    summary.failed === 0
                        ? "Repository is healthy. No failing tests found."
                        : "Failures were detected, but no investigation report was produced."
                }

            </div>

        `;

        return;
    }


    container.innerHTML =
        data.reports
            .map(
                (report, index) => {

                    return `

                        <div
                            class="investigation-item"
                            style="margin-bottom:12px;"
                        >

                            <div class="file-icon">
                                ${index + 1}
                            </div>

                            <div class="investigation-info">

                                <div class="file-name">
                                    Bug Group ${report.bug_id}
                                </div>

                                <div class="file-location">
                                    Investigation completed
                                </div>

                            </div>

                            <div class="investigation-result">
                                ● Root cause analyzed
                            </div>

                        </div>


                        <div class="root-cause-preview">

                            <div class="preview-label">
                                ROOT CAUSE
                            </div>

                            <p>
                                ${escapeHTML(
                                    report.root_cause ||
                                    "Root cause details are available in the investigation report."
                                )}
                            </p>

                        </div>

                    `;

                }
            )
            .join("");

}


/* =========================================================
   INVESTIGATE NAV
   ========================================================= */

document
    .getElementById("navInvestigate")
    .addEventListener(
        "click",
        () => {

            setActiveNav(
                document.getElementById(
                    "navInvestigate"
                )
            );

            if (!selectedRepository) {

                repositoryInput.click();

                return;
            }


            analyzeRepository();

        }
    );


/* =========================================================
   REPOSITORIES NAV
   ========================================================= */

document
    .getElementById("navRepositories")
    .addEventListener(
        "click",
        () => {

            setActiveNav(
                document.getElementById(
                    "navRepositories"
                )
            );

            repositoryInput.click();

        }
    );


/* =========================================================
   HISTORY
   ========================================================= */

document
    .getElementById("navHistory")
    .addEventListener(
        "click",
        showHistory
    );


function showHistory() {

    setActiveNav(
        document.getElementById(
            "navHistory"
        )
    );


    const old =
        document.getElementById(
            "historyModal"
        );


    if (old) {
        old.remove();
    }


    const repo =
        selectedRepository?.name ||
        localStorage.getItem(
            "itdebugs_last_repository"
        );


    const summary =
        latestAnalysis?.test_summary;


    const modal =
        document.createElement(
            "div"
        );


    modal.id =
        "historyModal";


    modal.className =
        "ui-modal-overlay";


    modal.innerHTML = `

        <div class="ui-modal">

            <button
                class="modal-x"
                id="closeHistory"
            >
                ×
            </button>


            <div class="ui-modal-eyebrow">
                WORKSPACE
            </div>


            <h2>
                Investigation History
            </h2>


            <p>
                Your latest ItDebugs repository activity.
            </p>


            <div class="history-repository">

                <strong>
                    📁 ${
                        escapeHTML(
                            repo ||
                            "No repository selected"
                        )
                    }
                </strong>

                <span>

                    ${
                        summary
                            ? `${summary.total} tests · ${summary.passed} passed · ${summary.failed} failed`
                            : "No analysis has been performed yet."
                    }

                </span>

            </div>


            <button
                class="primary-button"
                id="historyBackDashboard"
            >
                ← Back to Dashboard
            </button>

        </div>

    `;


    document.body.appendChild(
        modal
    );


    document
        .getElementById(
            "closeHistory"
        )
        .onclick =
        closeModalToDashboard;


    document
        .getElementById(
            "historyBackDashboard"
        )
        .onclick =
        closeModalToDashboard;

}


/* =========================================================
   SETTINGS
   ========================================================= */

document
    .getElementById("navSettings")
    .addEventListener(
        "click",
        showSettings
    );


function showSettings() {

    setActiveNav(
        document.getElementById(
            "navSettings"
        )
    );


    const modal =
        document.createElement(
            "div"
        );


    modal.id =
        "settingsModal";


    modal.className =
        "ui-modal-overlay";


    modal.innerHTML = `

        <div class="ui-modal">

            <button
                class="modal-x"
                id="closeSettings"
            >
                ×
            </button>


            <div class="ui-modal-eyebrow">
                WORKSPACE
            </div>


            <h2>
                Settings
            </h2>


            <div class="setting-row">

                <div>
                    <strong>
                        Theme
                    </strong>

                    <span>
                        Switch between light and dark mode.
                    </span>
                </div>

                <button
                    class="secondary-button"
                    id="settingsTheme"
                >
                    Toggle
                </button>

            </div>


            <div class="setting-row">

                <div>
                    <strong>
                        AI Engine
                    </strong>

                    <span>
                        IBM Granite · Local Ollama
                    </span>
                </div>

                <span class="setting-status">
                    ONLINE
                </span>

            </div>


            <div class="setting-row">

                <div>
                    <strong>
                        Analysis Timeout
                    </strong>

                    <span>
                        Maximum test execution time.
                    </span>
                </div>

                <span>
                    60 sec
                </span>

            </div>


            <div class="about-card">

                <h3>
                    About ItDebugs
                </h3>

                <p>
                    ItDebugs is an agentic developer intelligence
                    platform built for the IBM Bob 2.0 Hackathon.
                    It analyzes repositories, investigates failing
                    tests, identifies root causes and supports
                    verified software repair.
                </p>

                <p style="margin-top:12px;">
                    Powered by IBM Granite and an autonomous
                    multi-agent debugging pipeline.
                </p>

            </div>

        </div>

    `;


    document.body.appendChild(
        modal
    );


    document
        .getElementById(
            "closeSettings"
        )
        .onclick =
        closeModalToDashboard;


    document
        .getElementById(
            "settingsTheme"
        )
        .onclick = () => {

            document.body.classList.toggle(
                "dark-mode"
            );

            localStorage.setItem(
                "itdebugs_dark",
                document.body.classList.contains(
                    "dark-mode"
                )
            );

        };

}


/* =========================================================
   PROFILE
   ========================================================= */

document
    .getElementById("profileButton")
    .addEventListener(
        "click",
        showProfile
    );


function showProfile() {

    const modal =
        document.createElement(
            "div"
        );


    modal.id =
        "profileModal";


    modal.className =
        "ui-modal-overlay";


    modal.innerHTML = `

        <div class="auth-page">

            <button
                class="auth-close"
                id="authClose"
            >
                ×
            </button>


            <div class="auth-page-logo">
                &lt;/&gt;
            </div>


            <div class="ui-modal-eyebrow">
                ITDEBUGS ACCOUNT
            </div>


            <h2>
                Welcome back.
            </h2>


            <p class="auth-page-description">
                Sign in or create your ItDebugs developer account.
            </p>


            <div class="auth-tabs">

                <button
                    class="auth-tab active"
                    id="loginTab"
                >
                    Login
                </button>

                <button
                    class="auth-tab"
                    id="registerTab"
                >
                    Register
                </button>

            </div>


            <input
                class="auth-form-input"
                id="authName"
                placeholder="Full name"
                style="display:none;"
            >


            <input
                class="auth-form-input"
                id="authEmail"
                type="email"
                placeholder="Email address"
            >


            <input
                class="auth-form-input"
                id="authPassword"
                type="password"
                placeholder="Password"
            >


            <div id="authMessage"></div>


            <button
                class="primary-button"
                id="authSubmit"
                style="width:100%;"
            >
                Login →
            </button>

        </div>

    `;


    document.body.appendChild(
        modal
    );


    let mode =
        "login";


    const loginTab =
        document.getElementById(
            "loginTab"
        );

    const registerTab =
        document.getElementById(
            "registerTab"
        );

    const nameInput =
        document.getElementById(
            "authName"
        );

    const emailInput =
        document.getElementById(
            "authEmail"
        );

    const passwordInput =
        document.getElementById(
            "authPassword"
        );

    const message =
        document.getElementById(
            "authMessage"
        );

    const submit =
        document.getElementById(
            "authSubmit"
        );


    loginTab.onclick = () => {

        mode = "login";

        loginTab.classList.add("active");
        registerTab.classList.remove("active");

        nameInput.style.display =
            "none";

        submit.textContent =
            "Login →";

        message.innerHTML =
            "";

    };


    registerTab.onclick = () => {

        mode = "register";

        registerTab.classList.add("active");
        loginTab.classList.remove("active");

        nameInput.style.display =
            "block";

        submit.textContent =
            "Create Account →";

        message.innerHTML =
            "";

    };


    submit.onclick = () => {

        const email =
            emailInput.value.trim();

        const password =
            passwordInput.value;

        const name =
            nameInput.value.trim();


        if (!email || !password) {

            message.innerHTML = `
                <div class="auth-error">
                    Please enter your email and password.
                </div>
            `;

            return;
        }


        if (mode === "register") {

            if (!name) {

                message.innerHTML = `
                    <div class="auth-error">
                        Please enter your name.
                    </div>
                `;

                return;
            }


            localStorage.setItem(
                "itdebugs_user",
                JSON.stringify({
                    name,
                    email,
                    password
                })
            );


            localStorage.setItem(
                "itdebugs_logged_in",
                "true"
            );


            message.innerHTML = `
                <div class="auth-success">
                    Account created successfully.
                </div>
            `;


            setTimeout(
                () => modal.remove(),
                900
            );


            return;

        }


        const saved =
            localStorage.getItem(
                "itdebugs_user"
            );


        if (!saved) {

            message.innerHTML = `
                <div class="auth-error">
                    No account found. Please register first.
                </div>
            `;

            return;
        }


        const user =
            JSON.parse(saved);


        if (
            user.email !== email ||
            user.password !== password
        ) {

            message.innerHTML = `
                <div class="auth-error">
                    Incorrect email or password.
                </div>
            `;

            return;
        }


        localStorage.setItem(
            "itdebugs_logged_in",
            "true"
        );


        message.innerHTML = `
            <div class="auth-success">
                Login successful. Welcome back!
            </div>
        `;


        setTimeout(
            () => modal.remove(),
            900
        );

    };


    document
        .getElementById(
            "authClose"
        )
        .onclick =
        closeModalToDashboard;

}


/* =========================================================
   CLOSE MODAL
   ========================================================= */

function closeModalToDashboard() {

    document
        .querySelectorAll(
            ".ui-modal-overlay"
        )
        .forEach(
            modal => modal.remove()
        );


    setActiveNav(
        navDashboard
    );


    window.scrollTo({
        top: 0,
        behavior: "smooth"
});

}


/* =========================================================
   QUICK ACTIONS
   ========================================================= */

document
    .getElementById(
        "runTestsButton"
    )
    .onclick = () => {

        if (!selectedRepository) {

            repositoryInput.click();

            return;

        }

        analyzeRepository();

    };


document
    .getElementById(
        "analyzeCodeButton"
    )
    .onclick = () => {

        if (!selectedRepository) {

            repositoryInput.click();

            return;

        }

        analyzeRepository();

    };


document
    .getElementById(
        "repairButton"
    )
    .onclick = () => {

        alert(
            "Repair & Verify is available after ItDebugs identifies a root cause.\n\n" +
            "Review the proposed repair before applying it."
        );

    };


/* =========================================================
   THEME
   ========================================================= */

const themeToggle =
    document.getElementById(
        "themeToggle"
    );


if (
    localStorage.getItem(
        "itdebugs_dark"
    ) === "true"
) {

    document.body.classList.add(
        "dark-mode"
    );

}


themeToggle.onclick = () => {

    document.body.classList.toggle(
        "dark-mode"
    );


    localStorage.setItem(
        "itdebugs_dark",
        document.body.classList.contains(
            "dark-mode"
        )
    );

};


/* =========================================================
   REACTION RUSH
   ========================================================= */

const gameModal =
    document.getElementById(
        "bugHunterModal"
    );

const reactionArea =
    document.getElementById(
        "reactionArea"
    );

const reactionButton =
    document.getElementById(
        "reactionButton"
    );

const reactionStatus =
    document.getElementById(
        "reactionStatus"
    );

const reactionMessage =
    document.getElementById(
        "reactionMessage"
    );

const reactionResults =
    document.getElementById(
        "reactionResults"
    );


function updateGameStats() {

    document.getElementById(
        "gameScore"
    ).textContent =
        lastReaction
            ? `${lastReaction} ms`
            : "—";


    document.getElementById(
        "gameStreak"
    ).textContent =
        bestReaction
            ? `${bestReaction} ms`
            : "—";


    document.getElementById(
        "gameRound"
    ).textContent =
        reactionStreak;


    document.getElementById(
        "dashboardBest"
    ).textContent =
        bestReaction
            ? `⚡ Best ${bestReaction} ms`
            : "⚡ Best —";

}


updateGameStats();


document
    .getElementById(
        "bugHunterButton"
    )
    .onclick = () => {

        gameModal.classList.remove(
            "hidden"
        );

        resetReactionGame();

    };


document
    .getElementById(
        "closeBugHunter"
    )
    .onclick = () => {

        clearTimeout(
            reactionTimeout
        );

        gameModal.classList.add(
            "hidden"
        );

    };


document
    .getElementById(
        "restartGame"
    )
    .onclick =
    resetReactionGame;


reactionButton.onclick =
    startReaction;


function resetReactionGame() {

    clearTimeout(
        reactionTimeout
    );


    reactionResults.classList.add(
        "hidden"
    );


    reactionArea.classList.remove(
        "reaction-ready"
    );


    reactionStatus.textContent =
        "READY?";


    reactionMessage.textContent =
        "Hit START and wait for the signal.";


    reactionButton.textContent =
        "START";


    reactionButton.disabled =
        false;

}


function startReaction() {

    reactionButton.disabled =
        true;


    reactionStatus.textContent =
        "WAIT...";


    reactionMessage.textContent =
        "Do not click until the signal turns green.";


    const delay =
        1000 +
        Math.random() * 3500;


    reactionTimeout =
        setTimeout(
            () => {

                reactionStartTime =
                    performance.now();


                reactionArea.classList.add(
                    "reaction-ready"
                );


                reactionStatus.textContent =
                    "CLICK!";


                reactionMessage.textContent =
                    "GO GO GO!";


                reactionButton.disabled =
                    false;


                reactionButton.textContent =
                    "CLICK!";

            },
            delay
        );

}


/* CLICK AFTER SIGNAL */

reactionButton.addEventListener(
    "click",
    () => {

        if (
            !reactionStartTime
        ) {

            return;

        }


        const elapsed =
            Math.round(
                performance.now() -
                reactionStartTime
            );


        reactionStartTime =
            null;


        lastReaction =
            elapsed;


        reactionStreak++;


        if (
            !bestReaction ||
            elapsed < bestReaction
        ) {

            bestReaction =
                elapsed;


            localStorage.setItem(
                "itdebugs_reaction_best",
                bestReaction
            );

        }


        updateGameStats();


        reactionStatus.textContent =
            `${elapsed} MS`;


        reactionMessage.textContent =
            "Excellent reaction!";


        reactionResults.classList.remove(
            "hidden"
        );


        document.getElementById(
            "finalScore"
        ).textContent =
            `${elapsed} ms`;


        document.getElementById(
            "finalDetails"
        ).textContent =
            `Streak: ${reactionStreak} · Best: ${bestReaction} ms`;

    }
);


/* =========================================================
   ESCAPE
   ========================================================= */

document.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Escape"
        ) {

            gameModal.classList.add(
                "hidden"
            );


            document
                .querySelectorAll(
                    ".ui-modal-overlay"
                )
                .forEach(
                    modal =>
                        modal.remove()
                );

        }

    }
);