/**
 * Lully · Plano de etiquetas — Apps Script
 *
 * Lives inside your Google Sheet
 * Open via Extensions → Apps Script, paste this whole file, save.
 *
 * What this does:
 *   onOpen()           — adds the "🥖 Lully" custom menu when the sheet opens
 *   setup()            — initialises the 3 tabs (idempotent, safe to re-run)
 *   configureGithub()  — one-time prompt to store the GitHub PAT
 *   generateLabels()   — POSTs a repository_dispatch event to GitHub. The
 *                        Action handles CSV → PDF → Drive → release_history.
 *
 * One-time setup:
 *   1. Run setup() from the menu (or from the editor → ▶ setup).
 *   2. Run "Configure GitHub trigger" from the menu and paste:
 *        owner   = '<your-github-username>'
 *        repo    = '<your-repo-name>'
 *        PAT     = a fine-grained GitHub PAT with Contents: write on this repo
 */

const TAB = {
  sample:   'sample',
  realData: 'real_data',
  history:  'release_history'
};

// Header slugs — must match what scripts/build-labels.py reads.
// Order in this array = on-sheet column order = on-label icon order for allergens.
// 5 allergens (gluten/milk/egg/peanut/soy). The 5th source-PDF icon depicts
// soybeans (originally mislabelled "nuts" in this repo); slug corrected.
const COLUMNS = [
  {key:'name_fr',        kind:'text',     width:220, note:'Nome do produto em francês — será impresso em maiúsculas. Use Alt+Enter para forçar quebra de linha no título.'},
  {key:'description_pt', kind:'text',     width:280, note:'Descrição curta em português — em itálico'},
  {key:'gluten',         kind:'checkbox', width: 70, note:'Contém glúten?'},
  {key:'milk',           kind:'checkbox', width: 70, note:'Contém leite?'},
  {key:'egg',            kind:'checkbox', width: 70, note:'Contém ovos?'},
  {key:'peanut',         kind:'checkbox', width: 70, note:'Contém amendoim?'},
  {key:'soy',            kind:'checkbox', width: 70, note:'Contém soja?'},
  {key:'price',          kind:'number',   width: 90, note:'Use ponto como separador decimal — ex: 4.20'},
  {key:'active',         kind:'checkbox', width: 70, note:'Marque ✓ para incluir no próximo PDF'}
];

// 8 sample products from the original Plano etiquetas PDF, in the same
// row-by-row visual order as the source layout.
// The "\n" inside name_fr / description_pt is a forced line break — bakery
// staff insert these in their own data with Alt+Enter inside a Sheet cell.
// Allergen flags reflect what's actually shown in each label of the source.
const SAMPLE_ROWS = [
  // [name_fr, description_pt, gluten, milk, egg, peanut, soy, price, active]
  // row 1
  ['GATEAU BASQUE\nÀ LA PART','tarte de massa sablé,\ncreme de amêndoa, rum',  true, true, true, false, false, 4.20, true],
  ['CAKE AU CITRON',          'bolo de citrinos',                              true, true, true, false, false, 3.50, true],
  // row 2
  ['CAKE\nAU CHOCOLAT',       'bolo de chocolate negro',                       true, true, true, true,  true,  4.00, true],
  ['BROWNIE',                 'brownie de chocolate negro',                    true, true, true, true,  true,  3.50, true],
  // row 3
  ['CANNELÉ\nBORDELAIS',      'cannele caramelizado,\nbaunilha e rum',         true, true, true, false, false, 2.50, true],
  ['COOKIE\nAU CHOCOLAT',     'cookie de chocolate negro',                     true, true, true, true,  true,  3.20, true],
  // row 4
  ['FINANCIER',               'bolo de farinha de amêndoa,\nmanteiga caramelizada', true, true, true, false, false, 2.80, true],
  ['GATEAU BASQUE\nENTIER',   'tarte de massa sablé,\ncreme de amêndoa, rum',  true, true, true, false, false, 28.00, true]
];

const HISTORY_HEADERS = [
  'timestamp', 'requested_by', 'pdf_drive_link',
  'csv_snapshot_link', 'num_labels', 'status', 'notes'
];

// ---------------- menu ----------------

function onOpen() {
  SpreadsheetApp.getUi().createMenu('🥖 Lully')
    .addItem('Generate labels (PDF)', 'generateLabels')
    .addSeparator()
    .addItem('Setup / repair tabs', 'setup')
    .addItem('Configure GitHub trigger', 'configureGithub')
    .addItem('Show config', 'showConfig')
    .addToUi();
}

// ---------------- setup ----------------

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  _setupSampleTab(ss);
  _setupRealDataTab(ss);
  _setupHistoryTab(ss);
  // Drop the auto-generated "Sheet1" if still present
  const sheet1 = ss.getSheetByName('Sheet1');
  if (sheet1 && ss.getSheets().length > 1) ss.deleteSheet(sheet1);
  // Reorder tabs: real_data first, then sample, then history
  ss.setActiveSheet(ss.getSheetByName(TAB.realData));
  ss.moveActiveSheet(1);
  ss.setActiveSheet(ss.getSheetByName(TAB.sample));
  ss.moveActiveSheet(2);
  ss.setActiveSheet(ss.getSheetByName(TAB.history));
  ss.moveActiveSheet(3);
  ss.setActiveSheet(ss.getSheetByName(TAB.realData));
  SpreadsheetApp.getUi().alert(
    'Tabs ready',
    'real_data → edit your products here\nsample → reference (read-only)\nrelease_history → audit log',
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function _setupSampleTab(ss) {
  const sh = _ensureSheet(ss, TAB.sample);
  sh.clear();
  _writeHeaderRow(sh);
  sh.getRange(2, 1, SAMPLE_ROWS.length, COLUMNS.length).setValues(SAMPLE_ROWS);
  _applyValidations(sh, SAMPLE_ROWS.length);
  _applyColumnWidths(sh);
  sh.getRange(1, 1, 1, COLUMNS.length).setBackground('#F4EEDF').setFontWeight('bold');
  sh.setFrozenRows(1);
  // Make sample read-only (warning only, so admin can still edit if needed)
  sh.getProtections(SpreadsheetApp.ProtectionType.SHEET).forEach(p => p.remove());
  const protection = sh.protect()
    .setDescription('Reference data — please do not edit')
    .setWarningOnly(true);
}

function _setupRealDataTab(ss) {
  const sh = _ensureSheet(ss, TAB.realData);

  // Guard: if A2 already contains a formula (e.g. =IMPORTRANGE pulling
  // from a separate staff-editing sheet), don't touch the data area —
  // overwriting it would clobber the cross-sheet link. Header row 1 is
  // still allowed to be (re-)written below since the IMPORTRANGE setup
  // documented in docs/usage.*.md keeps row 1 hard-coded.
  const importedDataPresent = !!sh.getRange(2, 1).getFormula();

  // Don't clear if user data already exists — only seed when truly empty
  const hadHeader = sh.getRange(1, 1).getValue() === COLUMNS[0].key;
  _writeHeaderRow(sh);
  if (!hadHeader && sh.getLastRow() < 2 && !importedDataPresent) {
    // First-time setup: seed with one example so the user sees the format
    sh.getRange(2, 1, 1, COLUMNS.length).setValues([SAMPLE_ROWS[0]]);
  }
  if (!importedDataPresent) {
    _applyValidations(sh, 200);
  }
  _applyColumnWidths(sh);
  sh.getRange(1, 1, 1, COLUMNS.length)
    .setBackground('#1A1613').setFontColor('#FFFFFF').setFontWeight('bold');
  sh.setFrozenRows(1);
}

function _setupHistoryTab(ss) {
  const sh = _ensureSheet(ss, TAB.history);
  sh.getRange(1, 1, 1, HISTORY_HEADERS.length).setValues([HISTORY_HEADERS])
    .setBackground('#1A1613').setFontColor('#FFFFFF').setFontWeight('bold');
  sh.setColumnWidths(1, HISTORY_HEADERS.length, 160);
  sh.setColumnWidth(3, 320);  // pdf_drive_link
  sh.setColumnWidth(4, 280);  // csv_snapshot_link
  sh.setColumnWidth(7, 240);  // notes
  sh.setFrozenRows(1);
}

function _ensureSheet(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function _writeHeaderRow(sh) {
  const headers = COLUMNS.map(c => c.key);
  const notes   = COLUMNS.map(c => c.note || '');
  sh.getRange(1, 1, 1, COLUMNS.length).setValues([headers]).setNotes([notes]);
}

function _applyValidations(sh, dataRows) {
  COLUMNS.forEach((col, i) => {
    const range = sh.getRange(2, i + 1, dataRows, 1);
    if (col.kind === 'checkbox') {
      range.setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());
    } else if (col.kind === 'number') {
      range.setNumberFormat('0.00');
    }
    // name_fr can contain forced line breaks (Alt+Enter); WRAP keeps the
    // cell visually showing them. Description is also long, wrap helps too.
    if (col.key === 'name_fr' || col.key === 'description_pt') {
      range.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
    }
  });
}

function _applyColumnWidths(sh) {
  COLUMNS.forEach((col, i) => sh.setColumnWidth(i + 1, col.width));
}

// ---------------- config ----------------

function configureGithub() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  const cur = props.getProperties();

  const owner = ui.prompt(
    'GitHub repo owner',
    'e.g. <your-github-username>' + (cur.GITHUB_OWNER ? '\n(currently: ' + cur.GITHUB_OWNER + ')' : ''),
    ui.ButtonSet.OK_CANCEL);
  if (owner.getSelectedButton() !== ui.Button.OK) return;

  const repo = ui.prompt(
    'GitHub repo name',
    'e.g. <your-repo-name>' + (cur.GITHUB_REPO ? '\n(currently: ' + cur.GITHUB_REPO + ')' : ''),
    ui.ButtonSet.OK_CANCEL);
  if (repo.getSelectedButton() !== ui.Button.OK) return;

  const pat = ui.prompt(
    'GitHub PAT',
    'Fine-grained PAT with Contents: write on this repo.\nLeave empty to keep current value.',
    ui.ButtonSet.OK_CANCEL);
  if (pat.getSelectedButton() !== ui.Button.OK) return;

  const updates = {
    GITHUB_OWNER: owner.getResponseText().trim() || cur.GITHUB_OWNER,
    GITHUB_REPO:  repo.getResponseText().trim()  || cur.GITHUB_REPO
  };
  if (pat.getResponseText().trim()) updates.GITHUB_PAT = pat.getResponseText().trim();
  props.setProperties(updates);

  ui.alert('Saved. You can now use "Generate labels (PDF)".');
}

function showConfig() {
  const props = PropertiesService.getScriptProperties().getProperties();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  SpreadsheetApp.getUi().alert(
    'Lully · Config',
    [
      'Sheet ID: ' + ss.getId(),
      '',
      'Script Properties:',
      '  GITHUB_OWNER = ' + (props.GITHUB_OWNER || '(not set)'),
      '  GITHUB_REPO  = ' + (props.GITHUB_REPO  || '(not set)'),
      '  GITHUB_PAT   = ' + (props.GITHUB_PAT ? '✓ set (hidden)' : '(not set)')
    ].join('\n'),
    SpreadsheetApp.getUi().ButtonSet.OK);
}

// ---------------- the trigger ----------------

function generateLabels() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  const owner = props.getProperty('GITHUB_OWNER');
  const repo  = props.getProperty('GITHUB_REPO');
  const pat   = props.getProperty('GITHUB_PAT');
  if (!owner || !repo || !pat) {
    ui.alert('Configuration missing',
      'Run "Configure GitHub trigger" from the 🥖 Lully menu first.',
      ui.ButtonSet.OK);
    return;
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(TAB.realData);
  if (!sh || sh.getLastRow() < 2) {
    ui.alert('No data', 'The "real_data" tab is empty.', ui.ButtonSet.OK);
    return;
  }

  // Validate: every active row must have a name_fr
  const data = sh.getRange(2, 1, sh.getLastRow() - 1, COLUMNS.length).getValues();
  const activeIdx = COLUMNS.findIndex(c => c.key === 'active');
  const nameIdx   = COLUMNS.findIndex(c => c.key === 'name_fr');
  let active = 0;
  const errors = [];
  data.forEach((row, i) => {
    if (row[activeIdx]) {
      active++;
      if (!String(row[nameIdx] || '').trim()) errors.push('row ' + (i + 2));
    }
  });
  if (errors.length) {
    ui.alert('Missing names',
      'Active rows without name_fr: ' + errors.join(', '),
      ui.ButtonSet.OK);
    return;
  }
  if (active === 0) {
    ui.alert('No active rows',
      'No row has the "active" checkbox ticked.',
      ui.ButtonSet.OK);
    return;
  }

  const requestId = Utilities.getUuid();
  const requestedBy = Session.getActiveUser().getEmail() || 'anonymous';

  const payload = {
    event_type: 'generate-labels',
    client_payload: {
      request_id: requestId,
      sheet_id:   ss.getId(),
      tab:        TAB.realData,
      requested_by: requestedBy,
      requested_at: new Date().toISOString(),
      num_active: active
    }
  };
  const resp = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + owner + '/' + repo + '/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: {
        'Authorization': 'Bearer ' + pat,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

  // GitHub returns 204 No Content on success
  if (resp.getResponseCode() !== 204) {
    ui.alert('GitHub dispatch failed',
      'HTTP ' + resp.getResponseCode() + '\n\n' + resp.getContentText(),
      ui.ButtonSet.OK);
    return;
  }

  // Append a "submitted" row immediately; the Action will append a "success" or "failed" row when done
  ss.getSheetByName(TAB.history).appendRow([
    new Date().toISOString(),
    requestedBy,
    '',
    '',
    active,
    'submitted',
    'request_id=' + requestId
  ]);

  ss.toast('Submitted. PDF will appear in release_history within ~2 min.', '🥖 Lully', 8);
}
