/**
 * Widget de chat pentru Clinica Primera.
 *
 * JavaScript vanilla, fără build step, montat în shadow DOM: stilurile temei
 * Squarespace nu intră înăuntru, iar ale noastre nu ies afară.
 *
 * Instalare (Squarespace → Settings → Advanced → Code Injection → Footer):
 *   <script src="https://BACKEND/widget/widget.js"
 *           data-api-url="https://BACKEND"
 *           data-title="Asistent Clinica Primera"
 *           data-lang="ro" data-accent="#0f766e" defer></script>
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  // Lipsă `data-api-url` ⇒ backend-ul e acolo de unde a venit scriptul.
  // Backend-ul își servește singur widget-ul, deci asta e mereu corect — și
  // evită capcana unui `localhost` scris fix, care pe telefon ar însemna
  // telefonul, nu calculatorul care rulează serverul.
  function defaultApiUrl() {
    try {
      return new URL(script.src, location.href).origin;
    } catch (e) {
      return "";
    }
  }

  // Valorile implicite sunt tokenurile de brand ale site-ului, citite din CSS-ul
  // lui: verde primar #05534E, crem #F7F0DB, font Montserrat. Montserrat e
  // încărcat de Squarespace, iar @font-face e la nivel de document — se aplică
  // și înăuntrul shadow DOM-ului. Unde nu există, se cade pe fontul de sistem.
  var config = {
    apiUrl: (script.getAttribute("data-api-url") || defaultApiUrl()).replace(/\/$/, ""),
    title: script.getAttribute("data-title") || "Asistent Clinica Primera",
    accent: script.getAttribute("data-accent") || "#05534E",
    surface: script.getAttribute("data-surface") || "#F7F0DB",
    font: script.getAttribute("data-font") || "Montserrat",
    phone: script.getAttribute("data-phone") || "0349 999",
    email: script.getAttribute("data-email") || "office@clinicaprimera.ro",
    lang: script.getAttribute("data-lang") || detectLanguage(),
  };

  if (!config.apiUrl) {
    console.error("[widget] lipsește data-api-url");
    return;
  }
  // Site-ul clinicii e pe HTTPS. Un backend pe HTTP e blocat de browser ca
  // mixed content, TĂCUT: widget-ul arată perfect, dar niciun mesaj nu pleacă.
  if (location.protocol === "https:" && config.apiUrl.indexOf("http://") === 0) {
    console.error("[widget] data-api-url trebuie să folosească https://");
    return;
  }

  function detectLanguage() {
    var pageLang = (document.documentElement.lang || "ro").toLowerCase();
    return pageLang.indexOf("en") === 0 ? "en" : "ro";
  }

  var TEXT = {
    ro: {
      open: "Deschide asistentul",
      close: "Închide",
      greeting:
        "Bună! Sunt asistentul informațional al clinicii. Te pot ajuta cu " +
        "informații despre servicii, prețuri, medici și program.",
      placeholder: "Scrie o întrebare...",
      send: "Trimite",
      privacy: "Nu introduce date personale sau medicale.",
      offline:
        "Momentan nu pot răspunde. Sună la " + config.phone + " sau scrie la " + config.email + ".",
      suggestions: [
        ["Program", "Care este programul clinicii?"],
        ["Locație", "Unde se află clinica?"],
        ["Specialități", "Ce specialități medicale aveți?"],
        ["Preț consultație", "Cât costă o consultație?"],
      ],
    },
    en: {
      open: "Open the assistant",
      close: "Close",
      greeting:
        "Hello! I'm the clinic's information assistant. I can help with " +
        "services, prices, doctors and opening hours.",
      placeholder: "Ask a question...",
      send: "Send",
      privacy: "Please don't enter personal or medical data.",
      offline:
        "I can't answer right now. Please call " + config.phone + " or email " + config.email + ".",
      suggestions: [
        ["Hours", "What are your opening hours?"],
        ["Location", "Where is the clinic located?"],
        ["Specialties", "What medical specialties do you have?"],
        ["Consultation price", "How much is a consultation?"],
      ],
    },
  };

  var t = TEXT[config.lang] || TEXT.ro;

  // --- stiluri (izolate în shadow DOM) ------------------------------------

  var CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: var(--font), -apple-system,
        BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }

    .launcher {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
      width: 56px; height: 56px; border-radius: 50%; border: 0; cursor: pointer;
      background: var(--accent); color: #fff; font-size: 24px; line-height: 1;
      box-shadow: 0 4px 14px rgba(0,0,0,.25);
      display: flex; align-items: center; justify-content: center;
    }
    .launcher:focus-visible { outline: 3px solid #fff; outline-offset: 2px; }

    .panel {
      position: fixed; right: 20px; bottom: 88px; z-index: 2147483000;
      width: 380px; max-width: calc(100vw - 40px);
      height: 560px; max-height: calc(100vh - 120px);
      background: #fff; border-radius: 16px; overflow: hidden;
      box-shadow: 0 12px 40px rgba(0,0,0,.22);
      display: none; flex-direction: column;
    }
    .panel[data-open="true"] { display: flex; }

    .header {
      background: var(--accent); color: #fff; padding: 14px 16px;
      display: flex; align-items: center; justify-content: space-between;
      flex: 0 0 auto;
    }
    .header h2 { margin: 0; font-size: 15px; font-weight: 600; }
    .header button {
      background: transparent; border: 0; color: #fff; cursor: pointer;
      font-size: 22px; line-height: 1; padding: 4px 8px; border-radius: 6px;
    }

    /* Crem, ca secțiunile alternante ale site-ului: cartonașe albe pe crem. */
    .messages { flex: 1 1 auto; overflow-y: auto; padding: 16px;
                background: var(--surface); -webkit-overflow-scrolling: touch; }
    .msg { max-width: 85%; padding: 10px 13px; border-radius: 14px;
           margin-bottom: 10px; font-size: 14.5px; line-height: 1.5;
           white-space: pre-wrap; overflow-wrap: anywhere; }
    /* Verdele de brand ca text: 8,2:1 contrast pe alb, peste pragul AAA. */
    .msg.bot { background: #fff; color: var(--accent); border: 1px solid rgba(5,83,78,.14); }
    .msg.user { background: var(--accent); color: #fff; margin-left: auto; }
    .msg.error { background: #fff4f2; border: 1px solid #f2c4bb; color: #7a2418; }

    .typing span {
      display: inline-block; width: 6px; height: 6px; margin-right: 3px;
      border-radius: 50%; background: #9a9aa2; animation: blink 1.2s infinite;
    }
    .typing span:nth-child(2) { animation-delay: .2s; }
    .typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 60%, 100% { opacity: .25 } 30% { opacity: 1 } }

    .suggestions { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 16px 12px;
                   background: var(--surface); flex: 0 0 auto; }
    .suggestions button {
      border: 1px solid var(--accent); background: #fff; color: var(--accent);
      border-radius: 999px; padding: 9px 14px; font-size: 13px; cursor: pointer;
      min-height: 40px;
    }

    .composer { border-top: 1px solid #e6e6e8; padding: 10px 12px 8px;
                background: #fff; flex: 0 0 auto; }
    .row { display: flex; gap: 8px; align-items: flex-end; }
    textarea {
      flex: 1 1 auto; resize: none; border: 1px solid #d7d7db; border-radius: 10px;
      padding: 10px 12px; font-size: 16px; /* 16px: sub atât, iOS face zoom */
      line-height: 1.4; max-height: 96px; min-height: 42px; outline: none;
    }
    textarea:focus { border-color: var(--accent); }
    .row button {
      background: var(--accent); color: #fff; border: 0; border-radius: 10px;
      padding: 0 16px; height: 42px; min-width: 44px; cursor: pointer; font-size: 14px;
    }
    .row button:disabled { opacity: .5; cursor: default; }
    .privacy { margin: 7px 2px 0; font-size: 11.5px; color: #6b6b73; }

    @media (max-width: 640px) {
      .panel {
        right: 0; left: 0; bottom: 0; width: 100%; max-width: 100%;
        border-radius: 16px 16px 0 0;
        /* dvh urmărește tastatura virtuală; vh nu. */
        height: 88dvh; max-height: 88dvh;
      }
      .launcher { right: 16px; bottom: 16px; }
    }
  `;

  // --- construirea interfeței ---------------------------------------------

  var host = document.createElement("div");
  host.setAttribute("data-clinic-agent", "");
  var root = host.attachShadow({ mode: "open" });
  document.body.appendChild(host);

  var style = document.createElement("style");
  style.textContent = CSS;
  root.appendChild(style);

  var wrapper = document.createElement("div");
  wrapper.style.setProperty("--accent", config.accent);
  wrapper.style.setProperty("--surface", config.surface);
  wrapper.style.setProperty("--font", config.font);
  wrapper.innerHTML = `
    <button class="launcher" type="button" aria-label="${esc(t.open)}">💬</button>
    <section class="panel" role="dialog" aria-label="${esc(config.title)}" data-open="false">
      <div class="header">
        <h2>${esc(config.title)}</h2>
        <button type="button" class="close" aria-label="${esc(t.close)}">×</button>
      </div>
      <div class="messages" role="log" aria-live="polite"></div>
      <div class="suggestions"></div>
      <div class="composer">
        <div class="row">
          <textarea rows="1" placeholder="${esc(t.placeholder)}"
                    aria-label="${esc(t.placeholder)}"></textarea>
          <button type="button" class="send">${esc(t.send)}</button>
        </div>
        <p class="privacy">${esc(t.privacy)}</p>
      </div>
    </section>
  `;
  root.appendChild(wrapper);

  var launcher = wrapper.querySelector(".launcher");
  var panel = wrapper.querySelector(".panel");
  var closeBtn = wrapper.querySelector(".close");
  var messagesEl = wrapper.querySelector(".messages");
  var suggestionsEl = wrapper.querySelector(".suggestions");
  var textarea = wrapper.querySelector("textarea");
  var sendBtn = wrapper.querySelector(".send");

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // --- stare ---------------------------------------------------------------

  var history = [];
  var busy = false;

  function addMessage(role, text) {
    var el = document.createElement("div");
    el.className = "msg " + role;
    el.textContent = text; // textContent, nu innerHTML: agentul nu produce HTML
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showTyping() {
    var el = document.createElement("div");
    el.className = "msg bot typing";
    el.innerHTML = "<span></span><span></span><span></span>";
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function renderSuggestions() {
    suggestionsEl.innerHTML = "";
    t.suggestions.forEach(function (pair) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = pair[0];
      button.addEventListener("click", function () {
        // Formulări fixe: lovesc cache-ul de răspunsuri aproape întotdeauna.
        send(pair[1]);
      });
      suggestionsEl.appendChild(button);
    });
  }

  function hideSuggestions() {
    suggestionsEl.style.display = "none";
  }

  // --- comunicarea cu backend-ul ------------------------------------------

  async function send(text) {
    var question = (text || textarea.value).trim();
    if (!question || busy) return;

    busy = true;
    sendBtn.disabled = true;
    textarea.value = "";
    hideSuggestions();
    addMessage("user", question);
    history.push({ role: "user", content: question });

    var typing = showTyping();
    var bubble = null;
    var answer = "";

    try {
      var response = await fetch(config.apiUrl + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
      });

      if (!response.ok) {
        typing.remove();
        // Mesajele serverului (429, 400, 503) sunt scrise pentru vizitator
        // și conțin numărul de telefon — le arătăm ca atare.
        var detail = t.offline;
        try {
          var body = await response.json();
          if (body && body.detail) detail = body.detail;
        } catch (e) { /* corp non-JSON: rămâne mesajul implicit */ }
        addMessage("error", detail);
        history.pop();
        return;
      }

      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });

        var parts = buffer.split("\n\n");
        buffer = parts.pop();

        for (var i = 0; i < parts.length; i++) {
          var line = parts[i].trim();
          if (line.indexOf("data: ") !== 0) continue;
          var event = JSON.parse(line.slice(6));

          if (event.type === "token") {
            if (!bubble) {
              typing.remove();
              bubble = addMessage("bot", "");
            }
            answer += event.text;
            bubble.textContent = answer;
            scrollToBottom();
          } else if (event.type === "error") {
            if (!bubble) typing.remove();
            addMessage("error", event.message);
          }
        }
      }

      if (bubble) history.push({ role: "assistant", content: answer });
      else typing.remove();
    } catch (err) {
      // Rețea căzută sau CORS: vizitatorul pleacă cu numărul de telefon,
      // nu cu impresia că site-ul e stricat.
      if (typing.isConnected) typing.remove();
      addMessage("error", t.offline);
      history.pop();
    } finally {
      busy = false;
      sendBtn.disabled = false;
    }
  }

  // --- interacțiuni --------------------------------------------------------

  function open() {
    panel.setAttribute("data-open", "true");
    if (!messagesEl.childElementCount) {
      addMessage("bot", t.greeting);
      renderSuggestions();
    }
    if (window.matchMedia("(min-width: 641px)").matches) textarea.focus();
  }

  function close() {
    panel.setAttribute("data-open", "false");
    launcher.focus();
  }

  launcher.addEventListener("click", function () {
    panel.getAttribute("data-open") === "true" ? close() : open();
  });
  closeBtn.addEventListener("click", close);
  sendBtn.addEventListener("click", function () { send(); });

  textarea.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  textarea.addEventListener("input", function () {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 96) + "px";
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && panel.getAttribute("data-open") === "true") close();
  });

  // Pe telefon, tastatura virtuală acoperă câmpul de scris dacă panoul nu se
  // micșorează odată cu zona vizibilă. `dvh` rezolvă majoritatea cazurilor;
  // visualViewport acoperă browserele care nu-l respectă.
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", function () {
      if (panel.getAttribute("data-open") !== "true") return;
      if (!window.matchMedia("(max-width: 640px)").matches) return;
      panel.style.height = Math.round(window.visualViewport.height * 0.94) + "px";
      scrollToBottom();
    });
  }
})();
