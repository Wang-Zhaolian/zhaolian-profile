(() => {
  const content = document.querySelector('#app-content');
  const modalHost = document.querySelector('#modal-host');
  const reviewHost = document.querySelector('#ai-review-host');
  const toastHost = document.querySelector('#toast-host');
  const state = { config: null, preferences: {ai_model:null,sorts:{}}, view: 'dashboard', category: null, archived: false, query: '', basics: null, records: [], revision: null, ai: null, models: [], aiModel: '', listMode: localStorage.getItem('academic-profile-list-mode') || 'cards', sidebarCollapsed: localStorage.getItem('academic-profile-sidebar-collapsed') === '1', review: null, showCompletedNotes: false, categoryRequest: 0 };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-Academic-Profile', 'local-ui');
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(url, { ...options, headers });
    const type = response.headers.get('content-type') || '';
    const payload = type.includes('application/json') ? await response.json() : response;
    if (!response.ok) { const message = payload.request_id ? `${payload.error || '操作未完成，请重试。'}（请求编号：${payload.request_id}）` : (payload.error || '操作未完成，请重试。'); const error = new Error(message); error.payload = payload; error.status = response.status; throw error; }
    return payload;
  };
  const toast = (message, kind = '') => { const node = document.createElement('div'); node.className = `toast ${kind ? `toast-${kind}` : ''}`; node.textContent = message; toastHost.append(node); setTimeout(() => node.remove(), 4200); };
  const labelFor = (category) => state.config.categories.find((item) => item.id === category)?.label || category;
  const navigate = (view, category = null) => { state.view = view; state.category = category; state.query = ''; state.archived = false; render(); };
  const heading = (eyebrow, title, subtitle, action = '') => `<div class="page-heading"><div><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p class="page-subtitle">${esc(subtitle)}</p></div>${action}</div>`;
  const empty = (title, note, action = '') => `<div class="empty-state"><span class="empty-icon">◇</span><strong>${esc(title)}</strong><p>${esc(note)}</p>${action}</div>`;
  const enumNames = { idea:'构思中', literature:'文献调研', method:'方法设计', experiment:'实验中', writing:'写作中', submitted:'已提交', completed:'已完成', planned:'计划中', active:'进行中', archived:'已归档', published:'已发表', accepted:'已录用', under_review:'审稿中', preprint:'预印本', manuscript:'手稿', introductory:'入门', intermediate:'中级', advanced:'高级', graduate:'研究生', Programming:'编程', ML:'机器学习', Data:'数据', Optimization:'优化', 'Research Tools':'科研工具', 'Development Tools':'开发工具', Languages:'语言' };
  const enumLabel = (value) => enumNames[value] || value.replaceAll('_',' ');

  function syncNavigation() {
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === state.view && !button.dataset.category));
    document.querySelectorAll('[data-category]').forEach((button) => button.classList.toggle('active', button.dataset.category === state.category && state.view === 'category'));
    const crumb = state.view === 'category' ? labelFor(state.category) : ({dashboard:'总览', notes:'草稿箱', basics:'个人资料', 'category-manager':'管理分类', settings:'备份与设置'}[state.view] || '总览');
    document.querySelector('#page-breadcrumb').textContent = crumb;
  }
  function buildNav() {
    const nav = document.querySelector('#category-nav');
    nav.replaceChildren();
    for (const category of state.config.categories.filter((item) => !item.archived)) {
      const button = document.createElement('button'); button.className = 'nav-item'; button.dataset.category = category.id;
      button.innerHTML = `<span class="nav-icon">${esc(category.icon)}</span><span>${esc(category.label)}</span>`;
      button.addEventListener('click', () => navigate('category', category.id)); nav.append(button);
    }
  }
  async function render() {
    syncNavigation(); content.innerHTML = '<div class="loading">正在载入…</div>';
    try {
      if (state.view === 'dashboard') await renderDashboard();
      else if (state.view === 'notes') await renderNotes();
      else if (state.view === 'basics') await renderBasics();
      else if (state.view === 'category') await renderCategory();
      else if (state.view === 'category-manager') await renderCategoryManager();
      else if (state.view === 'settings') await renderSettings();
    } catch (error) { content.innerHTML = `<div class="notice notice-warning">${esc(error.message)}</div>`; }
    syncNavigation();
  }
  async function loadAIState() {
    try {
      state.ai = await api('/api/ai/status');
      if (state.ai.connected && state.ai.sharing) {
        if (!state.models.length && !state.modelPromise) {
          state.modelPromise = loadAIModels().finally(() => { state.modelPromise = null; refreshAIControls(); });
        }
      } else state.models = [];
    } catch (error) {
      state.ai = {connected:false, error:error.message};
      state.models = [];
    }
    updateAIStatusPill();
    refreshAIControls();
    return state.ai;
  }
  async function loadAIModels() {
    try {
      const response = await api('/api/ai/models');
      if (!state.ai?.connected || !state.ai.sharing) { state.models = []; return; }
      state.models = (response.models || []).map((model) => typeof model === 'string' ? {slug:model, display_name:model} : model).filter((model) => model.slug);
    } catch (error) {
      state.models = [];
      state.ai = {...state.ai, error:error.message};
    }
  }
  function refreshAIControls() {
    const targets = [['.capture-model','capture-model'],['.notes-model-container','notes-model'],['.editor-ai-model','editor-ai-model'],['.settings-model-row','settings-model']];
    for (const [selector,id] of targets) {
      const container = document.querySelector(selector);
      if (!container) continue;
      container.innerHTML = modelPicker(id);
      rememberModel(container.querySelector(`#${id}`));
    }
    for (const id of ['#generate-quick-note','#editor-ai-generate']) {
      const button = document.querySelector(id);
      if (button) button.disabled = !aiCanGenerate();
    }
    document.querySelectorAll('[data-note-generate]').forEach((button) => { button.disabled = !aiCanGenerate(); });
    const modelCount = document.querySelector('.ai-settings-card .settings-meta .settings-row:last-child span:last-child');
    if (modelCount) modelCount.textContent = state.models.length ? `${state.models.length} 个` : '尚未获取';
    updateAIStatusPill();
  }
  function updateAIStatusPill() {
    const pill = document.querySelector('#ai-status-pill');
    const label = document.querySelector('#ai-status-text');
    pill.classList.toggle('connected', !!(state.ai?.connected && state.ai?.sharing));
    label.textContent = state.ai?.connected ? (state.ai.sharing ? 'ChatGPT 方案已授权' : (state.ai.ai_blocked ? 'ChatGPT AI 暂停' : 'ChatGPT 尚未授予方案权限')) : 'ChatGPT 未连接';
  }
  const selectedModel = () => state.aiModel ? (state.models.some((model) => model.slug === state.aiModel) ? state.aiModel : '') : (state.models[0]?.slug || '');
  const aiCanGenerate = () => !!(state.ai?.connected && state.ai?.sharing && selectedModel());
  function modelPicker(id) {
    if (!state.ai?.connected) return '<span class="field-hint">连接 ChatGPT 后可生成候选记录；保存笔记无需网络。</span>';
    if (!state.ai.sharing) return `<span class="field-hint">${esc(state.ai.error || '此账号尚未授予 ChatGPT 方案使用权限。')} 笔记仍可保存在本机。</span>`;
    if (!state.models.length) return `<span class="field-hint">${esc(state.aiModel?`已保存模型“${state.aiModel}”；模型列表暂不可用，暂时不能整理。`:'模型列表暂不可用，请到设置页刷新连接状态。')}</span>`;
    const unavailable = state.aiModel && !state.models.some((model) => model.slug === state.aiModel);
    return `<label class="model-picker">模型 <select id="${esc(id)}" class="field-control compact-select" aria-label="选择 ChatGPT 模型">${unavailable?`<option value="" selected disabled>已保存模型不可用，请手动选择</option>`:''}${state.models.map((model) => `<option value="${esc(model.slug)}" ${(state.aiModel?state.aiModel===model.slug:selectedModel()===model.slug)?'selected':''}>${esc(model.display_name || model.slug)}</option>`).join('')}</select></label>${unavailable?'<span class="field-hint">已暂停 AI 整理；请选择可用模型后继续。</span>':''}<a class="text-link" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">管理用量 ↗</a>`;
  }
  function rememberModel(select) {
    if (!select) return;
    select.addEventListener('change', async () => {
      const previous = state.aiModel;
      select.disabled = true;
      try {
        state.preferences = await api('/api/preferences', {method:'PATCH', body:JSON.stringify({ai_model:select.value})});
        state.aiModel = state.preferences.ai_model || '';
        toast('模型选择已保存在本机。','success');
      } catch (error) {
        state.aiModel = previous;
        toast(`模型设置未保存：${error.message}`,'error');
      }
      refreshAIControls();
    });
  }

  async function loadPreferences() {
    try {
      state.preferences = await api('/api/preferences');
      state.aiModel = state.preferences.ai_model || '';
      if (!state.aiModel) {
        let legacy = '';
        try { legacy = localStorage.getItem('academic-profile-ai-model') || ''; } catch (_) {}
        if (legacy) {
          try {
            state.preferences = await api('/api/preferences', {method:'PATCH', body:JSON.stringify({ai_model:legacy})});
            state.aiModel = state.preferences.ai_model || '';
            try { localStorage.removeItem('academic-profile-ai-model'); } catch (_) {}
          } catch (error) { toast(`旧模型选择迁移失败：${error.message}`,'error'); }
        }
      }
    } catch (error) {
      toast(`本机偏好设置暂不可读取：${error.message}`,'error');
    }
  }
  async function saveNote(text, files = []) {
    const clean = text.trim();
    if (!clean && !files.length) throw new Error('请先输入文字或选择图片、文档。');
    let body;
    if (files.length) {
      body = new FormData(); body.append('text', clean);
      for (const file of files) body.append('files', file, file.name);
    } else body = JSON.stringify({text:clean});
    const response = await api('/api/ai/notes', {method:'POST', body});
    return response.note || response;
  }
  async function generateProposals(noteId, attachmentIds = []) {
    if (!state.ai?.connected || !state.ai.sharing) throw new Error('请先在「备份与设置」连接并授权使用 ChatGPT 方案。笔记仍可保存在本机。');
    const model = selectedModel();
    if (!model) throw new Error('暂时没有可用的 ChatGPT 模型，请在设置页刷新连接状态。');
    try { return await api('/api/ai/proposals', {method:'POST', body:JSON.stringify({note_id:noteId, model, attachment_ids:attachmentIds})}); }
    catch (error) {
      if (['subscription_sharing_user_not_eligible','subscription_sharing_usage_limit_exceeded','subscription_sharing_invalid_user','chatpass_v2_scope_not_authorized'].includes(error.payload?.code)) await loadAIState();
      throw error;
    }
  }
  function aiDisclosure() {
    return '<p class="ai-disclosure">点击 ChatGPT 整理时，本次文字、你选中的附件，以及资料库各分类的学术文字（包括草稿）会发送给 ChatGPT。不会发送联系方式、未选中的附件、本机路径或旧笔记。原始附件仍保存在本机；识读结果需要你核对后再采纳。</p>';
  }
  async function renderDashboard() {
    const data = await api('/api/dashboard');
    const cards = data.counts.map((item) => `<button class="category-card" data-open-category="${esc(item.id)}" data-category-name="${esc(item.label.toLocaleLowerCase())}"><span class="category-glyph">${esc(item.icon || '类')}</span><span class="category-card-copy"><span class="category-name">${esc(item.label)}</span><span class="category-count">${item.count} 条</span></span><span class="category-arrow">›</span></button>`).join('');
    content.innerHTML = `${heading('昭濂个人履历库', '履历分类', '点击分类开始录入经历。','<button class="button button-primary" data-view="category-manager">管理分类</button>')}<label class="search-box category-filter"><span class="search-icon">⌕</span><input id="dashboard-category-search" type="search" placeholder="检索分类名称"></label><section class="panel dashboard-categories"><div class="category-grid">${cards}</div><div id="dashboard-search-empty" class="empty-state" hidden><strong>没有匹配的分类</strong></div></section>`;
    bindOpenCategory();
    content.querySelector('#dashboard-category-search').addEventListener('input',(event)=>{
      const query=event.target.value.trim().toLocaleLowerCase();let visible=0;
      content.querySelectorAll('[data-open-category]').forEach((card)=>{const matches=card.dataset.categoryName.includes(query);card.hidden=!matches;if(matches)visible++;});
      content.querySelector('#dashboard-search-empty').hidden=visible>0;
    });
  }
  function draftCapture() {
    return `<section class="capture-panel" aria-labelledby="capture-title"><div class="capture-copy"><p class="eyebrow">草稿箱</p><h2 id="capture-title">先记下来，再慢慢整理。</h2><p>文字、图片或文档可以放在同一条草稿中；需要时再交给 ChatGPT 整理成待审核候选。</p></div><label class="sr-only" for="quick-note">原始文字</label><textarea id="quick-note" class="capture-input" placeholder="可以写一段经历，也可以只添加附件，之后再慢慢补充……"></textarea><div class="capture-attachments"><label class="button button-small file-select">添加图片或文档<input id="quick-files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.xlsx,.pptx"></label><span id="quick-file-names" class="field-hint">支持 PNG、JPG、WEBP、PDF、Word、Excel、PowerPoint、TXT 和 Markdown。</span></div><div class="capture-footer"><div class="capture-actions"><button id="save-quick-note" class="button" type="button">保存到草稿箱</button><button id="generate-quick-note" class="button button-primary" type="button" ${aiCanGenerate()?'':'disabled'}>用 ChatGPT 整理 ↗</button></div><div class="capture-model">${modelPicker('capture-model')}</div></div>${aiDisclosure()}</section>`;
  }
  function bindDraftCapture() {
    const textarea = content.querySelector('#quick-note');
    const fileInput = content.querySelector('#quick-files');
    fileInput?.addEventListener('change', () => {
      const names = Array.from(fileInput.files || []).map((file) => file.name);
      content.querySelector('#quick-file-names').textContent = names.length ? `已选 ${names.length} 个文件：${names.join('、')}` : '支持 PNG、JPG、WEBP、PDF、Word、Excel、PowerPoint、TXT 和 Markdown。';
    });
    rememberModel(content.querySelector('#capture-model'));
    const save = content.querySelector('#save-quick-note');
    const generate = content.querySelector('#generate-quick-note');
    const run = async (doGenerate) => {
      const button = doGenerate ? generate : save;
      button.disabled = true;
      button.textContent = doGenerate ? '正在整理…' : '正在保存…';
      let note;
      try {
        note = await saveNote(textarea.value, Array.from(fileInput?.files || []));
      } catch (error) {
        toast(error.message, 'error');
        button.disabled = doGenerate && !aiCanGenerate();
        button.textContent = doGenerate ? '用 ChatGPT 整理 ↗' : '保存到草稿箱';
        return;
      }
      textarea.value = '';
      if (fileInput) { fileInput.value = ''; content.querySelector('#quick-file-names').textContent = '支持 PNG、JPG、WEBP、PDF、Word、Excel、PowerPoint、TXT 和 Markdown。'; }
      toast('原始资料已保存在本机草稿箱。', 'success');
      if (doGenerate) {
        if ((note.attachments || []).reduce((total, file) => total + file.size, 0) > 50 * 1024 * 1024) {
          toast('资料已保存在本机；所选附件超过 ChatGPT 单次限制，请到草稿箱分批整理。', 'error');
        } else {
          try { openProposalReview(await generateProposals(note.id, (note.attachments || []).map((file) => file.id)), note); }
          catch (error) { toast(`笔记已保存，AI 整理未完成：${error.message}`, 'error'); }
        }
      }
      button.disabled = doGenerate && !aiCanGenerate();
      button.textContent = doGenerate ? '用 ChatGPT 整理 ↗' : '保存到草稿箱';
    };
    save.addEventListener('click', () => run(false));
    generate.addEventListener('click', () => run(true));
  }
  function bindNavigation() { /* Navigation is delegated to document.body. */ }
  function bindOpenCategory() { content.querySelectorAll('[data-open-category]').forEach((button) => button.addEventListener('click', () => navigate('category', button.dataset.openCategory))); }
  function bindEditButtons() { content.querySelectorAll('[data-edit-id]').forEach((button) => button.addEventListener('click', () => openRecord(button.dataset.editCategory, button.dataset.editId))); }

  async function renderNotes() {
    loadAIState();
    const result = await api('/api/ai/notes');
    const allNotes = result.notes || [];
    const notes = allNotes.filter((note) => !note.completed);
    const noteCards = notes.length ? notes.map((note) => {
      const attachments = note.attachments || [];
      const choices = attachments.map((file) => `<label class="note-attachment-choice"><input type="checkbox" data-attachment-id="${esc(file.id)}" data-size="${Number(file.size)||0}" checked><span>${esc(file.name)}</span><small>${formatBytes(file.size)}</small></label>`).join('');
      const batches = (note.batches || []).filter(batch=>batch.pending_candidates>0).map((batch) => `<button class="button button-small" data-open-batch="${esc(note.id)}" data-batch-id="${esc(batch.id)}">审核候选 · ${Number(batch.pending_candidates||0)} 条待处理</button>`).join('');
      return `<article class="note-card" data-note-id="${esc(note.id)}"><div class="note-card-top"><span class="note-date">${esc(note.created_at || '本机草稿')}</span><span class="badge">${note.completed?'已完成 · 本机历史':'草稿箱 · 仅保存在本机'}</span></div><p class="note-preview">${esc(note.preview || '仅有附件，可点击查看')}</p>${attachments.length?`<div class="note-attachments"><strong>${attachments.length} 个附件 · 默认全部发送</strong>${choices}</div>`:''}<div class="note-card-actions"><button class="button button-small" data-note-detail="${esc(note.id)}">查看原始内容</button><button class="button button-small button-soft" data-note-generate="${esc(note.id)}" ${aiCanGenerate()?'':'disabled'}>用 ChatGPT 整理 ↗</button>${note.completed?'<button class="button button-small" data-note-complete="0">恢复到待处理</button>':'<button class="button button-small" data-note-complete="1">全部处理完成</button>'}</div>${batches?`<div class="note-batches">${batches}</div>`:''}<div class="note-full" hidden></div></article>`;
    }).join('') : empty(state.showCompletedNotes?'还没有处理历史':'草稿箱还是空的','添加文字、图片或文档；原始素材只保存在本机。');
    const pendingCount = allNotes.filter((note) => !note.completed).length;
    const tabs = `<div class="note-tabs"><span class="badge">${pendingCount} 条待处理</span><span class="field-hint">采纳后从草稿箱移除；部分成功时保留未处理项。</span></div>`;
    content.innerHTML = `${heading('本机草稿', '草稿箱', '原始文字和附件只保存在本机；点击 ChatGPT 整理时，仅所选内容会发送给 ChatGPT。')}${draftCapture()}${tabs}${aiDisclosure()}<div class="notes-grid">${noteCards}</div>`;
    rememberModel(content.querySelector('#notes-model'));
    bindDraftCapture();
    content.querySelectorAll('[data-note-tab]').forEach((button) => button.addEventListener('click', () => { state.showCompletedNotes = button.dataset.noteTab === '1'; renderNotes(); }));
    for (const button of content.querySelectorAll('[data-note-complete]')) button.addEventListener('click', async () => {
      try { if (button.dataset.noteComplete === '1' && !confirm('确认这条资料已全部处理并从草稿箱移除？尚未采纳的候选不会入库。原件仅留作本机恢复，不再显示在草稿箱。')) return; await api(`/api/ai/notes/${encodeURIComponent(button.closest('.note-card').dataset.noteId)}/status`, {method:'POST', body:JSON.stringify({completed:button.dataset.noteComplete==='1'})}); await renderNotes(); }
      catch (error) { toast(error.message, 'error'); }
    });
    for (const button of content.querySelectorAll('[data-note-detail]')) button.addEventListener('click', async () => {
      const card = button.closest('.note-card'); const detail = card.querySelector('.note-full');
      if (!detail.hidden) { detail.hidden = true; button.textContent = '查看素材'; return; }
      try { const response = await api(`/api/ai/notes/${encodeURIComponent(button.dataset.noteDetail)}`); const note = response.note || response; const files=(note.attachments||[]).map((file)=>`<li><a href="/api/ai/notes/${encodeURIComponent(note.id)}/attachments/${encodeURIComponent(file.id)}">${esc(file.name)}</a> · ${formatBytes(file.size)}</li>`).join(''); detail.innerHTML = `${note.text?`<pre>${esc(note.text)}</pre>`:'<p class="field-hint">这条草稿没有附加文字。</p>'}${files?`<ul class="note-downloads">${files}</ul>`:''}`; detail.hidden = false; button.textContent = '收起原始内容'; }
      catch (error) { toast(error.message, 'error'); }
    });
    for (const button of content.querySelectorAll('[data-open-batch]')) button.addEventListener('click', async () => {
      try { const response = await api(`/api/ai/notes/${encodeURIComponent(button.dataset.openBatch)}`); const batch = (response.batches||[]).find((item)=>item.id===button.dataset.batchId); if (!batch) throw new Error('没有找到这批候选记录。'); const pending=(batch.candidates||[]).filter((item)=>item.status==='pending'); if (!pending.length) { toast('这批候选已经处理完成。','success'); return; } openProposalReview({candidates:pending,batch_id:batch.id,context_mode:'saved',records_count:0},response.note); }
      catch (error) { toast(error.message, 'error'); }
    });
    for (const button of content.querySelectorAll('[data-note-generate]')) button.addEventListener('click', async () => {
      button.disabled = true; button.textContent = '正在整理…';
      try { const card=button.closest('.note-card'); const selected=[...card.querySelectorAll('[data-attachment-id]:checked')]; const size=selected.reduce((total,input)=>total+Number(input.dataset.size||0),0); if(size>50*1024*1024) throw new Error('所选附件超过 ChatGPT 单次 50 MB 限制。请取消部分附件，或拆分文件后分批上传。'); const result = await generateProposals(button.dataset.noteGenerate, selected.map((input)=>input.dataset.attachmentId)); openProposalReview(result, {id:button.dataset.noteGenerate}); }
      catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = !aiCanGenerate(); button.textContent = '用 ChatGPT 整理 ↗'; }
    });
  }

  function formatBytes(value) { const bytes=Number(value)||0; return bytes<1024*1024?`${Math.max(1,Math.round(bytes/1024))} KB`:`${(bytes/1024/1024).toFixed(1)} MB`; }

  async function renderBasics() {
    const result = await api('/api/basics'); state.basics = result;
    const basics = result.basics || {}; const contact = result.contact || {};
    content.innerHTML = `${heading('关于你', '个人资料', '填写中文资料；联系方式和电话号码只保存在本机。')}<form id="basics-form" class="profile-card"><div class="form-grid"><h2 class="form-section-title">基本资料</h2>${inputField('name_zh','中文姓名','text',basics.name_zh,'例如：昭濂',true)}${inputField('headline_zh','中文简介','text',basics.headline_zh,'例如研究方向或当前身份',true)}${inputField('research_interests','研究兴趣（每行一项）','list',(basics.research_interests||[]).join('\n'),'可选',true)}<h2 class="form-section-title">联系方式（只保存在本机）</h2>${inputField('email','电子邮箱','email',contact.email,'')}${inputField('phone','电话号码','tel',contact.phone,'可选，支持国家区号')}${inputField('website','个人网站','url',contact.website,'https://…')}${inputField('github','GitHub','text',contact.github,'GitHub 用户名或网址')}${inputField('location','所在地','text',contact.location,'')}</div><div class="form-footer"><span class="form-footer-note">保存后写入本机数据</span><div class="form-footer-actions"><button class="button button-primary" type="submit">保存个人资料</button></div></div></form>`;
    const form = content.querySelector('#basics-form'); form.addEventListener('submit', async (event) => { event.preventDefault(); clearErrors(form); const values = formValues(form); const value=(key)=>form.elements[key]?.value.trim()||''; try { const saved = await api('/api/basics', {method:'POST', body:JSON.stringify({revision:result.revision, basics:{name_zh:value('name_zh'),headline_zh:value('headline_zh'),research_interests:values.research_interests||[]},contact:{email:value('email'),phone:value('phone'),website:value('website'),github:value('github'),location:value('location')}})}); state.basics.revision=saved.revision; toast('个人资料已保存在本机。','success'); } catch(error) { showFormError(form,error); } });
  }
  function inputField(key, label, type, value='', placeholder='', full=false, required=false) { const control = type === 'list' ? `<textarea class="field-control" name="${esc(key)}" data-type="list" placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : `<input class="field-control" name="${esc(key)}" type="${esc(type)}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${required?'required':''}>`; return `<label class="field ${full?'full':''}" data-field="${esc(key)}"><span class="field-label">${esc(label)}${required?' *':''}</span>${control}<span class="field-error"></span></label>`; }

  async function renderCategoryManager() {
    const categories = state.config.all_categories || state.config.categories;
    const typeNames = {text:'短文本',textarea:'长文本',date:'日期',number:'数字',list:'多行列表',select:'单选',multiselect:'多选',bool:'是／否',url:'网址',map:'键值列表'};
    const cards = categories.map((category) => {
      const fields = (category.fields || []).filter((field) => !field.deleted && !field.key.endsWith('_en') && !field.label.includes('英文')).sort((a,b)=>a.order-b.order);
      const fieldRows = fields.map((field) => {
        const currentType = field.type;
        const kinds = ['text','textarea','date','number','list','select','multiselect'];
        if (!kinds.includes(currentType)) kinds.unshift(currentType);
        const options = kinds.map((kind) => `<option value="${esc(kind)}" ${currentType===kind?'selected':''}>${esc(typeNames[kind]||(kind.startsWith('relation')?'关联'+labelFor(kind.split(':')[1]):'其他'))}</option>`).join('');
        return `<div class="managed-field" data-managed-field="${esc(field.key)}"><input class="field-control" name="label" value="${esc(field.label)}" aria-label="字段名称"><select class="field-control" name="type" aria-label="字段类型">${options}</select><input class="field-control field-options" name="options" value="${esc((field.options||[]).map(enumLabel).join('，'))}" placeholder="单选选项，用逗号分隔" aria-label="单选选项"><label class="toggle"><input type="checkbox" name="required" ${field.required?'checked':''} ${field.key===category.title_field||currentType==='date'?'disabled':''}>必填</label><label class="toggle"><input type="checkbox" name="active" ${field.active!==false?'checked':''} ${field.key===category.title_field?'disabled':''}>启用</label><label class="toggle"><input type="checkbox" name="advanced" ${field.advanced?'checked':''}>更多内容</label><input class="field-control field-order" name="order" type="number" value="${Number(field.order||0)}" aria-label="字段顺序"><button class="button button-small" type="button" data-delete-field ${field.key===category.title_field?'disabled title="请保留名称字段，可修改名称"':''}>删除</button></div>`;
      }).join('');
      return `<details class="managed-category" data-settings-category="${esc(category.id)}" data-settings-revision="${esc(state.config.revision)}"><summary><span class="category-glyph">${esc(category.icon||'类')}</span><strong>${esc(category.label)}</strong><span class="badge">${fields.length} 个字段</span><span class="badge ${category.archived?'badge-draft':'badge-ready'}">${category.archived?'已归档':'使用中'}</span></summary><div class="managed-category-body"><div class="managed-category-settings"><label class="field"><span class="field-label">分类名称</span><input class="field-control" name="category-label" value="${esc(category.label)}"></label><label class="field"><span class="field-label">显示顺序</span><input class="field-control" name="category-order" type="number" value="${Number(category.order||0)}"></label><label class="toggle"><input type="checkbox" name="category-archived" ${category.archived?'checked':''}>归档此分类</label><button class="button button-small button-primary" type="button" data-save-category="${esc(category.id)}">保存设置</button></div><p class="field-hint">新增、删除、排序和修改统一在“保存设置”时生效。删除字段不抹除历史值；记录名称字段需保留。</p><div class="managed-fields">${fieldRows}</div><form class="add-field-form" data-category-id="${esc(category.id)}"><strong>添加表单项目</strong><input class="field-control" name="label" placeholder="例如：研究阶段" required><select class="field-control" name="type"><option value="text">短文本</option><option value="textarea">长文本</option><option value="date">日期</option><option value="number">数字</option><option value="list">多行列表</option><option value="select">单选</option><option value="multiselect">多选</option></select><input class="field-control field-options" name="options" placeholder="单选选项，用逗号分隔"><label class="toggle"><input type="checkbox" name="required">整理完成时必填</label><button class="button button-small" type="submit">添加项目</button></form></div></details>`;
    }).join('');
    content.innerHTML = `${heading('自定义履历结构', '管理分类与表单', '分类和字段设置会保存在本机，也会包含在 GitHub 备份中。字段内容会参与 AI 整理与备份。','<button class="button" data-view="dashboard">返回分类</button>')}<label class="search-box category-filter"><span class="search-icon">⌕</span><input id="category-manager-search" type="search" placeholder="检索分类名称"></label><form id="new-category-form" class="new-category-form"><input class="field-control" name="label" placeholder="新分类名称" required maxlength="40"><button class="button button-primary" type="submit">新增分类</button></form><div class="managed-category-list">${cards}</div><div id="category-manager-search-empty" class="empty-state" hidden><strong>没有匹配的分类</strong></div>`;
    content.querySelector('#category-manager-search').addEventListener('input',(event)=>{
      const query=event.target.value.trim().toLocaleLowerCase();let visible=0;
      content.querySelectorAll('.managed-category').forEach((card)=>{const matches=card.querySelector('summary strong').textContent.toLocaleLowerCase().includes(query);card.hidden=!matches;if(matches)visible++;});
      content.querySelector('#category-manager-search-empty').hidden=visible>0;
    });
    content.querySelector('#new-category-form').addEventListener('submit', async (event) => {
      event.preventDefault(); const label=event.currentTarget.elements.label.value.trim();
      if(content.querySelector('.managed-category[data-dirty="1"]')&&!confirm('其他分类有未保存修改，新增分类将重新载入页面。是否继续？'))return;
      try { await api('/api/categories',{method:'POST',body:JSON.stringify({label,revision:state.config.revision})}); await refreshConfiguration(); await renderCategoryManager(); toast('分类已新增。','success'); }
      catch(error){toast(error.message,'error');}
    });
    content.querySelectorAll('[data-save-category]').forEach((button)=>button.addEventListener('click', async()=>{
      const card=button.closest('.managed-category');
      const addForm=card.querySelector('.add-field-form');
      if(addForm.elements.label.value.trim()) addForm.requestSubmit();
      const category=state.config.all_categories.find(item=>item.id===button.dataset.saveCategory);
      const rows=[...card.querySelectorAll('.managed-field')];
      const fields=rows.map(row=>{
        const values=formValues(row);const key=row.dataset.managedField;const original=category.fields.find(item=>item.key===key);
        const options=values.options.split(/[,，]/).map(item=>item.trim()).filter(Boolean).map(label=>(original?.options||[]).find(option=>enumLabel(option)===label)||label);
        return {...values,options,...(key?{key}:{}),deleted:row.dataset.deleted==='1',required:values.type==='date'?false:values.required};
      });
      const payload={revision:card.dataset.settingsRevision,label:card.querySelector('[name="category-label"]').value.trim(),order:Number(card.querySelector('[name="category-order"]').value),archived:card.querySelector('[name="category-archived"]').checked,fields};
      button.disabled=true;
      try {
        const result=await api(`/api/categories/${encodeURIComponent(button.dataset.saveCategory)}/settings`,{method:'POST',body:JSON.stringify(payload)});
        const oldKeys=new Set(category.fields.map(field=>field.key));const added=result.category.fields.filter(field=>!oldKeys.has(field.key));
        rows.filter(row=>!row.dataset.managedField&&!row.dataset.deleted).forEach((row,index)=>row.dataset.managedField=added[index].key);
        rows.filter(row=>row.dataset.deleted==='1').forEach(row=>row.remove());
        content.querySelectorAll('.managed-category').forEach(item=>{if(item.dataset.settingsRevision===payload.revision)item.dataset.settingsRevision=result.revision;});
        card.dataset.dirty='';card.querySelector('summary strong').textContent=result.category.label;
        const badges=card.querySelectorAll('summary .badge');badges[0].textContent=`${card.querySelectorAll('.managed-field').length} 个字段`;badges[1].textContent=result.category.archived?'已归档':'使用中';
        await refreshConfiguration();toast('本分类的全部设置已保存。','success');
      }
      catch(error){toast(error.message,'error');}
      finally{button.disabled=false;}
    }));
    content.querySelectorAll('.managed-category').forEach(card=>{
      card.addEventListener('input',()=>card.dataset.dirty='1');
      card.addEventListener('change',event=>{if(event.target.name==='type'){const row=event.target.closest('.managed-field')||event.target.closest('form');const required=row.querySelector('[name="required"]');required.disabled=event.target.value==='date';if(required.disabled)required.checked=false;}});
      card.addEventListener('click',event=>{const button=event.target.closest('[data-delete-field]');if(!button)return;const row=button.closest('.managed-field');card.dataset.dirty='1';if(!row.dataset.managedField){row.remove();return;}row.dataset.deleted=row.dataset.deleted==='1'?'':'1';row.classList.toggle('field-pending-delete',row.dataset.deleted==='1');button.textContent=row.dataset.deleted==='1'?'撤销删除':'删除';});
    });
    content.querySelectorAll('.add-field-form').forEach((form)=>form.addEventListener('submit',(event)=>{
      event.preventDefault();const values=formValues(form);if(!values.label)return;
      const card=form.closest('.managed-category');const rows=card.querySelector('.managed-fields');
      const order=Math.max(-1,...[...rows.querySelectorAll('[name="order"]')].map(input=>Number(input.value)))+1;
      rows.insertAdjacentHTML('beforeend',`<div class="managed-field" data-managed-field=""><input class="field-control" name="label" value="${esc(values.label)}" aria-label="字段名称"><select class="field-control" name="type">${['text','textarea','date','number','list','select','multiselect'].map(kind=>`<option value="${kind}" ${kind===values.type?'selected':''}>${typeNames[kind]}</option>`).join('')}</select><input class="field-control field-options" name="options" value="${esc(values.options)}" placeholder="选项，用逗号分隔"><label class="toggle"><input type="checkbox" name="required" ${values.required&&values.type!=='date'?'checked':''} ${values.type==='date'?'disabled':''}>必填</label><label class="toggle"><input type="checkbox" name="active" checked>启用</label><label class="toggle"><input type="checkbox" name="advanced">更多内容</label><input class="field-control field-order" name="order" type="number" value="${order}" aria-label="字段顺序"><button class="button button-small" type="button" data-delete-field>删除</button></div>`);
      card.dataset.dirty='1';form.reset();toast('已加入本次设置，点击上方“保存设置”生效。');
    }));
  }
  async function refreshConfiguration() { state.config = await api('/api/config'); buildNav(); }
  function formValues(form) { const out={}; form.querySelectorAll('[name]').forEach((input) => { if (input.type === 'checkbox') out[input.name]=input.checked; else if (input.multiple) out[input.name]=Array.from(input.selectedOptions).map(o=>o.value); else if (input.dataset.type === 'list') out[input.name]=input.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean); else if (input.dataset.type === 'map') out[input.name]=Object.fromEntries(input.value.split(/\r?\n/).map(s=>s.split(/:(.+)/,2)).filter(pair=>pair.length===2&&pair[0].trim()).map(pair=>[pair[0].trim(),pair[1].trim()])); else out[input.name]=input.value.trim()===''?'':(input.type==='number'?Number(input.value):input.value.trim()); }); return out; }
  function clearErrors(form) { form.querySelectorAll('.field').forEach((field) => field.classList.remove('has-error')); const global = form.querySelector('[data-global-error]'); if (global) global.remove(); }
  function showFormError(form,error) { clearErrors(form); if (error.payload?.field_errors) { for (const [name,message] of Object.entries(error.payload.field_errors)) { const field=form.querySelector(`[data-field="${CSS.escape(name)}"]`); if(field){field.classList.add('has-error');field.querySelector('.field-error').textContent=message;} } } const message=error.payload?.error || (error.status===409?'资料已在另一个窗口更新。请返回列表重新打开，再保存。':error.message); const note=document.createElement('div'); note.className='notice notice-warning'; note.dataset.globalError='1'; note.textContent=message; form.prepend(note); }

  async function renderCategory({preserveSearch=false}={}) {
    const category=state.category; const meta=state.config.categories.find((item)=>item.id===category); const requestId=++state.categoryRequest;
    const savedSort=state.preferences.sorts?.[category]||{};
    const params=new URLSearchParams({archived:state.archived?'1':'0',q:state.query});
    if(savedSort.sort_by){params.set('sort_by',savedSort.sort_by);params.set('sort_direction',savedSort.direction||'asc');}
    let result;
    try { result=await api(`/api/records/${category}?${params}`); }
    catch(error) {
      if(savedSort.sort_by&&error.status===400){state.preferences=await api('/api/preferences');return renderCategory({preserveSearch});}
      throw error;
    }
    if(requestId!==state.categoryRequest||state.view!=='category'||state.category!==category)return;
    state.records=result.records; state.revision=result.revision;
    const definition=state.config.fields[category]||[];
    const previewFields=definition.slice(0,5);
    const searchLabel=previewFields[0]?.label||'名称';
    const effectiveSort=(result.sort_fields||[]).some(field=>field.key===savedSort.sort_by)?savedSort:{};
    if(savedSort.sort_by&&!effectiveSort.sort_by){
      api('/api/preferences',{method:'PATCH',body:JSON.stringify({sorts:{[category]:{sort_by:''}}})}).then(value=>{state.preferences=value;}).catch(error=>toast(`分类排序设置未清除：${error.message}`,'error'));
    }
    const displayValue=(record,field)=>{const value=record[field.key];if(value===undefined||value===null||value===''||(Array.isArray(value)&&!value.length))return '未填写';if(typeof value==='boolean')return value?'是':'否';if(Array.isArray(value))return value.map(item=>enumLabel(String(item))).join('、');if(typeof value==='object')return Object.entries(value).map(([key,item])=>`${key}：${item}`).join('；');return enumLabel(String(value));};
    const preview=record=>({title:previewFields[0]?displayValue(record,previewFields[0]):'未填写',details:previewFields.slice(1).map(field=>`<span class="record-preview-line"><span>${esc(field.label)}：</span>${esc(displayValue(record,field))}</span>`).join('')});
    const badge=record=>`<span class="badge ${record.record_state==='draft'?'badge-draft':'badge-ready'}">${record.record_state==='draft'?'待完善':'已整理'}</span>`;
    const action=record=>`<button class="button button-small" data-action-id="${esc(record.id)}" data-action="${state.archived?'restore':'archive'}">${state.archived?'恢复':'归档'}</button>`;
    const noResults=state.query?'没有匹配结果':state.archived?'没有已归档记录':'这个分类还没有记录';
    const noResultsNote=state.query?'试试其他名称关键词。':state.archived?'归档记录会保留在这里，可随时恢复。':'点击“新增记录”开始录入。';
    const rows=result.records.length ? result.records.map(record=>{const p=preview(record);return `<tr data-open-id="${esc(record.id)}" tabindex="0"><td><span class="table-primary">${esc(p.title)}</span><div class="table-secondary">${p.details}</div></td><td>${badge(record)}</td><td>${action(record)}</td></tr>`;}).join('') : `<tr><td colspan="3">${empty(noResults,noResultsNote)}</td></tr>`;
    const cards=result.records.map(record=>{const p=preview(record);return `<article class="record-card" data-open-id="${esc(record.id)}" tabindex="0" role="button" aria-label="打开 ${esc(p.title)}"><div class="record-card-top">${badge(record)}</div><h2>${esc(p.title)}</h2><div class="record-preview">${p.details}</div><div class="record-card-bottom"><span class="record-card-id">${esc(meta.label)}</span>${action(record)}</div></article>`;}).join('');
    const recordsContent=state.listMode==='cards' ? (cards?`<section class="record-card-grid">${cards}</section>`:empty(noResults,noResultsNote)) : `<section class="list-panel"><table class="record-table"><thead><tr><th>记录 · 表单前五项</th><th>状态</th><th></th></tr></thead><tbody>${rows}</tbody></table></section>`;
    const sortOptions=(result.sort_fields||[]).map(field=>`<option value="${esc(field.key)}" ${effectiveSort.sort_by===field.key?'selected':''}>${esc(field.label)}${field.type==='date'?'（日期）':'（数字）'}</option>`).join('');
    content.innerHTML=`${heading('履历分类',meta.label,'记录保存在本机；可先保存为待完善草稿，之后再补充。',`<button id="new-record" class="button button-primary">＋ 新增记录</button>`)}<div class="list-toolbar"><label class="search-box"><span class="search-icon">⌕</span><input id="record-search" type="search" placeholder="搜索${esc(searchLabel)}" value="${esc(state.query)}"></label><label class="sort-control">排序依据 <select id="record-sort-field" class="field-control compact-select"><option value="">默认顺序</option>${sortOptions||'<option value="" disabled>暂无可排序字段</option>'}</select></label>${(result.sort_fields||[]).length?`<label class="sort-control">顺序 <select id="record-sort-direction" class="field-control compact-select"><option value="asc" ${effectiveSort.direction!=='desc'?'selected':''}>升序</option><option value="desc" ${effectiveSort.direction==='desc'?'selected':''}>降序</option></select></label>`:''}<label class="toggle"><input id="show-archived" type="checkbox" ${state.archived?'checked':''}>显示已归档</label><div class="view-switch" role="group" aria-label="记录显示方式"><button class="view-switch-button ${state.listMode==='cards'?'selected':''}" type="button" data-list-mode="cards" aria-pressed="${state.listMode==='cards'}">卡片</button><button class="view-switch-button ${state.listMode==='list'?'selected':''}" type="button" data-list-mode="list" aria-pressed="${state.listMode==='list'}">列表</button></div><span class="panel-note">${result.records.length} 条</span></div>${recordsContent}`;
    if(preserveSearch){const search=content.querySelector('#record-search');search?.focus();search?.setSelectionRange(search.value.length,search.value.length);}
    content.querySelector('#new-record').addEventListener('click',()=>openRecord(category));
    const search=content.querySelector('#record-search');
    search.addEventListener('input',()=>{state.query=search.value;state.categoryRequest++;clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>renderCategory({preserveSearch:true}),180);});
    content.querySelector('#show-archived').addEventListener('change',(event)=>{state.archived=event.target.checked;renderCategory();});
    const saveSort=async()=>{const sort_by=content.querySelector('#record-sort-field')?.value||'';const direction=content.querySelector('#record-sort-direction')?.value||'asc';try{state.preferences=await api('/api/preferences',{method:'PATCH',body:JSON.stringify({sorts:{[category]:{sort_by,direction}}})});await renderCategory();}catch(error){toast(`排序设置未保存：${error.message}`,'error');await renderCategory();}};
    content.querySelector('#record-sort-field')?.addEventListener('change',saveSort);content.querySelector('#record-sort-direction')?.addEventListener('change',saveSort);
    content.querySelectorAll('[data-list-mode]').forEach((button)=>button.addEventListener('click',()=>{state.listMode=button.dataset.listMode;localStorage.setItem('academic-profile-list-mode',state.listMode);renderCategory();}));
    content.querySelectorAll('[data-open-id]').forEach((row)=>{row.addEventListener('click',(event)=>{if(!event.target.closest('button'))openRecord(category,row.dataset.openId);});row.addEventListener('keydown',(event)=>{if(event.target.closest('button'))return;if(event.key==='Enter'||event.key===' '){event.preventDefault();openRecord(category,row.dataset.openId);}});});
    content.querySelectorAll('[data-action-id]').forEach((button)=>button.addEventListener('click',async(event)=>{event.stopPropagation();try{const action=button.dataset.action;await api(`/api/records/${category}/${button.dataset.actionId}/${action}`,{method:'POST',body:JSON.stringify({revision:result.revision})});toast(action==='archive'?'已归档。':'已恢复。','success');renderCategory();}catch(error){toast(error.message,'error');}}));
  }

  function controlFor(field, value, fieldOptions) {
    const kind=field.type; const name=esc(field.key); const safe=esc(value??''); let control='';
    if(kind==='textarea') control=`<textarea class="field-control" name="${name}">${safe}</textarea>`;
    else if(kind==='list') control=`<textarea class="field-control" name="${name}" data-type="list" placeholder="每行一项">${esc(Array.isArray(value)?value.join('\n'):'')}</textarea>`;
    else if(kind==='map') control=`<textarea class="field-control" name="${name}" data-type="map" placeholder="每行一项，格式：名称: 分数">${esc(value&&typeof value==='object'?Object.entries(value).map(([k,v])=>`${k}: ${v}`).join('\n'):'')}</textarea>`;
    else if(kind==='bool') control=`<label class="toggle"><input type="checkbox" name="${name}" ${value?'checked':''}><span>${esc(field.label)}</span></label>`;
    else if(kind==='multiselect') control=`<select class="field-control" name="${name}" multiple size="4">${(field.options||[]).map((option)=>`<option value="${esc(option)}" ${(Array.isArray(value)&&value.includes(option))?'selected':''}>${esc(enumLabel(option))}</option>`).join('')}</select>`;
    else if(kind.startsWith('relation')) { const many=kind.startsWith('relation:'); const selected=many?(value||[]):value?[value]:[]; control=`<select class="field-control" name="${name}" ${many?'multiple':''} ${many?'size="3"':''}><option value="" ${selected.length?'':'selected'}>${many?'不关联':'不关联'}</option>${(field.options||[]).map((item)=>`<option value="${esc(item.id)}" ${selected.includes(item.id)?'selected':''}>${esc(item.label)}</option>`).join('')}</select>`; }
    else if(kind.startsWith('select:')) { const multi=kind.startsWith('multiselect:'); control=`<select class="field-control" name="${name}" ${multi?'multiple size="4"':''}>${multi?'':'<option value="">请选择</option>'}${(field.options||[]).map((option)=>`<option value="${esc(option)}" ${(multi?(Array.isArray(value)&&value.includes(option)):value===option)?'selected':''}>${esc(enumLabel(option))}</option>`).join('')}</select>`; }
    else { const type=kind==='date'?'text':kind==='number'?'number':kind==='url'?'url':'text'; const pattern=kind==='date'?'placeholder="YYYY-MM 或 YYYY-MM-DD"':''; control=`<input class="field-control" name="${name}" type="${type}" value="${safe}" ${pattern}>`; }
    const isRelation=kind.startsWith('relation'); return `<div class="field ${field.advanced?'advanced-field':''} ${field.full||kind==='textarea'||kind==='list'||kind==='map'||kind==='relation'||isRelation?'full':''}" data-field="${name}"><span class="field-label">${esc(field.label)}${field.required_for_ready?' *':''}</span>${control}<span class="field-error"></span></div>`;
  }
  function editorAIPanel() {
    return `<aside class="editor-ai-panel" aria-labelledby="editor-ai-title"><div class="editor-ai-heading"><span class="ai-sparkle" aria-hidden="true">✦</span><div><p class="eyebrow">AI 辅助整理</p><h3 id="editor-ai-title">写下补充信息</h3></div></div><p class="editor-ai-intro">可以把文字、图片或文档交给 ChatGPT 整理，再逐项填入左侧表单。不会自动覆盖你已经写好的内容。</p><label class="field-label" for="editor-ai-note">本次补充资料</label><textarea id="editor-ai-note" class="field-control" placeholder="可以写补充信息，也可以只添加附件……"></textarea><label class="button button-small file-select">添加图片或文档<input id="editor-ai-files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.xlsx,.pptx"></label><span id="editor-ai-file-names" class="field-hint">可添加图片、PDF、Office、TXT 或 Markdown。</span><div class="editor-ai-actions"><button id="editor-ai-save" class="button button-small" type="button">只存素材</button><button id="editor-ai-generate" class="button button-primary button-small" type="button" ${aiCanGenerate()?'':'disabled'}>生成建议</button></div><div class="editor-ai-model">${modelPicker('editor-ai-model')}</div><div id="editor-ai-results" class="editor-ai-results">${state.ai?.error ? esc(state.ai.error) : state.ai?.connected?'建议会在这里出现；你决定是否填入。':'尚未连接 ChatGPT。可先保存笔记；如需 AI 建议，请先保存记录，再到设置页连接。'}</div>${aiDisclosure()}</aside>`;
  }
  function bindEditorAI(category, form) {
    const panel = modalHost.querySelector('.editor-ai-panel');
    const textarea = panel.querySelector('#editor-ai-note');
    const fileInput = panel.querySelector('#editor-ai-files');
    const results = panel.querySelector('#editor-ai-results');
    fileInput.addEventListener('change', () => { panel.querySelector('#editor-ai-file-names').textContent = Array.from(fileInput.files||[]).map((file)=>file.name).join('、') || '可添加图片、PDF、Office、TXT 或 Markdown。'; });
    rememberModel(panel.querySelector('#editor-ai-model'));
    const run = async (generate) => {
      const button = panel.querySelector(generate ? '#editor-ai-generate' : '#editor-ai-save');
      button.disabled = true; button.textContent = generate ? '整理中…' : '保存中…';
      try {
        const note = await saveNote(textarea.value, Array.from(fileInput.files||[]));
        textarea.value = ''; fileInput.value = ''; panel.querySelector('#editor-ai-file-names').textContent='可添加图片、PDF、Office、TXT 或 Markdown。';
        toast('补充资料已保存到本机草稿箱。', 'success');
        if (generate) {
          try {
            if ((note.attachments||[]).reduce((total,file)=>total+file.size,0)>50*1024*1024) throw new Error('附件超过 ChatGPT 单次 50 MB 限制。资料已保存；请到草稿箱选择部分附件或拆分后分批整理。');
            const proposal = await generateProposals(note.id,(note.attachments||[]).map((file)=>file.id));
            renderEditorSuggestions(category, form, results, proposal, note);
          } catch (error) { results.textContent = `笔记已保存，AI 建议未完成：${error.message}`; }
        }
      } catch (error) { results.textContent = error.message; }
      finally { button.disabled = generate && !aiCanGenerate(); button.textContent = generate ? '生成建议' : '只存笔记'; }
    };
    panel.querySelector('#editor-ai-save').addEventListener('click', () => run(false));
    panel.querySelector('#editor-ai-generate').addEventListener('click', () => run(true));
  }
  function renderEditorSuggestions(category, form, container, proposal, note) {
    const related = (proposal.candidates || []).filter((item) => item.category === category);
    const fields = state.config.fields[category] || [];
    const suggestions = related.flatMap((candidate, candidateIndex) => Object.entries(candidate.fields || {}).filter(([key]) => fields.some((field) => field.key === key)).map(([key,value]) => ({key,value,candidateIndex})));
    container.innerHTML = `<div class="editor-ai-result-title"><strong>${proposal.candidates?.length || 0} 条候选</strong><span>${related.length} 条属于当前分类</span></div>${suggestions.length ? suggestions.map((suggestion, index) => `<div class="editor-ai-suggestion"><span class="field-label">${esc(fields.find((field) => field.key === suggestion.key)?.label || suggestion.key)}</span><p>${esc(typeof suggestion.value === 'string' ? suggestion.value : JSON.stringify(suggestion.value))}</p><button type="button" class="button button-small" data-fill-index="${index}">填入表单</button></div>`).join('') : '<p class="field-hint">没有当前分类的字段建议。可以打开全部候选，分别审核。</p>'}<button type="button" class="button button-soft" id="editor-ai-review-all">审核全部候选 ↗</button>`;
    for (const button of container.querySelectorAll('[data-fill-index]')) button.addEventListener('click', () => {
      const suggestion = suggestions[Number(button.dataset.fillIndex)];
      const target = form.querySelector(`[name="${CSS.escape(suggestion.key)}"]`);
      if (!target) { toast('当前表单没有这个字段，可在全部候选中审核。', 'error'); return; }
      if (target.closest('details')) target.closest('details').open = true;
      if (target.type === 'checkbox') target.checked = !!suggestion.value;
      else if (target.multiple) for (const option of target.options) option.selected = (Array.isArray(suggestion.value) ? suggestion.value : []).includes(option.value);
      else if (Array.isArray(suggestion.value)) target.value = suggestion.value.join('\n');
      else if (suggestion.value && typeof suggestion.value === 'object') target.value = Object.entries(suggestion.value).map(([key,value]) => `${key}: ${value}`).join('\n');
      else target.value = String(suggestion.value ?? '');
      target.focus(); button.textContent = '已填入 · 可修改';
    });
    container.querySelector('#editor-ai-review-all').addEventListener('click', () => openProposalReview(proposal, note));
  }
  async function openRecord(category, id=null) {
    let original={}, fields=state.config.fields[category], revision=state.revision;
    if(id) { const result=await api(`/api/records/${category}/${id}`); original=result; fields=result.fields; revision=result.revision; }
    loadAIState();
    const main=fields.filter((field)=>!field.advanced); const advanced=fields.filter((field)=>field.advanced);
    const titleField=state.config.categories.find((item)=>item.id===category).title_field; const headingTitle=id?(original._title||'编辑记录'):'新增记录';
    modalHost.innerHTML=`<div class="modal-backdrop" role="presentation"><section class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div class="drawer-header"><div><h2 id="drawer-title" class="drawer-title">${esc(headingTitle)}</h2><p class="drawer-subtitle">${esc(labelFor(category))} · 标 * 项在整理完成时必填，可先保存草稿</p></div><button class="button button-icon" data-close aria-label="关闭">×</button></div><form id="record-form"><div class="drawer-body"><div class="form-grid">${main.map((field)=>controlFor(field,original[field.key],field)).join('')}</div>${advanced.length?`<details><summary>更多内容</summary><div class="details-fields">${advanced.map((field)=>controlFor(field,original[field.key],field)).join('')}</div></details>`:''}<div class="form-grid"><div class="field full"><span class="field-label">记录状态</span><div class="inline-controls"><label class="toggle"><input type="radio" name="record_state" value="draft" ${original.record_state!=='ready'?'checked':''}>保存为待完善</label><label class="toggle"><input type="radio" name="record_state" value="ready" ${original.record_state==='ready'?'checked':''}>整理完成</label></div><span class="field-hint">整理完成时会检查必填项目。</span></div></div></div><div class="drawer-footer"><span class="form-footer-note">${esc(original.id||'保存时自动分配稳定 ID')}</span><div class="form-footer-actions">${id?'<button class="button button-danger" type="button" data-archive>归档</button>':''}<button class="button" type="button" data-close>取消</button><button class="button button-primary" type="submit">保存记录</button></div></div></form></section></div>`;
    modalHost.querySelector('.drawer').insertAdjacentHTML('beforeend', editorAIPanel());
    const close=()=>modalHost.replaceChildren(); modalHost.querySelectorAll('[data-close]').forEach((button)=>button.addEventListener('click',close)); modalHost.querySelector('.modal-backdrop').addEventListener('click',(event)=>{if(event.target.classList.contains('modal-backdrop'))close();}); modalHost.querySelectorAll('select[multiple]').forEach((select)=>select.addEventListener('change',()=>{const placeholder=select.querySelector('option[value=""]');if(placeholder)placeholder.disabled=Array.from(select.selectedOptions).some(o=>o.value);}));
    const form=modalHost.querySelector('#record-form'); const idField=form.querySelector(`[name="${CSS.escape(titleField)}"]`); if(idField&& !idField.value)idField.placeholder='填写记录名称';
    bindEditorAI(category, form);
    form.addEventListener('submit',async(event)=>{event.preventDefault();const values=formValues(form);const checked=form.querySelector('[name="record_state"]:checked');values.record_state=checked?.value||'draft';const payload={revision,record:values};if(original.id)payload.id=original.id;try{await api(`/api/records/${category}`,{method:'POST',body:JSON.stringify(payload)});close();toast(values.record_state==='draft'?'草稿已保存在本机。':'记录已整理并保存。','success');if(state.view==='category')renderCategory();}catch(error){showFormError(form,error);}});
    const archive=modalHost.querySelector('[data-archive]'); if(archive)archive.addEventListener('click',async()=>{try{await api(`/api/records/${category}/${id}/archive`,{method:'POST',body:JSON.stringify({revision})});close();toast('已归档。','success');renderCategory();}catch(error){toast(error.message,'error');}});
  }

  function proposalField(field, value) {
    const options = field.type.startsWith('select:') ? field.type.slice(7).split(',').map((item) => item.trim()) : field.options;
    return `<div class="proposal-field">${controlFor({...field, options, advanced:false}, value, null)}<button class="button button-small" type="button" data-remove-proposal-field>删除此项</button></div>`;
  }
  function proposalCard(candidate, index) {
    const category = candidate.category;
    const valid = state.config.categories.some((item) => item.id === category);
    if (!valid) return `<article class="candidate-card"><div class="notice notice-warning">第 ${index + 1} 条建议的分类无法识别，请跳过并手动录入。</div></article>`;
    const definition = state.config.fields[category] || [];
    const candidateFields = candidate.fields || {};
    const primary = state.config.categories.find((item) => item.id === category).title_field;
    const shown = definition.filter((field) => field.key !== primary && Object.prototype.hasOwnProperty.call(candidateFields, field.key));
    const unknown = Object.keys(candidateFields).filter((key) => !definition.some((field) => field.key === key));
    const duplicates = (candidate.possible_duplicates || []).filter((item) => (typeof item === 'string' || !item.category || item.category === category));
    const options = duplicates.map((item) => { const id = typeof item === 'string' ? item : item.id; const title = typeof item === 'string' ? item : (item.title || item.id); const revision = typeof item === 'string' ? '' : (item.revision || ''); return `<option value="update:${esc(id)}:${esc(revision)}" ${revision?'':'disabled'}>更新现有：${esc(title)}${revision?'':'（版本未知，请重新整理）'}</option>`; }).join('');
    const title = candidateFields[primary] || '';
    const sources=(candidate.source_references||[]).map((source)=>`<li><a href="/api/ai/notes/${encodeURIComponent(state.review.note.id)}/attachments/${encodeURIComponent(source.attachment_id)}">${esc(source.filename||'原始附件')}</a>${source.page?` · 第 ${source.page} 页`:''}${source.excerpt?`<blockquote>${esc(source.excerpt)}</blockquote>`:''}</li>`).join('');
    return `<article class="candidate-card" data-candidate-index="${index}" data-operation-id="${esc(candidate.operation_id||'')}"><div class="candidate-top"><span class="candidate-number">${String(index + 1).padStart(2, '0')}</span><div class="candidate-identity"><label class="field-label">保存到分类<select class="field-control candidate-category-select">${state.config.categories.map(item=>`<option value="${esc(item.id)}" ${item.id===category?'selected':''}>${esc(item.label)}</option>`).join('')}</select></label><label class="field-label">${esc(definition.find(field=>field.key===primary)?.label||'记录名称')}<input class="field-control candidate-title" value="${esc(title)}" placeholder="填写名称，可修改或清空"></label></div><div><span class="candidate-result" aria-live="polite">待审核</span><button class="button button-small" type="button" data-delete-candidate>删除此记录</button></div></div>${candidate.source_excerpt?`<blockquote class="source-excerpt"><span>对应原文</span>${esc(candidate.source_excerpt)}</blockquote>`:''}${sources?`<div class="source-files"><strong>AI 识读来源 · 请对照核查</strong><ul>${sources}</ul></div>`:''}${duplicates.length?`<div class="notice notice-warning">发现 ${duplicates.length} 条可能相似的记录。请核对后选择新建或更新；不会自动合并。</div>`:''}<label class="candidate-action-label">如何处理 <select class="field-control candidate-action"><option value="new">新建草稿</option>${options}<option value="skip">暂时跳过</option><option value="discard">删除此建议</option></select></label><form class="candidate-fields" data-category="${esc(category)}"><div class="form-grid">${shown.map((field) => proposalField(field, candidateFields[field.key])).join('')}</div>${unknown.length?'<p class="field-hint">无法对应当前表单的字段未纳入保存。</p>':''}</form><div class="proposal-add"><select class="field-control proposal-add-key" aria-label="添加字段">${definition.filter(field=>field.key!==primary).map(field=>`<option value="${esc(field.key)}">${esc(field.label)}</option>`).join('')}</select><button class="button button-small" type="button" data-add-proposal-field>添加字段</button></div></article>`;
  }
  function reviewedValues(card) {
    const category=card.querySelector('.candidate-fields').dataset.category;
    const primary=state.config.categories.find(item=>item.id===category).title_field;
    return {...formValues(card.querySelector('.candidate-fields')),[primary]:card.querySelector('.candidate-title').value.trim()};
  }
  function bindProposalCard(card) {
    card.querySelector('[data-delete-candidate]').addEventListener('click',event=>{
      if(card.dataset.committed)return;
      const action=card.querySelector('.candidate-action');action.value=action.value==='discard'?'new':'discard';
      card.classList.toggle('candidate-pending-delete',action.value==='discard');event.currentTarget.textContent=action.value==='discard'?'撤销删除':'删除此记录';
    });
    card.addEventListener('click',event=>{const button=event.target.closest('[data-remove-proposal-field]');if(button&&!card.dataset.committed)button.closest('.proposal-field').remove();});
    card.querySelector('[data-add-proposal-field]').addEventListener('click',()=>{
      const key=card.querySelector('.proposal-add-key').value;const form=card.querySelector('.candidate-fields');
      if(!key||form.querySelector(`[name="${CSS.escape(key)}"]`))return;
      const field=state.config.fields[form.dataset.category].find(item=>item.key===key);
      form.querySelector('.form-grid').insertAdjacentHTML('beforeend',proposalField(field,''));
    });
    card.querySelector('.candidate-category-select').addEventListener('change',event=>{
      const index=Number(card.dataset.candidateIndex);const candidate=state.review.proposal.candidates[index];const oldCategory=card.querySelector('.candidate-fields').dataset.category;
      const category=event.target.value;const values=reviewedValues(card);const oldPrimary=state.config.categories.find(item=>item.id===oldCategory).title_field;const nextPrimary=state.config.categories.find(item=>item.id===category).title_field;
      const allowed=new Set(state.config.fields[category].map(field=>field.key));const retained=Object.fromEntries(Object.entries(values).filter(([key])=>allowed.has(key)));retained[nextPrimary]=values[oldPrimary];
      const lost=Object.keys(values).filter(key=>key!==oldPrimary&&!allowed.has(key)&&values[key]!==''&&values[key]!==false);
      if(lost.length&&!confirm('切换分类后，无法对应到新表单的字段将从本次候选中移除。原始资料不变。是否继续？')){event.target.value=oldCategory;return;}
      const updated={...candidate,category,fields:retained,possible_duplicates:[]};state.review.proposal.candidates[index]=updated;
      const node=document.createElement('div');node.innerHTML=proposalCard(updated,index);const replacement=node.firstElementChild;card.replaceWith(replacement);bindProposalCard(replacement);
    });
  }
  function openProposalReview(proposal, note) {
    const candidates = Array.isArray(proposal.candidates) ? proposal.candidates : [];
    const warnings = Array.isArray(proposal.warnings) ? proposal.warnings : [];
    state.review = {proposal, note, batchId:proposal.batch_id};
    reviewHost.innerHTML = `<div class="review-backdrop" role="presentation"><section class="review-sheet" role="dialog" aria-modal="true" aria-labelledby="review-title"><header class="review-header"><div><p class="eyebrow">AI 建议 · 人工确认</p><h2 id="review-title">逐项审核履历候选</h2><p>你检查字段和相似记录后，再保存到相应分类。</p></div><button class="button button-icon" type="button" data-review-close aria-label="关闭候选审核">×</button></header><div class="review-summary"><span class="badge badge-ready">${candidates.length} 条候选</span><span class="badge">参考 ${Number(proposal.records_count || 0)} 条本机记录</span><span class="badge">${proposal.context_mode === 'summary' ? '已用全库提纲＋相关全文' : '已参考全库学术文字'}</span></div>${proposal.context_mode === 'summary' ? '<div class="notice">资料较多：AI 收到每条记录的提纲和相关记录的全文，而不是完整的全库正文。</div>' : ''}${warnings.map((warning) => `<div class="notice notice-warning">${esc(warning)}</div>`).join('')}<div class="candidate-list">${candidates.length ? candidates.map((candidate,index) => proposalCard(candidate,index)).join('') : empty('没有可审核的建议','原始资料仍保存在本机草稿箱。你可以换一种写法后重试，或手工录入。')}</div><footer class="review-footer"><p id="review-outcome" aria-live="polite">请核对 AI 建议；未知事实留空，采纳后仍可编辑。</p><div><button class="button" type="button" data-review-close>稍后处理</button>${candidates.length?'<button id="review-save" class="button button-primary" type="button">保存已选择的记录</button>':''}</div></footer></section></div>`;
    reviewHost.querySelector('.review-summary').insertAdjacentHTML('afterend', '<div class="notice">采纳后会保存到对应分类，默认待完善；稍后处理的候选仍留在草稿箱。</div>');
    for (const card of reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')) {
      const candidate = candidates[Number(card.dataset.candidateIndex)];
      for (const warning of candidate.warnings || []) card.querySelector('.candidate-fields')?.insertAdjacentHTML('beforebegin', `<div class="notice notice-warning">${esc(warning)}</div>`);
      bindProposalCard(card);
    }
    const close = async () => {
      if(state.review?.saving)return;
      try {
        for(const card of reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')){
          if(['saved','discarded'].includes(card.dataset.result)||card.dataset.committed)continue;
          const candidate=state.review.proposal.candidates[Number(card.dataset.candidateIndex)];
          await api(`/api/ai/notes/${encodeURIComponent(note.id)}/batches/${encodeURIComponent(proposal.batch_id)}/candidates/${encodeURIComponent(candidate.operation_id)}`,{method:'POST',body:JSON.stringify({status:'pending',category:card.querySelector('.candidate-fields').dataset.category,fields:reviewedValues(card)})});
        }
      }catch(error){toast(`审核修改尚未保存：${error.message}`,'error');return;}
      reviewHost.replaceChildren();state.review=null;if(state.view==='notes')renderNotes();
    };
    reviewHost.querySelectorAll('[data-review-close]').forEach((button) => button.addEventListener('click', close));
    reviewHost.querySelector('.review-backdrop').addEventListener('click', (event) => { if (event.target.classList.contains('review-backdrop')) close(); });
    reviewHost.querySelector('#review-save')?.addEventListener('click', saveProposalSelections);
    if(reviewHost.querySelector('#review-save'))reviewHost.querySelector('#review-save').textContent='保存审核结果';
    reviewHost.querySelector('[data-review-close]').focus();
  }
  async function saveProposalSelections() {
    const button = reviewHost.querySelector('#review-save');
    const outcome = reviewHost.querySelector('#review-outcome');
    button.disabled = true; button.textContent = '正在逐条保存…';
    state.review.saving=true;
    let saved = 0; let failed = 0; let skipped = 0; let discarded = 0;
    for (const card of reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')) {
      if (['saved','deferred','discarded'].includes(card.dataset.result)) continue;
      const action = card.querySelector('.candidate-action').value;
      const indicator = card.querySelector('.candidate-result');
      const form = card.querySelector('.candidate-fields');
      const category = form.dataset.category;
      const values = reviewedValues(card);
      const candidate=state.review.proposal.candidates[Number(card.dataset.candidateIndex)];
      const statusUrl=`/api/ai/notes/${encodeURIComponent(state.review.note.id)}/batches/${encodeURIComponent(state.review.batchId)}/candidates/${encodeURIComponent(candidate.operation_id)}`;
      if (action === 'skip') { try { await api(statusUrl,{method:'POST',body:JSON.stringify({status:'pending',category,fields:values})});card.dataset.result='deferred';indicator.textContent='仍留在草稿箱';skipped++; } catch(error) { failed++;indicator.textContent=`保存失败：${error.message}`;indicator.classList.add('candidate-result-error'); } continue; }
      if (action === 'discard') { try { await api(statusUrl,{method:'POST',body:JSON.stringify({status:'discarded'})});card.dataset.result='discarded';indicator.textContent='已移出待处理';discarded++; } catch(error) { failed++;indicator.textContent=`保存失败：${error.message}`;indicator.classList.add('candidate-result-error'); } continue; }
      values.record_state = 'draft';
      try {
        await api(statusUrl,{method:'POST',body:JSON.stringify({status:'pending',category,fields:values})});
        let revision; let id;
        if (action.startsWith('update:')) {
          const [targetId, reviewedRevision] = action.slice(7).split(':');
          id = targetId;
          if (!reviewedRevision) throw new Error('这条旧候选没有审核时的记录版本，请重新整理后再更新。');
          // The server checks this review-time revision atomically. Sending it
          // directly also lets an already-committed operation_id retry return
          // its existing record before stale-revision validation.
          revision = reviewedRevision;
        } else {
          const list = await api(`/api/records/${encodeURIComponent(category)}?archived=0`);
          revision = list.revision;
        }
        const recordPayload={revision,record:values,operation_id:candidate.operation_id};if(id)recordPayload.id=id;
        const result = card._committedResult || await api(`/api/records/${encodeURIComponent(category)}`, {method:'POST', body:JSON.stringify(recordPayload)});
        card._committedResult=result;card.dataset.committed='1';
        card.querySelectorAll('input,select,textarea,button').forEach(input=>input.disabled=true);
        await api(statusUrl,{method:'POST',body:JSON.stringify({status:'adopted',category,fields:values})});
        card.dataset.result = 'saved';
        indicator.textContent = `已保存到${labelFor(category)}`;
        card.querySelector('.candidate-action').disabled = true;
        card.querySelectorAll('.field-control').forEach((input) => { input.disabled = true; });
        saved++;
      } catch (error) {
        failed++; indicator.textContent = `保存失败：${error.payload?.error || error.message}`;
        indicator.classList.add('candidate-result-error');
        try { await api(statusUrl,{method:'POST',body:JSON.stringify({status:'pending',category,fields:values})}); } catch (_) { /* 保留原候选；用户可重试。 */ }
      }
    }
    const remaining = [...reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')].filter((card) => !['saved','deferred','discarded'].includes(card.dataset.result)).length;
    outcome.textContent = `${saved} 条已归类，${skipped} 条保留待处理，${discarded} 条已移出，${failed} 条失败。${remaining ? '失败项仍可修正后重试。' : '可关闭审核；待处理项仍在草稿箱。'}`;
    button.disabled = remaining === 0; button.textContent = remaining ? '重试失败项' : '已完成';
    state.review.saving=false;
    if(state.view==='notes'&&(saved||discarded))renderNotes();
    if (saved) toast(`${saved} 条履历草稿已保存在本机。`, 'success');
    if (failed) toast(`${failed} 条未保存，请查看对应错误后重试。`, 'error');
    if (state.view === 'category' && saved) renderCategory();
  }

  async function renderSettings() {
    const [backup, config] = await Promise.all([api('/api/backup/status'), api('/api/backup/config')]);
    await loadAIState();
    content.innerHTML = `${heading('本机与数据安全','备份与设置','手动备份到你自己的私有仓库，日常录入保存在本机。')}<div class="settings-grid">${chatgptSettingsCard()}<section class="settings-card"><div class="settings-icon">↥</div><h2 class="settings-title">GitHub 私有备份</h2><p class="settings-text">请先在自己的 GitHub 账号下创建一个空的私有仓库。不要选择公开项目仓库，也不要勾选初始化说明文档。</p><form id="backup-config-form"><label>私有仓库<input class="field-control" id="backup-repository" name="repository" placeholder="用户名/仓库名" value="${esc(config.repository || '')}" autocomplete="off"></label><p class="field-hint">留空并保存可停用备份。这里不填写访问令牌。</p><button class="button" type="submit">保存备份设置</button></form><div class="settings-meta"><div class="settings-row"><span>目标仓库</span><span>${esc(backup.repository)}</span></div><div class="settings-row"><span>待备份更改</span><span>${backup.pending ? '有' : '无'}</span></div><div class="settings-row"><span>未推送提交</span><span>${Number(backup.pending_commits || 0)} 个</span></div><div class="settings-row"><span>上次成功备份</span><span>${esc(backup.last_successful_backup || '尚无')}</span></div></div><button id="backup-now" class="button button-primary" ${!config.repository ? 'disabled' : ''}>备份到 GitHub</button> <button id="refresh-backup" class="button">核验仓库</button><p id="backup-message" class="field-hint">${esc(backup.message)}</p><p class="field-hint">可选依赖：安装 Git、GitHub CLI，并完成 GitHub CLI 登录。<a href="https://cli.github.com/" target="_blank" rel="noopener noreferrer">安装说明 ↗</a></p></section><section class="settings-card"><div class="settings-icon">⌂</div><h2 class="settings-title">资料与隐私范围</h2><ul class="privacy-list"><li>会备份：履历文字、分类与表单配置、程序版本说明，包含待完善记录。</li><li>不会备份：联系方式、证明材料路径、原始附件、草稿原文、处理历史、模型偏好、令牌和运行环境。</li><li>自定义字段属于普通履历内容，会参与备份及 AI 上下文。</li><li>每次推送前核验仓库私有状态及权限，远端冲突时停止上传。</li></ul></section><section class="settings-card"><div class="settings-icon">▣</div><h2 class="settings-title">本机数据位置</h2><p class="settings-text" style="overflow-wrap:anywhere">${esc(config.data_location)}</p><p class="field-hint">记录在 data 中，联系方式、草稿和本机设置在 private 中。更新时替换程序文件即可；完整恢复副本应包含整个资料目录。AI 凭据由 Windows 当前用户加密保存。</p></section></div>`;
    bindChatGPTSettings();
    content.querySelector('#backup-config-form').addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button');
      button.disabled = true;
      try {
        await api('/api/backup/config', {method:'PATCH', body:JSON.stringify({repository:content.querySelector('#backup-repository').value.trim()})});
        toast('备份设置已保存在本机。','success');
        await renderSettings();
      } catch (error) { toast(error.message,'error'); button.disabled = false; }
    });
    content.querySelector('#refresh-backup').addEventListener('click', async event => {
      const button = event.currentTarget; button.disabled = true;
      try { const result = await api('/api/backup/status?refresh=1'); content.querySelector('#backup-message').textContent = result.message; }
      catch (error) { toast(error.message,'error'); }
      finally { button.disabled = false; }
    });
    content.querySelector('#backup-now').addEventListener('click', async event => {
      const button = event.currentTarget; button.disabled = true; button.textContent = '正在备份…';
      try { await api('/api/backup', {method:'POST',body:'{}'}); toast('GitHub 备份成功。','success'); await renderSettings(); }
      catch (error) { content.querySelector('#backup-message').textContent = error.payload?.error || error.message; button.disabled = false; button.textContent = '重试备份'; }
    });
  }

  function chatgptSettingsCard() {
    const connected = !!state.ai?.connected;
    const sharing = !!state.ai?.sharing;
    const status = connected ? (sharing ? '已连接 · 订阅资格以请求结果为准' : (state.ai.ai_blocked ? 'AI 已暂停 · 需要重新授权' : '已登录 · 尚无方案使用权限')) : '未连接';
    return `<section class="settings-card ai-settings-card"><div class="settings-icon">✦</div><h2 class="settings-title">ChatGPT 辅助录入</h2><p class="settings-text">仅通过你的 ChatGPT 账号使用符合资格的订阅方案；这里不配置 API Key，也不会自动改用付费 API。普通录入和分类管理不依赖 AI。</p><div class="settings-meta"><div class="settings-row"><span>连接状态</span><span>${esc(status)}</span></div>${connected?`<div class="settings-row"><span>当前账号</span><span>${esc(state.ai.email || '已授权账号')}</span></div>`:''}<div class="settings-row"><span>可用模型</span><span>${esc(state.models.length ? `${state.models.length} 个` : '尚未获取')}</span></div></div>${state.ai?.error?`<div class="notice notice-warning">${esc(state.ai.error)}</div>`:''}<div class="ai-settings-actions">${!connected || !sharing?'<button id="ai-connect" class="button button-primary" type="button">使用 ChatGPT 登录</button>':''}${connected?'<button id="ai-disconnect" class="button" type="button">断开连接</button>':''}<a class="button" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">在 ChatGPT 管理用量 ↗</a></div>${connected && sharing?`<div class="settings-model-row">${modelPicker('settings-model')}</div>`:''}${aiDisclosure()}<p class="field-hint">授权只允许符合资格的 AI 请求，不会读取已有的 ChatGPT 对话。达到用量上限时请在 ChatGPT 设置中查看；本机笔记不受影响。</p></section>`;
  }
  function bindChatGPTSettings() {
    rememberModel(content.querySelector('#settings-model'));
    content.querySelector('#ai-connect')?.addEventListener('click', async (event) => {
      const button = event.currentTarget; button.disabled = true; button.textContent = '正在开始授权…';
      try {
        const response = await api('/api/ai/connect', {method:'POST', body:'{}'});
        const url = new URL(response.authorization_url);
        if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com') throw new Error('授权地址不正确，已停止跳转。');
        window.location.assign(url.href);
      } catch (error) { toast(error.message, 'error'); button.disabled = false; button.textContent = '使用 ChatGPT 登录'; }
    });
    content.querySelector('#ai-disconnect')?.addEventListener('click', async (event) => {
      const button = event.currentTarget; button.disabled = true;
      try { await api('/api/ai/disconnect', {method:'POST', body:'{}'}); toast('ChatGPT 已断开，本机履历资料未改变。', 'success'); await renderSettings(); }
      catch (error) { toast(error.message, 'error'); button.disabled = false; }
    });
  }

  document.body.addEventListener('click',(event)=>{const nav=event.target.closest('[data-view]');if(nav)navigate(nav.dataset.view);});
  function syncSidebar() {
    document.body.classList.toggle('sidebar-collapsed', state.sidebarCollapsed);
    const button = document.querySelector('#sidebar-toggle');
    button.setAttribute('aria-expanded', String(!state.sidebarCollapsed));
    button.setAttribute('aria-label', state.sidebarCollapsed ? '展开分类导航' : '收起分类导航');
  }
  document.querySelector('#sidebar-toggle').addEventListener('click', () => { state.sidebarCollapsed = !state.sidebarCollapsed; localStorage.setItem('academic-profile-sidebar-collapsed', state.sidebarCollapsed ? '1' : '0'); syncSidebar(); });
  document.addEventListener('keydown', (event) => { if (event.key !== 'Escape') return; if (reviewHost.childElementCount) reviewHost.querySelector('[data-review-close]')?.click(); else if (modalHost.childElementCount) modalHost.querySelector('[data-close]')?.click(); });
  document.querySelector('#quit-button').addEventListener('click',async()=>{if(!confirm('退出平台会关闭本机服务。已保存的数据不会删除。'))return;try{await api('/api/shutdown',{method:'POST',body:'{}'});toast('平台已退出。','success');setTimeout(()=>window.close(),300);}catch(error){toast(error.message,'error');}});
  window.addEventListener('focus',async()=>{try{const latest=await api('/api/preferences');const modelChanged=latest.ai_model!==state.preferences.ai_model;const sortChanged=JSON.stringify(latest.sorts)!==JSON.stringify(state.preferences.sorts);state.preferences=latest;state.aiModel=latest.ai_model||'';if(modelChanged)refreshAIControls();if(sortChanged&&state.view==='category')renderCategory();}catch(_){}});
  (async()=>{syncSidebar();try{state.config=await api('/api/config');await loadPreferences();buildNav();await render();}catch(error){content.innerHTML=`<div class="notice notice-warning">无法连接本机平台：${esc(error.message)}。请双击桌面快捷方式重新打开。</div>`;}})();
})();
