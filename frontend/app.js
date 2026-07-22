// En local (127.0.0.1 ou localhost), on tape le backend local.
// Une fois déployé, remplace l'URL ci-dessous par celle de ton backend Render
// (ex: "https://soren-backend.onrender.com") — un seul endroit à changer,
// le frontend bascule automatiquement selon où il tourne.
const IS_LOCAL = ["localhost", "127.0.0.1"].includes(window.location.hostname);
const API_URL = IS_LOCAL
  ? "http://127.0.0.1:8000"
  : "https://soren-eulu.onrender.com"; // <-- à remplacer une fois déployé sur Render

const STATUS_CHECK_INTERVAL_MS = 15000;
const LOCAL_LIST_KEY = "soren_conversations";
const CURRENT_SESSION_KEY = "soren_current_session";

const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const clearBtn = document.getElementById("clear-btn");
const orb = document.getElementById("orb");
const tagline = document.getElementById("tagline");
const typingRow = document.getElementById("typing-row");

const historyBtn = document.getElementById("history-btn");
const historyCloseBtn = document.getElementById("history-close-btn");
const historyPanel = document.getElementById("history-panel");
const historyBackdrop = document.getElementById("history-backdrop");
const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");

let currentSessionId = null;

// ============================================================
// Historique local (localStorage) — la liste des conversations de CE
// navigateur uniquement. Le serveur ne liste jamais "toutes les
// conversations" (voir la note de confidentialité dans db.py côté
// backend) : chaque client ne connaît que ses propres identifiants.
// ============================================================
function getLocalList() {
  try {
    const raw = localStorage.getItem(LOCAL_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_) {
    return [];
  }
}

function saveLocalList(list) {
  localStorage.setItem(LOCAL_LIST_KEY, JSON.stringify(list));
}

function upsertLocalEntry(id, title) {
  const list = getLocalList();
  const now = new Date().toISOString();
  const existing = list.find((c) => c.id === id);
  if (existing) {
    existing.title = title;
    existing.updatedAt = now;
  } else {
    list.push({ id, title, updatedAt: now });
  }
  saveLocalList(list);
  renderHistoryList();
}

function removeLocalEntry(id) {
  const list = getLocalList().filter((c) => c.id !== id);
  saveLocalList(list);
  renderHistoryList();
}

function getCurrentSessionId() {
  let id = localStorage.getItem(CURRENT_SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(CURRENT_SESSION_KEY, id);
  }
  return id;
}

function setCurrentSessionId(id) {
  currentSessionId = id;
  localStorage.setItem(CURRENT_SESSION_KEY, id);
}

function relativeTime(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  const j = Math.floor(h / 24);
  if (j < 7) return `il y a ${j} j`;
  return new Date(isoString).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

function renderHistoryList() {
  const list = getLocalList().sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
  historyList.querySelectorAll(".history-item").forEach((el) => el.remove());
  historyEmpty.hidden = list.length > 0;

  for (const conv of list) {
    const item = document.createElement("div");
    item.className = "history-item" + (conv.id === currentSessionId ? " active" : "");

    const info = document.createElement("div");
    info.className = "history-item-info";
    const title = document.createElement("span");
    title.className = "history-item-title";
    title.textContent = conv.title || "Nouvelle conversation";
    const date = document.createElement("span");
    date.className = "history-item-date";
    date.textContent = relativeTime(conv.updatedAt);
    info.appendChild(title);
    info.appendChild(date);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "history-item-delete";
    deleteBtn.type = "button";
    deleteBtn.title = "Supprimer cette conversation";
    deleteBtn.innerHTML =
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(conv.id);
    });

    item.appendChild(info);
    item.appendChild(deleteBtn);
    item.addEventListener("click", () => switchToConversation(conv.id));
    historyList.appendChild(item);
  }
}

function openHistoryPanel() {
  renderHistoryList();
  historyPanel.classList.add("open");
  historyBackdrop.classList.add("open");
}

function closeHistoryPanel() {
  historyPanel.classList.remove("open");
  historyBackdrop.classList.remove("open");
}

historyBtn.addEventListener("click", openHistoryPanel);
historyCloseBtn.addEventListener("click", closeHistoryPanel);
historyBackdrop.addEventListener("click", closeHistoryPanel);

// ============================================================
// Rendu des messages (identique à avant : blocs de code, gras, inline code)
// ============================================================
function timestamp(isoString) {
  const d = isoString ? new Date(isoString) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineFormat(str) {
  let out = escapeHtml(str);
  out = out.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return out;
}

function appendTextSegment(container, str) {
  const trimmed = str.trim();
  if (!trimmed) return;
  const div = document.createElement("div");
  div.className = "text-segment";
  div.innerHTML = inlineFormat(trimmed);
  container.appendChild(div);
}

function appendCodeBlock(container, lang, code) {
  const block = document.createElement("div");
  block.className = "code-block";

  const header = document.createElement("div");
  header.className = "code-block-header";

  const langLabel = document.createElement("span");
  langLabel.className = "code-lang";
  langLabel.textContent = lang || "text";

  const copyBtn = document.createElement("button");
  copyBtn.className = "code-copy-btn";
  copyBtn.type = "button";
  copyBtn.textContent = "copier";
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(code.trim()).then(() => {
      copyBtn.textContent = "copié";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.textContent = "copier";
        copyBtn.classList.remove("copied");
      }, 1400);
    });
  });

  header.appendChild(langLabel);
  header.appendChild(copyBtn);

  const pre = document.createElement("pre");
  const codeEl = document.createElement("code");
  if (lang) codeEl.className = `language-${lang}`;
  codeEl.textContent = code.trim();
  pre.appendChild(codeEl);

  block.appendChild(header);
  block.appendChild(pre);
  container.appendChild(block);

  if (window.hljs) {
    try {
      window.hljs.highlightElement(codeEl);
    } catch (_) {
      // langage non reconnu par hljs — le code reste affiché, juste sans coloration
    }
  }
}

function renderMessageContent(container, text) {
  const codeBlockRegex = /```(\w+)?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let hasCode = false;
  let match;

  while ((match = codeBlockRegex.exec(text)) !== null) {
    hasCode = true;
    const before = text.slice(lastIndex, match.index);
    appendTextSegment(container, before);
    appendCodeBlock(container, (match[1] || "").toLowerCase(), match[2]);
    lastIndex = codeBlockRegex.lastIndex;
  }

  const after = text.slice(lastIndex);
  if (hasCode) {
    appendTextSegment(container, after);
  } else {
    appendTextSegment(container, text);
  }

  return hasCode;
}

function addMessage(role, text, opts = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (opts.pending) bubble.classList.add("pending");
  if (opts.error) bubble.classList.add("error");
  if (opts.rateLimited) bubble.classList.add("rate-limited");

  let hasCode = false;
  if (role === "assistant" && !opts.pending && !opts.error && !opts.rateLimited) {
    hasCode = renderMessageContent(bubble, text);
  } else {
    bubble.textContent = text;
  }

  if (role === "assistant" && !opts.pending && !hasCode) {
    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.type = "button";
    copyBtn.textContent = "copier";
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.textContent = "copié";
        copyBtn.classList.add("copied");
        setTimeout(() => {
          copyBtn.textContent = "copier";
          copyBtn.classList.remove("copied");
        }, 1400);
      });
    });
    bubble.appendChild(copyBtn);
  }

  const time = document.createElement("span");
  time.className = "timestamp";
  time.textContent = timestamp(opts.createdAt);

  wrapper.appendChild(bubble);
  wrapper.appendChild(time);
  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return bubble;
}

function showWelcomeMessage() {
  chatWindow.innerHTML = "";
  addMessage("assistant", "Bon. Je t'écoute. Essaie d'être clair, pour une fois.");
}

function setThinking(isThinking) {
  typingRow.hidden = !isThinking;
  orb.classList.toggle("thinking", isThinking);
  if (isThinking) chatWindow.scrollTop = chatWindow.scrollHeight;
}

// ============================================================
// Chargement / changement de conversation
// ============================================================
async function loadConversation(sessionId) {
  chatWindow.innerHTML = "";
  try {
    const res = await fetch(`${API_URL}/conversations/${sessionId}`);
    if (res.status === 404) {
      // Conversation pas encore commencée côté serveur (nouvelle session) : écran d'accueil.
      showWelcomeMessage();
      return;
    }
    if (!res.ok) throw new Error(`Erreur serveur (${res.status})`);

    const conv = await res.json();
    if (conv.messages.length === 0) {
      showWelcomeMessage();
      return;
    }
    for (const m of conv.messages) {
      addMessage(m.role, m.content, { createdAt: m.created_at });
    }
    upsertLocalEntry(sessionId, conv.title);
  } catch (err) {
    showWelcomeMessage();
    addMessage(
      "assistant",
      `Erreur au chargement de la conversation : ${err.message}. Vérifie que le backend tourne sur ${API_URL}.`,
      { error: true }
    );
  }
}

async function switchToConversation(sessionId) {
  setCurrentSessionId(sessionId);
  closeHistoryPanel();
  await loadConversation(sessionId);
  renderHistoryList();
}

function startNewConversation() {
  setCurrentSessionId(crypto.randomUUID());
  closeHistoryPanel();
  showWelcomeMessage();
  renderHistoryList();
  input.focus();
}

async function deleteConversation(sessionId) {
  try {
    await fetch(`${API_URL}/conversations/${sessionId}`, { method: "DELETE" });
  } catch (_) {
    // même si l'appel serveur échoue, on retire quand même de la liste locale
  }
  removeLocalEntry(sessionId);

  if (sessionId === currentSessionId) {
    startNewConversation();
  }
}

// ============================================================
// Envoi de message
// ============================================================
async function sendMessage(message) {
  addMessage("user", message);
  setThinking(true);

  sendBtn.disabled = true;
  input.disabled = true;

  try {
    const res = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: currentSessionId }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const error = new Error(err.detail || `Erreur serveur (${res.status})`);
      error.status = res.status;
      throw error;
    }

    const data = await res.json();
    setThinking(false);
    addMessage("assistant", data.reply);
    upsertLocalEntry(currentSessionId, data.title);
  } catch (err) {
    setThinking(false);
    if (err.status === 429) {
      addMessage("assistant", err.message, { rateLimited: true });
    } else {
      addMessage(
        "assistant",
        `Erreur : ${err.message}. Vérifie que le backend tourne sur ${API_URL}.`,
        { error: true }
      );
    }
  } finally {
    sendBtn.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

// --- Auto-resize du textarea ---
function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autoResize);

// --- Entrée pour envoyer, Maj+Entrée pour nouvelle ligne ---
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  autoResize();
  sendMessage(message);
});

clearBtn.addEventListener("click", startNewConversation);

// --- Statut de connexion en direct, reflété par l'orbe ---
async function checkBackendStatus() {
  try {
    const res = await fetch(`${API_URL}/`, { method: "GET" });
    if (!res.ok) throw new Error();
    orb.classList.remove("offline");
    orb.classList.add("online");
    tagline.textContent = "plusieurs IA, une seule voix";
  } catch (_) {
    orb.classList.remove("online");
    orb.classList.add("offline");
    tagline.textContent = "backend injoignable";
  }
}

checkBackendStatus();
setInterval(checkBackendStatus, STATUS_CHECK_INTERVAL_MS);

// ============================================================
// Initialisation : reprend la conversation en cours (si elle existe déjà
// côté serveur) ou affiche l'écran d'accueil.
// ============================================================
currentSessionId = getCurrentSessionId();
loadConversation(currentSessionId);
renderHistoryList();
input.focus();
