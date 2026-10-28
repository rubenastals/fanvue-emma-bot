/* Same-origin client. Provider credentials exist only in the Python backend. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {config: null, session: null, selected: new Map(), sessions: new Map(), candidates: [], comparisonId: null, busy: false, tab: 'memory', traceId: null, drafts: new Map(), ratings: new Map(), batchSessions: [], search: ''};
  const axes = {naturalness: 'Naturalidad', relevance: 'Pertinencia', continuity: 'Continuidad', commercial_judgment: 'Criterio comercial'};
  const actionNames = {CONTINUE_CHAT: 'Continuar la conversación', PRESENT_OFFER: 'Presentar una opción', SUPPORT_ACCESS: 'Atender el acceso', ANSWER_PENDING_OFFER: 'Responder sobre la oferta', EXPLAIN_IDENTITY: 'Explicar la identidad', NO_CONTACT: 'Respetar la petición de no contacto', HUMAN_CONTROL: 'Control humano'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
  const key = (provider, model) => `${provider}\u001f${model}`;
  const money = (amount, currency = 'USD') => new Intl.NumberFormat('es-ES', {style: 'currency', currency}).format(Number(amount || 0) / 100);
  const display = value => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—');
  const setStatus = value => { $('status-text').textContent = value; };
  const setError = value => { $('error-banner').textContent = value || ''; $('error-banner').hidden = !value; };
  const choices = () => [...state.selected.values()].map(item => ({provider: item.provider, model: item.model, ...(item.provider_tag ? {provider_tag: item.provider_tag} : {})}));
  const scenario = () => state.config?.scenarios.find(item => item.id === state.session?.scenario_id);
  function errorText(data) {
    const detail = data?.detail ?? data?.error ?? data?.message;
    if (Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join(' ');
    if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
    return String(detail || 'No se pudo completar la solicitud.');
  }
  async function api(path, method = 'GET', body) {
    const response = await fetch(path, {method, credentials: 'same-origin', headers: body === undefined ? {} : {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(errorText(data)); error.status = response.status; throw error; }
    return data;
  }
  function setBusy(value) {
    state.busy = value;
    $('busy-progress').hidden = !value;
    document.querySelectorAll('button,input,textarea,select').forEach(el => {
      if (value) { el.dataset.preBusyDisabled = String(el.disabled); el.disabled = true; }
      else if ('preBusyDisabled' in el.dataset) { el.disabled = el.dataset.preBusyDisabled === 'true'; delete el.dataset.preBusyDisabled; }
    });
  }
  async function perform(label, fn) {
    if (state.busy) return;
    setError(''); setStatus(label); setBusy(true);
    try { await fn(); }
    catch (error) {
      if (error.status === 409 && state.session) {
        try { adopt(await api(`/lab/sessions/${encodeURIComponent(state.session.id)}`)); } catch (_) { /* Preserve original failure. */ }
      }
      setError(error.message + (error.status === 409 ? ' Se ha recargado el estado disponible.' : ''));
      setStatus('La operación no se completó. Revisa el mensaje de error.');
    } finally { setBusy(false); render(); }
  }
  function adopt(session, candidates) {
    state.session = session;
    if (!session) return;
    state.sessions.set(session.scenario_id, session.id);
    const all = candidates || session.candidates || [];
    const last = all[all.length - 1];
    state.comparisonId = last?.comparison_id || null;
    state.candidates = last ? all.filter(item => item.comparison_id === last.comparison_id) : [];
    if (!state.candidates.some(item => item.id === state.traceId)) state.traceId = state.candidates[0]?.id || null;
  }
  async function loadConfig(initial = false) {
    state.config = await api('/lab/config');
    if (initial || !state.selected.size) {
      const available = state.config.providers.filter(item => item.configured && item.id !== 'fixture');
      const initialProviders = available.length ? available : state.config.providers.filter(item => item.configured);
      for (const provider of initialProviders) {
        for (const model of provider.models.slice(0, available.length ? 2 : 1)) {
          const m = typeof model === 'string' ? {id: model, label: model} : model;
          state.selected.set(key(provider.id, m.id), {provider: provider.id, model: m.id, provider_tag: m.provider_tag});
        }
      }
    }
  }
  async function selectCase(id, fresh = false) {
    const sid = !fresh && state.sessions.get(id);
    const session = sid ? await api(`/lab/sessions/${encodeURIComponent(sid)}`) : await api('/lab/sessions', 'POST', {scenario_id: id});
    adopt(session); $('fan-message').value = '';
    setStatus(`${scenario()?.title || 'Caso'} · contexto cargado.`);
  }
  function renderProviders() {
    if (!state.config) return;
    const rows = [];
    for (const provider of state.config.providers) {
      for (const entry of provider.models || []) {
        const model = typeof entry === 'string' ? {id: entry, label: entry} : entry;
        const selected = state.selected.has(key(provider.id, model.id));
        if (state.search && !`${model.id} ${model.label} ${provider.label}`.toLowerCase().includes(state.search) && !selected) continue;
        rows.push({provider, model, selected});
      }
    }
    // A refreshed catalog can contain hundreds of models: search expands the relevant subset.
    const shown = rows.sort((a, b) => Number(b.selected) - Number(a.selected)).slice(0, state.search ? 40 : 12);
    $('provider-options').innerHTML = shown.map(({provider, model, selected}) => `<div class="provider-option${selected ? ' selected' : ''}"><label class="provider-label"><input type="checkbox" data-provider="${escape(provider.id)}" data-model="${escape(model.id)}" ${selected ? 'checked' : ''} ${provider.configured ? '' : 'disabled'}><span class="provider-copy"><span class="provider-name">${escape(model.label || model.id)}</span><span class="badge ${provider.configured ? (provider.id === 'fixture' ? 'warning' : 'good') : ''}">${provider.id === 'fixture' ? 'Sin IA' : provider.configured ? 'Con clave' : 'Sin configurar'}</span></span></label><p class="provider-reason">${escape(provider.id === 'fixture' ? 'Ejemplos para comprobar el funcionamiento' : `${provider.label} · ${model.id}`)}</p>${model.provider_tag ? `<p class="provider-reason">Ruta: ${escape(model.provider_tag)}${model.quantization ? ` · ${escape(model.quantization)}` : ''}</p>` : ''}${provider.reason ? `<p class="provider-reason">${escape(provider.reason)}</p>` : ''}</div>`).join('') || '<p class="muted small">Ningún modelo coincide con la búsqueda.</p>';
    const selected = choices();
    $('provider-summary').textContent = `${selected.length} seleccionado${selected.length === 1 ? '' : 's'} · máximo ${state.config.evaluation?.max_models || 4}${rows.length > shown.length ? ` · ${shown.length} de ${rows.length} visibles; busca para filtrar` : ''}`;
    $('mode-notice').textContent = selected.some(item => item.provider !== 'fixture') ? 'Inferencias reales mediante OpenRouter. Se comparan copias del mismo contexto; los nombres se revelan después de valorar. Las llamadas consumen saldo del proveedor.' : 'Modo funcional: respuestas preparadas, sin modelo. Sirve para probar controles y estado; no mide calidad de conversación.';
  }
  function renderCases() {
    if (!state.config) return;
    $('case-count').textContent = state.config.scenarios.length;
    $('scenario-list').innerHTML = state.config.scenarios.map(item => `<button type="button" class="scenario-button" data-case="${escape(item.id)}" aria-pressed="${item.id === state.session?.scenario_id}"><span class="scenario-name">${escape(item.title)}</span><span class="scenario-description">${escape(item.description)}</span></button>`).join('');
  }
  function renderSession() {
    const s = state.session;
    if (!s) return;
    $('conversation-title').textContent = s.fan.name;
    $('fan-avatar').textContent = s.fan.name.slice(0, 1).toUpperCase();
    $('session-meta').textContent = `Emma · personaje IA · ${s.fan.language === 'en' ? 'Inglés' : 'Español'}`;
    $('revision-label').textContent = `Revisión ${s.revision}`;
    const commerce = s.memory.commerce;
    const status = !commerce.offers_enabled ? 'Ofertas desactivadas' : commerce.paused ? 'Pausa comercial' : commerce.offer_pending ? 'Oferta pendiente' : 'Sin oferta pendiente';
    $('session-badges').innerHTML = `<span class="badge brand">${escape(scenario()?.title || s.scenario_id)}</span><span class="badge ${!commerce.offers_enabled || commerce.paused ? 'warning' : ''}">${escape(status)}</span>`;
    $('pause-notice').hidden = !s.paused;
    $('pause-button').textContent = s.paused ? 'Reanudar' : 'Pausar';
    $('pause-button').setAttribute('aria-pressed', String(s.paused));
    $('transcript').innerHTML = s.messages.map(message => {
      if (message.role === 'event') return `<p class="event-message">${escape(message.content)}</p>`;
      const assistant = message.role === 'assistant';
      return `<div class="message${assistant ? ' assistant' : ''}"><div class="message-meta"><span>${escape(assistant ? 'Emma · IA' : `${s.fan.name} · fan ficticio`)}</span><span>${escape(message.id.slice(0, 8))}</span></div><div class="message-bubble">${escape(message.content)}</div></div>`;
    }).join('');
    $('generate-button').textContent = choices().length > 1 ? 'Comparar respuestas' : 'Generar respuesta';
    $('generate-button').disabled = !choices().length || s.paused || commerce.no_contact;
    $('batch-button').disabled = !choices().length;
    $('send-turn-button').disabled = !$('fan-message').value.trim();
  }
  function candidateState(candidate) {
    if (candidate.review === 'approved') return ['Aprobada', 'good'];
    if (candidate.review === 'rejected') return ['Rechazada', ''];
    if (candidate.status === 'incomplete') return ['Respuesta incompleta', 'warning'];
    if (candidate.status !== 'ready') return ['Error del proveedor', 'error'];
    if (candidate.revision !== state.session?.revision) return ['Contexto anterior', 'warning'];
    return [candidate.is_fixture ? 'Ejemplo preparado' : 'Por revisar', candidate.is_fixture ? 'warning' : 'brand'];
  }
  function renderCandidates() {
    const comparisons = [...new Set((state.session?.candidates || []).map(item => item.comparison_id))];
    $('comparison-history').innerHTML = comparisons.length > 1 ? `<label class="comparison-history-label">Comparación de esta sesión<select id="comparison-history-select">${comparisons.map((id, index) => `<option value="${escape(id)}" ${id === state.comparisonId ? 'selected' : ''}>Intento ${index + 1} · ${(state.session.candidates || []).filter(item => item.comparison_id === id).length} respuesta(s)</option>`).join('')}</select></label>` : '';
    $('candidates').classList.toggle('multiple', state.candidates.length > 1);
    $('comparison-description').textContent = state.candidates.length ? `${state.candidates.length} alternativa${state.candidates.length === 1 ? '' : 's'} sobre una copia del mismo contexto.` : 'Genera una respuesta al último mensaje.';
    $('reveal-button').hidden = !state.comparisonId || !state.candidates.some(item => !item.revealed && !item.is_fixture);
    if (!state.candidates.length) {
      $('candidates').innerHTML = '<div class="empty-state"><h3>La siguiente respuesta está por probar.</h3><p>Selecciona hasta cuatro modelos y genera sus propuestas. Después podrás valorarlas y continuar con una.</p></div>';
      return;
    }
    $('candidates').innerHTML = state.candidates.map(c => {
      const [label, tone] = candidateState(c);
      const ready = c.status === 'ready';
      const canReview = ready && c.review === 'pending' && c.revision === state.session?.revision && !state.session?.paused;
      const draft = state.drafts.get(c.id) ?? c.text;
      const rating = state.ratings.get(c.id) || {scores: {}, notes: '', saved: false};
      const metrics = c.metrics || {};
      const meta = [Number.isFinite(metrics.latency_ms) ? `${(metrics.latency_ms / 1000).toFixed(1)} s` : null, Number.isFinite(metrics.input_tokens) ? `${metrics.input_tokens} tokens entrada` : null, Number.isFinite(metrics.output_tokens) ? `${metrics.output_tokens} salida` : null, Number.isFinite(metrics.cost_usd) ? `${metrics.cost_usd.toFixed(5)} USD` : null].filter(Boolean);
      return `<article class="candidate ${ready ? 'ready' : ''}" data-candidate="${escape(c.id)}"><div class="candidate-heading"><h3><span class="candidate-letter">${escape(c.label)}</span>Respuesta</h3><span class="badge ${tone}">${escape(label)}</span></div><p class="candidate-model">${escape(c.model ? `${c.model}${c.requested_provider_tag ? ` · ${c.requested_provider_tag}` : ''}` : 'Modelo oculto para la valoración')}</p>${c.error ? `<div class="candidate-error">${escape(c.error)}</div>` : ''}${c.text ? `<label class="candidate-text-label" for="draft-${escape(c.id)}">Borrador · editable antes de aprobar</label><textarea id="draft-${escape(c.id)}" class="candidate-text" data-draft="${escape(c.id)}" maxlength="6000" ${canReview ? '' : 'disabled'}>${escape(draft)}</textarea>` : ''}${(c.validation_issues || []).length ? `<p class="fixture-notice">${escape(c.validation_issues.join(' '))}</p>` : ''}<div class="candidate-meta">${meta.map(value => `<span>${escape(value)}</span>`).join('')}</div>${ready ? `<div class="candidate-actions"><button class="button primary" type="button" data-review="approve" data-id="${escape(c.id)}" ${canReview ? '' : 'disabled'}>Aprobar y continuar</button><button class="button" type="button" data-review="reject" data-id="${escape(c.id)}" ${canReview ? '' : 'disabled'}>Rechazar</button><button class="button quiet" type="button" data-trace="${escape(c.id)}">Ver contexto</button></div>` : `<button class="button quiet small-button" type="button" data-trace="${escape(c.id)}">Ver diagnóstico</button>`}${c.is_fixture ? '<p class="fixture-notice">Prueba funcional sin IA. Este ejemplo no entra en la valoración de modelos.</p>' : ready ? `<details class="rating-details"><summary>Valorar la respuesta original${rating.saved ? ' · guardada' : ''}</summary><p class="rating-note">1 = deficiente · 3 = aceptable · 5 = muy buena. Valora el texto original del modelo, antes de tus cambios.</p><p class="rating-original">${escape(c.text)}</p><div class="rating-grid">${Object.entries(axes).map(([axis, name]) => `<label>${name}<select data-rating="${axis}" data-id="${escape(c.id)}"><option value="">Sin valorar</option>${[1,2,3,4,5].map(score => `<option value="${score}" ${Number(rating.scores[axis]) === score ? 'selected' : ''}>${score}${score === 1 ? ' · Deficiente' : score === 3 ? ' · Aceptable' : score === 5 ? ' · Muy buena' : ''}</option>`).join('')}</select></label>`).join('')}</div><label class="rating-notes">¿Qué mejorarías?<textarea data-rating-notes="${escape(c.id)}" maxlength="2000" rows="2">${escape(rating.notes)}</textarea></label><div class="rating-footer"><button class="button small-button" type="button" data-save-rating="${escape(c.id)}">Guardar valoración</button><span class="rating-note">${c.revealed ? 'Modelo revelado' : 'Valoración a ciegas'}${rating.saved ? ' · Guardada' : ''}</span></div></details>` : ''}</article>`;
    }).join('');
  }
  function factName(name) { return ({preferred_name: 'Nombre preferido', language: 'Idioma', occupation: 'Profesión', favorite_music: 'Música preferida'}[name] || name); }
  function renderInspector() {
    const s = state.session;
    if (!s) return;
    const commerce = s.memory.commerce;
    $('memory-panel').innerHTML = `<section class="inspector-section"><h3 class="inspector-label">Datos con procedencia</h3>${s.memory.facts.length ? s.memory.facts.map(fact => `<div class="memory-item"><div class="memory-line"><span class="memory-key">${escape(factName(fact.key))}</span><span class="memory-value">${escape(display(fact.value))}</span></div><p class="memory-source">Origen: ${escape(fact.source_message_id)}</p></div>`).join('') : '<p class="muted small">No hay hechos duraderos registrados para este caso.</p>'}</section><section class="inspector-section"><h3 class="inspector-label">Estado comercial</h3><div class="memory-item"><div class="memory-line"><span class="memory-key">Ofertas</span><span class="memory-value">${!commerce.offers_enabled ? 'Desactivadas' : commerce.paused ? 'Pausadas' : 'Permitidas según contexto'}</span></div><p class="memory-source">${escape(commerce.preference_source || commerce.pause_source || 'Estado inicial del caso')}</p></div><div class="memory-item"><div class="memory-line"><span class="memory-key">Archivos adquiridos</span><span class="memory-value">${commerce.purchased_assets.length}</span></div></div><div class="memory-item"><div class="memory-line"><span class="memory-key">Compras ficticias</span><span class="memory-value">${escape(money(commerce.spent_minor, commerce.currency))}</span></div></div>${s.memory.corrections?.length ? `<p class="memory-source">${s.memory.corrections.length} corrección(es) conservadas en la traza.</p>` : ''}</section>`;
    const d = s.decision;
    const offer = commerce.offer_pending || d.offer;
    $('decision-panel').innerHTML = `<section class="inspector-section"><h3 class="inspector-label">Acción autorizada</h3><div class="decision-card"><h3>${escape(actionNames[d.action] || d.action)}</h3><p>${escape(d.reason)}</p></div><h3 class="inspector-label evidence-heading">Evidencias</h3><ul class="evidence-list">${(d.evidence_message_ids || []).map(id => `<li>${escape(s.messages.find(message => message.id === id)?.content || id)}</li>`).join('')}</ul></section>${offer ? `<section class="inspector-section"><h3 class="inspector-label">Catálogo ficticio</h3><div class="product-card"><div class="product-heading"><h3>${escape(offer.title)}</h3><span class="product-price">${escape(money(offer.price_minor, offer.currency))}</span></div><p>${offer.assets.length} archivos · ${commerce.offer_pending ? 'Oferta aprobada pendiente' : 'Opción propuesta; todavía sin aprobar'}</p><button class="button" type="button" id="purchase-button" ${commerce.offer_pending ? '' : 'disabled'}>Simular compra</button></div></section>` : '<section class="inspector-section"><h3 class="inspector-label">Oferta</h3><p class="muted small">Ningún producto autorizado en este turno.</p></section>'}`;
    const c = state.candidates.find(item => item.id === state.traceId) || state.candidates[0];
    const trace = c?.trace;
    const diagnostic = state.config.diagnostics;
    $('context-panel').innerHTML = `<section class="inspector-section"><h3 class="inspector-label">Persona del laboratorio</h3><p class="muted small">${escape(diagnostic.lab_persona_chars ?? '—')} caracteres. El laboratorio usa una ficha propia y reglas sintéticas.</p><details class="context-message"><summary>Diagnóstico estático del repositorio</summary><div class="context-size"><span>Ficha original</span><span>${escape(diagnostic.persona_input_chars)}</span></div><div class="context-size"><span>Presupuesto CORE</span><span>${escape(diagnostic.core_budget_chars)}</span></div>${diagnostic.truncated ? '<p class="context-warning">La ficha original excede el presupuesto. Este dato no comprueba la configuración de producción.</p>' : ''}</details></section>${trace ? `<section class="inspector-section"><h3 class="inspector-label">Traza de ${escape(c.label)}</h3><p class="muted small">${escape(trace.pipeline || '')}</p><details class="context-message"><summary>Tamaños del contexto</summary><pre>${escape(JSON.stringify(trace.prompt_sizes, null, 2))}</pre></details>${Object.entries(trace.stages || {}).map(([name, text]) => `<div class="trace-stage"><h4>${escape(({original:'Respuesta original',first_sanitized:'Primera normalización',final:'Respuesta final'})[name] || name)}</h4><p>${escape(text)}</p></div>`).join('')}<details class="context-message"><summary>Mensajes enviados al modelo</summary>${(trace.messages || []).map(message => `<div class="context-message"><h4>${escape(message.role)}</h4><pre>${escape(message.content)}</pre></div>`).join('')}</details><details class="context-message"><summary>Cambios registrados</summary><pre>${escape(JSON.stringify(trace.changes || [], null, 2))}</pre></details></section>` : '<section class="inspector-section"><p class="muted small">Genera una respuesta para inspeccionar su contexto efectivo y las etapas de redacción.</p></section>'}`;
    setTab(state.tab);
  }
  function setTab(tab) {
    state.tab = tab;
    ['memory', 'decision', 'context'].forEach(name => { $(`${name}-panel`).hidden = name !== tab; $(`${name}-tab`).setAttribute('aria-selected', String(name === tab)); });
  }
  function render() { renderProviders(); renderCases(); renderSession(); renderCandidates(); renderInspector(); }
  async function showReports(scroll = true) {
    const [report, history] = await Promise.all([api('/lab/reports'), api('/lab/sessions')]);
    $('reports-section').hidden = false;
    $('reports-content').innerHTML = `<div class="report-summary"><div><strong>${report.real_candidates}</strong><span>Respuestas reales completas</span></div><div><strong>${report.rated_real_candidates}</strong><span>Valoraciones humanas</span></div><div><strong>${report.functional_candidates}</strong><span>Pruebas funcionales</span></div><div><strong>${report.errors || 0}</strong><span>Errores registrados</span></div></div>${report.ratings_by_model.length ? `<div class="table-wrap"><table class="results-table"><thead><tr><th>Modelo y ruta</th><th>n</th><th>A ciegas</th>${Object.values(axes).map(axis => `<th>${axis}</th>`).join('')}</tr></thead><tbody>${report.ratings_by_model.map(row => `<tr><td>${escape(row.model)}${row.provider_tag ? `<br><span class="muted">${escape(row.provider_tag)}</span>` : ''}</td><td>${row.count}</td><td>${row.blind_ratings ?? '—'}</td>${Object.keys(axes).map(axis => `<td>${escape(row.scores[axis] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="small muted">Medias de valoraciones humanas sobre 5. Compara tamaños de muestra y casos antes de elegir un modelo.</p>` : '<div class="empty-state"><h3>Todavía no hay una valoración de calidad.</h3><p>Valora respuestas reales desde las tarjetas del chat. Las respuestas preparadas quedan excluidas.</p></div>'}`;
    const sessions = (history.sessions || []).filter(item => item.comparison_count > 0);
    $('history-results').innerHTML = `<h3 class="batch-heading">Continuar una prueba guardada</h3><p class="small muted">Recupera respuestas de sesiones anteriores sin revelar los modelos.</p>${sessions.length ? `<div class="history-controls"><label for="session-history-select">Sesión</label><select id="session-history-select">${sessions.map(item => { const title = state.config.scenarios.find(s => s.id === item.scenario_id)?.title || item.scenario_id; const date = item.created_at ? new Date(item.created_at).toLocaleString('es-ES', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : ''; return `<option value="${escape(item.id)}">${escape(`${title} · ${item.fan_name || ''} · ${date} · ${item.comparison_count} comparación(es)`)}</option>`; }).join('')}</select><button class="button" id="open-history-button" type="button">Abrir respuestas</button></div>` : '<p class="small muted">Las sesiones aparecerán aquí después de generar respuestas.</p>'}`;
    if (scroll) $('reports-section').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  function ratingFor(id) {
    if (!state.ratings.has(id)) state.ratings.set(id, {scores: {}, notes: '', saved: false});
    return state.ratings.get(id);
  }
  document.addEventListener('change', event => {
    const el = event.target;
    if (el.matches('[data-provider]')) {
      const selectionKey = key(el.dataset.provider, el.dataset.model);
      if (el.checked) {
        if (state.selected.size >= (state.config.evaluation?.max_models || 4)) { el.checked = false; setError('Selecciona como máximo cuatro modelos.'); return; }
        const provider = state.config.providers.find(item => item.id === el.dataset.provider);
        const model = provider.models.find(item => item.id === el.dataset.model);
        state.selected.set(selectionKey, {provider: provider.id, model: model.id, provider_tag: model.provider_tag});
      } else state.selected.delete(selectionKey);
      setError(''); renderProviders(); renderSession();
    } else if (el.matches('[data-rating]')) { const rating = ratingFor(el.dataset.id); rating.scores[el.dataset.rating] = Number(el.value); rating.saved = false; }
    else if (el.id === 'comparison-history-select') {
      state.comparisonId = el.value;
      state.candidates = (state.session.candidates || []).filter(item => item.comparison_id === el.value);
      state.traceId = state.candidates[0]?.id || null;
      renderCandidates(); renderInspector();
    }
  });
  document.addEventListener('input', event => {
    const el = event.target;
    if (el.id === 'fan-message') $('send-turn-button').disabled = !el.value.trim() || state.busy;
    else if (el.matches('[data-draft]')) state.drafts.set(el.dataset.draft, el.value);
    else if (el.matches('[data-rating-notes]')) { const rating = ratingFor(el.dataset.ratingNotes); rating.notes = el.value; rating.saved = false; }
    else if (el.id === 'model-search') { state.search = el.value.trim().toLowerCase(); renderProviders(); }
  });
  $('fan-form').addEventListener('submit', event => {
    event.preventDefault();
    const message = $('fan-message').value.trim();
    if (!message || !state.session) return;
    perform('Añadiendo mensaje y actualizando contexto…', async () => {
      adopt(await api(`/lab/sessions/${state.session.id}/turns`, 'POST', {message, expected_revision: state.session.revision}));
      $('fan-message').value = ''; setStatus('Mensaje añadido. Genera las respuestas para este nuevo contexto.');
    });
  });
  $('fan-message').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('fan-form').requestSubmit(); } });
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || button.disabled || state.busy) return;
    if (button.dataset.tab) return setTab(button.dataset.tab);
    if (button.dataset.case) return perform('Cargando caso…', () => selectCase(button.dataset.case));
    if (button.dataset.trace) { state.traceId = button.dataset.trace; renderInspector(); setTab('context'); return; }
    if (button.dataset.batchSession) return perform('Cargando respuesta del lote…', async () => { adopt(await api(`/lab/sessions/${encodeURIComponent(button.dataset.batchSession)}`)); setStatus('Sesión del lote cargada. Puedes valorar sus respuestas.'); $('conversation').scrollIntoView({behavior:'smooth', block:'start'}); });
    if (button.dataset.review) return perform('Guardando revisión…', async () => {
      const candidate = state.candidates.find(item => item.id === button.dataset.id);
      const body = {candidate_id: candidate.id, expected_revision: state.session.revision, action: button.dataset.review};
      if (button.dataset.review === 'approve') body.edited_text = state.drafts.get(candidate.id) ?? candidate.text;
      adopt(await api(`/lab/sessions/${state.session.id}/review`, 'POST', body));
      setStatus(button.dataset.review === 'approve' ? 'Respuesta aprobada e incorporada a la conversación ficticia.' : 'Respuesta rechazada.');
    });
    if (button.dataset.saveRating) return perform('Guardando valoración…', async () => {
      const id = button.dataset.saveRating, rating = ratingFor(id);
      if (!Object.keys(axes).every(axis => rating.scores[axis] >= 1 && rating.scores[axis] <= 5)) throw new Error('Completa las cuatro valoraciones antes de guardar.');
      await api('/lab/ratings', 'POST', {candidate_id: id, scores: rating.scores, notes: rating.notes}); rating.saved = true;
      setStatus('Valoración humana guardada.');
    });
    if (button.id === 'generate-button') return perform('Generando respuestas sobre el mismo contexto…', async () => {
      const data = await api(`/lab/sessions/${state.session.id}/generate`, 'POST', {providers: choices(), expected_revision: state.session.revision, blind: true});
      adopt(data.session, data.candidates); state.comparisonId = data.comparison_id;
      const errors = data.candidates.filter(item => item.status !== 'ready').length;
      setStatus(errors ? `Comparación terminada con ${errors} respuesta(s) fallida(s) o incompleta(s). Revisa cada tarjeta.` : 'Respuestas listas. Valóralas antes de revelar los modelos.');
    });
    if (button.id === 'reveal-button') return perform('Revelando modelos…', async () => {
      const data = await api(`/lab/comparisons/${state.comparisonId}/reveal`, 'POST'); state.candidates = data.candidates;
      const updates = new Map(data.candidates.map(item => [item.id, item]));
      state.session.candidates = state.session.candidates.map(item => updates.get(item.id) || item);
      setStatus('Modelos revelados. Las nuevas valoraciones constarán como no ciegas.');
    });
    if (button.id === 'reset-button') return perform('Creando un nuevo intento…', () => selectCase(state.session.scenario_id, true));
    if (button.id === 'pause-button') return perform('Actualizando control humano…', async () => {
      adopt(await api(`/lab/sessions/${state.session.id}/events`, 'POST', {type: state.session.paused ? 'resume' : 'pause', expected_revision: state.session.revision}));
      setStatus(state.session.paused ? 'Caso pausado. El control humano está activo.' : 'Caso reanudado.');
    });
    if (button.id === 'purchase-button') return perform('Registrando compra ficticia…', async () => {
      adopt(await api(`/lab/sessions/${state.session.id}/events`, 'POST', {type: 'purchase', expected_revision: state.session.revision, event_id: crypto.randomUUID(), offer_id: state.session.memory.commerce.offer_pending.id}));
      setStatus('Compra ficticia registrada. Los archivos adquiridos quedan en el historial.');
    });
    if (button.id === 'refresh-config-button') return perform('Comprobando conexiones…', async () => { await loadConfig(); setStatus('Configuración actualizada.'); });
    if (button.id === 'toggle-models-button') {
      const hidden = !$('model-picker').hidden; $('model-picker').hidden = hidden;
      button.setAttribute('aria-expanded', String(!hidden)); button.textContent = hidden ? 'Elegir modelos' : 'Ocultar modelos'; return;
    }
    if (button.id === 'catalog-button') return perform('Actualizando catálogo de OpenRouter…', async () => {
      const data = await api('/lab/providers/openrouter/models');
      const provider = state.config.providers.find(item => item.id === 'openrouter'); provider.models = data.models;
      setStatus(`Catálogo actualizado: ${data.models.length} modelos. Busca por nombre o identificador.`);
    });
    if (button.id === 'report-button') return perform('Cargando resultados…', async () => { await showReports(); setStatus('Resultados actualizados.'); });
    if (button.id === 'open-history-button') return perform('Recuperando prueba guardada…', async () => {
      const id = $('session-history-select').value;
      adopt(await api(`/lab/sessions/${encodeURIComponent(id)}`));
      setStatus('Respuestas guardadas recuperadas. Puedes continuar la valoración.');
      $('conversation').scrollIntoView({behavior:'smooth', block:'start'});
    });
    if (button.id === 'close-reports-button') { $('reports-section').hidden = true; return; }
    if (button.id === 'export-button') return perform('Preparando exportación…', async () => {
      const data = await api('/lab/export'); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'conversation-lab-results.json'; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
      setStatus('Resultados exportados. La exportación incluye los nombres de los modelos.');
    });
    if (button.id === 'batch-button') return perform(`Evaluando ${state.config.scenarios.length} casos con ${choices().length} modelo(s). Esta operación puede tardar varios minutos…`, async () => {
      const result = await api('/lab/evaluations', 'POST', {providers: choices(), scenario_ids: state.config.scenarios.map(item => item.id), repetitions: 1});
      state.batchSessions = result.session_ids;
      $('batch-results').innerHTML = `<h3 class="batch-heading">Sesiones del último lote</h3><p class="small muted">${result.comparisons} comparaciones · ${result.errors} errores. Abre cada caso para revisar sus respuestas.</p><div class="batch-list">${result.session_ids.map((id, index) => `<button class="button small-button" type="button" data-batch-session="${escape(id)}">${escape(state.config.scenarios[index % state.config.scenarios.length]?.title || `Caso ${index + 1}`)}</button>`).join('')}</div>`;
      await showReports(); setStatus(`Lote terminado: ${result.comparisons} comparaciones y ${result.errors} errores.`);
    });
  });
  document.querySelector('.tabs').addEventListener('keydown', event => {
    const tabs = ['memory', 'decision', 'context'];
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault(); let index = tabs.indexOf(state.tab);
    index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : -1) + 3) % 3;
    setTab(tabs[index]); $(`${tabs[index]}-tab`).focus();
  });
  perform('Conectando con el laboratorio…', async () => {
    await loadConfig(true);
    if (!state.config.scenarios.length) throw new Error('No hay casos de prueba configurados.');
    await selectCase(state.config.scenarios[0].id);
    if (matchMedia('(max-width: 640px)').matches) { $('model-picker').hidden = true; $('toggle-models-button').setAttribute('aria-expanded', 'false'); $('toggle-models-button').textContent = 'Elegir modelos'; }
  });
})();
