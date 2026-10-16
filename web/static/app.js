/*
  Browser-side code for the interface.

  It does four things:
    - sends what the user types to the server
    - shows the reply as it streams in
    - fills the "Why this reply" panel: emotion, tone, memory
    - draws the mood timeline and the memory store

  Written as plain JavaScript with no framework, so there is nothing between
  what is written here and what the browser runs.
*/

// Short helper for finding an element by id.
const el = (id) => document.getElementById(id);

// Escape text before putting it into HTML, so a message containing < or >
// cannot break the page or inject markup.
function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// One text face per emotion, typed with plain keyboard characters.
// The colours live in style.css (--joy, --sadness...).
const FACE = {
  joy:      "^_^",    // smiling eyes
  sadness:  "T_T",    // tears running down
  anger:    ">_<",    // eyes squeezed shut in frustration
  fear:     "O_O",    // eyes wide open
  surprise: "o_O",    // one eye wider than the other
  disgust:  "=_=",    // fed up
  neutral:  "-_-",    // flat, no reaction
};

function percent(value) {
  return Math.round((value || 0) * 100) + "%";
}


/* ------------------------------------------------------------- transcript */

// Each message is a row holding the bubble and a small tag underneath it.
// The tag is filled in later (the emotion, or the tone used).
function addMessage(text, who) {
  const welcome = el("welcome");
  if (welcome) welcome.remove();

  const row = document.createElement("div");
  row.className = "msg msg-" + who;

  const bubble = document.createElement("div");
  bubble.className = "bubble bubble-" + who;
  bubble.textContent = text;          // textContent, so no HTML is interpreted

  const tag = document.createElement("div");
  tag.className = "msg-tag";

  row.appendChild(bubble);
  row.appendChild(tag);
  el("transcript").appendChild(row);
  scrollToBottom();
  return { row: row, bubble: bubble, tag: tag };
}

function setTag(tag, html) {
  tag.innerHTML = html;
  tag.classList.add("shown");
}

function addNotice(text) {
  const notice = document.createElement("div");
  notice.className = "notice";
  notice.textContent = text;
  el("transcript").appendChild(notice);
  scrollToBottom();
}

function scrollToBottom() {
  const transcript = el("transcript");
  transcript.scrollTop = transcript.scrollHeight;
}

// In a crisis the reply is not a normal chat bubble. It is a calm card with
// the helpline numbers large enough to read at a glance.
function showSafetyCard(bubble, helplines) {
  bubble.className = "bubble bubble-safety";
  bubble.innerHTML = `
    <div class="safety-title">You don't have to go through this alone.</div>
    <p>I'm really sorry you're feeling this way, and I'm glad you told me.
       Please talk to someone who can help right now:</p>
    ${helplines.map((h) => `
      <div class="helpline">
        <span class="helpline-number">${escapeHtml(h.number)}</span>
        <span><b>${escapeHtml(h.name)}</b><br><small>${escapeHtml(h.note)}</small></span>
      </div>`).join("")}
    <p class="safety-foot">I'm still here if you want to keep talking.</p>`;
}


/* ----------------------------------------------------------- sending text */

async function sendMessage(event) {
  if (event) event.preventDefault();

  const input = el("messageInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";

  // "/forget <topic>" is handled separately - it deletes rather than chats.
  if (message.toLowerCase().startsWith("/forget ")) {
    return forgetTopic(message.slice(8).trim(), message);
  }

  const user = addMessage(message, "user");

  // The bot bubble starts with a placeholder and fills up as the reply arrives.
  const bot = addMessage("reading your message...", "bot");
  bot.bubble.classList.add("waiting");
  el("btnSend").disabled = true;
  showPanelLoading();

  let replyStarted = false;
  let isCrisis = false;
  let text = "";

  function addText(piece) {
    if (isCrisis) return;             // the safety card is already showing
    if (!replyStarted) {
      replyStarted = true;
      bot.bubble.classList.remove("waiting");
      bot.bubble.classList.add("streaming");
      bot.bubble.textContent = "";
    }
    text += piece;
    bot.bubble.textContent = text;
    scrollToBottom();
  }

  // One event from the server. See send_stream in chat_engine.py for the list.
  function handleEvent(event) {
    if (event.type === "context") {
      // The analysis arrives before the reply is written, so the user's
      // emotion and the chosen tone appear while the model is still thinking.
      const d = event.details;
      const mood = d.mood;
      // Only a coloured dot. A real user should not see a label of how
      // they feel; the full reading is in the side panel for the demo.
      setTag(user.tag, `<span class="dot dot-${mood.emotion}"></span>`);
      setMoodLine(mood.emotion);
      renderPanel(d);

      if (d.safety.level === 2) {
        isCrisis = true;
        showSafetyCard(bot.bubble, d.helplines);
      } else {
        bot.bubble.textContent = "thinking...";
      }
    } else if (event.type === "token") {
      addText(event.text);
    } else if (event.type === "done") {
      text = text || event.reply;
      const tone = event.details.tone;
      if (tone && !isCrisis) setTag(bot.tag, "tone: " + escapeHtml(tone.name));
      if (isCrisis) setTag(bot.tag, "fixed safe reply &middot; no AI generation");
    } else if (event.type === "error") {
      addText("\n\nError: " + event.error);
    }
  }

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message }),
    });

    if (!response.ok || !response.body) {
      throw new Error("server returned status " + response.status);
    }

    // Read the response as it arrives instead of waiting for all of it.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;

      // A read can end in the middle of an event, so we collect text in a
      // buffer and only handle the events that are complete. A blank line
      // marks the end of an event.
      buffer += decoder.decode(chunk.value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      parts.forEach(function (part) {
        if (!part.startsWith("data: ")) return;
        handleEvent(JSON.parse(part.slice(6)));
      });
    }
  } catch (error) {
    addText("\n\nCould not reach the server: " + error);
  } finally {
    bot.bubble.classList.remove("waiting", "streaming");
    if (!text && !isCrisis) bot.bubble.textContent = "No reply came back.";
    el("btnSend").disabled = false;
    loadMemories();
    input.focus();
  }
}


/* ------------------------------------------- the "Why this reply" panel */

function showPanelLoading() {
  ["emotionBox", "toneBox", "memoryBox"].forEach(function (id) {
    el(id).innerHTML = '<div class="skeleton"></div>';
  });
}

function renderPanel(details) {
  renderEmotion(details.mood);
  renderTone(details.tone, details.safety);
  renderMemory(details);

  // Let the three steps appear one after another, in pipeline order.
  ["stepEmotion", "stepTone", "stepMemory"].forEach(function (id, i) {
    const step = el(id);
    step.classList.remove("reveal");
    void step.offsetWidth;            // restart the animation
    step.style.animationDelay = (i * 120) + "ms";
    step.classList.add("reveal");
  });
}

// Step 1: the final emotion, and what each of the two readers said.
function renderEmotion(mood) {
  const verdicts = {
    "agree":      ["ok",   "Both agree"],
    "disagree":   ["warn", "Disagree &rarr; LLM used (reads context)"],
    "local only": ["info", "Local model only (LLM unavailable)"],
    "llm only":   ["info", "LLM only (local model unavailable)"],
    "llm skipped": ["danger", "LLM skipped: crisis rules took over"],
  };
  const verdict = verdicts[mood.agreement] || ["info", "No signal"];
  const local = mood.local || {};

  el("emotionBox").innerHTML = `
    <div class="emotion-main">
      <span class="emotion-face face-${mood.emotion}">${FACE[mood.emotion] || "-_-"}</span>
      <div class="emotion-text">
        <div class="emotion-label">${escapeHtml(mood.emotion)}</div>
        <div class="bar"><span class="bar-fill fill-${mood.emotion}"
             style="width:${percent(mood.confidence)}"></span></div>
        <div class="muted">confidence ${percent(mood.confidence)}</div>
      </div>
    </div>
    <div class="readers">
      <div class="reader"><span>Local model</span>
        <b>${escapeHtml(local.label || "-")}</b>
        <span class="muted">${local.label ? percent(local.score) : ""}</span></div>
      <div class="reader"><span>LLM</span>
        <b>${escapeHtml(mood.llm || "-")}</b><span></span></div>
    </div>
    <div class="pill pill-${verdict[0]}">${verdict[1]}</div>`;
}

// Step 2: the tone and the safety level that shaped it.
function renderTone(tone, safety) {
  const levelClass = ["ok", "warn", "danger"][safety.level];
  el("toneBox").innerHTML = `
    <div class="tone-name">${escapeHtml(tone.name)}</div>
    <p class="tone-instruction">&ldquo;${escapeHtml(tone.instruction)}&rdquo;</p>
    <div class="pill pill-${levelClass}">
      Safety: ${escapeHtml(safety.name)} &middot; ${escapeHtml(safety.reason)}
    </div>`;
}

// Step 3: memories retrieved for this message, plus any fact that changed.
function renderMemory(details) {
  const box = el("memoryBox");

  if (details.safety.level === 2) {
    box.innerHTML = '<p class="empty-note">Skipped. A crisis message is not ' +
                    'stored or searched.</p>';
    return;
  }

  let html = "";

  (details.contradictions || []).forEach(function (item) {
    html += `
      <div class="change">
        ${escapeHtml(item.key)}:
        <span class="old-value">${escapeHtml(item.old_value)}</span> &rarr;
        <b>${escapeHtml(item.new_value)}</b>
      </div>`;
  });

  (details.facts_found || []).forEach(function (fact) {
    html += `<div class="memory-row new-fact">
               <span>+ learned <b>${escapeHtml(fact.key)}: ${escapeHtml(fact.value)}</b></span>
             </div>`;
  });

  (details.memories_used || []).forEach(function (memory) {
    html += `
      <div class="memory-row">
        <span>${escapeHtml(memory.text)}</span>
        <span class="muted">${memory.similarity.toFixed(2)}</span>
      </div>`;
  });

  box.innerHTML = html || '<p class="empty-note">Nothing relevant in memory yet.</p>';
}

// The thin coloured line under the header follows the current emotion.
function setMoodLine(emotion) {
  el("moodLine").style.background = "var(--" + emotion + ")";
}


/* --------------------------------------------------------- mood timeline */

function renderTimeline(moods) {
  const box = el("timeline");
  if (!moods || moods.length === 0) {
    box.innerHTML = '<p class="empty-note">No moods recorded yet.</p>';
    return;
  }

  let html = "";
  let lastSession = null;

  moods.forEach(function (m, i) {
    // A small gap and label where a new session begins.
    if (m.session_id !== lastSession) {
      html += `<span class="session-mark">${escapeHtml(m.session_id.replace("session-", "S"))}</span>`;
      lastSession = m.session_id;
    }
    const tip = m.time.slice(0, 16).replace("T", " ") + " - " + m.emotion +
                (m.reason ? " (" + m.reason + ")" : "");
    let flags = m.safety_level === 2 ? " dot-crisis" : "";
    if (i === moods.length - 1) flags += " dot-new";   // only the newest one pops in
    html += `<span class="dot dot-big dot-${m.emotion}${flags}" title="${escapeHtml(tip)}"></span>`;
  });

  box.innerHTML = html;
}


/* --------------------------------------------------- the full memory list */

async function loadMemories() {
  const response = await fetch("/api/memories");
  const data = await response.json();

  renderTimeline(data.moods);
  el("storeCount").textContent = data.memories.length + " records";

  const container = el("memoryList");
  if (data.memories.length === 0) {
    container.innerHTML = '<p class="empty-note">The memory store is empty.</p>';
    return;
  }

  container.innerHTML = data.memories.map(function (memory) {
    const isFact = memory.type === "semantic";
    const privacy = memory.privacy_filtered
      ? ` &middot; <span class="privacy-flag">private data removed</span>`
      : "";

    return `
      <div class="card ${isFact ? "card-fact" : "card-message"}">
        <div class="card-text">
          ${escapeHtml(memory.text)}
          <span class="tag tag-${memory.status}">${memory.status}</span>
        </div>
        <div class="card-meta">
          ${memory.id} &middot; ${memory.session_id} &middot;
          used ${memory.times_retrieved}x${privacy}
        </div>
      </div>`;
  }).join("");
}


/* ------------------------------------------------------------- controls */

async function forgetTopic(topic, originalText) {
  addMessage(originalText, "user");

  const response = await fetch("/api/forget", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: topic }),
  });
  const data = await response.json();

  addNotice(
    "Deleted " + data.removed.length + " record(s) about \"" + topic +
    "\". This is a permanent removal, not a replacement."
  );
  loadMemories();
}

async function startNewSession() {
  // The server decides the name, because only it can see which sessions
  // already exist.
  const response = await fetch("/api/session/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await response.json();

  el("chipSession").textContent = data.session_id;
  el("transcript").innerHTML = "";
  addNotice(
    "Started " + data.session_id + ". Recent messages cleared - anything the " +
    "bot remembers from here, including how you felt, came from the database."
  );
}

async function resetEverything() {
  const confirmed = confirm(
    "Permanently delete every stored memory and mood?\n\nThis cannot be undone."
  );
  if (!confirmed) return;

  const response = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await response.json();

  el("transcript").innerHTML = "";
  el("chipSession").textContent = "session-1";
  el("emotionBox").innerHTML = '<p class="empty-note">Send a message to see how it is read.</p>';
  el("toneBox").innerHTML = '<p class="empty-note">Waiting for a message.</p>';
  el("memoryBox").innerHTML = '<p class="empty-note">Waiting for a message.</p>';
  el("moodLine").style.background = "";
  addNotice("Deleted " + data.deleted + " memories and the mood history. Starting fresh.");
  loadMemories();
}


/* ------------------------------------------------------------- start-up */

el("composer").addEventListener("submit", sendMessage);

// Send on Enter. A form normally does this by itself, but doing it explicitly
// means it cannot fail, which matters when the app is being demonstrated.
el("messageInput").addEventListener("keydown", function (event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(event);
  }
});

// The suggestion chips on the welcome screen send their text as a message.
document.querySelectorAll(".suggestion").forEach(function (chip) {
  chip.addEventListener("click", function () {
    el("messageInput").value = chip.dataset.text;
    sendMessage();
  });
});

el("btnNewSession").addEventListener("click", startNewSession);
el("btnReset").addEventListener("click", resetEverything);


/* ---------------------------------------------------- tech stack dropdown */

// Opens on click, and closes again when the pointer leaves it, so it never
// stays in the way while presenting.
function setStackOpen(open) {
  el("stackToggle").setAttribute("aria-expanded", open ? "true" : "false");
  el("stackPanel").hidden = !open;
}

function fillStackPanel(stack) {
  el("stackPanel").innerHTML = stack.map(function (item) {
    return `
      <div class="stack-row">
        <span class="stack-part">${escapeHtml(item.part)}</span>
        <span class="stack-value">${escapeHtml(item.value)}</span>
        <span class="stack-purpose">${escapeHtml(item.purpose)}</span>
      </div>`;
  }).join("");
}

el("stackToggle").addEventListener("click", function () {
  const isOpen = el("stackToggle").getAttribute("aria-expanded") === "true";
  setStackOpen(!isOpen);
});

el("stackMenu").addEventListener("mouseleave", function () {
  setStackOpen(false);
});

// Fill in the current state as soon as the page opens.
fetch("/api/status")
  .then((response) => response.json())
  .then(function (status) {
    el("chipSession").textContent = status.session_id;
    fillStackPanel(status.stack);

    // If there is no key the bot cannot reply, so say so plainly rather than
    // letting it look broken.
    if (!status.api_key_present) {
      el("stackToggle").firstChild.textContent = "no API key ";
    }
  });

loadMemories();
