import './styles.css';

const output = document.getElementById('output');
    const landingPage = document.getElementById('landingPage');
    const chatApp = document.getElementById('chatApp');
    const loginPanel = document.getElementById('loginPanel');
    const sessionList = document.getElementById('sessionList');
    const authStatus = document.getElementById('authStatus');
    const runState = document.getElementById('runState');
    const authMetric = document.getElementById('authMetric');
    const jobMetric = document.getElementById('jobMetric');
    const outputMetric = document.getElementById('outputMetric');
    const outputSummary = document.getElementById('outputSummary');
    const nextAction = document.getElementById('nextAction');
    const conversation = document.getElementById('conversation');
    const analysisMetric = document.getElementById('analysisMetric');
    const sourceMetric = document.getElementById('sourceMetric');
    const resultMetric = document.getElementById('resultMetric');
    const flowSteps = [
      document.getElementById('flowLogin'),
      document.getElementById('flowSession'),
      document.getElementById('flowSource'),
      document.getElementById('flowAnalyze'),
      document.getElementById('flowResult')
    ];
    const linkSourcePanel = null;
    const uploadSourcePanel = null;
    let attachedFile = null;
    let composerMode = 'chat';
    const composerAttachment = document.getElementById('composerAttachment');
    const composerAttachmentName = document.getElementById('composerAttachmentName');
    const composerLinkHint = document.getElementById('composerLinkHint');
    const videoFileInput = document.getElementById('videoFile');
    const VIDEO_LINK_RE = /(https?:\/\/(?:[\w.-]*\.)?douyin\.com\/(?!user\/)[^\s]*|https?:\/\/v\.douyin\.com\/[^\s]+|https?:\/\/www\.iesdouyin\.com\/[^\s]+)/i;
    let currentJobId = '';
    const apiPrefix = window.location.hostname === 'ai001.huahuoai.com'
      ? '/console/api/openclaw-api'
      : (window.location.pathname.startsWith('/ai/openclaw-lab') ? '/api/openclaw-api' : '/openclaw-api');
    const terminalStatuses = new Set(['succeeded', 'failed', 'timed_out', 'cancelled']);
    let linkReadable = false;
    let knownSessions = [];

    function openLoginPanel() {
      loginPanel.hidden = false;
      window.setTimeout(() => document.getElementById('loginAccount').focus(), 30);
    }
    function closeLoginPanel() {
      loginPanel.hidden = true;
    }
    function showLanding() {
      landingPage.hidden = false;
      chatApp.hidden = true;
      closeLoginPanel();
    }
    function showChatApp() {
      landingPage.hidden = true;
      loginPanel.hidden = true;
      chatApp.hidden = false;
    }
    function setPanelState(panelId, unlocked) {
      const panel = document.getElementById(panelId);
      if (!panel) return;
      panel.classList.toggle('locked', !unlocked);
      panel.setAttribute('aria-disabled', unlocked ? 'false' : 'true');
    }
    function setPrimaryAction(buttonId) {
      ['loginButton', 'createSession', 'readVideoLink', 'submitJob', 'uploadJob', 'pollJob', 'sendChat'].forEach(id => {
        const button = document.getElementById(id);
        if (button) button.classList.toggle('primary-active', id === buttonId);
      });
    }
    function setNextAction(text) {
      nextAction.textContent = '';
      const label = document.createElement('span');
      label.textContent = '下一步';
      nextAction.appendChild(label);
      nextAction.appendChild(document.createTextNode(text));
    }
    function setFlowStep(index, state) {
      const item = flowSteps[index];
      if (!item) return;
      item.classList.remove('active', 'done', 'locked');
      if (state) item.classList.add(state);
    }
    function activateFlow(index) {
      flowSteps.forEach((item, itemIndex) => {
        item.classList.remove('active', 'done', 'locked');
        if (itemIndex < index) item.classList.add('done');
        if (itemIndex === index) item.classList.add('active');
        if (itemIndex > index) item.classList.add('locked');
      });
    }
    function hasSession() {
      return Boolean(document.getElementById('sessionId').value.trim());
    }
    function isAuthenticated() {
      return authStatus.classList.contains('ok');
    }
    function moveToSourceIfReady() {
      if (hasSession()) {
        activateFlow(2);
      } else if (isAuthenticated()) {
        activateFlow(1);
      } else {
        activateFlow(0);
      }
    }
    function detectVideoLink(text) {
      const match = (text || '').match(VIDEO_LINK_RE);
      return match ? match[0] : '';
    }
    function updateComposerMode() {
      const text = document.getElementById('prompt').value || '';
      const link = detectVideoLink(text);
      if (attachedFile) {
        composerMode = 'upload';
      } else if (link) {
        composerMode = 'link';
        document.getElementById('videoUrl').value = link;
      } else {
        composerMode = 'chat';
        document.getElementById('videoUrl').value = '';
      }
      if (composerLinkHint) composerLinkHint.hidden = !(composerMode === 'link');
      moveToSourceIfReady();
      syncActionAvailability();
    }
    function setAttachedFile(file) {
      attachedFile = file || null;
      if (composerAttachment) composerAttachment.hidden = !attachedFile;
      if (composerAttachmentName) composerAttachmentName.textContent = attachedFile ? attachedFile.name : '未选择文件';
      updateComposerMode();
    }
    function syncActionAvailability() {
      const authenticated = isAuthenticated();
      const sessionReady = hasSession();
      const uploadMode = composerMode === 'upload';
      const chatReady = authenticated && sessionReady;
      document.getElementById('logoutButton').disabled = !authenticated;
      document.getElementById('refreshMe').disabled = false;
      document.getElementById('loginButton').disabled = authenticated;
      document.getElementById('createSession').disabled = !authenticated;
      document.getElementById('readVideoLink').disabled = !authenticated || !sessionReady;
      document.getElementById('submitJob').disabled = !authenticated || !sessionReady;
      document.getElementById('pollJob').disabled = !authenticated || !currentJobId;
      document.getElementById('uploadJob').disabled = !authenticated || !sessionReady;
      document.getElementById('uploadSmoke').disabled = !authenticated;
      document.getElementById('sendChat').disabled = !chatReady;
      document.getElementById('refreshMessages').disabled = !chatReady;
      setPanelState('sessionPanel', authenticated);
      setPanelState('videoPanel', authenticated && sessionReady);
      setPanelState('conversationPanel', authenticated && sessionReady);
      if (!authenticated) {
        setPrimaryAction('loginButton');
        setNextAction('请先登录，解锁会话、视频来源和聊天分析。');
      } else if (!sessionReady) {
        setPrimaryAction('createSession');
        setNextAction('新建或选择一个历史对话，用来保存链接、上传、消息和结果。');
      } else if (currentJobId) {
        setPrimaryAction('sendChat');
        setNextAction('分析任务进行中，完成后结果会自动出现在对话里。');
      } else if (uploadMode) {
        setPrimaryAction('sendChat');
        setNextAction('已选择视频文件，点击发送即可提交分析。');
      } else if (composerMode === 'link') {
        setPrimaryAction('sendChat');
        setNextAction('检测到视频链接，点击发送将先读取链接再提交分析。');
      } else {
        setPrimaryAction('sendChat');
        setNextAction('粘贴抖音视频链接、上传视频，或直接输入问题后发送。');
      }
    }
    function setPreLoginView() {
      showLanding();
      setAuthState('未登录', 'todo');
      runState.textContent = '等待登录';
      runState.className = 'run-state todo';
      document.getElementById('loginAccount').disabled = false;
      document.getElementById('loginPassword').disabled = false;
      document.getElementById('loginFeedback').textContent = '';
      authMetric.textContent = '未登录';
      analysisMetric.textContent = '就绪';
      sourceMetric.textContent = '等待视频来源';
      resultMetric.textContent = '暂无结果';
      outputMetric.textContent = '就绪';
      outputSummary.textContent = '登录后新建对话，再添加视频链接或上传文件。';
      outputSummary.className = 'output-summary';
      knownSessions = [];
      renderSessions([]);
      renderMessages([]);
      linkReadable = false;
      setCurrentJob('');
      activateFlow(0);
      syncActionAvailability();
    }
    function setAuthenticatedView() {
      showChatApp();
      setAuthState('已登录', 'ok');
      runState.textContent = hasSession() ? '会话已就绪' : '请选择会话';
      runState.className = 'run-state ok';
      document.getElementById('loginAccount').disabled = true;
      document.getElementById('loginPassword').disabled = true;
      authMetric.textContent = '已登录';
      analysisMetric.textContent = hasSession() ? '可开始分析' : '就绪';
      sourceMetric.textContent = hasSession() ? '等待视频来源' : '请先选择会话';
      resultMetric.textContent = hasSession() ? '暂无结果' : '需要会话';
      outputMetric.textContent = hasSession() ? '就绪' : '需要会话';
      outputSummary.textContent = hasSession()
        ? '会话已就绪。添加视频链接或上传文件即可开始分析。'
        : '登录成功。请新建或选择一个历史对话。';
      outputSummary.className = 'output-summary ok';
      activateFlow(hasSession() ? 2 : 1);
      syncActionAvailability();
    }
    function setRunState(text, tone = 'busy') {
      runState.textContent = text;
      runState.className = 'run-state ' + tone;
      outputMetric.textContent = text;
      analysisMetric.textContent = text;
      syncActionAvailability();
    }
    function setAuthState(text, tone) {
      authStatus.textContent = text;
      authStatus.className = 'status ' + tone;
      authMetric.textContent = text;
      setFlowStep(0, tone === 'ok' ? 'done' : (tone === 'fail' ? 'active' : 'active'));
      syncActionAvailability();
    }
    function setCurrentJob(jobId) {
      currentJobId = jobId || '';
      jobMetric.textContent = currentJobId ? currentJobId.slice(0, 8) + '...' : '无任务';
      syncActionAvailability();
    }
    function summarizeOutput(value) {
      if (typeof value === 'string') {
        return { tone: 'warn', text: value || '暂无输出文本。' };
      }
      if (!value || typeof value !== 'object') {
        return { tone: 'warn', text: '暂无结构化响应。' };
      }
      if (value.post_login_acceptance) {
        const payload = value.post_login_acceptance;
        const steps = Array.isArray(payload.steps) ? payload.steps : [];
        const failed = steps.filter(step => step.ok === false).length;
        const tone = payload.overall === 'PASS' ? 'ok' : (payload.overall === 'FAIL' ? 'fail' : 'warn');
        return { tone, text: '登录后验收 ' + payload.overall + '：共 ' + steps.length + ' 项，失败 ' + failed + ' 项。' };
      }
      if (value.security_test) {
        const steps = Array.isArray(value.security_test) ? value.security_test : [];
        const failed = steps.filter(step => step.ok === false).length;
        return { tone: failed ? 'fail' : 'warn', text: '安全检查：已记录 ' + steps.length + ' 项，失败 ' + failed + ' 项。' };
      }
      if (value.self_test) {
        const steps = Array.isArray(value.self_test) ? value.self_test : [];
        return { tone: 'warn', text: '自检进行中：已记录 ' + steps.length + ' 项。' };
      }
      if (value.upload_smoke) {
        const steps = Array.isArray(value.upload_smoke) ? value.upload_smoke : [];
        const last = steps.length ? steps[steps.length - 1] : null;
        const tone = last && last.ok === false ? 'fail' : 'warn';
        return { tone, text: '上传检查：已记录 ' + steps.length + ' 步。' };
      }
      if (value.video_link_read_check) {
        const payload = value.video_link_read_check;
        const tone = payload.status === 'PASS' ? 'ok' : 'warn';
        const count = payload.direct_video_candidate_count || 0;
        sourceMetric.textContent = payload.status === 'PASS' ? count + ' 个候选' : '已检查链接';
        resultMetric.textContent = '预检';
        return { tone, text: '视频链接读取 ' + payload.status + '：发现 ' + count + ' 个直连候选，未调用模型。' };
      }
      if (value.chat) {
        const status = typeof value.chat.status === 'number' ? value.chat.status : null;
        if (status === 200) {
          return { tone: 'ok', text: 'OpenClaw 已回复，对话已更新。' };
        }
        return { tone: status >= 500 ? 'fail' : 'warn', text: 'OpenClaw 聊天响应：HTTP ' + (status || '未知') + '。' };
      }
      if (value.messages) {
        const count = Array.isArray(value.messages.messages) ? value.messages.messages.length : 0;
        return { tone: 'ok', text: '历史已刷新：当前可见 ' + count + ' 条消息。' };
      }
      const status = typeof value.status === 'number' ? value.status : null;
      const job = value.job || (value.body && value.body.job) || null;
      if (job && job.job_id) {
        setCurrentJob(job.job_id);
        const tone = job.status === 'succeeded' ? 'ok' : (terminalStatuses.has(job.status) ? 'fail' : 'warn');
        analysisMetric.textContent = job.status || '任务';
        resultMetric.textContent = job.result_schema_version || (job.status === 'succeeded' ? '已就绪' : '等待中');
        return { tone, text: '任务 ' + job.status + '：' + job.job_id.slice(0, 8) + '...' };
      }
      if (status) {
        const tone = status >= 200 && status < 300 ? 'ok' : (status === 401 || status === 403 || status >= 500 ? 'fail' : 'warn');
        return { tone, text: '已记录 HTTP ' + status + ' 响应。' };
      }
      return { tone: 'warn', text: '已记录结构化响应。' };
    }
    function show(value) {
      output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
      const summary = summarizeOutput(value);
      outputSummary.textContent = summary.text;
      outputSummary.className = 'output-summary ' + summary.tone;
    }
    function pushMessage(role, text) {
      const node = document.createElement('div');
      node.className = 'message ' + role;
      node.setAttribute('data-role-label', role === 'user' ? '你' : 'OpenClaw');
      const inner = document.createElement('div');
      inner.className = 'cg-msg-inner';
      inner.textContent = text;
      node.appendChild(inner);
      if (role === 'assistant') {
        node.appendChild(buildMsgActions(node));
      }
      conversation.appendChild(node);
      conversation.scrollTop = conversation.scrollHeight;
      return node;
    }
    function messageInner(node) {
      return node ? node.querySelector('.cg-msg-inner') : null;
    }
    function addAttachmentChip(node, name) {
      const inner = messageInner(node);
      if (!inner) return;
      const chip = document.createElement('div');
      chip.className = 'cg-msg-attachment';
      chip.textContent = name;
      inner.appendChild(chip);
      conversation.scrollTop = conversation.scrollHeight;
    }
    function attachProgress(node, label) {
      const inner = messageInner(node);
      if (!inner) return null;
      const wrap = document.createElement('div');
      wrap.className = 'cg-progress';
      const bar = document.createElement('div');
      bar.className = 'cg-progress-bar';
      const fill = document.createElement('div');
      fill.className = 'cg-progress-fill indeterminate';
      bar.appendChild(fill);
      const lab = document.createElement('p');
      lab.className = 'cg-progress-label';
      lab.textContent = label || '处理中…';
      wrap.appendChild(bar);
      wrap.appendChild(lab);
      inner.appendChild(wrap);
      conversation.scrollTop = conversation.scrollHeight;
      return {
        set(pct, text) {
          fill.classList.remove('indeterminate');
          fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
          if (text) lab.textContent = text;
        },
        indeterminate(text) {
          fill.classList.add('indeterminate');
          if (text) lab.textContent = text;
        },
        done(text) {
          // Remove the progress bar entirely and show a clean done line,
          // so a full bar never lingers and looks "stuck".
          wrap.classList.add('cg-progress-done');
          bar.remove();
          lab.textContent = (text ? ('✓ ' + text) : '✓ 已完成');
          lab.classList.add('cg-progress-label-done');
          conversation.scrollTop = conversation.scrollHeight;
        },
        fail(text) {
          wrap.classList.add('cg-progress-failed');
          bar.remove();
          lab.textContent = (text ? ('✕ ' + text) : '✕ 未完成');
          lab.classList.add('cg-progress-label-failed');
          conversation.scrollTop = conversation.scrollHeight;
        },
        remove() { wrap.remove(); }
      };
    }
    function addScreenshots(node, urls) {
      const inner = messageInner(node);
      if (!inner || !Array.isArray(urls) || !urls.length) return;
      const grid = document.createElement('div');
      grid.className = 'cg-shots';
      urls.forEach(u => {
        const img = document.createElement('img');
        img.src = u;
        img.loading = 'lazy';
        img.addEventListener('click', () => window.open(u, '_blank'));
        grid.appendChild(img);
      });
      inner.appendChild(grid);
      conversation.scrollTop = conversation.scrollHeight;
    }
    function formatSessionTime(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
    function sessionDisplayTitle(session) {
      const o = sessionOverrides[session.id];
      return (o && o.title) || session.title || '未命名对话';
    }
    function sessionGroup(value) {
      const d = value ? new Date(value) : null;
      if (!d || Number.isNaN(d.getTime())) return '更早';
      const now = new Date();
      const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      const t = d.getTime();
      if (t >= startToday) return '今天';
      if (t >= startToday - 86400000) return '昨天';
      if (t >= startToday - 7 * 86400000) return '最近 7 天';
      if (t >= startToday - 30 * 86400000) return '最近 30 天';
      return '更早';
    }
    function visibleSessions(list) {
      const q = (currentSearchQuery || '').trim().toLowerCase();
      return (list || [])
        .filter(s => !(sessionOverrides[s.id] && sessionOverrides[s.id].deleted))
        .filter(s => !q || sessionDisplayTitle(s).toLowerCase().includes(q));
    }
    function renderSessions(sessions) {
      sessionList.innerHTML = '';
      const all = Array.isArray(sessions) ? sessions : [];
      const q = (currentSearchQuery || '').trim();
      const visible = visibleSessions(all);
      if (visible.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cg-list-empty';
        if (!isAuthenticated()) empty.textContent = '登录后显示历史对话';
        else if (q) empty.textContent = '没有匹配“' + q + '”的对话';
        else empty.textContent = '还没有对话，点击上方“新建对话”开始。';
        sessionList.appendChild(empty);
        return;
      }
      const activeId = document.getElementById('sessionId').value;
      const order = ['今天', '昨天', '最近 7 天', '最近 30 天', '更早'];
      const groups = {};
      visible.forEach(s => {
        const g = sessionGroup(s.updated_at || s.created_at);
        (groups[g] = groups[g] || []).push(s);
      });
      order.forEach(g => {
        if (!groups[g]) return;
        const label = document.createElement('div');
        label.className = 'cg-group-label';
        label.textContent = g;
        sessionList.appendChild(label);
        groups[g].forEach(session => {
          const row = document.createElement('div');
          row.className = 'session-row' + (session.id === activeId ? ' active' : '');
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'session-item' + (session.id === activeId ? ' active' : '');
          item.dataset.sessionId = session.id || '';
          const title = document.createElement('span');
          title.className = 'session-title';
          title.textContent = sessionDisplayTitle(session);
          item.appendChild(title);
          item.addEventListener('click', () => selectSession(session));
          const menuBtn = document.createElement('button');
          menuBtn.type = 'button';
          menuBtn.className = 'row-menu-btn';
          menuBtn.setAttribute('aria-label', '对话操作');
          menuBtn.setAttribute('aria-haspopup', 'menu');
          menuBtn.innerHTML = '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><circle cx="5" cy="12" r="1.7"></circle><circle cx="12" cy="12" r="1.7"></circle><circle cx="19" cy="12" r="1.7"></circle></svg>';
          menuBtn.addEventListener('click', e => { e.stopPropagation(); openSessionRowMenu(menuBtn, session); });
          row.appendChild(item);
          row.appendChild(menuBtn);
          sessionList.appendChild(row);
        });
      });
    }
    function renderMessages(messages) {
      conversation.innerHTML = '';
      if (!Array.isArray(messages) || messages.length === 0) {
        pushMessage('assistant', '当前对话还没有消息。可以发送问题，或提交视频链接开始分析。');
        return;
      }
      messages.forEach(message => pushMessage(message.role === 'user' ? 'user' : 'assistant', message.content || ''));
    }
    async function withBusy(label, task) {
      setRunState(label, 'busy');
      try {
        const result = await task();
        return result;
      } catch (error) {
        setRunState('发生错误', 'fail');
        show({ error: String(error && error.message || error) });
        throw error;
      }
    }
    function setSessionFromAcceptance(session) {
      if (!session || !session.id) return;
      knownSessions = [session, ...knownSessions.filter(item => item.id !== session.id)];
      document.getElementById('sessionId').value = session.id;
      document.getElementById('sessionTitle').value = session.title || '短视频分析';
      renderSessions(knownSessions);
    }
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    async function pollTerminalJob(jobId, attempts = 40) {
      let lastPoll = null;
      let lastJob = null;
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        await delay(1000);
        lastPoll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId));
        lastJob = lastPoll.body.job || null;
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      return { poll: lastPoll, job: lastJob };
    }
    async function api(path, options = {}) {
      const response = await fetch(path, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      return { status: response.status, body };
    }
    async function loadSessions(options = {}) {
      const result = await api(apiPrefix + '/sessions');
      if (result.status === 200) {
        const sessions = result.body.sessions || [];
        knownSessions = sessions;
        renderSessions(knownSessions);
        if (!document.getElementById('sessionId').value && sessions.length > 0) {
          await selectSession(sessions[0], { quiet: true });
        }
      } else if (!options.quiet) {
        show({ status: result.status, sessions: result.body });
      }
      return result;
    }
    async function selectSession(session, options = {}) {
      if (!session || !session.id) return;
      document.getElementById('sessionId').value = session.id;
      document.getElementById('sessionTitle').value = session.title || '短视频分析';
      linkReadable = false;
      setCurrentJob('');
      setAuthenticatedView();
      renderSessions(knownSessions);
      await refreshMessages({ quiet: true });
      if (!options.quiet) show({ session: { selected: true, id_length: session.id.length } });
    }
    async function refreshMessages(options = {}) {
      return withBusy('刷新消息', async () => {
      const sessionId = document.getElementById('sessionId').value;
      if (!sessionId) {
        show('请先新建或选择一个对话。');
        setRunState('需要会话', 'fail');
        return;
      }
      const result = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      if (result.status === 200) {
        renderMessages(result.body.messages || []);
        setRunState('历史已刷新', 'ok');
      } else {
        setRunState('需要处理', 'fail');
      }
      if (!options.quiet) show({ status: result.status, messages: result.body });
      });
    }
    async function login() {
      return withBusy('正在登录', async () => {
      document.getElementById('loginFeedback').textContent = '';
      const result = await api(apiPrefix + '/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          account: document.getElementById('loginAccount').value,
          password: document.getElementById('loginPassword').value
        })
      });
      if (result.status === 200) {
        document.getElementById('loginPassword').value = '';
        document.getElementById('loginAccount').value = '';
        setAuthenticatedView();
        await loadSessions({ quiet: true });
      } else {
        const message = result.status === 429 ? '登录过于频繁，请稍后再试。' : '账号或密码不正确，请重新输入。';
        document.getElementById('loginFeedback').textContent = message;
        setAuthState(result.status === 429 ? '频率受限' : '登录失败', 'fail');
        setRunState('需要处理', 'fail');
        activateFlow(0);
      }
      show(result);
      });
    }
    async function logout() {
      return withBusy('正在退出', async () => {
      const result = await api(apiPrefix + '/auth/logout', { method: 'POST', body: JSON.stringify({}) });
      document.getElementById('sessionId').value = '';
      knownSessions = [];
      setCurrentJob('');
      setPreLoginView();
      show(result);
      });
    }
    async function refreshMe(options = {}) {
      return withBusy('刷新状态', async () => {
      const result = await api(apiPrefix + '/me');
      if (result.status === 200) {
        setAuthenticatedView();
        await loadSessions({ quiet: true });
      } else {
        setPreLoginView();
      }
      if (!options.quiet) show(result);
      });
    }
    async function createSession() {
      return withBusy('创建对话', async () => {
      const result = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: document.getElementById('sessionTitle').value || '短视频分析' })
      });
      if (result.body.session && result.body.session.id) {
        setSessionFromAcceptance(result.body.session);
        linkReadable = false;
        setCurrentJob('');
        setAuthenticatedView();
        setRunState('会话已就绪', 'ok');
        sourceMetric.textContent = '等待视频来源';
        resultMetric.textContent = '会话已就绪';
        activateFlow(2);
        // Load messages from the server so the per-session greeting (if any)
        // posted by the Bridge appears in the conversation.
        await refreshMessages({ quiet: true });
      } else {
        setRunState('需要处理', 'fail');
      }
      show(result);
      });
    }
    async function identityDiagnostics() {
      return withBusy('身份诊断', async () => {
      show(await api(apiPrefix + '/identity/diagnostics'));
      setRunState('诊断完成', 'ok');
      });
    }
    async function runSelfTest() {
      return withBusy('自检运行中', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ self_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setPreLoginView();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, body: me.body });
      if (me.status !== 200) {
        setRunState('需要处理', 'fail');
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const missing = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: missing.status, ok: missing.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw self test ' + new Date().toISOString() })
      });
      add('create_session', { status: sessionResult.status, body: sessionResult.body });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id;
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const jobResult = await api(apiPrefix + '/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          video_url: 'https://example.com/not-douyin',
          content: 'Self-test invalid URL should be rejected by the worker.',
          idempotency_key: 'self-test-' + sessionId
        })
      });
      add('submit_invalid_url_job', { status: jobResult.status, body: jobResult.body });
      setCurrentJob(jobResult.body.job && jobResult.body.job.job_id || '');
      if (!currentJobId) {
        setRunState('需要处理', 'fail');
        return;
      }

      let lastJob = null;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await delay(1000);
        const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
        lastJob = poll.body.job || null;
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      add('poll_invalid_url_job', { body: lastJob });

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0
      });
      setRunState('自检完成', 'ok');
      });
    }
    async function runSecurityTest() {
      return withBusy('安全检查运行中', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ security_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setPreLoginView();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, authenticated: me.body.authenticated === true });
      if (me.status !== 200) {
        setRunState('需要处理', 'fail');
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const randomMessages = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: randomMessages.status, ok: randomMessages.status === 404 });
      const randomJob = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId));
      add('random_job_404', { status: randomJob.status, ok: randomJob.status === 404 });
      const randomResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId) + '/result');
      add('random_result_404', { status: randomResult.status, ok: randomResult.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw security test ' + new Date().toISOString() })
      });
      add('create_session', { status: sessionResult.status, body: sessionResult.body });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id;
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const negativeCases = [
        ['non_allowlisted_domain', 'https://example.com/not-douyin'],
        ['localhost_blocked', 'http://127.0.0.1:8081/apps'],
        ['cloud_metadata_blocked', 'http://169.254.169.254/latest/meta-data/']
      ];
      for (const [caseName, videoUrl] of negativeCases) {
        const created = await api(apiPrefix + '/jobs', {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            video_url: videoUrl,
            content: 'Security negative case: ' + caseName,
            idempotency_key: 'security-' + caseName + '-' + sessionId
          })
        });
        add(caseName + '_submitted', { status: created.status, body: created.body });
        const jobId = created.body.job && created.body.job.job_id || '';
        if (!jobId) continue;
        setCurrentJob(jobId);
        let lastJob = null;
        for (let attempt = 0; attempt < 30; attempt += 1) {
          await delay(1000);
          const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId));
          lastJob = poll.body.job || null;
          if (lastJob && terminalStatuses.has(lastJob.status)) break;
        }
        add(caseName + '_terminal', {
          job_id: jobId,
          status: lastJob ? lastJob.status : 'missing',
          error_code: lastJob ? lastJob.error_code : null,
          ok: !!lastJob && lastJob.status === 'failed' && lastJob.error_code === 'url_rejected'
        });
      }

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0
      });
      const failed = steps.filter(step => step.ok === false).length;
      setRunState(failed ? '安全检查异常' : '安全检查完成', failed ? 'fail' : 'ok');
      });
    }
    async function runPostLoginAcceptance() {
      return withBusy('验收运行中', async () => {
      const steps = [];
      const render = (overall = 'RUNNING') => show({ post_login_acceptance: { overall, steps } });
      const add = (name, result) => {
        steps.push({ name, ...result });
        render();
      };
      const finish = () => {
        const failed = steps.filter(step => step.ok === false);
        const overall = failed.length ? 'FAIL' : 'PASS';
        render(overall);
        setRunState(overall === 'PASS' ? '验收通过' : '验收失败', overall === 'PASS' ? 'ok' : 'fail');
        if (overall === 'PASS') {
          setAuthState('已登录', 'ok');
          if (hasSession()) {
            sourceMetric.textContent = '等待视频来源';
            resultMetric.textContent = '会话已就绪';
            activateFlow(2);
          }
        }
      };

      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      const diagnosticsOk = diagnostics.status === 200
        && diagnostics.body.authenticated === true
        && diagnostics.body.profile_ok === true
        && diagnostics.body.workspace_ok === true
        && diagnostics.body.access_ok === true;
      add('identity_diagnostics', {
        status: diagnostics.status,
        ok: diagnosticsOk,
        authenticated: diagnostics.body.authenticated === true,
        profile_ok: diagnostics.body.profile_ok === true,
        workspace_ok: diagnostics.body.workspace_ok === true,
        access_ok: diagnostics.body.access_ok === true,
        failure_stage: diagnostics.body.failure_stage || null
      });
      if (!diagnosticsOk) {
        finish();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', {
        status: me.status,
        ok: me.status === 200 && me.body.authenticated === true && typeof me.body.principal_id === 'string',
        authenticated: me.body.authenticated === true,
        principal_len: typeof me.body.principal_id === 'string' ? me.body.principal_id.length : 0
      });
      if (me.status !== 200) {
        finish();
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const randomMessages = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: randomMessages.status, ok: randomMessages.status === 404 });
      const randomJob = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId));
      add('random_job_404', { status: randomJob.status, ok: randomJob.status === 404 });
      const randomResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId) + '/result');
      add('random_result_404', { status: randomResult.status, ok: randomResult.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw post-login acceptance ' + new Date().toISOString() })
      });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id || '';
      add('create_session', { status: sessionResult.status, ok: sessionResult.status === 201 && !!sessionId });
      if (!sessionId) {
        finish();
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const negativeCases = [
        ['non_allowlisted_domain', 'https://example.com/not-douyin'],
        ['localhost_blocked', 'http://127.0.0.1:8081/apps'],
        ['cloud_metadata_blocked', 'http://169.254.169.254/latest/meta-data/']
      ];
      for (const [caseName, videoUrl] of negativeCases) {
        const created = await api(apiPrefix + '/jobs', {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            video_url: videoUrl,
            content: 'Post-login acceptance negative case: ' + caseName,
            idempotency_key: 'post-login-' + caseName + '-' + sessionId
          })
        });
        const jobId = created.body.job && created.body.job.job_id || '';
        add(caseName + '_submitted', { status: created.status, ok: created.status === 202 && !!jobId });
        if (!jobId) continue;
        setCurrentJob(jobId);
        const terminal = await pollTerminalJob(jobId, 30);
        const terminalJob = terminal.job;
        add(caseName + '_terminal', {
          job_id: jobId,
          status: terminalJob ? terminalJob.status : 'missing',
          error_code: terminalJob ? terminalJob.error_code : null,
          ok: !!terminalJob && terminalJob.status === 'failed' && terminalJob.error_code === 'url_rejected'
        });
      }

      const fileBytes = new Uint8Array([
        0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109,
        0, 0, 0, 0, 105, 115, 111, 109, 109, 112, 52, 49
      ]);
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', 'Post-login acceptance uploaded video.');
      form.append('video', new File([fileBytes], 'post-login-acceptance.mp4', { type: 'video/mp4' }));
      const uploadResponse = await fetch(apiPrefix + '/uploads', {
        method: 'POST',
        credentials: 'include',
        body: form
      });
      const uploadText = await uploadResponse.text();
      let uploadBody;
      try { uploadBody = uploadText ? JSON.parse(uploadText) : {}; } catch { uploadBody = { text: uploadText }; }
      const uploadJobId = uploadBody.job && uploadBody.job.job_id || '';
      add('tiny_upload_submitted', { status: uploadResponse.status, ok: uploadResponse.status === 202 && !!uploadJobId });
      if (uploadJobId) {
        setCurrentJob(uploadJobId);
        const uploadTerminal = await pollTerminalJob(uploadJobId, 40);
        const uploadJob = uploadTerminal.job;
        add('tiny_upload_terminal', {
          job_id: uploadJobId,
          status: uploadJob ? uploadJob.status : 'missing',
          ok: !!uploadJob && uploadJob.status === 'succeeded'
        });
        if (uploadJob && uploadJob.status === 'succeeded') {
          const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(uploadJobId) + '/result');
          const platform = result.body.result && result.body.result.result && result.body.result.result.source
            ? result.body.result.result.source.platform
            : null;
          add('tiny_upload_result', {
            status: result.status,
            platform,
            ok: result.status === 200 && platform === 'upload'
          });
        }
      }

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages_visible_to_owner', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0,
        ok: messages.status === 200 && !!messages.body.messages && messages.body.messages.length >= 1
      });
      finish();
      });
    }
    async function sendChat() {
      return withBusy('发送中', async () => {
      const sessionId = document.getElementById('sessionId').value;
      const promptText = document.getElementById('prompt').value.trim();
      if (!sessionId || !promptText) {
        show('请先新建或选择对话，并输入问题。');
        setRunState('需要输入', 'fail');
        return;
      }
      pushMessage('user', promptText);
      const result = await api(apiPrefix + '/chat', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, content: promptText })
      });
      if (result.status === 200 && result.body.message) {
        pushMessage('assistant', result.body.message.content || 'OpenClaw 已回复。');
        setRunState('已回复', 'ok');
        resultMetric.textContent = '对话';
        activateFlow(4);
      } else {
        pushMessage('assistant', result.status === 501 ? '当前文本聊天适配器尚未配置，请先使用视频分析入口。' : '聊天请求返回 HTTP ' + result.status + '。');
        setRunState(result.status >= 500 ? '聊天不可用' : '聊天结束', result.status >= 500 ? 'fail' : 'warn');
      }
      show({ chat: { status: result.status, body: result.body } });
      });
    }
    async function submitJob() {
      return withBusy('提交分析', async () => {
      const promptText = document.getElementById('prompt').value || '请分析这个视频。';
      const videoUrl = document.getElementById('videoUrl').value;
      const result = await api(apiPrefix + '/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: document.getElementById('sessionId').value,
          video_url: videoUrl,
          content: promptText
        })
      });
      if (result.body.job && result.body.job.job_id) {
        linkReadable = false;
        setCurrentJob(result.body.job.job_id);
        setRunState('任务已提交', 'ok');
        sourceMetric.textContent = '链接已提交';
        resultMetric.textContent = '等待中';
        activateFlow(3);
        pushMessage('user', '已提交视频链接进行分析。');
        pushMessage('assistant', '任务已提交。稍后刷新状态查看分析进度。');
      } else {
        setRunState('需要处理', 'fail');
      }
      show(result);
      });
    }
    async function readVideoLink() {
      return withBusy('读取链接', async () => {
      const videoUrl = document.getElementById('videoUrl').value;
      const result = await api(apiPrefix + '/video-link/read-check', {
        method: 'POST',
        body: JSON.stringify({ video_url: videoUrl })
      });
      show({ status: result.status, video_link_read_check: result.body });
      if (result.status === 200 && result.body.status === 'PASS') {
        linkReadable = true;
        setRunState('链接可读取', 'ok');
        sourceMetric.textContent = (result.body.direct_video_candidate_count || 0) + ' 个候选';
        resultMetric.textContent = '可提交';
        activateFlow(3);
        pushMessage('assistant', '视频链接可读取。已找到直连候选，尚未调用模型。');
      } else {
        linkReadable = false;
        setRunState('链接检查结束', result.status >= 400 ? 'fail' : 'warn');
        resultMetric.textContent = '预检结束';
      }
      });
    }
    function uploadVideoWithProgress(file, sessionId, content, progress) {
      return new Promise((resolve) => {
        const form = new FormData();
        form.append('session_id', sessionId);
        form.append('content', content || '请分析上传的视频。');
        form.append('video', file);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', apiPrefix + '/uploads', true);
        xhr.withCredentials = true;
        xhr.upload.onprogress = (e) => {
          if (progress && e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progress.set(pct, '上传中… ' + pct + '%');
          }
        };
        xhr.onload = () => {
          let body; try { body = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch { body = { text: xhr.responseText }; }
          resolve({ status: xhr.status, body });
        };
        xhr.onerror = () => resolve({ status: 0, body: {} });
        xhr.send(form);
      });
    }
    async function uploadJob() {
      return withBusy('上传视频', async () => {
      const fileInput = document.getElementById('videoFile');
      const file = fileInput.files && fileInput.files[0];
      const sessionId = document.getElementById('sessionId').value;
      if (!file || !sessionId) {
        show('请先选择视频文件和对话。');
        setRunState('需要输入', 'fail');
        return;
      }
      const { status, body } = await uploadVideoWithProgress(file, sessionId, document.getElementById('prompt').value, null);
      if (body.job && body.job.job_id) {
        linkReadable = false;
        setCurrentJob(body.job.job_id);
        setRunState('上传已提交', 'ok');
        sourceMetric.textContent = '上传已接收';
        resultMetric.textContent = '等待中';
        activateFlow(3);
      } else {
        setRunState('需要处理', 'fail');
      }
      show({ status, body });
      });
    }
    async function uploadTinySmoke() {
      return withBusy('上传检查运行中', async () => {
      let sessionId = document.getElementById('sessionId').value;
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ upload_smoke: steps });
      };
      if (!sessionId) {
        const sessionResult = await api(apiPrefix + '/sessions', {
          method: 'POST',
          body: JSON.stringify({ title: 'OpenClaw upload smoke ' + new Date().toISOString() })
        });
        add('create_session', { status: sessionResult.status, body: sessionResult.body });
        sessionId = sessionResult.body.session && sessionResult.body.session.id || '';
        setSessionFromAcceptance(sessionResult.body.session);
        if (sessionId) setAuthenticatedView();
      }
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      const fileBytes = new Uint8Array([
        0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109,
        0, 0, 0, 0, 105, 115, 111, 109, 109, 112, 52, 49
      ]);
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', 'Smoke test uploaded video.');
      form.append('video', new File([fileBytes], 'tiny-smoke.mp4', { type: 'video/mp4' }));
      const response = await fetch(apiPrefix + '/uploads', {
        method: 'POST',
        credentials: 'include',
        body: form
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      add('upload_job', { status: response.status, body });
      setCurrentJob(body.job && body.job.job_id || '');
      sourceMetric.textContent = '上传检查';
      resultMetric.textContent = currentJobId ? '等待中' : '无任务';
      if (currentJobId) activateFlow(3);
      if (!currentJobId) {
        setRunState('需要处理', 'fail');
        return;
      }
      let lastJob = null;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await delay(1000);
        const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
        lastJob = poll.body.job || null;
        add('poll_job', { status: poll.status, body: poll.body });
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      if (lastJob && lastJob.status === 'succeeded') {
        add('job_result', await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result'));
      }
      if (lastJob && lastJob.status === 'succeeded') {
        resultMetric.textContent = lastJob.result_schema_version || '已就绪';
        activateFlow(4);
      } else if (lastJob) {
        resultMetric.textContent = terminalStatuses.has(lastJob.status) ? lastJob.status : '等待中';
      }
      setRunState(lastJob && lastJob.status === 'succeeded' ? '上传检查完成' : '上传检查结束', lastJob && lastJob.status === 'succeeded' ? 'ok' : 'fail');
      });
    }
    async function pollJob() {
      return withBusy('刷新任务', async () => {
      if (!currentJobId) {
        show('当前还没有可刷新的任务。');
        setRunState('无任务', 'fail');
        return;
      }
      const jobResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
      const job = jobResult.body.job;
      if (job && job.status === 'succeeded') {
        const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result');
        pushMessage('assistant', '分析结果已就绪，请查看右侧结构化结果。');
        show({ job: jobResult, result });
        setRunState('结果已就绪', 'ok');
        resultMetric.textContent = result.body.result && result.body.result.schema_version || '已就绪';
        activateFlow(4);
        return;
      }
      show(jobResult);
      if (job && job.status) {
        resultMetric.textContent = terminalStatuses.has(job.status) ? (job.result_schema_version || job.status) : '等待中';
      }
      setRunState(job && terminalStatuses.has(job.status) ? '任务已结束' : '任务运行中', job && terminalStatuses.has(job.status) ? 'fail' : 'busy');
      });
    }
    function extractScreenshots(result) {
      // Pull any frame/screenshot URLs from the sanitized result payload if present.
      const r = result && result.body && result.body.result && result.body.result.result;
      if (!r) return [];
      const urls = [];
      const collect = (arr) => { if (Array.isArray(arr)) arr.forEach(u => { if (typeof u === 'string' && /^https?:|^\//.test(u)) urls.push(u); }); };
      collect(r.frame_urls); collect(r.screenshots); collect(r.frames);
      if (r.signals && Array.isArray(r.signals.frame_urls)) collect(r.signals.frame_urls);
      return urls.slice(0, 8);
    }
    async function autoPollCurrentJob(progress, assistantNode) {
      if (!currentJobId) return;
      const jobId = currentJobId;
      if (progress) progress.indeterminate('正在分析视频…');
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await delay(2000);
        if (currentJobId !== jobId) return;
        let poll;
        try { poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId)); }
        catch { continue; }
        const job = poll.body.job || null;
        if (!job) continue;
        if (job.status === 'succeeded') {
          const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId) + '/result');
          if (progress) progress.done('分析完成');
          const summary = result.body.result && result.body.result.result && result.body.result.result.summary;
          const shots = extractScreenshots(result);
          if (assistantNode) {
            const inner = messageInner(assistantNode);
            if (inner) inner.firstChild ? (inner.childNodes[0].textContent = summary || '分析完成，结果已就绪。') : (inner.textContent = summary || '分析完成，结果已就绪。');
            if (shots.length) addScreenshots(assistantNode, shots);
          } else {
            const node = pushMessage('assistant', summary || '分析完成，结果已就绪。');
            if (shots.length) addScreenshots(node, shots);
          }
          show({ job: poll, result });
          setRunState('结果已就绪', 'ok');
          resultMetric.textContent = (result.body.result && result.body.result.schema_version) || '已就绪';
          activateFlow(4);
          return;
        }
        if (terminalStatuses.has(job.status)) {
          if (progress) progress.fail('分析未完成');
          const reply = buildJobErrorReply(job.error_code);
          if (assistantNode) { const inner = messageInner(assistantNode); if (inner) inner.childNodes[0] ? (inner.childNodes[0].textContent = reply) : (inner.textContent = reply); }
          else pushMessage('assistant', reply);
          show({ job: poll });
          setRunState('任务结束', 'fail');
          resultMetric.textContent = job.status;
          return;
        }
      }
      if (progress) progress.fail('分析超时，请稍后重试');
    }
    function buildJobErrorReply(errorCode) {
      const map = {
        url_rejected: '这个链接没有通过安全校验或无法解析。请发抖音单条视频页链接（形如 https://www.douyin.com/video/xxxx），不要发主页或非抖音链接。',
        tool_timeout: '这条视频解析超时了。可以稍后重试，或换一条更短的单条视频链接。',
        tool_failed: '这条视频暂时没能成功解析，所以我不能假装看过它。可以确认视频未被删除/设为私密，或换完整视频页链接重试。'
      };
      return map[errorCode] || '分析任务未能完成。可以稍后重试，或换一条视频链接。';
    }
    async function handleComposerSend() {
      const promptText = document.getElementById('prompt').value.trim();
      // Upload path
      if (composerMode === 'upload' && attachedFile) {
        const sessionId = document.getElementById('sessionId').value;
        if (!sessionId) { setNextAction('请先登录并新建对话。'); return; }
        const fileName = attachedFile.name;
        const userNode = pushMessage('user', promptText || '请分析我上传的视频。');
        addAttachmentChip(userNode, fileName);
        const assistantNode = pushMessage('assistant', '已收到视频文件，正在上传…');
        const progress = attachProgress(assistantNode, '准备上传…');
        document.getElementById('prompt').value = '';
        updateComposerMode();
        const { body } = await uploadVideoWithProgress(attachedFile, sessionId, promptText || '请分析上传的视频。', progress);
        setAttachedFile(null);
        if (body.job && body.job.job_id) {
          setCurrentJob(body.job.job_id);
          progress.indeterminate('上传完成，正在分析视频…');
          activateFlow(3);
          await autoPollCurrentJob(progress, assistantNode);
        } else {
          progress.fail('上传失败，请重试');
        }
        return;
      }
      // Video link path
      if (composerMode === 'link') {
        const sessionId = document.getElementById('sessionId').value;
        if (!sessionId) { setNextAction('请先登录并新建对话。'); return; }
        const link = document.getElementById('videoUrl').value;
        const userNode = pushMessage('user', promptText || '请分析这个视频。');
        addAttachmentChip(userNode, link);
        const assistantNode = pushMessage('assistant', '正在读取视频链接…');
        const progress = attachProgress(assistantNode, '读取链接中…');
        document.getElementById('prompt').value = '';
        const read = await api(apiPrefix + '/video-link/read-check', { method: 'POST', body: JSON.stringify({ video_url: link }) });
        show({ status: read.status, video_link_read_check: read.body });
        if (read.status === 200 && read.body.status === 'PASS') {
          linkReadable = true;
          progress.indeterminate('链接可读取，正在提交分析…');
          const jobRes = await api(apiPrefix + '/jobs', { method: 'POST', body: JSON.stringify({ session_id: sessionId, video_url: link, content: promptText || '请分析这个视频。' }) });
          if (jobRes.body.job && jobRes.body.job.job_id) {
            setCurrentJob(jobRes.body.job.job_id);
            activateFlow(3);
            await autoPollCurrentJob(progress, assistantNode);
          } else {
            progress.fail('提交分析失败，请重试');
          }
        } else {
          progress.fail('链接无法读取');
          const inner = messageInner(assistantNode);
          if (inner) inner.childNodes[0].textContent = buildJobErrorReply('url_rejected');
        }
        updateComposerMode();
        return;
      }
      // Plain chat path
      await sendChat();
    }
    document.getElementById('composerAttach').addEventListener('click', () => videoFileInput.click());
    videoFileInput.addEventListener('change', () => {
      const file = videoFileInput.files && videoFileInput.files[0];
      setAttachedFile(file || null);
    });
    document.getElementById('composerAttachmentClear').addEventListener('click', () => {
      videoFileInput.value = '';
      setAttachedFile(null);
    });
    document.getElementById('prompt').addEventListener('input', updateComposerMode);
    document.getElementById('prompt').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!document.getElementById('sendChat').disabled) handleComposerSend();
      }
    });
    document.getElementById('openLogin').addEventListener('click', openLoginPanel);
    document.getElementById('closeLogin').addEventListener('click', closeLoginPanel);
    window.addEventListener('openclaw:open-login', openLoginPanel);
    loginPanel.addEventListener('click', event => {
      if (event.target === loginPanel) closeLoginPanel();
    });
    ['loginAccount', 'loginPassword'].forEach(id => {
      document.getElementById(id).addEventListener('keydown', event => {
        if (event.key === 'Enter') login();
      });
    });
    document.getElementById('loginButton').addEventListener('click', login);
    document.getElementById('logoutButton').addEventListener('click', logout);
    document.getElementById('refreshMe').addEventListener('click', refreshMe);
    document.getElementById('identityDiagnostics').addEventListener('click', identityDiagnostics);
    document.getElementById('runSelfTest').addEventListener('click', runSelfTest);
    document.getElementById('runSecurityTest').addEventListener('click', runSecurityTest);
    document.getElementById('runPostLoginAcceptance').addEventListener('click', runPostLoginAcceptance);
    document.getElementById('createSession').addEventListener('click', createSession);
    document.getElementById('readVideoLink').addEventListener('click', readVideoLink);
    document.getElementById('submitJob').addEventListener('click', submitJob);
    document.getElementById('sendChat').addEventListener('click', handleComposerSend);
    document.getElementById('refreshMessages').addEventListener('click', refreshMessages);
    document.getElementById('uploadJob').addEventListener('click', uploadJob);
    document.getElementById('uploadSmoke').addEventListener('click', uploadTinySmoke);
    document.getElementById('pollJob').addEventListener('click', pollJob);
    document.getElementById('sessionId').addEventListener('input', () => {
      if (isAuthenticated()) setAuthenticatedView();
      syncActionAvailability();
    });

    /* ===== M-UI overhaul: theme, menus, modal, toast, search, mobile ===== */
    // theme (light / dark / system). Session-scoped only: the page intentionally
    // keeps NO browser storage (security contract), so this resets to system on reload.
    let themeChoice = 'system';
    const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    function applyTheme() {
      const choice = themeChoice || 'system';
      const dark = choice === 'dark' || (choice === 'system' && themeMedia.matches);
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
      document.querySelectorAll('[data-theme-choice]').forEach(b => {
        b.setAttribute('aria-checked', String(b.dataset.themeChoice === choice));
      });
    }
    function setTheme(choice) { themeChoice = choice; applyTheme(); }
    themeMedia.addEventListener('change', applyTheme);
    applyTheme();

    // toast
    const toastHost = document.getElementById('toastHost');
    function toast(message, opts) {
      opts = opts || {};
      const el = document.createElement('div');
      el.className = 'toast' + (opts.type ? (' ' + opts.type) : '');
      el.setAttribute('role', 'status');
      const span = document.createElement('span');
      span.textContent = message;
      el.appendChild(span);
      let timer;
      const dismiss = () => { el.classList.remove('show'); setTimeout(() => el.remove(), 220); };
      if (opts.actionLabel && typeof opts.onAction === 'function') {
        const btn = document.createElement('button');
        btn.className = 'toast-action'; btn.type = 'button'; btn.textContent = opts.actionLabel;
        btn.addEventListener('click', () => { clearTimeout(timer); dismiss(); opts.onAction(); });
        el.appendChild(btn);
      }
      toastHost.appendChild(el);
      requestAnimationFrame(() => el.classList.add('show'));
      timer = setTimeout(dismiss, opts.duration || 3200);
      return dismiss;
    }

    // modal (confirm / prompt) -> Promise
    const modalHost = document.getElementById('modalHost');
    const modalTitle = document.getElementById('modalTitle');
    const modalDesc = document.getElementById('modalDesc');
    const modalInput = document.getElementById('modalInput');
    const modalCancel = document.getElementById('modalCancel');
    const modalConfirm = document.getElementById('modalConfirm');
    let modalResolve = null;
    let modalLastFocus = null;
    function closeModal(value) {
      modalHost.classList.remove('show');
      modalHost.hidden = true;
      const r = modalResolve; modalResolve = null;
      if (modalLastFocus && modalLastFocus.focus) { try { modalLastFocus.focus(); } catch (e) {} }
      if (r) r(value);
    }
    function openModal(opts) {
      opts = opts || {};
      modalLastFocus = document.activeElement;
      modalTitle.textContent = opts.title || '提示';
      modalDesc.textContent = opts.desc || '';
      modalDesc.style.display = opts.desc ? '' : 'none';
      if (opts.prompt) { modalInput.hidden = false; modalInput.value = opts.value || ''; }
      else { modalInput.hidden = true; }
      modalConfirm.textContent = opts.confirmText || '确定';
      modalConfirm.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
      modalHost.hidden = false;
      requestAnimationFrame(() => modalHost.classList.add('show'));
      setTimeout(() => {
        const f = opts.prompt ? modalInput : modalConfirm;
        if (f && f.focus) f.focus();
        if (opts.prompt && modalInput.select) modalInput.select();
      }, 30);
      return new Promise(resolve => { modalResolve = resolve; });
    }
    modalConfirm.addEventListener('click', () => closeModal(modalInput.hidden ? true : modalInput.value));
    modalCancel.addEventListener('click', () => closeModal(null));
    modalHost.addEventListener('click', e => { if (e.target === modalHost) closeModal(null); });
    modalInput.addEventListener('keydown', e => { if (e.key === 'Enter') closeModal(modalInput.value); });

    // single open popup manager + outside-click + Esc
    let openPop = null;
    function closePop() {
      if (openPop) {
        openPop.el.hidden = true;
        if (openPop.btn) openPop.btn.setAttribute('aria-expanded', 'false');
        openPop = null;
      }
    }
    function showPop(el, btn) {
      closePop();
      el.hidden = false;
      if (btn) btn.setAttribute('aria-expanded', 'true');
      openPop = { el: el, btn: btn };
    }
    function placePop(el, btn, opts) {
      opts = opts || {};
      el.hidden = false;
      el.style.position = 'fixed';
      el.style.left = '-9999px';
      el.style.top = '0px';
      const w = el.offsetWidth, h = el.offsetHeight;
      const r = btn.getBoundingClientRect();
      let left = opts.alignRight ? (r.right - w) : r.left;
      let top = opts.above ? (r.top - h - 6) : (r.bottom + 6);
      if (opts.above && top < 8) top = r.bottom + 6;
      left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
      top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
      el.style.left = left + 'px';
      el.style.top = top + 'px';
    }
    document.addEventListener('click', e => {
      if (openPop && !openPop.el.contains(e.target) && (!openPop.btn || !openPop.btn.contains(e.target))) closePop();
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (modalHost && !modalHost.hidden) { closeModal(null); return; }
      if (openPop) { const b = openPop.btn; closePop(); if (b && b.focus) b.focus(); return; }
      if (sidebar && sidebar.classList.contains('drawer-open')) closeDrawer();
    });

    // user menu (theme / about / logout)
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userMenu = document.getElementById('userMenu');
    userMenuBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (openPop && openPop.el === userMenu) { closePop(); return; }
      placePop(userMenu, userMenuBtn, { above: true });
      showPop(userMenu, userMenuBtn);
      const first = userMenu.querySelector('button');
      if (first) first.focus();
    });
    userMenu.querySelectorAll('[data-theme-choice]').forEach(b => {
      b.addEventListener('click', () => {
        setTheme(b.dataset.themeChoice);
        const label = { light: '浅色', dark: '深色', system: '跟随系统' }[b.dataset.themeChoice] || '';
        toast('已切换至' + label + '模式');
      });
    });
    document.getElementById('aboutBtn').addEventListener('click', () => {
      closePop();
      openModal({ title: '关于 OpenClaw', desc: 'OpenClaw 短视频分析助手：支持抖音视频链接读取与本地视频文件上传的多模态分析，围绕选题、前 3 秒钩子、内容结构、画面设计与转化引导给出可执行建议。本页为 OpenClaw 自有会话，独立于 Dify 登录。', confirmText: '知道了' });
    });

    // local session overrides (rename / delete). Session-scoped in-memory only —
    // the page keeps no browser storage by design; swappable to a backend prefs API later.
    let sessionOverrides = {};
    function persistOverrides() { /* session-scoped; intentionally no browser storage */ }
    function setSessionOverride(id, patch) { sessionOverrides[id] = Object.assign({}, sessionOverrides[id], patch); persistOverrides(); }

    // per-session row menu
    const sessionRowMenu = document.getElementById('sessionRowMenu');
    let rowMenuSession = null;
    function openSessionRowMenu(btn, session) {
      rowMenuSession = session;
      placePop(sessionRowMenu, btn, { alignRight: true });
      showPop(sessionRowMenu, btn);
    }
    sessionRowMenu.querySelector('[data-row-action="rename"]').addEventListener('click', async () => {
      const s = rowMenuSession; closePop(); if (!s) return;
      const name = await openModal({ title: '重命名对话', prompt: true, value: sessionDisplayTitle(s), confirmText: '保存' });
      if (name == null) return;
      const t = String(name).trim();
      if (!t) return;
      setSessionOverride(s.id, { title: t });
      renderSessions(knownSessions);
      if (document.getElementById('sessionId').value === s.id) document.getElementById('cgConvTitle').textContent = t;
      toast('已重命名（本地）', { type: 'success' });
    });
    sessionRowMenu.querySelector('[data-row-action="delete"]').addEventListener('click', async () => {
      const s = rowMenuSession; closePop(); if (!s) return;
      const ok = await openModal({ title: '删除对话', desc: '将从本地列表移除“' + sessionDisplayTitle(s) + '”。该操作仅在当前浏览器生效，不会删除服务器端记录。', danger: true, confirmText: '删除' });
      if (!ok) return;
      const prev = sessionOverrides[s.id] ? Object.assign({}, sessionOverrides[s.id]) : null;
      setSessionOverride(s.id, { deleted: true });
      if (document.getElementById('sessionId').value === s.id) {
        document.getElementById('sessionId').value = '';
        conversation.innerHTML = '';
        document.getElementById('cgConvTitle').textContent = 'OpenClaw';
      }
      renderSessions(knownSessions);
      toast('已删除（本地）', {
        type: 'success', actionLabel: '撤销', duration: 5000,
        onAction: () => {
          if (prev) sessionOverrides[s.id] = prev; else delete sessionOverrides[s.id];
          persistOverrides();
          renderSessions(knownSessions);
          toast('已撤销删除');
        }
      });
    });

    // session search (client-side filter)
    let currentSearchQuery = '';
    const sessionSearch = document.getElementById('sessionSearch');
    const sessionSearchWrap = document.getElementById('sessionSearchWrap');
    sessionSearch.addEventListener('input', () => {
      currentSearchQuery = sessionSearch.value;
      sessionSearchWrap.classList.toggle('has-value', !!currentSearchQuery);
      renderSessions(knownSessions);
    });
    document.getElementById('sessionSearchClear').addEventListener('click', () => {
      sessionSearch.value = '';
      currentSearchQuery = '';
      sessionSearchWrap.classList.remove('has-value');
      renderSessions(knownSessions);
      sessionSearch.focus();
    });

    // message copy action
    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text));
      }
      return Promise.resolve(fallbackCopy(text));
    }
    function fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        const ok = document.execCommand('copy'); ta.remove(); return ok;
      } catch (e) { return false; }
    }
    function buildMsgActions(node) {
      const bar = document.createElement('div');
      bar.className = 'cg-msg-actions';
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button'; copyBtn.title = '复制'; copyBtn.setAttribute('aria-label', '复制消息');
      copyBtn.innerHTML = '<svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg><span>复制</span>';
      copyBtn.addEventListener('click', () => {
        const inner = messageInner(node);
        const txt = inner ? inner.textContent : '';
        copyText(txt).then(ok => toast(ok ? '已复制' : '复制失败', { type: ok ? 'success' : 'error' }));
      });
      bar.appendChild(copyBtn);
      return bar;
    }

    // mobile sidebar drawer
    const sidebar = document.getElementById('sessionPanel');
    const scrim = document.getElementById('cgScrim');
    const cgMenuBtn = document.getElementById('cgMenuBtn');
    function openDrawer() {
      sidebar.classList.add('drawer-open');
      scrim.hidden = false;
      requestAnimationFrame(() => scrim.classList.add('show'));
      cgMenuBtn.setAttribute('aria-expanded', 'true');
    }
    function closeDrawer() {
      sidebar.classList.remove('drawer-open');
      scrim.classList.remove('show');
      setTimeout(() => { scrim.hidden = true; }, 200);
      cgMenuBtn.setAttribute('aria-expanded', 'false');
    }
    cgMenuBtn.addEventListener('click', () => {
      if (sidebar.classList.contains('drawer-open')) closeDrawer(); else openDrawer();
    });
    scrim.addEventListener('click', closeDrawer);
    sessionList.addEventListener('click', e => {
      if (e.target.closest('.session-item') && window.innerWidth <= 820) closeDrawer();
    });
    document.getElementById('createSession').addEventListener('click', () => {
      if (window.innerWidth <= 820) closeDrawer();
    });

    // composer textarea autosize
    const promptEl = document.getElementById('prompt');
    function autosizePrompt() {
      promptEl.style.height = 'auto';
      const next = Math.min(promptEl.scrollHeight, 200);
      promptEl.style.height = next + 'px';
      promptEl.style.overflowY = promptEl.scrollHeight > 200 ? 'auto' : 'hidden';
    }
    promptEl.addEventListener('input', autosizePrompt);

    // reflect auth state into the sidebar user identity
    function reflectIdentity() {
      const authed = isAuthenticated();
      const name = authed ? '已登录用户' : '未登录';
      const un = document.getElementById('userName');
      const mn = document.getElementById('menuUserName');
      const av = document.getElementById('userAvatar');
      if (un) un.textContent = name;
      if (mn) mn.textContent = name;
      if (av) av.textContent = authed ? '用' : 'OC';
    }
    try {
      new MutationObserver(reflectIdentity).observe(
        document.getElementById('authStatus'),
        { childList: true, characterData: true, subtree: true, attributes: true }
      );
    } catch (e) {}
    reflectIdentity();

    setPreLoginView();
    refreshMe({ quiet: true });
