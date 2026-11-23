"use strict";
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
const $ = id => document.getElementById(id);
function notice(message, error = false) { $("notice").textContent = message; $("notice").classList.toggle("error", error); }
function details(value) { $("details").textContent = JSON.stringify(value, null, 2); }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...options.headers, Authorization: "Bearer " + token}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
function item(title, subtitle, action, callback) {
  const row = document.createElement("div"); row.className = "item";
  const text = document.createElement("div"), name = document.createElement("strong"), meta = document.createElement("small");
  name.textContent = title; meta.textContent = subtitle; text.append(name, meta);
  const button = document.createElement("button"); button.className = "small"; button.textContent = action;
  button.onclick = async () => { try { button.disabled = true; await callback(); } catch (error) { notice(error.message, true); } finally { button.disabled = false; } };
  row.append(text, button); return row;
}
async function refresh() {
  const [sessions, proposals, summary] = await Promise.all([api("/api/sessions"), api("/api/proposals"), api("/api/summary")]);
  $("session-count").textContent = summary.session_count ?? sessions.length;
  $("proposal-count").textContent = proposals.length;
  $("evidence-count").textContent = summary.evaluations ?? summary.evaluation_count ?? 0;
  $("sessions").replaceChildren();
  if (!sessions.length) $("sessions").textContent = "Your first session starts the evidence trail.";
  for (const session of sessions) $("sessions").append(item(session.source_name || session.id.slice(0, 12), `${session.project} · ${session.source_format} · ${session.events_count} events · ${session.parse_status}`, "Inspect", async () => { details(await api("/api/analyze/" + session.id, {method: "POST", body: ""})); }));
  $("proposals").replaceChildren();
  if (!proposals.length) $("proposals").textContent = "No candidate experiments yet. No detected signal does not prove a session was efficient.";
  for (const proposal of proposals) {
    const states = [...new Set((proposal.scoped_evidence || []).map(e => e.state))];
    const state = states.length ? states.join(" / ") + " (scoped)" : proposal.status || "proposed";
    $("proposals").append(item(proposal.title || proposal.hypothesis || proposal.id, `${state} · ${proposal.scope?.project || "scoped experiment"}`, "Evidence", async () => details(proposal)));
  }
}
$("upload-form").onsubmit = async event => {
  event.preventDefault(); const button = $("upload-button"); button.disabled = true;
  try {
    const files = [...$("transcript").files];
    for (const file of files) {
      if (file.size > 32 * 1024 * 1024) throw new Error(file.name + " exceeds 32 MiB. Import it with the CLI.");
      notice("Archiving and analyzing " + file.name + "...");
      details(await api("/api/ingest", {method: "POST", headers: {"Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name), "X-Project": encodeURIComponent($("project").value), "X-Format": $("format").value}, body: file}));
    }
    notice(files.length + " file(s) archived. Candidate explanations still require evaluation."); await refresh();
  } catch (error) { notice(error.message, true); } finally { button.disabled = false; }
};
$("evaluate-form").onsubmit = async event => {
  event.preventDefault(); const button = event.currentTarget.querySelector("button"); button.disabled = true;
  try {
    const file = $("evaluation").files[0];
    if (file.size > 8 * 1024 * 1024) throw new Error("Evaluation report exceeds 8 MiB.");
    details(await api("/api/evaluate", {method: "POST", headers: {"Content-Type": "application/json"}, body: file}));
    notice("Experiment report recorded. Recommendations retain its scope and reported-evidence status."); await refresh();
  } catch (error) { notice(error.message, true); } finally { button.disabled = false; }
};
$("refresh").onclick = () => refresh().catch(error => notice(error.message, true));
$("matrix").onclick = () => api("/api/matrix").then(details).catch(error => notice(error.message, true));
refresh().catch(error => notice(error.message, true));
