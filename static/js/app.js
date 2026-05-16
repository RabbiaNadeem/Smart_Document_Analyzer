(function () {
  const ENTITY_LABELS = {
    monetary_values: 'Monetary',
    dates: 'Dates',
    organizations: 'Organizations',
    key_metrics: 'Metrics',
  };
  const PROCESS_LABELS = ['Uploading document...', 'Analyzing content...', 'Extracting insights...'];
  const ICONS = { pdf: 'PDF', docx: 'DOCX', txt: 'TXT', csv: 'CSV' };

  const $ = (id) => document.getElementById(id);
  const dropZone = $('drop-zone');
  const fileInput = $('file-input');
  const uploadCard = $('upload-card');
  const analysisCard = $('analysis-card');
  const analysisBody = $('analysis-body');
  const progressWrap = $('progress-wrap');
  const progressFill = $('progress-bar-fill');
  const progressBarTrack = $('progress-bar-track');
  const progressStatus = $('progress-status');
  const processingSteps = $('processing-steps');
  const qaThread = $('qa-thread');
  const qaInput = $('qa-input');
  const qaSend = $('qa-send');
  const toast = $('toast');
  const stepUpload = $('step-upload');
  const stepAnalyze = $('step-analyze');
  const stepAsk = $('step-ask');

  let selectedFile = null;
  let uploadedFileId = null;
  let uploadedFileExt = null;
  let uploadedOriginalName = '';
  let lastAnalysis = null;
  let qaHistory = [];
  let analyzeStepTimer = null;
  let progressPhase = null;

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function fileExtension(name) {
    const i = name.lastIndexOf('.');
    return i >= 0 ? name.slice(i).toLowerCase() : '';
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showToast(msg, type) {
    if (!toast) return;
    toast.textContent = msg;
    toast.className = 'toast visible ' + (type || '');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove('visible'), 4000);
  }

  function setAppStep(step) {
    const map = { upload: stepUpload, analyze: stepAnalyze, ask: stepAsk };
    [stepUpload, stepAnalyze, stepAsk].forEach((el, i) => {
      if (!el) return;
      el.classList.remove('active', 'done');
      const order = ['upload', 'analyze', 'ask'];
      const idx = order.indexOf(step);
      const myIdx = order.indexOf(el.dataset.step);
      if (myIdx < idx) el.classList.add('done');
      else if (myIdx === idx) el.classList.add('active');
    });
  }

  function setProcessingStep(activeIndex, pct) {
    if (!processingSteps) return;
    processingSteps.querySelectorAll('li').forEach((li, i) => {
      li.classList.remove('active', 'done');
      if (i < activeIndex) li.classList.add('done');
      else if (i === activeIndex) li.classList.add('active');
    });
    if (progressStatus && PROCESS_LABELS[activeIndex]) {
      progressStatus.textContent = PROCESS_LABELS[activeIndex];
    }
    if (progressBarTrack) {
      if (pct == null) {
        progressBarTrack.classList.add('indeterminate');
        progressFill.style.width = '35%';
      } else {
        progressBarTrack.classList.remove('indeterminate');
        progressFill.style.width = Math.min(100, Math.max(0, pct)) + '%';
      }
    }
  }

  function showProgress() {
    if (!progressWrap) return;
    progressWrap.classList.add('visible');
    if (progressPhase === 'analyze') {
      progressWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function clearProgress() {
    progressPhase = null;
    if (analyzeStepTimer) clearTimeout(analyzeStepTimer);
    analyzeStepTimer = null;
    if (!progressWrap) return;
    progressWrap.classList.remove('visible');
    progressFill.style.width = '0%';
    if (progressBarTrack) progressBarTrack.classList.remove('indeterminate');
    processingSteps?.querySelectorAll('li').forEach((li) => {
      li.classList.remove('active', 'done');
    });
  }

  function updateUploadCard() {
    const row = $('upload-row');
    const empty = $('upload-empty');
    if (!selectedFile && !uploadedFileId) {
      uploadCard.style.display = 'block';
      if (row) row.style.display = 'none';
      if (empty) empty.style.display = 'block';
      dropZone.style.display = 'block';
      return;
    }
    if (empty) empty.style.display = 'none';
    dropZone.style.display = 'none';
    if (row) row.style.display = 'flex';
    const name = uploadedOriginalName || selectedFile?.name || 'document';
    const ext = (name.split('.').pop() || '').toLowerCase();
    $('file-icon-label').textContent = ICONS[ext] || 'DOC';
    $('upload-filename').textContent = name;
    const size = selectedFile ? formatBytes(selectedFile.size) : '';
    $('upload-meta').textContent = uploadedFileId ? 'Uploaded · ' + size : 'Ready to upload · ' + size;
    $('btn-reanalyze').disabled = !uploadedFileId;
  }

  function autoGrowTextarea() {
    qaInput.style.height = 'auto';
    qaInput.style.height = Math.min(120, Math.max(40, qaInput.scrollHeight)) + 'px';
  }

  function scrollThread() {
    if (qaThread) qaThread.scrollTop = qaThread.scrollHeight;
  }

  function renderThreadEmpty() {
    if (!qaThread) return;
    if (qaHistory.length) return;
    qaThread.innerHTML =
      '<div class="thread-empty">' +
      '<div class="thread-empty-icon" aria-hidden="true">💬</div>' +
      '<p>No questions yet</p>' +
      '<span>Ask anything about your document after analysis completes.</span>' +
      '</div>';
  }

  function appendUserMessage(text) {
    if (qaThread.querySelector('.thread-empty')) qaThread.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'msg-row user';
    wrap.innerHTML = '<div class="bubble user">' + escapeHtml(text) + '</div>';
    qaThread.appendChild(wrap);
    scrollThread();
  }

  function appendAiMessage(text, isThinking) {
    if (qaThread.querySelector('.thread-empty')) qaThread.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'msg-row ai';
    wrap.innerHTML =
      '<div class="ai-avatar" aria-hidden="true">✦</div>' +
      '<div class="bubble ai' + (isThinking ? ' thinking' : '') + '">' +
      escapeHtml(text) +
      '</div>';
    qaThread.appendChild(wrap);
    scrollThread();
    return wrap;
  }

  function removeThinking() {
    qaThread?.querySelector('.bubble.thinking')?.closest('.msg-row')?.remove();
  }

  function renderEntityPills(key, items) {
    const label = ENTITY_LABELS[key] || key;
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    const pills = list.length
      ? list.map((x) => '<span class="tag-pill">' + escapeHtml(String(x)) + '</span>').join('')
      : '<span class="tag-pill muted">None</span>';
    return (
      '<div class="entity-mini"><h4>' + escapeHtml(label) + '</h4><div class="tag-list">' + pills + '</div></div>'
    );
  }

  function renderAnalysis(data) {
    lastAnalysis = data;
    const src = data.analysis_source === 'gemini' ? 'gemini' : 'fallback';
    $('ai-badge').textContent = src === 'gemini' ? 'AI · Gemini' : 'AI · Fallback';
    $('ai-badge').className = 'ai-badge ' + (src === 'gemini' ? 'purple' : 'amber');

    $('summary-text').textContent = data.summary || '—';

    const kps = Array.isArray(data.key_points) ? data.key_points : [];
    $('key-points-list').innerHTML = kps.length
      ? kps.map((k) => '<li>' + escapeHtml(String(k)) + '</li>').join('')
      : '<li class="muted">—</li>';

    const ent = data.entities && typeof data.entities === 'object' ? data.entities : {};
    $('entity-grid').innerHTML = ['monetary_values', 'dates', 'organizations', 'key_metrics']
      .map((k) => renderEntityPills(k, ent[k]))
      .join('');

    const preview = data.extracted_text_preview || '';
    $('source-pre').textContent = preview;
    const trunc = data.extracted_text_truncated;
    $('source-trunc-hint').textContent = trunc
      ? 'Showing first ' + preview.length + ' of ' + (data.extracted_text_length || '') + ' characters.'
      : '';

    analysisCard.style.display = 'block';
    analysisBody.style.display = 'block';
    setAppStep('ask');
    qaInput.disabled = false;
    qaSend.disabled = false;
    renderThreadEmpty();

    $('export-pdf').onclick = () => exportReport('pdf');
    $('export-docx').onclick = () => exportReport('docx');
  }

  function parseFilenameFromContentDisposition(cd) {
    if (!cd) return '';
    const star = /filename\*=UTF-8''([^;\n]+)/i.exec(cd);
    if (star) {
      try {
        return decodeURIComponent(star[1].trim());
      } catch (_) {}
    }
    const quoted = /filename="([^"]+)"/i.exec(cd);
    return quoted ? quoted[1] : '';
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function exportReport(kind) {
    if (!lastAnalysis) return;
    const pdfBtn = $('export-pdf');
    const docxBtn = $('export-docx');
    pdfBtn.disabled = true;
    docxBtn.disabled = true;
    try {
      const body = {
        document_name: uploadedOriginalName || 'document' + (uploadedFileExt || ''),
        analyzed_at: new Date().toISOString(),
        summary: lastAnalysis.summary || '',
        key_points: lastAnalysis.key_points || [],
        entities: lastAnalysis.entities || {},
        analysis_source: lastAnalysis.analysis_source || null,
      };
      const res = await fetch('/api/export/' + kind, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const fn =
        parseFilenameFromContentDisposition(res.headers.get('Content-Disposition')) ||
        (kind === 'pdf' ? 'Analysis_Report.pdf' : 'Analysis_Report.docx');
      const blob = await res.blob();
      if (!res.ok) {
        showToast('Export failed', 'error');
        return;
      }
      downloadBlob(blob, fn);
    } catch (e) {
      showToast('Export failed: ' + e.message, 'error');
    } finally {
      pdfBtn.disabled = false;
      docxBtn.disabled = false;
    }
  }

  function scheduleClearProgress(phase, delayMs) {
    setTimeout(() => {
      if (progressPhase === phase) clearProgress();
    }, delayMs);
  }

  async function uploadFile() {
    if (!selectedFile) return false;
    progressPhase = 'upload';
    showProgress();
    setProcessingStep(0, 5);
    setAppStep('upload');
    const formData = new FormData();
    formData.append('file', selectedFile);
    try {
      const xhr = await new Promise((resolve, reject) => {
        const x = new XMLHttpRequest();
        x.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) setProcessingStep(0, Math.round((e.loaded / e.total) * 100));
        });
        x.addEventListener('load', () => resolve(x));
        x.addEventListener('error', () => reject(new Error('Network error')));
        x.open('POST', '/api/upload');
        x.send(formData);
      });
      setProcessingStep(0, 100);
      let data = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch (_) {}
      if (xhr.status !== 200) {
        const detail = typeof data.detail === 'string' ? data.detail : xhr.statusText;
        showToast('Upload failed: ' + detail, 'error');
        return false;
      }
      uploadedFileId = data.file_id;
      uploadedFileExt = data.file_ext || fileExtension(selectedFile.name);
      uploadedOriginalName = selectedFile.name;
      updateUploadCard();
      setAppStep('analyze');
      showToast('Document uploaded', 'success');
      return true;
    } catch (e) {
      showToast('Upload failed: ' + e.message, 'error');
      return false;
    } finally {
      scheduleClearProgress('upload', 400);
    }
  }

  async function analyzeDocument() {
    if (!uploadedFileId || !uploadedFileExt) return;
    progressPhase = 'analyze';
    showProgress();
    setAppStep('analyze');
    setProcessingStep(1, null);
    analyzeStepTimer = setTimeout(() => setProcessingStep(2, null), 1800);
    analysisBody.style.display = 'none';
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: uploadedFileId, file_ext: uploadedFileExt }),
      });
      const data = await res.json().catch(() => ({}));
      if (analyzeStepTimer) clearTimeout(analyzeStepTimer);
      setProcessingStep(2, 100);
      if (!res.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : res.statusText;
        showToast('Analysis failed: ' + detail, 'error');
        return;
      }
      qaHistory = [];
      renderAnalysis(data);
      showToast('Analysis complete', 'success');
    } catch (e) {
      showToast('Analysis failed: ' + e.message, 'error');
    } finally {
      scheduleClearProgress('analyze', 600);
    }
  }

  async function submitQuestion() {
    const q = (qaInput.value || '').trim();
    if (!q || !uploadedFileId || !uploadedFileExt || qaSend.disabled) return;
    qaInput.value = '';
    autoGrowTextarea();
    appendUserMessage(q);
    qaSend.disabled = true;
    qaInput.disabled = true;
    const thinkingRow = appendAiMessage('Thinking…', true);
    try {
      const body = {
        file_id: uploadedFileId,
        file_ext: uploadedFileExt,
        question: q,
        conversation: qaHistory.length ? qaHistory.slice() : undefined,
      };
      if (lastAnalysis) {
        body.insights = {
          summary: lastAnalysis.summary || '',
          key_points: lastAnalysis.key_points || [],
          entities: lastAnalysis.entities || {},
        };
      }
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      removeThinking();
      const detail = typeof payload.detail === 'string' ? payload.detail : res.statusText;
      const answer = res.ok ? payload.answer || '' : 'Error: ' + detail;
      if (res.ok && answer) qaHistory.push({ question: q, answer });
      appendAiMessage(answer, false);
    } catch (e) {
      removeThinking();
      appendAiMessage(e.message, false);
    } finally {
      qaSend.disabled = false;
      qaInput.disabled = false;
      qaInput.focus();
    }
  }

  function onFileSelected(file) {
    selectedFile = file;
    uploadedFileId = null;
    uploadedFileExt = null;
    lastAnalysis = null;
    qaHistory = [];
    analysisCard.style.display = 'none';
    analysisBody.style.display = 'none';
    qaInput.disabled = true;
    qaSend.disabled = true;
    setAppStep('upload');
    updateUploadCard();
    uploadFile().then((ok) => {
      if (ok) analyzeDocument();
    });
  }

  function resetFile() {
    selectedFile = null;
    uploadedFileId = null;
    uploadedFileExt = null;
    uploadedOriginalName = '';
    lastAnalysis = null;
    qaHistory = [];
    fileInput.value = '';
    analysisCard.style.display = 'none';
    analysisBody.style.display = 'none';
    qaInput.disabled = true;
    qaSend.disabled = true;
    renderThreadEmpty();
    setAppStep('upload');
    updateUploadCard();
  }

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) onFileSelected(f);
  });
  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) onFileSelected(fileInput.files[0]);
  });

  $('btn-replace').addEventListener('click', () => {
    resetFile();
    fileInput.click();
  });
  $('btn-reanalyze').addEventListener('click', () => analyzeDocument());

  qaSend.addEventListener('click', submitQuestion);
  qaInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitQuestion();
    }
  });
  qaInput.addEventListener('input', autoGrowTextarea);

  const sourceToggle = $('source-toggle');
  if (sourceToggle) {
    sourceToggle.addEventListener('click', () => {
      const open = sourceToggle.getAttribute('aria-expanded') === 'true';
      sourceToggle.setAttribute('aria-expanded', open ? 'false' : 'true');
      $('source-panel').hidden = open;
    });
  }

  setAppStep('upload');
  updateUploadCard();
  renderThreadEmpty();
  qaInput.disabled = true;
  qaSend.disabled = true;
  analysisCard.style.display = 'none';
})();
