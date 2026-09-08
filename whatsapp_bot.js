const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const { exec } = require('child_process');
const fs = require('fs');

async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');
    
    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log("\nSCAN QR CODE DI WHATSAPP:\n");
            qrcode.generate(qr, { small: true });
        }

        if (connection === 'close') {
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            if (shouldReconnect) startBot();
        } else if (connection === 'open') {
            console.log('\n✅ Bot Yuki WhatsApp Siap Digunakan!');
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg.message) return;

        // Mendukung pesan dari orang lain DAN pesan dari diri sendiri (Self-Chat)
        const from = msg.key.remoteJid;
        const text = msg.message.conversation || msg.message.extendedTextMessage?.text || '';

        if (text.toLowerCase().startsWith('putar')) {
            const query = text.slice(5).trim();
            if (!query) {
                await sock.sendMessage(from, { text: "Ketik: 'putar [judul lagu/artis]'" });
                return;
            }

            console.log(`📩 Memproses perintah WA: ${query}`);
            await sock.sendMessage(from, { text: `🔍 Mencari lagu online: '${query}'...` });

            if (fs.existsSync('temp_wa.mp3')) fs.unlinkSync('temp_wa.mp3');

            const searchCmd = `yt-dlp -x --audio-format mp3 -o "temp_wa.%(ext)s" --no-playlist "ytsearch1:${query} audio"`;

            exec(searchCmd, async (error) => {
                if (error) {
                    await sock.sendMessage(from, { text: "❌ Gagal mengunduh lagu." });
                    return;
                }

                if (fs.existsSync('temp_wa.mp3')) {
                    await sock.sendMessage(from, { text: "🎶 Mengirimkan audio..." });
                    await sock.sendMessage(from, {
                        audio: { url: 'temp_wa.mp3' },
                        mimetype: 'audio/mp4',
                        ptt: false
                    });
                    try { fs.unlinkSync('temp_wa.mp3'); } catch (e) {}
                } else {
                    await sock.sendMessage(from, { text: "❌ Lagu tidak ditemukan." });
                }
            });
        }
    });
}

startBot();
