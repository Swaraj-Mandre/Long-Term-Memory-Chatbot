/*
  Browser-side code for the interface.

  It does three things:
    - sends what the user types to the server
    - shows the reply
    - fills the right-hand panel with what the memory system did

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


/* ------------------------------------------------------------- transcript */

function addBubble(text, who) {
  const bubble = document.createElement("div");
  bubble.className = "bubble bubble-" + who;
  bubble.textContent = text;          // textContent, so no HTML is interpreted
  el("transcript").appendChild(bubble);
  scrollToBottom();
  return bubble;
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


/* ----------------------------------------------------------- sending text */

async function sendMessage(event) {
  event.preventDefault();

  const input = el("messageInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";

  // "/forget <topic>" is handled separately - it deletes rather than chats.
  if (message.toLowerCase().startsWith("/forget ")) {
    return forgetTopic(message.slice(8).trim(), message);
  }

  addBubble(message, "user");

  // The bubble starts empty and fills up as the reply arrives.
  const bubble = addBubble("thinking...", "bot");
  bubble.classList.add("waiting");
  el("btnSend").disabled = true;

  // Set to true by the first piece of real text, which is when we clear the
  // "thinking..." placeholder out of the bubble.
  let replyStarted = false;
  let text = "";

  function addText(piece) {
    if (!replyStarted) {
      replyStarted = true;
      bubble.classList.remove("waiting");
      bubble.classList.add("streaming");
      bubble.textContent = "";
    }
    text += piece;
    bubble.textContent = text;
    scrollToBottom();
  }

  // One event from the server. See send_stream in chat_engine.py for the list.
  function handleEvent(event) {
    if (event.type === "context") {
      // Memory results arrive before the reply is written, so the panel on
      // the right fills in while the model is still thinking.
      renderRetrieved(event.details.memories_used);
      renderContradictions(event.details.contradictions);
    } else if (event.type === "token") {
      addText(event.text);
    } else if (event.type === "done") {
      showTurnDetails(event.details);
    } else if (event.type === "error") {
      addText("\n\nError: " + event.error);
    }
    // "thinking" needs no action. The placeholder is already showing.
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
    bubble.classList.remove("waiting", "streaming");
    if (!text) bubble.textContent = "No reply came back.";
    el("btnSend").disabled = false;
    loadMemories();
    input.focus();
  }
}


/* ------------------------------------------------- right-hand side panel */

function showTurnDetails(details) {
  if (!details) return;

  renderRetrieved(details.memories_used);
  renderContradictions(details.contradictions);
  renderStatistics(details.summary);
}

// Which memories were used for this message, and how strongly each matched.
function renderRetrieved(memories) {
  const container = el("retrievedList");

  if (!memories || memories.length === 0) {
    container.innerHTML =
      '<p class="empty-note">Nothing scored above the similarity threshold.</p>';
    return;
  }

  container.innerHTML = memories.map(function (memory) {
    const isFact = memory.type === "semantic";
    const barWidth = Math.max(3, Math.min(100, memory.similarity * 100));

    return `
      <div class="card ${isFact ? "card-fact" : "card-message"}">
        <div class="card-text">${escapeHtml(memory.text)}</div>
        <div class="score-bar">
          <span class="score-fill" style="width:${barWidth}%"></span>
        </div>
        <div class="card-meta">
          ${memory.id} &middot; ${isFact ? "fact" : "message"} &middot;
          similarity ${memory.similarity} &middot;
          recency ${memory.recency} &middot;
          final ${memory.score}
        </div>
      </div>`;
  }).join("");
}

// Facts that replaced an earlier version. New entries are added at the top and
// earlier ones are kept, so the whole demo's history stays visible.
function renderContradictions(contradictions) {
  if (!contradictions || contradictions.length === 0) return;

  const container = el("contradictionList");

  // Clear the placeholder the first time something real arrives.
  const placeholder = container.querySelector(".empty-note");
  if (placeholder) placeholder.remove();

  const html = contradictions.map(function (item) {
    return `
      <div class="contradiction">
        <div class="contradiction-head">${escapeHtml(item.key)} updated</div>
        <span class="old-value">${escapeHtml(item.old_value)}</span>
        &rarr;
        <span class="new-value">${escapeHtml(item.new_value)}</span>
        <div class="card-meta">
          ${item.old_id} marked superseded &middot; ${item.new_id} now active
        </div>
      </div>`;
  }).join("");

  container.insertAdjacentHTML("afterbegin", html);
}

function renderStatistics(summary) {
  if (!summary) return;

  const tiles = [
    ["facts",      "Facts"],
    ["messages",   "Messages"],
    ["superseded", "Replaced"],
    ["pruned",     "Pruned"],
    ["sessions",   "Sessions"],
    ["total",      "Total"],
  ];

  el("statGrid").innerHTML = tiles.map(function (pair) {
    const value = summary[pair[0]] || 0;
    return `<div class="stat">
              <span class="stat-value">${value}</span>
              <span class="stat-label">${pair[1]}</span>
            </div>`;
  }).join("");
}


/* --------------------------------------------------- the full memory list */

async function loadMemories() {
  const response = await fetch("/api/memories");
  const data = await response.json();

  renderStatistics(data.summary);
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
  addBubble(originalText, "user");

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
  renderStatistics(data.summary);
  loadMemories();
}

async function startNewSession() {
  // The server decides the name. It can see which sessions already exist, so
  // the numbering runs session-1, session-2, session-3 in order.
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
    "assistant recalls from here came out of the database."
  );
}

async function resetEverything() {
  const confirmed = confirm(
    "Permanently delete every stored memory?\n\nThis cannot be undone."
  );
  if (!confirmed) return;

  const response = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await response.json();

  el("transcript").innerHTML = "";
  el("contradictionList").innerHTML =
    '<p class="empty-note">No contradictions yet.</p>';
  el("retrievedList").innerHTML =
    '<p class="empty-note">Nothing retrieved yet.</p>';
  addNotice("Deleted " + data.deleted + " memories. Starting fresh.");
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


/* ------------------------------------------------------------- start-up */

// Fill the panel with the current state as soon as the page opens.
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
