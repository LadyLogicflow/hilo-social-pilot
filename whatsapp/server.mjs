// HISOME/ShareNext WhatsApp-Dienst (Baileys) — MULTI-SESSION
// ----------------------------------------------------------------------------
// Laeuft als eigener kleiner Node-Prozess NEBEN dem Python-Dashboard auf dem Pi.
// Haelt MEHRERE WhatsApp-Verbindungen parallel (eine je Beratungsstelle = eigene
// Nummer), damit jede Stelle ihren eigenen Status an ihre eigenen Kontakte posten
// kann. Sessions werden ueber einen Schluessel (i.d.R. die Beratungsstellen-ID)
// angesprochen; Auth liegt persistent je Session in ./auth/<key>.
//
// HTTP-API (nur 127.0.0.1), vom Flask-Dashboard aufgerufen:
//   GET  /status?session=KEY   -> { state, qr, me, error, contacts }
//   GET  /sessions             -> { sessions: { KEY: {state,me,contacts}, ... } }
//   POST /connect              -> { ... }   body: { session }   (Session starten -> QR)
//   POST /post-status          -> { ok }|{ error }  body: { session, imagePath, caption, statusJidList?, toContacts? }
//   POST /post-channel         -> { ok }|{ error }  body: { session, jid|invite, imagePath, caption }
//   POST /logout               -> { ok }   body: { session }   (Auth loeschen, neuer QR)
//
// Hinweis: WhatsApp-Status hat keine offizielle API. Baileys nutzt das
// Linked-Device-Modell (QR-Scan). Rueckwaertskompatibel: fehlt 'session', wird
// der Standard-Schluessel 'default' benutzt.
import makeWASocket, {
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  Browsers,
  jidNormalizedUser,
} from 'baileys'
import { HttpsProxyAgent } from 'https-proxy-agent'
import qrcode from 'qrcode'
import pino from 'pino'
import http from 'http'
import fs from 'fs'
import path from 'path'

const PORT = parseInt(process.env.HILO_WHATSAPP_PORT || '8769', 10)
const AUTH_DIR = process.env.HILO_WHATSAPP_AUTH || path.join(process.cwd(), 'auth')
const proxyUrl = process.env.HTTPS_PROXY || process.env.https_proxy || ''
const agent = proxyUrl ? new HttpsProxyAgent(proxyUrl) : undefined
const logger = pino({ level: process.env.HILO_WHATSAPP_LOGLEVEL || 'warn' })

// --- Sessions ----------------------------------------------------------------
// key -> { key, state, qr, me, error, contacts:Set, sock, starting }
const sessions = new Map()

function safeKey(key) {
  const k = String(key == null || key === '' ? 'default' : key)
  return k.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 64) || 'default'
}
function authDirFor(key) { return path.join(AUTH_DIR, safeKey(key)) }

function getSess(key) {
  const k = safeKey(key)
  let s = sessions.get(k)
  if (!s) { s = { key: k, state: 'init', qr: null, me: null, error: null, contacts: new Set(), sock: null, starting: false }; sessions.set(k, s) }
  return s
}
function pub(s) { return { state: s.state, qr: s.qr, me: s.me, error: s.error, contacts: s.contacts.size } }
function ownJid(s) { return s.sock?.user?.id ? jidNormalizedUser(s.sock.user.id) : null }

function readImage(p) {
  if (!p) return null
  if (!fs.existsSync(p)) throw new Error('Bilddatei nicht gefunden: ' + p)
  return fs.readFileSync(p)
}

async function start(key) {
  const s = getSess(key)
  if (s.starting) return
  s.starting = true
  try {
    const authDir = authDirFor(key)
    const { state, saveCreds } = await useMultiFileAuthState(authDir)
    const { version } = await fetchLatestBaileysVersion()
    logger.info({ session: s.key, version: version.join('.'), proxy: proxyUrl || '(direkt)' }, 'starte WhatsApp-Sitzung')

    const sock = makeWASocket({
      version,
      auth: state,
      logger,
      agent,
      fetchAgent: agent,
      browser: Browsers.ubuntu('HISOME'),
      markOnlineOnConnect: false,
      // KONTAKT-SYNC (catrin 2026-08-27): vollen Verlaufs-/Kontakt-Abgleich beim Verbinden anfordern,
      // damit die auf dem Handy gespeicherten Kontakte ans verknuepfte Geraet uebertragen werden
      // (sonst Kontakte:0 -> Status hat kein Publikum). Kontakte kommen ueber messaging-history.set.
      syncFullHistory: true,
      // Verbindungs-Haertung (catrin-Incident 2026-08-27): gezielt gegen die beobachteten Fehler auf
      // dem Pi - "init queries Timed Out" (408) und "stream errored out" beim Nachrichten-Resend.
      defaultQueryTimeoutMs: 0,        // kein hartes Query-Timeout -> keine "Timed Out"-Abbrueche mehr
      keepAliveIntervalMs: 15000,      // Socket aktiv halten -> seltener Verbindungsabbruch
      connectTimeoutMs: 60000,         // mehr Zeit fuer den Verbindungsaufbau (Pi/Netz)
      retryRequestDelayMs: 500,        // sanftere Retries
      getMessage: async () => undefined, // Resend-Pfad graziell (verhindert stream-Fehler bei Retry)
    })
    s.sock = sock
    sock.ev.on('creds.update', saveCreds)

    const addContact = (c) => {
      const id = c?.id || c?.jid
      if (id && id.endsWith('@s.whatsapp.net')) s.contacts.add(jidNormalizedUser(id))
    }
    // DIAG (catrin 2026-08-27): Kontakte bleiben 0 trotz 1333 im Handy. Wir loggen, was WhatsApp beim
    // Verbinden wirklich schickt (Event, Anzahl, Beispiel-JIDs, laufende Summe) - auf warn-Level sichtbar.
    sock.ev.on('contacts.upsert', (cs) => {
      (cs || []).forEach(addContact)
      logger.warn({ session: s.key, ev: 'contacts.upsert', n: cs?.length || 0, total: s.contacts.size, sample: (cs || []).slice(0, 3).map(c => c?.id || c?.jid) }, 'DIAG-KONTAKTE')
    })
    sock.ev.on('contacts.update', (cs) => {
      (cs || []).forEach(addContact)
      logger.warn({ session: s.key, ev: 'contacts.update', n: cs?.length || 0, total: s.contacts.size }, 'DIAG-KONTAKTE')
    })
    sock.ev.on('messaging-history.set', (h) => {
      (h?.contacts || []).forEach(addContact)
      logger.warn({ session: s.key, ev: 'history.set', contacts: h?.contacts?.length || 0, chats: h?.chats?.length || 0, syncType: h?.syncType, isLatest: h?.isLatest, total: s.contacts.size, sample: (h?.contacts || []).slice(0, 3).map(c => c?.id || c?.jid) }, 'DIAG-KONTAKTE')
    })

    sock.ev.on('connection.update', async (u) => {
      const { connection, lastDisconnect, qr } = u
      if (qr) {
        s.state = 'qr'; s.error = null
        try { s.qr = await qrcode.toDataURL(qr, { width: 480, margin: 2 }) }
        catch (e) { s.error = 'QR-Render fehlgeschlagen: ' + e.message }
      }
      if (connection === 'open') {
        s.state = 'connected'; s.qr = null; s.error = null; s.me = sock.user?.id || null
        logger.info({ session: s.key, me: s.me }, 'verbunden')
      }
      if (connection === 'close') {
        const code = lastDisconnect?.error?.output?.statusCode
        const loggedOut = code === DisconnectReason.loggedOut
        s.error = lastDisconnect?.error?.message || null
        logger.warn({ session: s.key, code, loggedOut }, 'Verbindung geschlossen')
        if (loggedOut) {
          s.state = 'logged_out'; s.me = null; s.qr = null; s.contacts.clear()
          try { fs.rmSync(authDirFor(key), { recursive: true, force: true }) }
          catch (e) { logger.warn({ err: e.message }, 'Auth-Cleanup fehlgeschlagen') }
          setTimeout(() => start(key).catch(e => { s.error = e.message }), 1500)
        } else {
          s.state = 'closed'
          setTimeout(() => start(key).catch(e => { s.error = e.message }), 3000)
        }
      }
    })
  } catch (e) {
    s.state = 'closed'; s.error = e.message
    logger.error({ session: s.key, err: e.message }, 'Session-Start fehlgeschlagen')
  } finally {
    s.starting = false
  }
}

// --- Posting -----------------------------------------------------------------
async function postStatus(s, { imagePath, caption, statusJidList, toContacts }) {
  if (s.state !== 'connected') throw new Error('Nicht verbunden (Status: ' + s.state + ')')
  const img = readImage(imagePath)
  let recipients = []
  if (Array.isArray(statusJidList) && statusJidList.length) recipients = statusJidList.slice()
  else if (toContacts && s.contacts.size) recipients = Array.from(s.contacts)
  const me = ownJid(s)
  if (me && !recipients.includes(me)) recipients.push(me)
  if (!recipients.length) throw new Error('Keine Empfaenger fuer den Status ermittelbar.')

  const opts = { statusJidList: recipients }
  let content
  if (img) {
    content = { image: img, caption: caption || '' }
  } else {
    content = { text: caption || '' }
    opts.backgroundColor = '#0B2545'  // BSt-Next Navy
    opts.font = 3
  }
  await s.sock.sendMessage('status@broadcast', content, opts)
  return { ok: true, recipients: recipients.length }
}

async function resolveChannelJid(s, { jid, invite }) {
  if (jid) return jid
  if (invite) {
    const code = invite.split('/').pop()
    const meta = await s.sock.newsletterMetadata('invite', code)
    if (meta?.id) return meta.id
  }
  throw new Error('Kein Kanal angegeben (jid oder invite noetig)')
}

async function postChannel(s, { jid, invite, imagePath, caption }) {
  if (s.state !== 'connected') throw new Error('Nicht verbunden (Status: ' + s.state + ')')
  const target = await resolveChannelJid(s, { jid, invite })
  const img = readImage(imagePath)
  const content = img ? { image: img, caption: caption || '' } : { text: caption || '' }
  await s.sock.sendMessage(target, content)
  return { ok: true, jid: target }
}

async function logout(s) {
  try { await s.sock?.logout() } catch (_) {}
  try { fs.rmSync(authDirFor(s.key), { recursive: true, force: true }) } catch (_) {}
  s.state = 'init'; s.qr = null; s.me = null; s.error = null; s.contacts.clear()
  setTimeout(() => start(s.key).catch(e => { s.error = e.message }), 500)
  return { ok: true }
}

// Beim Start: bestehende Sessions (Auth-Ordner auf Platte) automatisch wieder verbinden.
function resumeExistingSessions() {
  let keys = []
  try { keys = fs.existsSync(AUTH_DIR) ? fs.readdirSync(AUTH_DIR, { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name) : [] }
  catch (_) { keys = [] }
  for (const k of keys) start(k).catch(e => logger.warn({ session: k, err: e.message }, 'Resume fehlgeschlagen'))
  logger.info({ count: keys.length }, 'bestehende Sessions wiederhergestellt')
}

// --- HTTP API (nur localhost) ------------------------------------------------
function sendJson(res, code, obj) {
  const body = JSON.stringify(obj)
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(body)
}
function readBody(req) {
  return new Promise((resolve) => {
    let d = ''
    req.on('data', c => { d += c; if (d.length > 5e6) req.destroy() })
    req.on('end', () => { try { resolve(d ? JSON.parse(d) : {}) } catch { resolve({}) } })
  })
}

const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, 'http://127.0.0.1')
    const p = u.pathname

    if (req.method === 'GET' && p === '/status') {
      const key = u.searchParams.get('session') || 'default'
      const s = sessions.get(safeKey(key))
      // Unbekannte Session -> noch nicht verbunden (kein Auto-Start bei reinem Status-Poll).
      return sendJson(res, 200, s ? pub(s) : { state: 'nicht_verbunden', qr: null, me: null, error: null, contacts: 0 })
    }
    if (req.method === 'GET' && p === '/sessions') {
      const out = {}
      for (const [k, s] of sessions) out[k] = { state: s.state, me: s.me, contacts: s.contacts.size }
      return sendJson(res, 200, { sessions: out })
    }
    if (req.method === 'POST' && p === '/connect') {
      const { session } = await readBody(req)
      const key = safeKey(session)
      const s = getSess(key)
      // (Neu) verbinden, wenn nicht schon verbunden/verbindend.
      if (s.state !== 'connected' && !s.starting) await start(key)
      return sendJson(res, 200, pub(getSess(key)))
    }
    if (req.method === 'POST' && p === '/post-status') {
      const body = await readBody(req)
      return sendJson(res, 200, await postStatus(getSess(body.session), body))
    }
    if (req.method === 'POST' && p === '/post-channel') {
      const body = await readBody(req)
      return sendJson(res, 200, await postChannel(getSess(body.session), body))
    }
    if (req.method === 'POST' && p === '/logout') {
      const { session } = await readBody(req)
      return sendJson(res, 200, await logout(getSess(session)))
    }
    sendJson(res, 404, { error: 'unbekannte Route' })
  } catch (e) {
    sendJson(res, 200, { error: e.message })
  }
})

server.listen(PORT, '127.0.0.1', () => logger.info({ port: PORT }, 'HTTP-API bereit (127.0.0.1)'))
resumeExistingSessions()
