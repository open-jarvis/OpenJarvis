/**
 * OpenJarvis WhatsApp Baileys Bridge
 *
 * JSON-line protocol on stdio:
 *
 * Input commands (stdin):
 *   {"type":"send","jid":"<jid>","text":"<message>"}
 *   {"type":"disconnect"}
 *
 * Output events (stdout):
 *   {"type":"message","jid":"<jid>","sender":"<sender>","text":"<text>","message_id":"<id>"}
 *   {"type":"status","status":"connected"|"disconnected"}
 *   {"type":"qr","data":"<qr-string>"}
 *   {"type":"error","message":"<description>"}
 */

import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  WASocket,
} from "@whiskeysockets/baileys";
import * as readline from "readline";
import * as qrcodeTerminal from "qrcode-terminal";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emit(event: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

function parseArgs(): { authDir: string } {
  const args = process.argv.slice(2);
  let authDir = "./auth";
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--auth-dir" && i + 1 < args.length) {
      authDir = args[i + 1];
      break;
    }
  }
  return { authDir };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const { authDir } = parseArgs();

  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  let sock: WASocket | null = null;

  function startSocket(): void {
    sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Show QR in stderr for local debugging and emit structured event.
        qrcodeTerminal.generate(qr, { small: true }, (code: string) => {
          process.stderr.write(code + "\n");
        });
        emit({ type: "qr", data: qr });
      }

      if (connection === "close") {
        // Baileys 7.x dropped DisconnectReason.unknown; treat absent statusCode
        // as a transient error and reconnect, matching the previous behaviour.
        const statusCode =
          (lastDisconnect?.error as any)?.output?.statusCode ?? 0;

        if (statusCode === DisconnectReason.loggedOut) {
          emit({ type: "status", status: "disconnected" });
          emit({ type: "error", message: "Logged out from WhatsApp" });
        } else {
          // Attempt reconnect for transient failures.
          emit({ type: "status", status: "disconnected" });
          startSocket();
        }
      } else if (connection === "open") {
        emit({ type: "status", status: "connected" });
      }
    });

    sock.ev.on("messages.upsert", (m) => {
      for (const msg of m.messages) {
        if (!msg.message || msg.key.fromMe) continue;
        const text =
          msg.message.conversation ||
          msg.message.extendedTextMessage?.text ||
          "";
        if (!text) continue;

        emit({
          type: "message",
          jid: msg.key.remoteJid || "",
          sender: msg.key.participant || msg.key.remoteJid || "",
          text,
          message_id: msg.key.id || "",
        });
      }
    });
  }

  startSocket();

  // -----------------------------------------------------------------------
  // Stdin command processing
  // -----------------------------------------------------------------------

  const rl = readline.createInterface({ input: process.stdin });

  rl.on("line", async (line: string) => {
    let cmd: Record<string, unknown>;
    try {
      cmd = JSON.parse(line);
    } catch {
      emit({ type: "error", message: "Invalid JSON on stdin" });
      return;
    }

    if (cmd.type === "send" && sock) {
      try {
        await sock.sendMessage(cmd.jid as string, { text: cmd.text as string });
      } catch (err: any) {
        emit({ type: "error", message: `Send failed: ${err.message}` });
      }
    } else if (cmd.type === "disconnect") {
      if (sock) {
        sock.end(undefined);
      }
      emit({ type: "status", status: "disconnected" });
      process.exit(0);
    }
  });

  rl.on("close", () => {
    if (sock) {
      sock.end(undefined);
    }
    process.exit(0);
  });
}

main().catch((err) => {
  emit({ type: "error", message: `Fatal: ${err.message}` });
  process.exit(1);
});
