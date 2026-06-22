// HISOME WhatsApp-Dienst (Baileys)
// ----------------------------------------------------------------------------
// Laeuft als eigener kleiner Node-Prozess NEBEN dem Python-Dashboard auf dem Pi.
// Stellt eine schlanke HTTP-API (nur 127.0.0.1) bereit, die das Flask-Dashboard
// aufruft:
//   GET  /status        -> { state, qr (dataURL|null), me, error }
//   GET  /channels      -> { channels: [...] }            (best effort)
//   POST /post-status   -> { ok } | { error }   body: { imagePath, caption, statusJidList? }
//   POST /post-channel  -> { ok } | { error }   body: { jid|invite, imagePath, caption }
//   POST /logout        -> { ok }   (Auth loeschen, neuer QR)
//
// Hinweis: WhatsApp-Status hat keine offizielle API. Baileys nutzt das
// Linked-Device-Modell (QR-Scan). Sessions liegen persistent in ./auth.
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

const S = { state: 'init', qr: null, me: null, error: null, contacts: 0 }
const contacts = new Set()  // synchronisierte Kontakt-JIDs (moegliche Status-Empfaenger)
let sock = null

function ownJid() {
  return sock?.user?.id ? jidNormalizedUser(sock.user.id) : null
}

function readImage(p) {
  if (!p) return null
  if (!fs.existsSync(p)) throw new Error('Bilddatei nicht gefunden: ' + p)
  return fs.readFileSync(p)
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()
  logger.info({ version: version.join('.'), proxy: proxyUrl || '(direkt)' }, 'starte WhatsApp-Sitzung')

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    agent,
    fetchAgent: agent,
    browser: Browsers.ubuntu('HISOME'),
    markOnlineOnConnect: false,
  })

  sock.ev.on('creds.update', saveCreds)

  // Kontakte sammeln (Empfaenger fuer Status-Broadcasts)
  const addContact = (c) => {
    const id = c?.id
    if (id && id.endsWith('@s.whatsapp.net')) { contacts.add(jidNormalizedUser(id)); S.contacts = contacts.size }
  }
  sock.ev.on('contacts.upsert', (cs) => (cs || []).forEach(addContact))
  sock.ev.on('contacts.update', (cs) => (cs || []).forEach(addContact))
  sock.ev.on('messaging-history.set', (h) => (h?.contacts || []).forEach(addContact))

  sock.ev.on('connection.update', async (u) => {
    const { connection, lastDisconnect, qr } = u
    if (qr) {
      S.state = 'qr'
      S.error = null
      try { S.qr = await qrcode.toDataURL(qr, { width: 480, margin: 2 }) }
      catch (e) { S.error = 'QR-Render fehlgeschlagen: ' + e.message }
    }
    if (connection === 'open') {
      S.state = 'connected'
      S.qr = null
      S.error = null
      S.me = sock.user?.id || null
      logger.info({ me: S.me }, 'verbunden')
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      const loggedOut = code === DisconnectReason.loggedOut
      S.error = lastDisconnect?.error?.message || null
      logger.warn({ code, loggedOut }, 'Verbindung geschlossen')
      if (loggedOut) {
        // Sitzung wurde entfernt/abgemeldet (z.B. 'device_removed') -> die gespeicherte
        // Auth ist tot. Verwerfen, damit beim Neustart ein FRISCHER QR entsteht statt
        // erneut sofort 401. Danach automatisch neu verbinden (zeigt dann den QR an).
        S.state = 'logged_out'; S.me = null; S.qr = null; contacts.clear(); S.contacts = 0
        try { fs.rmSync(AUTH_DIR, { recursive: true, force: true }) }
        catch (e) { logger.warn({ err: e.message }, 'Auth-Cleanup fehlgeschlagen') }
        setTimeout(() => start().catch(e => { S.error = e.message }), 1500)
      } else {
        S.state = 'closed'
        setTimeout(() => start().catch(e => { S.error = e.message }), 3000)
      }
    }
  })
}

// --- Posting -----------------------------------------------------------------
async function postStatus({ imagePath, caption, statusJidList, toContacts }) {
  if (S.state !== 'connected') throw new Error('Nicht verbunden (Status: ' + S.state + ')')
  const img = readImage(imagePath)
  // Ein Status-Broadcast braucht eine Empfaenger-Liste, sonst geht er ins Leere.
  //  - explizite Liste hat Vorrang
  //  - toContacts=true: an alle synchronisierten Kontakte (Produktiv-Reichweite)
  //  - sonst (Test): nur an die eigene Nummer -> erscheint in "Mein Status", ohne Kontakte zu spammen
  let recipients = []
  if (Array.isArray(statusJidList) && statusJidList.length) recipients = statusJidList.slice()
  else if (toContacts && contacts.size) recipients = Array.from(contacts)
  const me = ownJid()
  if (me && !recipients.includes(me)) recipients.push(me)  // eigene Sichtbarkeit garantieren
  if (!recipients.length) throw new Error('Keine Empfaenger fuer den Status ermittelbar.')

  const opts = { statusJidList: recipients }
  let content
  if (img) {
    content = { image: img, caption: caption || '' }
  } else {
    content = { text: caption || '' }
    opts.backgroundColor = '#1f428d'  // HILO-Blau
    opts.font = 3
  }
  await sock.sendMessage('status@broadcast', content, opts)
  return { ok: true, recipients: recipients.length }
}

async function resolveChannelJid({ jid, invite }) {
  if (jid) return jid
  if (invite) {
    const code = invite.split('/').pop()
    const meta = await sock.newsletterMetadata('invite', code)
    if (meta?.id) return meta.id
  }
  throw new Error('Kein Kanal angegeben (jid oder invite noetig)')
}

async function postChannel({ jid, invite, imagePath, caption }) {
  if (S.state !== 'connected') throw new Error('Nicht verbunden (Status: ' + S.state + ')')
  const target = await resolveChannelJid({ jid, invite })
  const img = readImage(imagePath)
  const content = img ? { image: img, caption: caption || '' } : { text: caption || '' }
  await sock.sendMessage(target, content)
  return { ok: true, jid: target }
}

async function listChannels() {
  // Baileys bietet (versionsabhaengig) keine stabile "liste alle meine Kanaele"-API.
  // Wir liefern, was wir aus dem Store kennen; ansonsten leer + Hinweis.
  try {
    const subs = await sock.newsletterFetchSubscribed?.()
    if (Array.isArray(subs)) return subs.map(n => ({ id: n.id, name: n.name || n.threadMetadata?.name }))
  } catch (_) { /* nicht verfuegbar */ }
  return []
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
    if (req.method === 'GET' && req.url === '/status') {
      return sendJson(res, 200, S)
    }
    if (req.method === 'GET' && req.url === '/channels') {
      return sendJson(res, 200, { channels: await listChannels() })
    }
    if (req.method === 'POST' && req.url === '/post-status') {
      return sendJson(res, 200, await postStatus(await readBody(req)))
    }
    if (req.method === 'POST' && req.url === '/post-channel') {
      return sendJson(res, 200, await postChannel(await readBody(req)))
    }
    if (req.method === 'POST' && req.url === '/logout') {
      try { await sock?.logout() } catch (_) {}
      fs.rmSync(AUTH_DIR, { recursive: true, force: true })
      S.state = 'init'; S.qr = null; S.me = null; S.error = null
      setTimeout(() => start().catch(e => { S.error = e.message }), 500)
      return sendJson(res, 200, { ok: true })
    }
    sendJson(res, 404, { error: 'unbekannte Route' })
  } catch (e) {
    sendJson(res, 200, { error: e.message })
  }
})

server.listen(PORT, '127.0.0.1', () => logger.info({ port: PORT }, 'HTTP-API bereit (127.0.0.1)'))
start().catch(e => { S.state = 'closed'; S.error = e.message; logger.error(e) })
