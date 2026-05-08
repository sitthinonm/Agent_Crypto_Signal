/**
 * Agent Signal Orchestrator (Google Apps Script)
 * - Runs by time-driven trigger (default every 15 mins)
 * - Calls analyzer API
 * - Pushes summary to LINE OA
 */

const LINE_PUSH_URL = 'https://api.line.me/v2/bot/message/push';
const LINE_REPLY_URL = 'https://api.line.me/v2/bot/message/reply';
const STATE_KEY = 'AGENT_SIGNAL_STATE_V1';
const MAX_FLEX_BUBBLES = 9;
const ALLOWED_INTERVALS = ['5m', '15m', '30m', '1h'];

function runAgentSignalCycle() {
  const cfg = loadConfig();
  const state = loadState();

  const payload = {
    symbols: cfg.symbols,
    interval: cfg.interval,
    limit: cfg.limit,
    include_news_context: false
  };

  const res = UrlFetchApp.fetch(cfg.analyzerUrl, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const code = res.getResponseCode();
  const body = res.getContentText();
  if (code < 200 || code >= 300) {
    if (shouldSendError(state, cfg.errorCooldownMinutes)) {
      pushLineText(cfg.token, cfg.to, 'Agent Signal error: analyzer API failed\n' + body);
      state.lastErrorAt = Date.now();
      saveState(state);
    }
    return;
  }

  const data = JSON.parse(body);
  const decision = buildSendDecision(data, state, cfg.cooldownMinutes, cfg.confidenceDelta);
  if (!decision.shouldSend) {
    writeAuditLog(cfg, data, decision, false);
    saveState(state);
    return;
  }

  const flexMessages = buildFlexMessages(data, decision.includedSymbols);
  pushLineMessages(cfg.token, cfg.to, flexMessages);
  state.lastSuccessAt = Date.now();
  saveState(state);
  writeAuditLog(cfg, data, decision, true);
}

function loadConfig() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('LINE_CHANNEL_ACCESS_TOKEN');
  const to = props.getProperty('LINE_TO');
  if (!token || !to) {
    throw new Error('Missing LINE_CHANNEL_ACCESS_TOKEN or LINE_TO script property');
  }
  const analyzerUrl = props.getProperty('ANALYZER_URL');
  if (!analyzerUrl) throw new Error('Missing ANALYZER_URL script property');

  const symbolsRaw = props.getProperty('SYMBOLS') || 'BTCUSDT,ETHUSDT,SOLUSDT';
  const symbols = symbolsRaw
    .split(',')
    .map(function (s) { return s.trim().toUpperCase(); })
    .filter(function (s) { return !!s; });
  const interval = props.getProperty('INTERVAL') || '15m';
  const limit = Number(props.getProperty('LIMIT') || '300');
  const cooldownMinutes = Number(props.getProperty('COOLDOWN_MINUTES') || '10');
  const errorCooldownMinutes = Number(props.getProperty('ERROR_COOLDOWN_MINUTES') || '15');
  const confidenceDelta = Number(props.getProperty('DUPLICATE_CONFIDENCE_DELTA') || '4');
  const auditSheetId = props.getProperty('AUDIT_SHEET_ID') || '';
  const auditSheetName = props.getProperty('AUDIT_SHEET_NAME') || 'audit_log';
  const adminUserIds = (props.getProperty('LINE_ADMIN_USER_IDS') || '')
    .split(',')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return !!s; });

  return {
    token: token,
    to: to,
    analyzerUrl: analyzerUrl,
    symbols: symbols.length ? symbols : ['BTCUSDT'],
    interval: interval,
    limit: isFinite(limit) ? Math.max(100, limit) : 300,
    cooldownMinutes: isFinite(cooldownMinutes) ? Math.max(0, cooldownMinutes) : 10,
    errorCooldownMinutes: isFinite(errorCooldownMinutes) ? Math.max(1, errorCooldownMinutes) : 15,
    confidenceDelta: isFinite(confidenceDelta) ? Math.max(1, confidenceDelta) : 4,
    auditSheetId: auditSheetId,
    auditSheetName: auditSheetName,
    adminUserIds: adminUserIds
  };
}

function doPost(e) {
  const cfg = loadConfig();
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const events = body.events || [];
    for (const ev of events) {
      handleLineEvent(cfg, ev);
    }
  } catch (err) {
    // swallow webhook parsing errors to avoid repeated retries
  }
  return ContentService.createTextOutput('ok');
}

function handleLineEvent(cfg, event) {
  if (!event || event.type !== 'message' || !event.message || event.message.type !== 'text') return;
  const replyToken = event.replyToken;
  const text = String(event.message.text || '').trim();
  const sourceUserId = (event.source && event.source.userId) || '';

  if (!isAdminAllowed(cfg, sourceUserId)) {
    replyLineText(cfg.token, replyToken, 'Permission denied: admin only');
    return;
  }

  const cmd = parseCommand(text);
  if (!cmd) return;

  if (cmd.type === 'status') {
    const interval = PropertiesService.getScriptProperties().getProperty('INTERVAL') || '15m';
    replyLineText(cfg.token, replyToken, 'Current interval: ' + interval + '\nAllowed: ' + ALLOWED_INTERVALS.join(', '));
    return;
  }

  if (cmd.type === 'set_interval') {
    if (ALLOWED_INTERVALS.indexOf(cmd.interval) < 0) {
      replyLineText(cfg.token, replyToken, 'Invalid interval. Allowed: ' + ALLOWED_INTERVALS.join(', '));
      return;
    }
    PropertiesService.getScriptProperties().setProperty('INTERVAL', cmd.interval);
    ensureRunTrigger(cmd.interval);
    replyLineText(cfg.token, replyToken, 'Interval updated to ' + cmd.interval + ' and trigger recreated.');
  }
}

function isAdminAllowed(cfg, sourceUserId) {
  if (!cfg.adminUserIds || cfg.adminUserIds.length === 0) return true;
  return cfg.adminUserIds.indexOf(sourceUserId) >= 0;
}

function parseCommand(text) {
  const lower = text.toLowerCase();
  if (lower === 'status') return { type: 'status' };
  const m = lower.match(/^(?:interval|set_interval|set interval)\s+(5m|15m|30m|1h)$/);
  if (m) return { type: 'set_interval', interval: m[1] };
  return null;
}

function ensureRunTrigger(interval) {
  const triggers = ScriptApp.getProjectTriggers();
  for (const t of triggers) {
    if (t.getHandlerFunction() === 'runAgentSignalCycle') {
      ScriptApp.deleteTrigger(t);
    }
  }

  let builder = ScriptApp.newTrigger('runAgentSignalCycle').timeBased();
  if (interval === '5m') builder = builder.everyMinutes(5);
  else if (interval === '15m') builder = builder.everyMinutes(15);
  else if (interval === '30m') builder = builder.everyMinutes(30);
  else if (interval === '1h') builder = builder.everyHours(1);
  else throw new Error('Unsupported interval: ' + interval);
  builder.create();
}

function loadState() {
  const raw = PropertiesService.getScriptProperties().getProperty(STATE_KEY);
  if (!raw) return { symbols: {}, lastErrorAt: 0, lastSuccessAt: 0, counters: {} };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed.symbols) parsed.symbols = {};
    if (!parsed.lastErrorAt) parsed.lastErrorAt = 0;
    if (!parsed.lastSuccessAt) parsed.lastSuccessAt = 0;
    if (!parsed.counters) parsed.counters = {};
    return parsed;
  } catch (err) {
    return { symbols: {}, lastErrorAt: 0, lastSuccessAt: 0, counters: {} };
  }
}

function saveState(state) {
  PropertiesService.getScriptProperties().setProperty(STATE_KEY, JSON.stringify(state));
}

function shouldSendError(state, cooldownMinutes) {
  const now = Date.now();
  const cooldownMs = cooldownMinutes * 60 * 1000;
  return now - (state.lastErrorAt || 0) >= cooldownMs;
}

function buildSendDecision(data, state, cooldownMinutes, confidenceDelta) {
  const now = Date.now();
  const cooldownMs = cooldownMinutes * 60 * 1000;
  const includedSymbols = [];
  const reasons = [];
  const transitionEvents = [];
  let skippedCount = 0;

  for (const analysis of (data.analyses || [])) {
    const key = analysis.symbol.toUpperCase();
    const plan = analysis.plan || {};
    const signature = [
      plan.signal_action || '',
      plan.strategy_mode || '',
      plan.direction || '',
      plan.entry_zone || '',
      plan.stop_loss || '',
      plan.take_profit_1 || '',
      plan.take_profit_2 || '',
      plan.take_profit_3 || '',
      plan.trailing_stop_rule || ''
    ].join('|');
    const symbolState = state.symbols[key] || {};
    const actionChanged = (symbolState.lastAction || '') !== (plan.signal_action || '');
    const tierChanged = (symbolState.lastTier || '') !== (plan.tier || '');
    const modeChanged = (symbolState.lastMode || '') !== (plan.strategy_mode || '');
    const confidenceDiff = Math.abs(Number(plan.confidence_pct || 0) - Number(symbolState.confidence || 0));
    const isDuplicate = symbolState.signature === signature && confidenceDiff < confidenceDelta;
    const inCooldown = now - Number(symbolState.lastSentAt || 0) < cooldownMs;
    const isTransition = actionChanged || tierChanged || modeChanged;
    const shouldInclude = isTransition || !isDuplicate || !inCooldown;

    if (shouldInclude) {
      includedSymbols.push(key);
      state.symbols[key] = {
        signature: signature,
        confidence: Number(plan.confidence_pct || 0),
        lastSentAt: now,
        lastAction: plan.signal_action || '',
        lastTier: plan.tier || '',
        lastMode: plan.strategy_mode || ''
      };
      const sendReason = isTransition ? 'transition' : 'fresh';
      reasons.push(key + ':send_' + sendReason);
      if (isTransition) transitionEvents.push(key + ':' + (plan.signal_action || '-') + ':' + (plan.strategy_mode || '-'));
    } else {
      reasons.push(key + ':skip_duplicate');
      skippedCount += 1;
    }
  }

  state.counters.sent = Number(state.counters.sent || 0) + includedSymbols.length;
  state.counters.skipped = Number(state.counters.skipped || 0) + skippedCount;
  state.counters.cycles = Number(state.counters.cycles || 0) + 1;

  return {
    shouldSend: includedSymbols.length > 0,
    includedSymbols: includedSymbols,
    reason: reasons.join(', '),
    transitions: transitionEvents,
    skippedCount: skippedCount
  };
}

function buildFlexMessages(data, includedSymbols) {
  const analyses = (data.analyses || []).filter(function (a) {
    return includedSymbols.indexOf(a.symbol.toUpperCase()) >= 0;
  });
  const bubbles = [];
  for (const a of analyses.slice(0, MAX_FLEX_BUBBLES)) {
    const p = a.plan || {};
    bubbles.push({
      type: 'bubble',
      body: {
        type: 'box',
        layout: 'vertical',
        spacing: 'sm',
        contents: [
          { type: 'text', text: a.symbol, weight: 'bold', size: 'xl' },
          { type: 'text', text: 'Bias: ' + (a.trend_bias || '-') + ' | Regime: ' + (a.market_regime || '-'), size: 'sm', wrap: true },
          { type: 'text', text: 'Action: ' + (p.signal_action || '-') + ' (' + (p.strategy_mode || '-') + ')', size: 'sm', wrap: true },
          { type: 'separator', margin: 'sm' },
          { type: 'text', text: 'Entry ' + (p.entry_zone || '-'), size: 'sm', wrap: true },
          { type: 'text', text: 'SL ' + (p.stop_loss || '-') + ' | TP1 ' + (p.take_profit_1 || '-') + ' | TP2 ' + (p.take_profit_2 || '-') + (p.take_profit_3 ? (' | TP3 ' + p.take_profit_3) : ''), size: 'sm', wrap: true },
          { type: 'text', text: 'Conf ' + (p.confidence_pct || 0) + '% | Tier ' + (p.tier || '-'), size: 'sm', wrap: true }
          ,{ type: 'text', text: 'Trail: ' + (p.trailing_stop_rule || '-'), size: 'xs', wrap: true, color: '#666666' }
        ]
      },
      footer: {
        type: 'box',
        layout: 'vertical',
        contents: [
          { type: 'text', text: (p.signal_id || '-'), size: 'xs', color: '#888888', wrap: true }
        ]
      }
    });
  }

  const headerText = 'Agent Signal ' + (data.interval || '-') + ' | ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  const messages = [{
    type: 'flex',
    altText: buildFallbackText(data, analyses),
    contents: {
      type: 'carousel',
      contents: bubbles.length ? bubbles : [{
        type: 'bubble',
        body: {
          type: 'box',
          layout: 'vertical',
          contents: [{ type: 'text', text: 'No new signal after cooldown/duplicate check', wrap: true }]
        }
      }]
    }
  }];
  messages.unshift({ type: 'text', text: headerText.substring(0, 4900) });
  return messages;
}

function pushLineText(token, to, text) {
  pushLineMessages(token, to, [{ type: 'text', text: text.substring(0, 4900) }]);
}

function pushLineMessages(token, to, messages) {
  UrlFetchApp.fetch(LINE_PUSH_URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({
      to: to,
      messages: messages
    }),
    muteHttpExceptions: true
  });
}

function replyLineText(token, replyToken, text) {
  if (!replyToken) return;
  UrlFetchApp.fetch(LINE_REPLY_URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({
      replyToken: replyToken,
      messages: [{ type: 'text', text: text.substring(0, 4900) }]
    }),
    muteHttpExceptions: true
  });
}

function buildFallbackText(data, analyses) {
  const lines = ['Agent Signal Report (' + (data.interval || '-') + ')'];
  for (const a of analyses) {
    const p = a.plan || {};
    lines.push(
      [
        a.symbol,
        'Bias ' + (a.trend_bias || '-') + ' | Action ' + (p.signal_action || '-'),
        'Entry ' + (p.entry_zone || '-'),
        'SL ' + (p.stop_loss || '-') + ' TP1 ' + (p.take_profit_1 || '-') + ' TP2 ' + (p.take_profit_2 || '-') + (p.take_profit_3 ? (' TP3 ' + p.take_profit_3) : ''),
        'Conf ' + (p.confidence_pct || 0) + '%'
      ].join('\n')
    );
  }
  return lines.join('\n\n').substring(0, 3800);
}

function writeAuditLog(cfg, data, decision, sent) {
  const nowIso = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss");
  const summary = {
    time: nowIso,
    interval: data.interval || cfg.interval,
    sent: sent,
    reason: decision.reason || '',
    symbols: decision.includedSymbols || [],
    transitions: decision.transitions || [],
    skipped_count: Number(decision.skippedCount || 0)
  };
  const props = PropertiesService.getScriptProperties();
  props.setProperty('LAST_AUDIT_LOG', JSON.stringify(summary));
  props.setProperty('LAST_CYCLE_METRICS', JSON.stringify({
    time: nowIso,
    sent_symbols: Number((decision.includedSymbols || []).length),
    skipped_symbols: Number(decision.skippedCount || 0),
    transitions: decision.transitions || []
  }));

  if (!cfg.auditSheetId) return;
  try {
    const ss = SpreadsheetApp.openById(cfg.auditSheetId);
    const sheet = ss.getSheetByName(cfg.auditSheetName) || ss.insertSheet(cfg.auditSheetName);
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(['timestamp', 'interval', 'symbol', 'action', 'strategy_mode', 'bias', 'entry', 'sl', 'tp1', 'tp2', 'confidence', 'rr_estimate', 'risk_grade', 'sent', 'reason']);
    }
    for (const a of (data.analyses || [])) {
      const p = a.plan || {};
      sheet.appendRow([
        nowIso,
        data.interval || cfg.interval,
        a.symbol,
        p.signal_action || '',
        p.strategy_mode || '',
        a.trend_bias || '',
        p.entry_zone || '',
        p.stop_loss || '',
        p.take_profit_1 || '',
        p.take_profit_2 || '',
        p.confidence_pct || 0,
        p.rr_estimate || '',
        p.risk_grade || '',
        sent,
        decision.reason || ''
      ]);
    }
  } catch (err) {
    props.setProperty('LAST_AUDIT_SHEET_ERROR', String(err));
  }
}
