/**
 * Google Sheets sync for telegram-store-admin-bot.
 *
 * Setup (5 minutes, no Google Cloud project needed):
 * 1. Create a Google Sheet -> Extensions -> Apps Script, paste this file.
 * 2. Project Settings -> Script properties -> add SECRET = any long random string.
 * 3. Deploy -> New deployment -> Web app: Execute as "Me", access "Anyone". Copy the /exec URL.
 * 4. In the bot's .env: SHEETS_WEBHOOK_URL=<that URL>, SHEETS_SECRET=<same secret>.
 *
 * The bot POSTs {"secret": "...", "row": {...}} on every paid order and every status change.
 * Rows are upserted by order_id, so the sheet always shows the current status.
 */
const SHEET_NAME = 'Orders';
const FIELDS = ['order_id', 'created', 'paid', 'status', 'customer', 'phone', 'email', 'country', 'address',
  'items', 'subtotal', 'shipping', 'shipping_option', 'total', 'currency', 'telegram_user_id', 'charge_id'];

function doPost(e) {
  const out = (obj) => ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out({ ok: false, error: 'bad json' });
  }
  const secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  if (!secret || body.secret !== secret) return out({ ok: false, error: 'forbidden' });
  const row = body.row || {};
  if (!row.order_id) return out({ ok: false, error: 'no order_id' });

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(FIELDS);
      sheet.setFrozenRows(1);
    }
    const values = FIELDS.map((f) => (row[f] === undefined ? '' : row[f]));
    const ids = sheet.getLastRow() > 1
      ? sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues().map((r) => String(r[0]))
      : [];
    const idx = ids.indexOf(String(row.order_id));
    if (idx >= 0) {
      sheet.getRange(idx + 2, 1, 1, FIELDS.length).setValues([values]);
    } else {
      sheet.appendRow(values);
    }
  } finally {
    lock.releaseLock();
  }
  return out({ ok: true });
}
