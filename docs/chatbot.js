(() => {
  'use strict';
  const API_BASE = (window.API_BASE && window.API_BASE.trim()) || 'http://127.0.0.1:8000';

  const chatForm = document.getElementById('chatForm');
  const userInput = document.getElementById('userInput');
  const chatWindow = document.getElementById('chatWindow');
  const newChatBtn = document.getElementById('newChat');
  const chatHistory = document.getElementById('chatHistory');
  const sidebar = document.getElementById('sidebar');
  const toggleBtn = document.getElementById('toggleSidebarBtn');
  const botIconBtn = document.getElementById('botIconBtn');
  const newChatIconBtn = document.getElementById('newChatIcon');
  const botIconImg = botIconBtn.querySelector('img') || null;
  const sendBtn = document.querySelector('.send-button');
  const attachBtn = document.querySelector('.attach-button');
  const chatInputBar = document.querySelector('.chat-input');
  const API_TIMEOUT_MS = 30000;
  const WAKE_TIMEOUT_MS = 90000;

  let hiddenFileInput;
  let isBusy = false;
  let chats = {};
  let currentChatId = null;
  let saveTimer = null;



  function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

  async function fetchWithTimeout(url, opts = {}, timeout = API_TIMEOUT_MS){
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeout);
    try {
      return await fetch(url, { ...opts, signal: ctl.signal });
    } finally {
      clearTimeout(t);
    }
  }

  async function wakeBackend(){
    try {
      const res = await fetchWithTimeout(`${API_BASE}/health`, {}, WAKE_TIMEOUT_MS);
      if (res.ok) return true;
    } catch (_) { }
    await sleep(3000);
    return false;
  }




  async function apiFetch(url, opts = {}, { chatId = currentChatId, timeout = API_TIMEOUT_MS } = {}) {
    const headers = { ...(opts.headers || {}) };
    if (chatId) headers['X-Chat-Id'] = chatId;
    return fetchWithTimeout(url, { ...opts, headers }, timeout);
  }

  function scrollToBottom() {
    chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
  }

  function syncSendEnabled() {
    if (!userInput || !sendBtn) return;
    const empty = !userInput.value.trim();
    sendBtn.disabled = isBusy || empty;
  }



  function setBusy(busy) {
    isBusy = busy;
    if (userInput) {
    userInput.readOnly = busy;
    }
    attachBtn && (attachBtn.disabled = busy);
    hiddenFileInput && (hiddenFileInput.disabled = busy);
    chatWindow?.classList.toggle('no-drop', busy);
    chatInputBar?.classList.toggle('no-drop', busy);
    syncSendEnabled();
  }
  
  function setBotIconDefault() {
    if (!botIconImg) return;
    botIconImg.src = "styles/images/png/robot_24dp_1F1F1F_FILL0_wght400_GRAD0_opsz24.png";
    botIconImg.alt = "Chatbot";
    botIconBtn.setAttribute('aria-label', 'Panel chatów');
  }

  function toggleSidebar() {
    const willHide = !sidebar.classList.contains('hidden'); 

    setSidebarHidden(willHide);
    setTimeout(() => {
      chatWindow.style.width = '100%';
      chatWindow.style.overflow = 'hidden';
      void chatWindow.offsetHeight;
      chatWindow.style.overflow = '';
    }, 10);

    if (window.innerWidth < 768) {
      setBotIconDefault();
    }
  }

  function setSidebarHidden(hidden) {
    sidebar.classList.toggle('hidden', hidden);
    localStorage.setItem('sidebar_hidden', String(hidden));
    const isHidden = sidebar.classList.contains('hidden');
    toggleBtn.setAttribute('aria-expanded', String(!isHidden));
    botIconBtn.setAttribute('aria-expanded', String(!isHidden));

    const main = document.querySelector('main');
    const overlay = document.querySelector('.sidebar-overlay');
    const onMobile = window.innerWidth < 768;
    if (onMobile) {
      if (!isHidden) {
        main?.setAttribute('inert', ''); 
        overlay?.setAttribute('aria-hidden', 'false');
      } else {
        main?.removeAttribute('inert'); 
        overlay?.setAttribute('aria-hidden', 'true');
      }
    }
  }
  function applyResponsiveSidebar() {
    const saved = localStorage.getItem('sidebar_hidden');
    const preferHidden = saved === 'true';
    if (window.innerWidth < 768) {
      setSidebarHidden(true);
      setBotIconDefault();
    } else {
      setSidebarHidden(preferHidden);
    }
  }



  function makeChatId() {
    return 'chat_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
  }

  function getNextChatTitle() {
    const used = new Set(
      Object.values(chats)
        .map(c => /^Czat\s+(\d+)$/.exec(c.title))
        .filter(Boolean)
        .map(m => parseInt(m[1], 10))
    );
    let n = 1;
    while (used.has(n)) n++;
    return `Czat ${n}`;
  }

  function handleNewChat() {
    const id = makeChatId();
    const title = getNextChatTitle();
    chats[id] = { title, messages: [] };

    const item = createChatItem(title, id);
    chatHistory.appendChild(item);

    item.click();
    userInput.focus();
    saveDebounced();
    
  
  }

  function createChatItem(title, id) {
    const li = document.createElement('li');
    li.className = 'chat-item';
    li.dataset.chatId = id;
    li.tabIndex = 0;
    li.setAttribute('aria-current', 'false');

    li.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        li.click();
      }
    });

    const titleEl = document.createElement('span');
    titleEl.className = 'chat-title';
    titleEl.textContent = title?.trim() || '(bez tytułu)';

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'delete-chat-btn';
    deleteBtn.setAttribute('aria-label', 'Usuń czat');
    deleteBtn.title = 'Usuń czat';
    deleteBtn.innerHTML = '<img src="styles/images/svg/delete_24dp_1F1F1F_FILL0_wght400_GRAD0_opsz24.svg" alt="" aria-hidden="true" />';


    deleteBtn.addEventListener('click', async e => {
      e.stopPropagation();
      delete chats[id];
      const wasActive = currentChatId === id;
      li.remove();
      saveDebounced();
      try {
        await apiFetch(`${API_BASE}/purge`,
          { method: 'DELETE' },
          { chatId: id }
        );
      } catch (err) {
        console.warn('Purge w Qdrant nie powiódł się:', err);
      }
      if (wasActive) {
        const next = chatHistory.querySelector('.chat-item');
        if (next) next.click();
        else {
          handleNewChat();
          userInput.focus();
        }
      }
    });

    li.append(titleEl, deleteBtn);


    li.addEventListener('click', () => {
      document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
        item.setAttribute('aria-current', 'false');
      });
      li.classList.add('active');
      li.setAttribute('aria-current', 'true');

      currentChatId = id;
      renderChat(id);
      saveDebounced();
      
      if (window.innerWidth < 768) {
        toggleSidebar();
      }
    });

    return li;
  }

  function addMessage(text, sender, save = true, doScroll = true, chatId = currentChatId) {
    const p = document.createElement('p');
    p.classList.add(sender === 'user' ? 'user' : 'bot');
    p.textContent = text;

    if (chatId === currentChatId) {
      chatWindow.appendChild(p);
      if (doScroll) scrollToBottom();
    }
    if (save && chatId && chats[chatId]) {
      chats[chatId].messages.push({ text, sender });
      saveDebounced();
    }
    return p;
  }

  function renderChat(chatId) {
    chatWindow.innerHTML = '';
    if (!chats[chatId] || chats[chatId].messages.length === 0) {
      chatWindow.innerHTML = `<p class="bot">Rozpocznij rozmowę</p>`;
      return;
    }
    chats[chatId].messages.forEach(msg => {
      addMessage(msg.text, msg.sender, false, false, chatId);
    });
    scrollToBottom();
  }




  const saveDebounced = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveState, 500);
  };

  function saveState() {
    try {
      localStorage.setItem('chats_state', JSON.stringify({
        chats,
        currentChatId
      }));
    } catch (e) {
      console.warn('Nie udało się zapisać stanu:', e);
    }
  }

  function loadState() {
    try {
      const raw = localStorage.getItem('chats_state');
      if (!raw) return false;
      const data = JSON.parse(raw);
      if (!data || typeof data !== 'object') return false;
      chats = data.chats || {};
      currentChatId = data.currentChatId || null;
      return true;
    } catch (e) {
      console.warn('Błąd odczytu stanu:', e);
      return false;
    }
  }



  async function askBackend(text, chatId) {
    const makeReq = () => apiFetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: text })
    }, { chatId });

    try {
      const res = await makeReq();
      const raw = await res.text();
      let data = null; try { data = raw ? JSON.parse(raw) : null; } catch {}
      if (!res.ok) throw new Error(data?.detail || `Błąd ${res.status}`);
      return data ?? { answer: '' };
    } catch (e) {
      const isTimeout = e?.name === 'AbortError' || /czas odpowiedzi/i.test(String(e?.message || ''));
      if (isTimeout) {
        addMessage("Budzenie serwera… spróbuję ponownie.", 'bot', false, true, chatId);
        await wakeBackend();
        const res2 = await makeReq();
        const raw2 = await res2.text();
        let data2 = null; try { data2 = raw2 ? JSON.parse(raw2) : null; } catch {}
        if (!res2.ok) throw new Error(data2?.detail || `Błąd ${res2.status}`);
        return data2 ?? { answer: '' };
      }
      throw e;
    }
  }


  async function processFile(file) {
    if (isBusy) return;
    setBusy(true);

    const opChatId = currentChatId;
    const loader = (opChatId === currentChatId) ? addMessage(`Wgrywam: ${file.name}`, 'bot', false, false, opChatId) : null;
    if (loader) loader.classList.add('thinking');
    const normalizePayload = (payload) => {
      const normItem = (it, i) => {
        if (typeof it === 'string') return { id: `item_${i+1}`, text: it };
        if (it && typeof it === 'object') {
          const text = it.text ?? it.content ?? it.value ?? it.body ?? it.description ?? it.message ?? it.answer ?? it.data;
          const id = it.id ?? it.key ?? it.slug ?? it.title ?? `item_${i+1}`;
          if (!text || !String(text).trim()) throw new Error(`Brak pola tekstowego w pozycji ${i+1}`);
          return { id: String(id), text: String(text) };
        }
        throw new Error(`Nieobsługiwany element w items (pozycja ${i+1})`);
      };
      if (payload && Array.isArray(payload.items)) return { items: payload.items.map(normItem) };
      if (Array.isArray(payload)) return { items: payload.map(normItem) };
      if (payload && typeof payload === 'object') {
        return { items: Object.entries(payload).map(([k,v],i)=>normItem(typeof v==='string'?{id:k,text:v}:{id:k, ...(v||{})}, i)) };
      }
      throw new Error('Nieprawidłowy kształt JSON');
    };

    async function withRetry(doRequest, kind = 'operacja') {
      try { return await doRequest(); }
      catch (e) {
        const isTimeout = e?.name === 'AbortError' || /aborted|czas odpowiedzi|timeout/i.test(String(e));
        if (!isTimeout) throw e;
        if (loader && currentChatId === opChatId) loader.textContent = `Budzenie serwera… spróbuję ponownie (${kind}).`;
        await wakeBackend();
        return await doRequest();
      }
    }

    try {
      if (file.name.toLowerCase().endsWith('.json')) {
        const raw = await file.text();
        const body = normalizePayload(JSON.parse(raw));
        const doRequest = () => apiFetch(`${API_BASE}/cms`, {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(body)
        }, { chatId: opChatId, timeout: 120_000 });

        const res = await withRetry(doRequest, 'import JSON');
        const text = await res.text();
        let info = null; try { info = text ? JSON.parse(text) : null; } catch {}
        if (!res.ok) throw new Error(info?.detail || `Błąd ${res.status}`);
        if (loader && currentChatId === opChatId) loader.remove();

        addMessage(`Zaimportowano ${info?.count ?? 0} fragmentów z ${file.name}`, 'bot', true, true, opChatId);

      } else {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('chat_id', opChatId);

        const doRequest = () => apiFetch(`${API_BASE}/upload`,
          { method: 'POST', body: fd },
          { chatId: opChatId, timeout: 120_000 } 
        );

        const res = await withRetry(doRequest, 'upload pliku');
        const text = await res.text();
        let info = null; try { info = text ? JSON.parse(text) : null; } catch {}
        if (!res.ok) throw new Error(info?.detail || `Błąd ${res.status}`);

        if (loader && currentChatId === opChatId) loader.remove();
        addMessage(`Wgrano: ${info?.filename ?? file.name} (${info?.size_bytes ?? '—'} B)`, 'bot', true, true, opChatId);
      }

    } catch (e) {
      console.error(e);
      if (loader && currentChatId === opChatId) loader.remove();
      addMessage('Błąd uploadu/importu: serwer odpowiada z opóźnieniem (zimny start). Wyślij plik/pytanie ponownie.', 'bot', true, true, opChatId);
    } finally {
      setBusy(false);
      userInput.focus();
      scrollToBottom();
    }
  }


  function wireDropZone(el) {
    if (!el) return;

    let dragDepth = 0;

    const onDragEnter = (e) => {
      if (isBusy) return;
      e.preventDefault(); 
      e.stopPropagation();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      if (++dragDepth === 1) el.classList.add('drop');
    };

    const onDragOver = (e) => {
      if (isBusy) return;
      e.preventDefault(); 
      e.stopPropagation();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    };

    const onDragLeave = (e) => {
      if (isBusy) return;
      e.preventDefault(); 
      e.stopPropagation();
      if (--dragDepth <= 0) {
        dragDepth = 0;
        el.classList.remove('drop');
      }
    };

    const onDrop = async (e) => {
      e.preventDefault(); 
      e.stopPropagation();
      dragDepth = 0;
      el.classList.remove('drop');
      if (isBusy) return;

      const files = e.dataTransfer?.files;
      if (files && files.length) {
        for (const f of files) await processFile(f);
      }
    };

    el.addEventListener('dragenter', onDragEnter);
    el.addEventListener('dragover', onDragOver);
    el.addEventListener('dragleave', onDragLeave);
    el.addEventListener('drop', onDrop);
  }



  applyResponsiveSidebar();
  window.addEventListener('resize', applyResponsiveSidebar);

  if (loadState()) {
    chatHistory.innerHTML = '';
    Object.entries(chats).forEach(([id, chat]) => {
      chatHistory.appendChild(createChatItem(chat.title, id));
    });
    const first = currentChatId && chats[currentChatId] ? currentChatId : Object.keys(chats)[0];
    if (first) {
      const node = chatHistory.querySelector(`[data-chat-id="${first}"]`);
      if (node) node.click();
    } else {
      handleNewChat();
    }
  } else {
    handleNewChat();
  }
  

  document.addEventListener('click', (e) => {
    const overlay = document.querySelector('.sidebar-overlay');
    if (!overlay) return;

    const visible = window.getComputedStyle(overlay).display !== 'none';
    if (visible && e.target === overlay) {
      toggleSidebar();
    }
  });

  
  botIconBtn.addEventListener('click', toggleSidebar);
  toggleBtn.addEventListener('click', toggleSidebar);
  
  newChatBtn.addEventListener('click', handleNewChat);
  newChatIconBtn.addEventListener('click', handleNewChat);

  window.addEventListener('beforeunload', saveState);

  window.addEventListener('dragend', () => {
    document.querySelectorAll('.drop').forEach(n => n.classList.remove('drop'));
  });

  wireDropZone(chatWindow);
  wireDropZone(document.querySelector('.chat-input'));
  
  userInput.addEventListener('input', syncSendEnabled);

  syncSendEnabled();
  
  chatForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (isBusy) return;

    const msg = userInput.value.trim();
    if (!msg) { 
      userInput.value = '';
      userInput.focus();
      syncSendEnabled();
      return;
    }

    const opChatId = currentChatId;
    setBusy(true);

    addMessage(msg, 'user', true, true, opChatId);
    userInput.value = '';

    const loaderEl = (opChatId === currentChatId) ? addMessage('Myślę', 'bot', false, false, opChatId) : null;
    if (loaderEl) loaderEl.classList.add('thinking');
    
    try {
      const data = await askBackend(msg, opChatId);

      if (loaderEl && currentChatId === opChatId) loaderEl.remove();
      const answerText = data.answer || 'Brak odpowiedzi';
      addMessage(answerText, 'bot', true, true, opChatId);

      if (data.sources?.length) {
        addMessage("Źródła:\n- " + data.sources.join("\n- "), 'bot', true, true, opChatId);
      }
    } catch (err) {
      if (loaderEl && currentChatId === opChatId) loaderEl.remove();
      addMessage('Serwer chwilowo nie odpowiada. Spróbuj ponownie za chwilę.', 'bot', true, true, opChatId);
    } finally {
      setBusy(false);
      userInput.focus();
      scrollToBottom();
    }
  });
  
  
  hiddenFileInput = document.createElement('input');
  hiddenFileInput.type = 'file';
  hiddenFileInput.accept = ".txt,.md,.pdf,.docx,.csv,.json";
  hiddenFileInput.style.display = 'none';
  hiddenFileInput.multiple = true;

  document.body.appendChild(hiddenFileInput);

  attachBtn.addEventListener('click', () => {
    if (isBusy) return;
    hiddenFileInput.click();
  });

  hiddenFileInput.addEventListener('change', async () => {
    if (isBusy) {
      hiddenFileInput.value = '';
      return;
    }
    if (!hiddenFileInput.files || !hiddenFileInput.files.length) return;
    for (const f of hiddenFileInput.files) await processFile(f);
    hiddenFileInput.value = '';
  });
  
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => e.preventDefault());
})();