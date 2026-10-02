(() => {
  const content = document.querySelector('#app-content');
  const modalHost = document.querySelector('#modal-host');
  const reviewHost = document.querySelector('#ai-review-host');
  const toastHost = document.querySelector('#toast-host');
  const state = { config: null, view: 'dashboard', category: null, profile: 'phd', cvLanguage: localStorage.getItem('zhaolian-cv-language') || 'zh', includePhone: localStorage.getItem('zhaolian-cv-phone') !== '0', archived: false, query: '', basics: null, records: [], revision: null, cv: null, ai: null, models: [], aiModel: localStorage.getItem('academic-profile-ai-model') || '', listMode: localStorage.getItem('academic-profile-list-mode') || 'cards', sidebarCollapsed: localStorage.getItem('academic-profile-sidebar-collapsed') === '1', review: null };
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
  const profileNames = { phd:'博士申请', ra:'科研助理申请', summer_research:'暑期科研申请', domestic:'国内升学申请', internship:'实习申请' };
  const enumNames = { idea:'构思中', literature:'文献调研', method:'方法设计', experiment:'实验中', writing:'写作中', submitted:'已提交', completed:'已完成', planned:'计划中', active:'进行中', archived:'已归档', published:'已发表', accepted:'已录用', under_review:'审稿中', preprint:'预印本', manuscript:'手稿', introductory:'入门', intermediate:'中级', advanced:'高级', graduate:'研究生', Programming:'编程', ML:'机器学习', Data:'数据', Optimization:'优化', 'Research Tools':'科研工具', 'Development Tools':'开发工具', Languages:'语言' };
  const enumLabel = (value) => enumNames[value] || value.replaceAll('_',' ');

  function syncNavigation() {
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === state.view && !button.dataset.category));
    document.querySelectorAll('[data-category]').forEach((button) => button.classList.toggle('active', button.dataset.category === state.category && state.view === 'category'));
    const crumb = state.view === 'category' ? labelFor(state.category) : ({dashboard:'总览', notes:'素材箱', basics:'个人资料', cv:'简历生成', settings:'备份与设置'}[state.view] || '总览');
    document.querySelector('#page-breadcrumb').textContent = crumb;
  }
  function buildNav() {
    const nav = document.querySelector('#category-nav');
    nav.replaceChildren();
    for (const category of state.config.categories) {
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
      else if (state.view === 'cv') await renderCV();
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
      if (!state.models.some((model) => model.slug === state.aiModel)) state.aiModel = state.models[0]?.slug || '';
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
  const selectedModel = () => state.models.some((model) => model.slug === state.aiModel) ? state.aiModel : (state.models[0]?.slug || '');
  const aiCanGenerate = () => !!(state.ai?.connected && state.ai?.sharing && state.models.length);
  function modelPicker(id) {
    if (!state.ai?.connected) return '<span class="field-hint">连接 ChatGPT 后可生成候选记录；保存笔记无需网络。</span>';
    if (!state.ai.sharing) return `<span class="field-hint">${esc(state.ai.error || '此账号尚未授予 ChatGPT 方案使用权限。')} 笔记仍可保存在本机。</span>`;
    if (!state.models.length) return '<span class="field-hint">模型列表暂不可用，请到设置页刷新连接状态。</span>';
    return `<label class="model-picker">模型 <select id="${esc(id)}" class="field-control compact-select" aria-label="选择 ChatGPT 模型">${state.models.map((model) => `<option value="${esc(model.slug)}" ${selectedModel()===model.slug?'selected':''}>${esc(model.display_name || model.slug)}</option>`).join('')}</select></label><a class="text-link" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">管理用量 ↗</a>`;
  }
  function rememberModel(select) {
    if (!select) return;
    select.addEventListener('change', () => { state.aiModel = select.value; localStorage.setItem('academic-profile-ai-model', state.aiModel); });
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
    await loadAIState();
    const cards = data.counts.map((item) => `<button class="category-card" data-open-category="${esc(item.id)}"><span class="category-glyph">${esc(state.config.categories.find(c => c.id === item.id)?.icon || '•')}</span><span class="category-card-copy"><span class="category-name">${esc(item.label)}</span><span class="category-count">${item.count} 条${item.drafts ? ` · ${item.drafts} 条草稿` : ''}</span></span><span class="category-arrow">›</span></button>`).join('');
    const drafts = data.drafts.length ? `<div class="record-list">${data.drafts.slice(0,5).map((record) => `<button class="record-row plain-row" data-edit-id="${esc(record.id)}" data-edit-category="${esc(record.category)}"><span class="record-copy"><span class="record-title">${esc(record.title)}</span><span class="record-caption">${esc(record.category_label)}</span></span><span class="badge badge-draft">待完善</span></button>`).join('')}</div>` : empty('还没有待完善草稿','新增一条经历后，可先保存草稿，之后再补充。');
    const recent = data.recent.length ? `<div class="record-list">${data.recent.map((record) => `<button class="record-row plain-row" data-edit-id="${esc(record.id)}" data-edit-category="${esc(record.category)}"><span class="record-copy"><span class="record-title">${esc(record.title)}</span><span class="record-caption">${esc(record.category_label)} · ${esc(record.updated_at)}</span></span></button>`).join('')}</div>` : empty('从这里开始','所有资料分类目前都是空白的。可以先填写个人资料，再逐步添加履历记录。', '<button class="button button-primary" data-view="basics">填写个人资料</button>');
    content.innerHTML = `${heading('个人工作台', data.name ? `你好，${data.name}` : '建立你的学术履历', data.total ? '内容保存在这台电脑；完成的记录可用于不同申请版本。' : '先把经历逐条录入，这里暂时没有任何示例或虚构资料。')}<div class="stats-grid"><div class="stat-card"><div class="stat-top">履历记录 <span class="stat-symbol">◫</span></div><div class="stat-value">${data.total}</div><div class="stat-foot">${data.counts.length} 个固定分类</div></div><div class="stat-card"><div class="stat-top">待完善草稿 <span class="stat-symbol">✎</span></div><div class="stat-value">${data.drafts.length}</div><div class="stat-foot">草稿不会出现在简历中</div></div><div class="stat-card"><div class="stat-top">最近修改 <span class="stat-symbol">◷</span></div><div class="stat-value">${data.recent.length}</div><div class="stat-foot">显示最近有修改日期的记录</div></div><div class="stat-card"><div class="stat-top">GitHub 备份 <span class="stat-symbol">↥</span></div><div class="stat-value stat-word">${data.backup.last_successful_backup ? '已备份' : '未备份'}</div><div class="stat-foot">${esc(data.backup.last_successful_backup || '仅保存在本机')}</div></div></div><div class="dashboard-grid"><section class="panel"><div class="panel-heading"><h2 class="panel-title">履历分类</h2><span class="panel-note">点击分类开始录入</span></div><div class="category-grid">${cards}</div></section><section class="panel"><div class="panel-heading"><h2 class="panel-title">快捷入口</h2></div><div class="quick-actions"><button class="quick-action" data-view="basics"><span class="quick-action-icon">○</span><span><strong>完善个人资料</strong><small>姓名、研究方向和联系方式</small></span></button><button class="quick-action" data-view="cv"><span class="quick-action-icon">▤</span><span><strong>预览申请简历</strong><small>按不同申请场景筛选记录</small></span></button><button class="quick-action" data-view="settings"><span class="quick-action-icon">↥</span><span><strong>查看备份状态</strong><small>仅点击时备份到私人 GitHub</small></span></button></div></section></div><div class="lower-grid"><section class="panel"><div class="panel-heading"><h2 class="panel-title">待完善草稿</h2><span class="panel-note">${data.drafts.length} 条</span></div>${drafts}</section><section class="panel"><div class="panel-heading"><h2 class="panel-title">最近修改</h2></div>${recent}</section></div>`;
    content.querySelector('.page-heading').insertAdjacentHTML('afterend', dashboardCapture());
    bindDashboardCapture(); bindNavigation(); bindOpenCategory(); bindEditButtons();
  }
  function dashboardCapture() {
    return `<section class="capture-panel" aria-labelledby="capture-title"><div class="capture-copy"><p class="eyebrow">QUICK CAPTURE · 快速录入</p><h2 id="capture-title">先记下来，再慢慢整理。</h2><p>文字、图片或文档可以放在同一条素材中；ChatGPT 会把它们整理成待确认的履历草稿。</p></div><label class="sr-only" for="quick-note">经历原笔记</label><textarea id="quick-note" class="capture-input" placeholder="可以写一段经历，也可以只添加附件，之后再慢慢补充……"></textarea><div class="capture-attachments"><label class="button button-small file-select">添加图片或文档<input id="quick-files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.xlsx,.pptx"></label><span id="quick-file-names" class="field-hint">支持 PNG、JPG、WEBP、PDF、Word、Excel、PowerPoint、TXT 和 Markdown。</span></div><div class="capture-footer"><div class="capture-actions"><button id="save-quick-note" class="button" type="button">存入素材箱</button><button id="generate-quick-note" class="button button-primary" type="button" ${aiCanGenerate()?'':'disabled'}>用 ChatGPT 整理 ↗</button></div><div class="capture-model">${modelPicker('capture-model')}</div></div>${aiDisclosure()}</section>`;
  }
  function bindDashboardCapture() {
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
      try {
        const note = await saveNote(textarea.value, Array.from(fileInput?.files || []));
        textarea.value = '';
        if (fileInput) { fileInput.value = ''; content.querySelector('#quick-file-names').textContent = '支持 PNG、JPG、WEBP、PDF、Word、Excel、PowerPoint、TXT 和 Markdown。'; }
        toast('原笔记已保存在本机素材箱。', 'success');
        if (doGenerate) {
          if ((note.attachments || []).reduce((total, file) => total + file.size, 0) > 50 * 1024 * 1024) throw new Error('所选附件总量超过 ChatGPT 单次 50 MB 限制。素材已保存在本机；请到素材箱取消部分附件，或拆分文件后分批整理。');
          try { openProposalReview(await generateProposals(note.id, (note.attachments || []).map((file) => file.id)), note); }
          catch (error) { toast(`笔记已保存，AI 整理未完成：${error.message}`, 'error'); }
        }
      } catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = doGenerate && !aiCanGenerate(); button.textContent = doGenerate ? '用 ChatGPT 整理 ↗' : '存入素材箱'; }
    };
    save.addEventListener('click', () => run(false));
    generate.addEventListener('click', () => run(true));
  }
  function bindNavigation() { /* Navigation is delegated to document.body. */ }
  function bindOpenCategory() { content.querySelectorAll('[data-open-category]').forEach((button) => button.addEventListener('click', () => navigate('category', button.dataset.openCategory))); }
  function bindEditButtons() { content.querySelectorAll('[data-edit-id]').forEach((button) => button.addEventListener('click', () => openRecord(button.dataset.editCategory, button.dataset.editId))); }

  async function renderNotes() {
    const [result] = await Promise.all([api('/api/ai/notes'), loadAIState()]);
    const notes = result.notes || [];
    const noteCards = notes.length ? notes.map((note) => { const attachments=note.attachments||[]; const choices=attachments.map((file)=>`<label class="note-attachment-choice"><input type="checkbox" data-attachment-id="${esc(file.id)}" data-size="${Number(file.size)||0}" checked><span>${esc(file.name)}</span><small>${formatBytes(file.size)}</small></label>`).join(''); return `<article class="note-card" data-note-id="${esc(note.id)}"><div class="note-card-top"><span class="note-date">${esc(note.created_at || '本机素材')}</span><span class="badge">仅保存在本机</span></div><p class="note-preview">${esc(note.preview || '仅有附件，可点击查看')}</p>${attachments.length?`<div class="note-attachments"><strong>${attachments.length} 个附件 · 默认全部发送</strong>${choices}</div>`:''}<div class="note-card-actions"><button class="button button-small" data-note-detail="${esc(note.id)}">查看素材</button><button class="button button-small button-soft" data-note-generate="${esc(note.id)}" ${aiCanGenerate()?'':'disabled'}>用 ChatGPT 整理 ↗</button></div><div class="note-full" hidden></div></article>`; }).join('') : empty('素材箱还是空的','可以直接在下方添加文字、图片或文档。内容只保存在本机。');
    content.innerHTML = `${heading('只在这台电脑', '素材箱', '文字和原始附件保存在本机；只有点击 ChatGPT 整理并选中的内容会发送给 ChatGPT。')}${dashboardCapture()}${aiDisclosure()}<div class="notes-grid">${noteCards}</div>`;
    rememberModel(content.querySelector('#notes-model'));
    bindDashboardCapture();
    for (const button of content.querySelectorAll('[data-note-detail]')) button.addEventListener('click', async () => {
      const card = button.closest('.note-card'); const detail = card.querySelector('.note-full');
      if (!detail.hidden) { detail.hidden = true; button.textContent = '查看素材'; return; }
      try { const response = await api(`/api/ai/notes/${encodeURIComponent(button.dataset.noteDetail)}`); const note = response.note || response; const files=(note.attachments||[]).map((file)=>`<li><a href="/api/ai/notes/${encodeURIComponent(note.id)}/attachments/${encodeURIComponent(file.id)}">${esc(file.name)}</a> · ${formatBytes(file.size)}</li>`).join(''); detail.innerHTML = `${note.text?`<pre>${esc(note.text)}</pre>`:'<p class="field-hint">这条素材没有附加文字。</p>'}${files?`<ul class="note-downloads">${files}</ul>`:''}`; detail.hidden = false; button.textContent = '收起素材'; }
      catch (error) { toast(error.message, 'error'); }
    });
    for (const button of content.querySelectorAll('[data-note-generate]')) button.addEventListener('click', async () => {
      button.disabled = true; button.textContent = '正在整理…';
      try { const card=button.closest('.note-card'); const selected=[...card.querySelectorAll('[data-attachment-id]:checked')]; const size=selected.reduce((total,input)=>total+Number(input.dataset.size||0),0); if(size>50*1024*1024) throw new Error('所选附件超过 ChatGPT 单次 50 MB 限制。请取消部分附件，或拆分文件后分批上传。'); const result = await generateProposals(button.dataset.noteGenerate, selected.map((input)=>input.dataset.attachmentId)); openProposalReview(result, {id:button.dataset.noteGenerate}); }
      catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = false; button.textContent = '用 ChatGPT 整理 ↗'; }
    });
  }

  function formatBytes(value) { const bytes=Number(value)||0; return bytes<1024*1024?`${Math.max(1,Math.round(bytes/1024))} KB`:`${(bytes/1024/1024).toFixed(1)} MB`; }

  async function renderBasics() {
    const result = await api('/api/basics'); state.basics = result;
    const basics = result.basics || {}; const contact = result.contact || {};
    content.innerHTML = `${heading('关于你', '个人资料', '先填写中文资料；英文内容可选。联系方式和电话号码只保存在本机，不进入 GitHub 备份。')}<form id="basics-form" class="profile-card"><div class="form-grid"><h2 class="form-section-title">基本资料</h2>${inputField('name_zh','中文姓名','text',basics.name_zh,'例如：昭濂',true)}${inputField('name_en','英文姓名','text',basics.name_en,'可选，例如：Alex Wang')}${inputField('headline_zh','中文简介','text',basics.headline_zh,'可选，例如研究方向或当前身份',true)}${inputField('headline_en','英文简介','text',basics.headline_en,'Optional',true)}${inputField('research_interests','中文研究兴趣（每行一项）','list',(basics.research_interests||[]).join('\n'),'可选；不同申请版本可选择展示',true)}${inputField('research_interests_en','英文研究兴趣（每行一项）','list',(basics.research_interests_en||[]).join('\n'),'可选，不自动翻译',true)}<h2 class="form-section-title">联系方式（只保存在本机）</h2>${inputField('email','电子邮箱','email',contact.email,'')}${inputField('phone','电话号码','tel',contact.phone,'可选，支持国家区号')}${inputField('website','个人网站','url',contact.website,'https://…')}${inputField('github','GitHub','text',contact.github,'GitHub 用户名或网址')}${inputField('location','所在地','text',contact.location,'')}</div><div class="form-footer"><span class="form-footer-note">保存后立即写入本机 YAML 文件</span><div class="form-footer-actions"><button class="button button-primary" type="submit">保存个人资料</button></div></div></form>`;
    const form = content.querySelector('#basics-form'); form.addEventListener('submit', async (event) => { event.preventDefault(); clearErrors(form); const values = formValues(form); const textValue=(key)=>form.elements[key]?.value.trim()||''; const contactValue=(key)=>form.elements[key]?.value.trim()||''; try { const saved = await api('/api/basics', {method:'POST', body:JSON.stringify({revision:result.revision, basics:{name_en:textValue('name_en'),name_zh:textValue('name_zh'),headline_en:textValue('headline_en'),headline_zh:textValue('headline_zh'),research_interests:values.research_interests||[],research_interests_en:values.research_interests_en||[]},contact:{email:contactValue('email'),phone:contactValue('phone'),website:contactValue('website'),github:contactValue('github'),location:contactValue('location')}})}); state.basics.revision=saved.revision; toast('个人资料已保存在本机。','success'); } catch(error) { showFormError(form,error); } });
  }
  function inputField(key, label, type, value='', placeholder='', full=false, required=false) { const control = type === 'list' ? `<textarea class="field-control" name="${esc(key)}" data-type="list" placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : `<input class="field-control" name="${esc(key)}" type="${esc(type)}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${required?'required':''}>`; return `<label class="field ${full?'full':''}" data-field="${esc(key)}"><span class="field-label">${esc(label)}${required?' *':''}</span>${control}<span class="field-error"></span></label>`; }
  function formValues(form) { const out={}; form.querySelectorAll('[name]').forEach((input) => { if (input.type === 'checkbox') out[input.name]=input.checked; else if (input.multiple) out[input.name]=Array.from(input.selectedOptions).map(o=>o.value); else if (input.dataset.type === 'list') out[input.name]=input.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean); else if (input.dataset.type === 'map') out[input.name]=Object.fromEntries(input.value.split(/\r?\n/).map(s=>s.split(/:(.+)/,2)).filter(pair=>pair.length===2&&pair[0].trim()).map(pair=>[pair[0].trim(),pair[1].trim()])); else if (input.value.trim() !== '') out[input.name]=input.type==='number'?Number(input.value):input.value.trim(); }); return out; }
  function clearErrors(form) { form.querySelectorAll('.field').forEach((field) => field.classList.remove('has-error')); const global = form.querySelector('[data-global-error]'); if (global) global.remove(); }
  function showFormError(form,error) { clearErrors(form); if (error.payload?.field_errors) { for (const [name,message] of Object.entries(error.payload.field_errors)) { const field=form.querySelector(`[data-field="${CSS.escape(name)}"]`); if(field){field.classList.add('has-error');field.querySelector('.field-error').textContent=message;} } } const message=error.payload?.error || (error.status===409?'资料已在另一个窗口更新。请返回列表重新打开，再保存。':error.message); const note=document.createElement('div'); note.className='notice notice-warning'; note.dataset.globalError='1'; note.textContent=message; form.prepend(note); }

  async function renderCategory() {
    const category=state.category; const meta=state.config.categories.find((item)=>item.id===category); const result=await api(`/api/records/${category}?archived=${state.archived?1:0}&q=${encodeURIComponent(state.query)}`); state.records=result.records; state.revision=result.revision;
    const rows=result.records.length ? result.records.map((record)=>{ const title=record._title; const secondary=[record.institution,record.venue,record.organization,record.semester,record.date,record.start_date].filter(Boolean).join(' · '); return `<tr data-open-id="${esc(record.id)}"><td><span class="table-primary">${esc(title)}</span><span class="table-secondary">${esc(secondary||record.id)}</span></td><td><span class="badge ${record.record_state==='draft'?'badge-draft':'badge-ready'}">${record.record_state==='draft'?'待完善':'已整理'}</span>${record.status?` <span class="badge">${esc(enumLabel(record.status))}</span>`:''}</td><td class="table-date">${esc(record.date||record.end_date||record.start_date||'—')}</td><td><div class="table-actions"><button class="button button-small" data-action-id="${esc(record.id)}" data-action="${state.archived?'restore':'archive'}">${state.archived?'恢复':'归档'}</button></div></td></tr>`; }).join('') : `<tr><td colspan="4">${empty(state.archived?'没有已归档记录':'这个分类还没有记录',state.archived?'归档记录会保留在这里，可随时恢复。':'点击“新增记录”开始逐步录入；可先保存草稿。')}</td></tr>`;
    const cards=result.records.map((record)=>{const secondary=[record.institution,record.venue,record.organization,record.semester].filter(Boolean).join(' · ');return `<article class="record-card" data-open-id="${esc(record.id)}" tabindex="0" role="button" aria-label="打开 ${esc(record._title)}"><div class="record-card-top"><span class="record-card-date">${esc(record.date||record.end_date||record.start_date||'日期未填')}</span><span class="badge ${record.record_state==='draft'?'badge-draft':'badge-ready'}">${record.record_state==='draft'?'待完善':'已整理'}</span></div><h2>${esc(record._title)}</h2><p>${esc(secondary||'点击继续完善这条记录')}</p><div class="record-card-bottom">${record.status?`<span class="badge">${esc(enumLabel(record.status))}</span>`:'<span class="record-card-id">'+esc(record.id)+'</span>'}<button class="button button-small" data-action-id="${esc(record.id)}" data-action="${state.archived?'restore':'archive'}">${state.archived?'恢复':'归档'}</button></div></article>`;}).join('');
    const recordsContent=state.listMode==='cards' ? (cards?`<section class="record-card-grid">${cards}</section>`:empty(state.archived?'没有已归档记录':'这个分类还没有记录',state.archived?'归档记录会保留在这里，可随时恢复。':'点击“新增记录”开始逐步录入；可先保存草稿。')) : `<section class="list-panel"><table class="record-table"><thead><tr><th>记录</th><th>状态</th><th>日期</th><th></th></tr></thead><tbody>${rows}</tbody></table></section>`;
    content.innerHTML=`${heading('学术档案',meta.label,'记录先保存在本机。草稿可暂缺信息，只有整理完成且勾选用于简历的记录才会进入生成结果。',`<button id="new-record" class="button button-primary">＋ 新增记录</button>`)}<div class="list-toolbar"><label class="search-box"><span class="search-icon">⌕</span><input id="record-search" type="search" placeholder="搜索记录名称或内容…" value="${esc(state.query)}"></label><label class="toggle"><input id="show-archived" type="checkbox" ${state.archived?'checked':''}>显示已归档</label><div class="view-switch" role="group" aria-label="记录显示方式"><button class="view-switch-button ${state.listMode==='cards'?'selected':''}" type="button" data-list-mode="cards" aria-pressed="${state.listMode==='cards'}">卡片</button><button class="view-switch-button ${state.listMode==='list'?'selected':''}" type="button" data-list-mode="list" aria-pressed="${state.listMode==='list'}">列表</button></div><span class="panel-note">${result.records.length} 条</span></div>${recordsContent}`;
    content.querySelector('#new-record').addEventListener('click',()=>openRecord(category)); const search=content.querySelector('#record-search'); search.addEventListener('input',()=>{clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>{state.query=search.value;renderCategory();},220);}); content.querySelector('#show-archived').addEventListener('change',(event)=>{state.archived=event.target.checked;renderCategory();}); content.querySelectorAll('[data-list-mode]').forEach((button)=>button.addEventListener('click',()=>{state.listMode=button.dataset.listMode;localStorage.setItem('academic-profile-list-mode',state.listMode);renderCategory();})); content.querySelectorAll('[data-open-id]').forEach((row)=>{row.addEventListener('click',(event)=>{if(!event.target.closest('button'))openRecord(category,row.dataset.openId);});row.addEventListener('keydown',(event)=>{if(event.target.closest('button'))return;if(event.key==='Enter'||event.key===' '){event.preventDefault();openRecord(category,row.dataset.openId);}});}); content.querySelectorAll('[data-action-id]').forEach((button)=>button.addEventListener('click',async(event)=>{event.stopPropagation();try{const action=button.dataset.action;await api(`/api/records/${category}/${button.dataset.actionId}/${action}`,{method:'POST',body:JSON.stringify({revision:result.revision})});toast(action==='archive'?'已归档。':'已恢复。','success');renderCategory();}catch(error){toast(error.message,'error');}}));
  }

  function controlFor(field, value, fieldOptions) {
    const kind=field.type; const name=esc(field.key); const safe=esc(value??''); let control='';
    if(kind==='textarea') control=`<textarea class="field-control" name="${name}">${safe}</textarea>`;
    else if(kind==='list') control=`<textarea class="field-control" name="${name}" data-type="list" placeholder="每行一项">${esc(Array.isArray(value)?value.join('\n'):'')}</textarea>`;
    else if(kind==='map') control=`<textarea class="field-control" name="${name}" data-type="map" placeholder="每行一项，格式：名称: 分数">${esc(value&&typeof value==='object'?Object.entries(value).map(([k,v])=>`${k}: ${v}`).join('\n'):'')}</textarea>`;
    else if(kind==='bool') control=`<label class="toggle"><input type="checkbox" name="${name}" ${value?'checked':''}><span>${esc(field.label)}</span></label>`;
    else if(kind.startsWith('relation')) { const many=kind.startsWith('relation:'); const selected=many?(value||[]):value?[value]:[]; control=`<select class="field-control" name="${name}" ${many?'multiple':''} ${many?'size="3"':''}><option value="" ${selected.length?'':'selected'}>${many?'不关联':'不关联'}</option>${(field.options||[]).map((item)=>`<option value="${esc(item.id)}" ${selected.includes(item.id)?'selected':''}>${esc(item.label)}</option>`).join('')}</select>`; }
    else if(kind.startsWith('select:')) control=`<select class="field-control" name="${name}"><option value="">请选择</option>${(field.options||[]).map((option)=>`<option value="${esc(option)}" ${value===option?'selected':''}>${esc(enumLabel(option))}</option>`).join('')}</select>`;
    else { const type=kind==='date'?'text':kind==='number'?'number':kind==='url'?'url':'text'; const pattern=kind==='date'?'placeholder="YYYY-MM 或 YYYY-MM-DD"':''; control=`<input class="field-control" name="${name}" type="${type}" value="${safe}" ${pattern}>`; }
    const isRelation=kind.startsWith('relation'); return `<div class="field ${field.advanced?'advanced-field':''} ${field.full||kind==='textarea'||kind==='list'||kind==='map'||kind==='relation'||isRelation?'full':''}" data-field="${name}"><span class="field-label">${esc(field.label)}${field.required_for_ready?' *':''}</span>${control}<span class="field-error"></span></div>`;
  }
  function editorAIPanel() {
    return `<aside class="editor-ai-panel" aria-labelledby="editor-ai-title"><div class="editor-ai-heading"><span class="ai-sparkle" aria-hidden="true">✦</span><div><p class="eyebrow">CHATGPT ASSIST</p><h3 id="editor-ai-title">写下补充信息</h3></div></div><p class="editor-ai-intro">可以把文字、图片或文档交给 ChatGPT 整理，再逐项填入左侧表单。不会自动覆盖你已经写好的内容。</p><label class="field-label" for="editor-ai-note">本次补充资料</label><textarea id="editor-ai-note" class="field-control" placeholder="可以写补充信息，也可以只添加附件……"></textarea><label class="button button-small file-select">添加图片或文档<input id="editor-ai-files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.xlsx,.pptx"></label><span id="editor-ai-file-names" class="field-hint">可添加图片、PDF、Office、TXT 或 Markdown。</span><div class="editor-ai-actions"><button id="editor-ai-save" class="button button-small" type="button">只存素材</button><button id="editor-ai-generate" class="button button-primary button-small" type="button" ${aiCanGenerate()?'':'disabled'}>生成建议</button></div><div class="editor-ai-model">${modelPicker('editor-ai-model')}</div><div id="editor-ai-results" class="editor-ai-results">${state.ai?.error ? esc(state.ai.error) : state.ai?.connected?'建议会在这里出现；你决定是否填入。':'尚未连接 ChatGPT。可先保存笔记；如需 AI 建议，请先保存记录，再到设置页连接。'}</div>${aiDisclosure()}</aside>`;
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
        toast('补充笔记已保存到本机素材箱。', 'success');
        if (generate) {
          try {
            if ((note.attachments||[]).reduce((total,file)=>total+file.size,0)>50*1024*1024) throw new Error('附件超过 ChatGPT 单次 50 MB 限制。素材已保存；请到素材箱选择部分附件或拆分后分批整理。');
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
    await loadAIState();
    const main=fields.filter((field)=>!field.advanced); const advanced=fields.filter((field)=>field.advanced);
    const titleField=state.config.categories.find((item)=>item.id===category).title_field; const headingTitle=id?(original._title||'编辑记录'):'新增记录';
    modalHost.innerHTML=`<div class="modal-backdrop" role="presentation"><section class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div class="drawer-header"><div><h2 id="drawer-title" class="drawer-title">${esc(headingTitle)}</h2><p class="drawer-subtitle">${esc(labelFor(category))} · 标 * 项仅在整理完成时必填，可先存草稿</p></div><button class="button button-icon" data-close aria-label="关闭">×</button></div><form id="record-form"><div class="drawer-body"><div class="form-grid">${main.map((field)=>controlFor(field,original[field.key],field)).join('')}<div class="field full"><span class="field-label">简历设置</span><div class="inline-controls"><label class="toggle"><input type="checkbox" name="cv_eligible" ${original.cv_eligible?'checked':''}>用于简历</label><label class="field-label">重要程度 <select class="field-control compact-select" name="priority">${[1,2,3,4,5].map((n)=>`<option value="${n}" ${Number(original.priority||3)===n?'selected':''}>${n} · ${['最高','很高','一般','较低','最低'][n-1]}</option>`).join('')}</select></label></div></div></div>${advanced.length?`<details><summary>更多内容（导师、贡献、成果、证明材料等）</summary><div class="details-fields">${advanced.map((field)=>controlFor(field,original[field.key],field)).join('')}</div></details>`:''}<div class="form-grid"><div class="field full"><span class="field-label">记录状态</span><div class="inline-controls"><label class="toggle"><input type="radio" name="record_state" value="draft" ${original.record_state!=='ready'?'checked':''}>保存为草稿</label><label class="toggle"><input type="radio" name="record_state" value="ready" ${original.record_state==='ready'?'checked':''}>整理完成</label></div><span class="field-hint">整理完成时会检查该分类的必填信息和关联。草稿不会用于生成简历。</span></div></div></div><div class="drawer-footer"><span class="form-footer-note">${esc(original.id||'保存时自动分配稳定 ID')}</span><div class="form-footer-actions">${id?'<button class="button button-danger" type="button" data-archive>归档</button>':''}<button class="button" type="button" data-close>取消</button><button class="button button-primary" type="submit">保存记录</button></div></div></form></section></div>`;
    modalHost.querySelector('.drawer').insertAdjacentHTML('beforeend', editorAIPanel());
    const close=()=>modalHost.replaceChildren(); modalHost.querySelectorAll('[data-close]').forEach((button)=>button.addEventListener('click',close)); modalHost.querySelector('.modal-backdrop').addEventListener('click',(event)=>{if(event.target.classList.contains('modal-backdrop'))close();}); modalHost.querySelectorAll('select[multiple]').forEach((select)=>select.addEventListener('change',()=>{const placeholder=select.querySelector('option[value=""]');if(placeholder)placeholder.disabled=Array.from(select.selectedOptions).some(o=>o.value);}));
    const form=modalHost.querySelector('#record-form'); const idField=form.querySelector(`[name="${CSS.escape(titleField)}"]`); if(idField&& !idField.value)idField.placeholder='填写记录名称';
    bindEditorAI(category, form);
    form.addEventListener('submit',async(event)=>{event.preventDefault();const values=formValues(form);const checked=form.querySelector('[name="record_state"]:checked');values.record_state=checked?.value||'draft';const eligibility=form.querySelector('[name="cv_eligible"]');values.cv_eligible=eligibility.checked;values.priority=Number(form.querySelector('[name="priority"]').value);try{await api(`/api/records/${category}`,{method:'POST',body:JSON.stringify({id:original.id||null,revision,record:values})});close();toast(values.record_state==='draft'?'草稿已保存在本机。':'记录已整理并保存。','success');if(state.view==='category')renderCategory();}catch(error){showFormError(form,error);}});
    const archive=modalHost.querySelector('[data-archive]'); if(archive)archive.addEventListener('click',async()=>{try{await api(`/api/records/${category}/${id}/archive`,{method:'POST',body:JSON.stringify({revision})});close();toast('已归档。','success');renderCategory();}catch(error){toast(error.message,'error');}});
  }

  function proposalField(field, value) {
    const options = field.type.startsWith('select:') ? field.type.slice(7).split(',').map((item) => item.trim()) : field.options;
    return `<div class="proposal-field"><label class="proposal-field-choice"><input type="checkbox" data-include-field="${esc(field.key)}" ${value === undefined || value === null || value === '' ? '' : 'checked'}>采纳此字段</label>${controlFor({...field, options, advanced:false}, value, null)}</div>`;
  }
  function proposalCard(candidate, index) {
    const category = candidate.category;
    const valid = state.config.categories.some((item) => item.id === category);
    if (!valid) return `<article class="candidate-card"><div class="notice notice-warning">第 ${index + 1} 条建议的分类无法识别，请跳过并手动录入。</div></article>`;
    const definition = state.config.fields[category] || [];
    const candidateFields = candidate.fields || {};
    const primary = state.config.categories.find((item) => item.id === category).title_field;
    const shown = definition.filter((field) => Object.prototype.hasOwnProperty.call(candidateFields, field.key) || field.key === primary);
    const unknown = Object.keys(candidateFields).filter((key) => !definition.some((field) => field.key === key));
    const duplicates = (candidate.possible_duplicates || []).filter((item) => (typeof item === 'string' || !item.category || item.category === category));
    const options = duplicates.map((item) => { const id = typeof item === 'string' ? item : item.id; const title = typeof item === 'string' ? item : (item.title || item.id); return `<option value="update:${esc(id)}">更新现有：${esc(title)}</option>`; }).join('');
    const title = candidateFields[primary] || candidateFields.title || `建议 ${index + 1}`;
    const sources=(candidate.source_references||[]).map((source)=>`<li><a href="/api/ai/notes/${encodeURIComponent(state.review.note.id)}/attachments/${encodeURIComponent(source.attachment_id)}">${esc(source.filename||'原始附件')}</a>${source.page?` · 第 ${source.page} 页`:''}${source.excerpt?`<blockquote>${esc(source.excerpt)}</blockquote>`:''}</li>`).join('');
    return `<article class="candidate-card" data-candidate-index="${index}"><div class="candidate-top"><span class="candidate-number">${String(index + 1).padStart(2, '0')}</span><div><span class="candidate-category">${esc(labelFor(category))}</span><h3>${esc(title)}</h3></div><span class="candidate-result" aria-live="polite">待审核</span></div>${candidate.source_excerpt?`<blockquote class="source-excerpt"><span>对应原文</span>${esc(candidate.source_excerpt)}</blockquote>`:''}${sources?`<div class="source-files"><strong>AI 识读来源 · 请对照核查</strong><ul>${sources}</ul></div>`:''}${duplicates.length?`<div class="notice notice-warning">发现 ${duplicates.length} 条可能相似的记录。请核对后选择新建或更新；不会自动合并。</div>`:''}<label class="candidate-action-label">如何处理 <select class="field-control candidate-action"><option value="new">新建草稿</option>${options}<option value="skip">暂时跳过</option></select></label><form class="candidate-fields" data-category="${esc(category)}"><div class="form-grid">${shown.map((field) => proposalField(field, candidateFields[field.key])).join('') || '<p class="field-hint">没有识别到可填写字段。你仍可新建空白草稿，再在分类中补充。</p>'}</div>${unknown.length?`<p class="field-hint">以下字段无法对应到本平台分类，未纳入保存：${esc(unknown.join('、'))}</p>`:''}</form></article>`;
  }
  function openProposalReview(proposal, note) {
    const candidates = Array.isArray(proposal.candidates) ? proposal.candidates : [];
    const warnings = Array.isArray(proposal.warnings) ? proposal.warnings : [];
    state.review = {proposal, note};
    reviewHost.innerHTML = `<div class="review-backdrop" role="presentation"><section class="review-sheet" role="dialog" aria-modal="true" aria-labelledby="review-title"><header class="review-header"><div><p class="eyebrow">AI 提议 · 人工确认</p><h2 id="review-title">逐项审核候选记录</h2><p>AI 只提出建议；你检查每个字段和相似记录后，才会保存为草稿。</p></div><button class="button button-icon" type="button" data-review-close aria-label="关闭候选审核">×</button></header><div class="review-summary"><span class="badge badge-ready">${candidates.length} 条候选</span><span class="badge">参考 ${Number(proposal.records_count || 0)} 条本机记录</span><span class="badge">${proposal.context_mode === 'summary' ? '已用全库提纲＋相关全文' : '已参考全库学术文字'}</span></div>${proposal.context_mode === 'summary' ? '<div class="notice">资料较多：AI 收到每条记录的提纲和相关记录的全文，而不是完整的全库正文。</div>' : ''}${warnings.map((warning) => `<div class="notice notice-warning">${esc(warning)}</div>`).join('')}<div class="candidate-list">${candidates.length ? candidates.map((candidate,index) => proposalCard(candidate,index)).join('') : empty('没有可审核的建议','原笔记仍保存在本机素材箱。你可以换一种写法后重试，或手工录入。')}</div><footer class="review-footer"><p id="review-outcome" aria-live="polite">请核对 AI 提议；未知事实留空，保存后仍可编辑。</p><div><button class="button" type="button" data-review-close>稍后再说</button>${candidates.length?'<button id="review-save" class="button button-primary" type="button">保存已选择的草稿</button>':''}</div></footer></section></div>`;
    reviewHost.querySelector('.review-summary').insertAdjacentHTML('afterend', '<div class="notice">新建和更新均先保存为草稿。更新已有完整记录时，它会暂时退出简历；请核对后重新标记“整理完成”。</div>');
    for (const card of reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')) {
      const candidate = candidates[Number(card.dataset.candidateIndex)];
      for (const warning of candidate.warnings || []) card.querySelector('.candidate-fields')?.insertAdjacentHTML('beforebegin', `<div class="notice notice-warning">${esc(warning)}</div>`);
    }
    const close = () => { reviewHost.replaceChildren(); state.review = null; };
    reviewHost.querySelectorAll('[data-review-close]').forEach((button) => button.addEventListener('click', close));
    reviewHost.querySelector('.review-backdrop').addEventListener('click', (event) => { if (event.target.classList.contains('review-backdrop')) close(); });
    reviewHost.querySelector('#review-save')?.addEventListener('click', saveProposalSelections);
    reviewHost.querySelector('[data-review-close]').focus();
  }
  async function saveProposalSelections() {
    const button = reviewHost.querySelector('#review-save');
    const outcome = reviewHost.querySelector('#review-outcome');
    button.disabled = true; button.textContent = '正在逐条保存…';
    let saved = 0; let failed = 0; let skipped = 0;
    for (const card of reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')) {
      if (card.dataset.result === 'saved' || card.dataset.result === 'skipped') continue;
      const action = card.querySelector('.candidate-action').value;
      const indicator = card.querySelector('.candidate-result');
      if (action === 'skip') { card.dataset.result = 'skipped'; indicator.textContent = '已跳过'; skipped++; continue; }
      const form = card.querySelector('.candidate-fields');
      const category = form.dataset.category;
      const values = formValues(form);
      for (const choice of form.querySelectorAll('[data-include-field]')) if (!choice.checked) delete values[choice.dataset.includeField];
      values.record_state = 'draft'; values.cv_eligible = false;
      try {
        let id = null; let revision;
        if (action.startsWith('update:')) {
          id = action.slice(7);
          const original = await api(`/api/records/${encodeURIComponent(category)}/${encodeURIComponent(id)}`);
          revision = original.revision;
        } else {
          const list = await api(`/api/records/${encodeURIComponent(category)}?archived=0`);
          revision = list.revision;
        }
        const result = await api(`/api/records/${encodeURIComponent(category)}`, {method:'POST', body:JSON.stringify({id, revision, record:values})});
        card.dataset.result = 'saved';
        indicator.textContent = `已保存草稿 · ${result.record?.id || ''}`;
        card.querySelector('.candidate-action').disabled = true;
        card.querySelectorAll('.field-control').forEach((input) => { input.disabled = true; });
        saved++;
      } catch (error) {
        failed++; indicator.textContent = `保存失败：${error.payload?.error || error.message}`;
        indicator.classList.add('candidate-result-error');
      }
    }
    const remaining = [...reviewHost.querySelectorAll('.candidate-card[data-candidate-index]')].filter((card) => !['saved','skipped'].includes(card.dataset.result)).length;
    outcome.textContent = `${saved} 条已保存，${skipped} 条跳过，${failed} 条失败。${remaining ? '失败或未处理的候选仍在这里，可修正后重试。' : '所有候选已处理。'}`;
    button.disabled = remaining === 0; button.textContent = remaining ? '重试未保存的候选' : '已完成';
    if (saved) toast(`${saved} 条履历草稿已保存在本机。`, 'success');
    if (failed) toast(`${failed} 条未保存，请查看对应错误后重试。`, 'error');
    if (state.view === 'category' && saved) renderCategory();
  }

  async function renderCV() {
    const choices=Object.entries(profileNames).map(([id,name])=>`<button class="choice-button ${state.profile===id?'selected':''}" data-profile="${id}"><span>${esc(name)}</span><small>预览与导出</small></button>`).join('');
    content.innerHTML=`${heading('申请材料','简历生成','中文为默认语言；可切换英文并临时隐藏电话号码。预览与导出使用相同选项。')}<div class="cv-layout"><section class="cv-panel cv-controls"><h2 class="panel-title">申请场景</h2><div class="profile-choice">${choices}</div><div class="cv-language-controls"><label class="field-label">简历语言 <select id="cv-language" class="field-control compact-select"><option value="zh" ${state.cvLanguage==='zh'?'selected':''}>中文</option><option value="en" ${state.cvLanguage==='en'?'selected':''}>English</option></select></label><label class="toggle"><input id="cv-phone" type="checkbox" ${state.includePhone?'checked':''}>在简历中显示电话号码</label></div><div id="cv-actions"></div><div class="notice">只有标记为“已整理”且勾选“用于简历”的记录会进入预览。缺少所选语言内容时会使用已有内容并提示，不会自动翻译。</div></section><section class="cv-panel" id="cv-preview"><div class="loading">正在生成预览…</div></section></div>`;
    const reload=()=>renderCV();
    content.querySelectorAll('[data-profile]').forEach((button)=>button.addEventListener('click',()=>{state.profile=button.dataset.profile;reload();}));
    content.querySelector('#cv-language').addEventListener('change',(event)=>{state.cvLanguage=event.target.value;localStorage.setItem('zhaolian-cv-language',state.cvLanguage);reload();});
    content.querySelector('#cv-phone').addEventListener('change',(event)=>{state.includePhone=event.target.checked;localStorage.setItem('zhaolian-cv-phone',state.includePhone?'1':'0');reload();});
    const query=new URLSearchParams({lang:state.cvLanguage,include_phone:state.includePhone?'1':'0'});
    const result=await api(`/api/cv/${state.profile}?${query}`); state.cv=result; const preview=content.querySelector('#cv-preview'); const actions=content.querySelector('#cv-actions');
    if(!result.ready){preview.innerHTML=empty('还不能生成简历',result.message);actions.innerHTML='<p class="field-hint">请先填写必要的个人资料。</p>';return;}
    const sections=result.context.sections; const sectionHtml=sections.length?sections.map((section)=>`<section class="preview-section"><h3>${esc(section.title)}</h3>${section.id==='research_interests'?`<div>${esc(section.items.join(' · '))}</div>`:section.items.map((item)=>`<article class="preview-entry"><div class="preview-entry-top"><span class="preview-entry-title">${esc(item.title)}</span><span class="preview-entry-date">${esc(item.date)}</span></div>${item.subtitle?`<div class="preview-entry-sub">${esc(item.subtitle)}</div>`:''}${item.metadata?.length?`<div class="preview-entry-sub">${item.metadata.map(esc).join(' · ')}</div>`:''}${item.bullets?.length?`<ul>${item.bullets.map((bullet)=>`<li>${esc(bullet)}</li>`).join('')}</ul>`:''}</article>`).join('')}</section>`).join(''):empty('当前版本还没有入选记录','先在相应分类中整理资料并勾选“用于简历”。不会生成虚构经历。');
    preview.innerHTML=`${(result.context.warnings||[]).length?`<div class="notice notice-warning">${(result.context.warnings||[]).map(esc).join('<br>')}</div>`:''}<div class="preview-document"><h2 class="preview-name">${esc(result.context.name)}</h2>${result.context.headline?`<p class="preview-headline">${esc(result.context.headline)}</p>`:''}${result.context.contact?.length?`<p class="preview-contact">${result.context.contact.map((item)=>esc(item.value)).join(' | ')}</p>`:''}${sectionHtml}</div>`;
    actions.innerHTML=`<div class="profile-badges"><span class="badge badge-ready">${result.items} 条入选记录</span><span class="badge">${esc(result.label)}</span></div><div class="export-buttons"><button class="button button-primary" data-export="pdf">下载 PDF</button><button class="button" data-export="docx">下载 Word</button><button class="button" data-export="latex">下载 LaTeX</button></div>`;
    actions.querySelectorAll('[data-export]').forEach((button)=>button.addEventListener('click',async()=>{button.disabled=true;button.textContent='正在生成…';try{const response=await fetch(`/api/cv/${state.profile}/export/${button.dataset.export}?${query}`,{method:'POST',headers:{'X-Academic-Profile':'local-ui'}});if(!response.ok){const payload=await response.json();throw new Error(payload.error||'导出失败。');}const blob=await response.blob();const disposition=response.headers.get('content-disposition')||'';const match=disposition.match(/filename="?([^";]+)"?/);const name=match?.[1]||`zhaolian-cv-${state.profile}.${button.dataset.export}`;const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);toast(`${button.dataset.export.toUpperCase()} 已下载。`,'success');}catch(error){toast(error.message,'error');}finally{button.disabled=false;button.textContent=`下载 ${button.dataset.export==='docx'?'Word':button.dataset.export==='latex'?'LaTeX':'PDF'}`;}}));
  }

  async function renderSettings() {
    const backup=await api('/api/backup/status?refresh=1'); const repo=backup.repository==='尚未创建'?'尚未创建':backup.repository;
    await loadAIState();
    content.innerHTML=`${heading('本机与数据安全','备份与设置','平台只在本机运行；备份需要你手动点击，不会后台自动上传。')}<div class="settings-grid"><section class="settings-card"><div class="settings-icon">↥</div><h2 class="settings-title">GitHub 私有备份</h2><p class="settings-text">备份前会核验你指定的 Wang-Zhaolian/academic-profile Private 仓库，并且只提交允许清单中的程序、配置和履历文字。</p><div class="settings-meta"><div class="settings-row"><span>仓库</span><span>${esc(repo)}</span></div><div class="settings-row"><span>仓库隐私</span><span>${backup.repository==='尚未创建'?'待创建':backup.is_private?'Private':'无法核实'}</span></div><div class="settings-row"><span>当前状态</span><span>${backup.pending?'有未备份更改':'无待备份更改'}</span></div><div class="settings-row"><span>未推送的本地提交</span><span>${Number(backup.pending_commits||0)} 个</span></div><div class="settings-row"><span>上次成功备份</span><span>${esc(backup.last_successful_backup||'从未备份')}</span></div></div><button id="backup-now" class="button button-primary" ${backup.is_private===false?'disabled':''}>备份到 GitHub</button><p id="backup-message" class="field-hint">${esc(backup.message||'备份包含草稿，推送失败时本机资料不会丢失。')}</p></section><section class="settings-card"><div class="settings-icon">⌂</div><h2 class="settings-title">本机资料与隐私范围</h2><p class="settings-text">日常录入和简历生成不需要网络。联系方式及证明材料仅存放在本机。</p><ul class="privacy-list"><li>会备份：空白结构、程序、Profile 配置与履历文字（包括草稿）。</li><li>不会备份：邮箱等联系方式、证明文件、导出的简历、运行环境与登录凭据。</li><li>平台服务只监听 127.0.0.1；数据保存在项目目录。</li><li>遇到远程冲突时会停止上传，不会强制覆盖远端。</li></ul></section><section class="settings-card"><div class="settings-icon">▣</div><h2 class="settings-title">本机数据位置</h2><p class="settings-text">履历分类保存在项目文件夹的 data 目录，个人联系方式保存在 private/contact.yaml。建议定期通过 GitHub 备份程序和履历文字。</p><button class="button" id="refresh-backup">刷新备份状态</button></section></div>`;
    const backupCard=content.querySelector('#backup-now').closest('.settings-card');
    backupCard.querySelector('.settings-text').textContent='只向 Wang-Zhaolian/academic-profile 手动提交程序、配置和履历文字；推送前会核验仓库为 Private。';
    backupCard.querySelector('.settings-meta').insertAdjacentHTML('afterbegin',`<div class="settings-row"><span>远程目标</span><span>${backup.origin_matches===false?'与指定仓库不匹配':backup.origin_matches===true?'已匹配指定仓库':'待连接或核验'}</span></div>`);
    if(backup.origin_matches===false){const backupButton=content.querySelector('#backup-now');backupButton.disabled=true;backupButton.title='请先将 origin 配置为 Wang-Zhaolian/academic-profile。';}
    content.querySelector('.settings-grid').insertAdjacentHTML('afterbegin', chatgptSettingsCard());
    content.querySelector('.privacy-list').insertAdjacentHTML('beforeend', '<li>原始笔记和图片、文档附件保存在本机素材箱，不进入 GitHub；只有你采纳后的履历文字才按备份规则上传。</li><li>邮箱、电话号码及其他联系方式只保存在本机。</li>');
    bindChatGPTSettings();
    content.querySelector('#backup-now').addEventListener('click',async(event)=>{const button=event.currentTarget;button.disabled=true;button.textContent='正在备份…';const message=content.querySelector('#backup-message');message.textContent='正在检查私人仓库和允许上传的文件…';try{const result=await api('/api/backup',{method:'POST',body:'{}'});message.textContent=result.message;toast('GitHub 备份成功。','success');await renderSettings();}catch(error){message.textContent=error.payload?.error||error.message;toast('备份未完成，本机数据仍已保存。','error');button.disabled=false;button.textContent='重试备份';}});content.querySelector('#refresh-backup').addEventListener('click',renderSettings);
  }

  function chatgptSettingsCard() {
    const connected = !!state.ai?.connected;
    const sharing = !!state.ai?.sharing;
    const status = connected ? (sharing ? '已连接 · 订阅资格以请求结果为准' : (state.ai.ai_blocked ? 'AI 已暂停 · 需要重新授权' : '已登录 · 尚无方案使用权限')) : '未连接';
    return `<section class="settings-card ai-settings-card"><div class="settings-icon">✦</div><h2 class="settings-title">ChatGPT 辅助录入</h2><p class="settings-text">仅通过你的 ChatGPT 账号使用符合资格的订阅方案；这里不配置 API Key，也不会自动改用付费 API。普通录入和简历导出不依赖 AI。</p><div class="settings-meta"><div class="settings-row"><span>连接状态</span><span>${esc(status)}</span></div>${connected?`<div class="settings-row"><span>当前账号</span><span>${esc(state.ai.email || '已授权账号')}</span></div>`:''}<div class="settings-row"><span>可用模型</span><span>${esc(state.models.length ? `${state.models.length} 个` : '尚未获取')}</span></div></div>${state.ai?.error?`<div class="notice notice-warning">${esc(state.ai.error)}</div>`:''}<div class="ai-settings-actions">${!connected || !sharing?'<button id="ai-connect" class="button button-primary" type="button">使用 ChatGPT 登录</button>':''}${connected?'<button id="ai-disconnect" class="button" type="button">断开连接</button>':''}<a class="button" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">在 ChatGPT 管理用量 ↗</a></div>${connected && sharing?`<div class="settings-model-row">${modelPicker('settings-model')}</div>`:''}${aiDisclosure()}<p class="field-hint">授权只允许符合资格的 AI 请求，不会读取已有的 ChatGPT 对话。达到用量上限时请在 ChatGPT 设置中查看；本机笔记不受影响。</p></section>`;
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
  (async()=>{syncSidebar();try{state.config=await api('/api/config');buildNav();await render();}catch(error){content.innerHTML=`<div class="notice notice-warning">无法连接本机平台：${esc(error.message)}。请双击桌面快捷方式重新打开。</div>`;}})();
})();
