const API_BASE="http://127.0.0.1:8000";
let selectedRepository=null, latestAnalysis=null;

const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");

function historyGet(){try{return JSON.parse(localStorage.getItem("itdebugs_repository_history")||"[]")}catch{return[]}}
function historySave(name){
  if(!name)return;
  let h=historyGet().filter(x=>x.name!==name);
  h.unshift({name,selectedAt:new Date().toLocaleString()});
  localStorage.setItem("itdebugs_repository_history",JSON.stringify(h));
}
function closeOverlays(){document.querySelectorAll(".ui-modal-overlay").forEach(x=>x.remove())}
function dashboard(){closeOverlays();document.querySelectorAll(".nav-item").forEach(x=>x.classList.remove("active"));$("navDashboard").classList.add("active");window.scrollTo({top:0,behavior:"smooth"})}
function active(id){document.querySelectorAll(".nav-item").forEach(x=>x.classList.remove("active"));$(id)?.classList.add("active")}

const input=$("repositoryInput"), repoName=$("repositoryName"), repoMeta=$("repositoryMeta"), analyze=$("repositoryAnalyze");

input.addEventListener("change",e=>{
  const files=[...e.target.files]; if(!files.length)return;
  const p=(files[0].webkitRelativePath||files[0].name).split("/");
  const name=p.length>1?p[0]:"Selected Repository";
  selectedRepository={name,files};
  repoName.textContent=name;
  repoMeta.textContent=`${files.length} files selected · Ready for analysis`;
  analyze.disabled=false;
  historySave(name);
});

$("changeRepository").onclick=()=>input.click();
$("investigateButton").onclick=()=>selectedRepository?runAnalysis():input.click();
analyze.onclick=runAnalysis;

async function runAnalysis(){
  if(!selectedRepository){input.click();return}
  analyze.disabled=true;analyze.textContent="Analyzing...";
  repoMeta.textContent="ItDebugs is analyzing the repository...";
  const fd=new FormData();
  selectedRepository.files.forEach(f=>fd.append("files",f,f.webkitRelativePath||f.name));
  fd.append("timeout","60");
  try{
    const r=await fetch(`${API_BASE}/api/investigate`,{method:"POST",body:fd});
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||"Analysis failed.");
    latestAnalysis=data;historySave(selectedRepository.name);updateDashboard(data);showAnalysis(data);
    repoMeta.textContent=`${data.test_summary.total} tests analyzed · Analysis completed`;
  }catch(e){
    repoMeta.textContent="Analysis failed.";
    showSimple("Analysis Error",e.message);
  }finally{
    analyze.disabled=false;analyze.textContent="Analyze →";
  }
}

function updateDashboard(data){
  const s=data.test_summary||{};
  $("metricTotal").textContent=s.total??"—";
  $("metricPassed").textContent=s.passed??"—";
  $("metricFailed").textContent=s.failed??"—";
  $("metricPassRate").textContent=s.total?`${(s.passed/s.total*100).toFixed(1)}% pass rate`:"—";
  $("metricFailedSub").textContent=s.failed? "Requires investigation":"No failures";
  $("metricTotalSub").textContent="Latest run";
  $("failureBadge").textContent=`${s.failed||0} failures`;
  $("resultsSection").classList.remove("hidden");
  const c=$("investigationResults");
  if(!data.reports?.length){c.innerHTML=`<div class="empty-result">${s.failed?"Failures detected, but no report was returned.":"Repository is healthy. No failing tests found."}</div>`;return}
  c.innerHTML=data.reports.map((r,i)=>`<div class="investigation-item"><div><div class="file-name">Bug Group ${i+1}</div><div class="file-location">ItDebugs investigation completed</div></div><div class="investigation-result">● Root cause analyzed</div></div><div class="root-cause-preview"><div class="preview-label">ROOT CAUSE</div><p>${esc(r.root_cause||"Root cause identified. See investigation report.")}</p></div>`).join("");
}

function showSimple(title,msg){
  closeOverlays();
  const o=document.createElement("div");o.className="ui-modal-overlay";o.innerHTML=`<div class="ui-modal"><button class="modal-x" id="simpleClose">×</button><div class="eyebrow">ITDEBUGS</div><h2>${esc(title)}</h2><p>${esc(msg)}</p><button class="primary-btn" id="simpleBack">Back to Dashboard →</button></div>`;
  document.body.appendChild(o);$("simpleClose").onclick=dashboard;$("simpleBack").onclick=dashboard;
}

function showAnalysis(data){
  closeOverlays();const s=data.test_summary||{}, reports=data.reports||[];
  const o=document.createElement("div");o.className="ui-modal-overlay";
  o.innerHTML=`<div class="ui-modal"><button class="modal-x" id="analysisClose">×</button><div class="eyebrow">ANALYSIS COMPLETE</div><h2>Repository Analysis</h2><p>ItDebugs finished analyzing <b>${esc(selectedRepository.name)}</b>.</p><div class="analysis-status"><b>● Analysis completed successfully</b></div><div class="analysis-stats"><div class="analysis-stat"><span>TESTS</span><strong>${s.total||0}</strong></div><div class="analysis-stat"><span>PASSED</span><strong class="green">${s.passed||0}</strong></div><div class="analysis-stat"><span>FAILED</span><strong class="red">${s.failed||0}</strong></div><div class="analysis-stat"><span>BUG GROUPS</span><strong>${data.bug_count||0}</strong></div></div><div class="analysis-bugs"><h3>ItDebugs Findings</h3>${reports.length?reports.map((r,i)=>`<div class="analysis-bug"><b>Bug Group ${i+1}</b><div>${esc(r.root_cause||"Root cause identified.")}</div></div>`).join(""):`<div class="analysis-bug">${s.failed?"Failures detected.":"No failing tests detected."}</div>`}</div><button class="primary-btn analysis-modal-button" id="analysisDash">View Dashboard →</button></div>`;
  document.body.appendChild(o);$("analysisClose").onclick=dashboard;$("analysisDash").onclick=dashboard;
}

$("navDashboard").onclick=dashboard;
$("navInvestigate").onclick=()=>{active("navInvestigate");selectedRepository?runAnalysis():input.click()};
$("navRepositories").onclick=()=>{active("navRepositories");input.click()};
$("navHistory").onclick=showHistory;
$("navSettings").onclick=showSettings;

function showHistory(){
  active("navHistory");closeOverlays();const h=historyGet();const o=document.createElement("div");o.className="ui-modal-overlay";
  o.innerHTML=`<div class="ui-modal"><button class="modal-x" id="historyClose">×</button><div class="eyebrow">WORKSPACE</div><h2>Investigation History</h2><p>Every repository you have selected previously.</p><div class="history-list">${h.length?h.map(x=>`<div class="history-item"><b>📁 ${esc(x.name)}</b><span>${esc(x.selectedAt)}</span></div>`).join(""):`<div class="history-item">No repositories selected yet.</div>`}</div><button class="primary-btn" id="historyDash">← Back to Dashboard</button></div>`;
  document.body.appendChild(o);$("historyClose").onclick=dashboard;$("historyDash").onclick=dashboard;
}

function showSettings(){
  active("navSettings");closeOverlays();const o=document.createElement("div");o.className="ui-modal-overlay";
  o.innerHTML=`<div class="ui-modal"><button class="modal-x" id="settingsClose">×</button><div class="eyebrow">WORKSPACE</div><h2>Settings</h2><div class="setting-row"><div><b>Theme</b><small>Switch between light and dark mode.</small></div><button class="secondary-btn" id="settingsTheme">Toggle</button></div><div class="setting-row"><div><b>AI Engine</b><small>IBM Granite · Local Ollama</small></div><span>ONLINE</span></div><div class="setting-row"><div><b>Analysis Timeout</b><small>Maximum test execution time.</small></div><span>60 sec</span></div><div class="about-card"><h3>About ItDebugs</h3><p>ItDebugs is an agentic developer intelligence platform built for the IBM Bob 2.0 Hackathon. It analyzes repositories, investigates failing tests, identifies root causes and supports verified software repair.</p><p>Powered by IBM Granite and an autonomous multi-agent debugging pipeline.</p></div></div>`;
  document.body.appendChild(o);$("settingsClose").onclick=dashboard;$("settingsTheme").onclick=toggleTheme;
}

function toggleTheme(){document.body.classList.toggle("dark-mode");localStorage.setItem("itdebugs_dark",document.body.classList.contains("dark-mode"))}
if(localStorage.getItem("itdebugs_dark")==="true")document.body.classList.add("dark-mode");
$("themeToggle").onclick=toggleTheme;

$("profileButton").onclick=showProfile;
function showProfile(){
  const saved=localStorage.getItem("itdebugs_user");
  saved?profilePage(JSON.parse(saved)):authPage();
}
function profilePage(user){
  closeOverlays();const h=historyGet();const o=document.createElement("div");o.className="ui-modal-overlay";
  o.innerHTML=`<div class="profile-page"><button class="modal-x" id="profileClose">×</button><div class="eyebrow">ITDEBUGS PROFILE</div><div class="profile-header"><div class="profile-avatar-large">${esc((user.name||"D")[0].toUpperCase())}</div><div><div class="profile-name">${esc(user.name)}</div><div class="profile-email">${esc(user.email)}</div></div></div><div class="profile-section"><div class="eyebrow">ACCOUNT</div><div class="setting-row"><b>Name</b><span>${esc(user.name)}</span></div><div class="setting-row"><b>Email</b><span>${esc(user.email)}</span></div></div><div class="profile-section"><div class="eyebrow">SELECTED REPOSITORIES</div><div class="profile-repositories">${h.length?h.map(x=>`<div class="profile-repository">📁 ${esc(x.name)}</div>`).join(""):`<div class="profile-repository">No repositories selected yet.</div>`}</div></div><button class="primary-btn profile-dashboard" id="profileDash">← Back to Dashboard</button></div>`;
  document.body.appendChild(o);$("profileClose").onclick=dashboard;$("profileDash").onclick=dashboard;
}
function authPage(){
  closeOverlays();const o=document.createElement("div");o.className="ui-modal-overlay";
  o.innerHTML=`<div class="auth-page"><button class="modal-x" id="authClose">×</button><div class="auth-page-logo">&lt;/&gt;</div><div class="eyebrow">ITDEBUGS ACCOUNT</div><h2>Welcome back.</h2><p>Sign in or create your ItDebugs developer account.</p><div class="auth-tabs"><button class="auth-tab active" id="loginTab">Login</button><button class="auth-tab" id="registerTab">Register</button></div><input class="auth-form-input" id="authName" placeholder="Full name" style="display:none"><input class="auth-form-input" id="authEmail" type="email" placeholder="Email address"><input class="auth-form-input" id="authPassword" type="password" placeholder="Password"><div id="authMessage"></div><button class="primary-btn" id="authSubmit">Login →</button></div>`;
  document.body.appendChild(o);
  let mode="login";const name=$("authName"),email=$("authEmail"),pass=$("authPassword"),msg=$("authMessage"),submit=$("authSubmit");
  $("authClose").onclick=dashboard;
  $("loginTab").onclick=()=>{mode="login";$("loginTab").classList.add("active");$("registerTab").classList.remove("active");name.style.display="none";submit.textContent="Login →"};
  $("registerTab").onclick=()=>{mode="register";$("registerTab").classList.add("active");$("loginTab").classList.remove("active");name.style.display="block";submit.textContent="Create Account →"};
  submit.onclick=()=>{
    const n=name.value.trim(),e=email.value.trim(),p=pass.value;
    if(!e||!p||(mode==="register"&&!n)){msg.innerHTML=`<div class="auth-error">Please complete all fields.</div>`;return}
    if(mode==="register"){localStorage.setItem("itdebugs_user",JSON.stringify({name:n,email:e,password:p}));msg.innerHTML=`<div class="auth-success">Account created successfully.</div>`;setTimeout(()=>profilePage({name:n,email:e}),500);return}
    let s;try{s=JSON.parse(localStorage.getItem("itdebugs_user")||"null")}catch{s=null}
    if(!s||s.email!==e||s.password!==p){msg.innerHTML=`<div class="auth-error">Incorrect email or password.</div>`;return}
    profilePage(s);
  };
}

/* Quick actions */
$("runTestsButton").onclick=()=>selectedRepository?runAnalysis():input.click();
$("analyzeCodeButton").onclick=()=>selectedRepository?runAnalysis():input.click();
$("repairButton").onclick=()=>{
  if(!latestAnalysis){showSimple("Repair & Verify","Analyze a repository first. ItDebugs will then have an identified root cause to repair.");return}
  showSimple("Repair & Verify","Root cause identified. Use the backend repair loop to generate, approve, apply and verify the fix.");
};

/* Reaction Rush */
let reactionPhase="idle",reactionStart=null,reactionTimer=null,lastReaction=null,streak=0;
let reactionTimes=JSON.parse(localStorage.getItem("itdebugs_reaction_times")||"[]");
let best=Number(localStorage.getItem("itdebugs_reaction_best"))||null;
const avg=()=>reactionTimes.length?Math.round(reactionTimes.reduce((a,b)=>a+b,0)/reactionTimes.length):null;
function gameStats(){ $("gameScore").textContent=lastReaction?`${lastReaction} ms`:"—";$("gameBest").textContent=best?`${best} ms`:"—";$("gameAverage").textContent=avg()?`${avg()} ms`:"—";$("gameStreak").textContent=streak}
function resetGame(){clearTimeout(reactionTimer);reactionPhase="idle";reactionStart=null;$("reactionArea").classList.remove("waiting-state","ready-state");$("reactionStatus").textContent="READY?";$("reactionMessage").textContent="Hit START and wait for the signal.";$("reactionButton").textContent="START";$("reactionResults").classList.add("hidden");gameStats()}
function startGame(){clearTimeout(reactionTimer);reactionPhase="waiting";reactionStart=null;$("reactionArea").classList.remove("ready-state");$("reactionArea").classList.add("waiting-state");$("reactionStatus").textContent="WAIT...";$("reactionMessage").textContent="Wait for GREEN. Do not click yet.";$("reactionButton").textContent="WAIT";reactionTimer=setTimeout(()=>{reactionPhase="ready";reactionStart=performance.now();$("reactionArea").classList.remove("waiting-state");$("reactionArea").classList.add("ready-state");$("reactionStatus").textContent="CLICK!";$("reactionMessage").textContent="GO! GO! GO!";$("reactionButton").textContent="CLICK!"},1200+Math.random()*3500)}
function tooSoon(){clearTimeout(reactionTimer);reactionPhase="idle";streak=0;$("reactionArea").classList.remove("waiting-state","ready-state");$("reactionStatus").textContent="TOO EARLY!";$("reactionMessage").textContent="Wait for the green signal.";$("reactionResults").classList.remove("hidden");$("finalScore").textContent="Too Early!";$("finalDetails").textContent=`Best: ${best||"—"} ms · Average: ${avg()||"—"} ms · Streak: 0`;$("reactionButton").textContent="TRY AGAIN";gameStats()}
function finishGame(){if(reactionPhase!=="ready")return;lastReaction=Math.round(performance.now()-reactionStart);reactionTimes.push(lastReaction);if(reactionTimes.length>50)reactionTimes=reactionTimes.slice(-50);streak++;if(!best||lastReaction<best)best=lastReaction;localStorage.setItem("itdebugs_reaction_times",JSON.stringify(reactionTimes));localStorage.setItem("itdebugs_reaction_best",String(best));reactionPhase="idle";$("reactionArea").classList.remove("ready-state");$("reactionStatus").textContent=`${lastReaction} MS`;$("reactionMessage").textContent="Excellent reaction!";$("reactionResults").classList.remove("hidden");$("finalScore").textContent=`${lastReaction} ms`;$("finalDetails").textContent=`Average: ${avg()} ms · Best: ${best} ms · Streak: ${streak}`;$("reactionButton").textContent="TRY AGAIN";gameStats()}
$("reactionButton").onclick=()=>reactionPhase==="idle"?startGame():reactionPhase==="waiting"?tooSoon():finishGame();
$("restartGame").onclick=startGame;
$("closeBugHunter").onclick=()=>{clearTimeout(reactionTimer);$("reactionArea").classList.remove("waiting-state","ready-state");$("reactionStatus").textContent="READY?";$("reactionMessage").textContent="Hit START and wait for the signal.";$("reactionButton").textContent="START";$("reactionResults").classList.add("hidden");reactionPhase="idle"};
document.addEventListener("keydown",e=>{if(e.key==="Escape"){clearTimeout(reactionTimer);closeOverlays()}});

gameStats();
