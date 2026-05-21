"""
Finance Monitor — Phase 2
Bot Telegram avec polling horaire + commandes manuelles
"""

import os
import json
import logging
import asyncio
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

async def send_safe(bot, chat_id: int, text: str, parse_mode: str = "Markdown"):
    """Send message with automatic RetryAfter handling."""
    while True:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return
        except Exception as e:
            if "Retry in" in str(e):
                import re
                wait = int(re.search(r"Retry in (\d+)", str(e)).group(1)) + 1
                log.warning(f"Flood control — waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                raise

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SLASH_API_KEY      = os.getenv("SLASH_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")  # optionnel au départ
POLL_INTERVAL_SEC  = int(os.getenv("POLL_INTERVAL_SEC", "3600"))  # 1h par défaut

SEEN_FILE = "seen_transactions.json"

SLASH_ENTITIES = [
    (os.getenv("SLASH_LEGAL_ENTITY_1"), "WCATFM LLC"),
    (os.getenv("SLASH_LEGAL_ENTITY_2"), "DG SOLUTION LLC"),
]

WHOP_API_KEY    = os.getenv("WHOP_API_KEY")
WHOP_COMPANY_ID = os.getenv("WHOP_COMPANY_ID")

# ─── SÉCURITÉ ─────────────────────────────────────────────────────────────────

def is_authorized(update: Update) -> bool:
    """Check that the command comes from the authorized group."""
    if not TELEGRAM_CHAT_ID:
        return True  # Pas encore configuré, on autorise pour récupérer le chat_id
    return str(update.effective_chat.id) == str(TELEGRAM_CHAT_ID)

def authorized_only(func):
    """Decorator qui bloque les commandes hors groupe autorisé."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update):
            log.warning(f"Access denied — chat_id: {update.effective_chat.id}")
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, context)
    return wrapper

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── SEEN TRANSACTIONS (déduplication) ────────────────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("tx_ids", []))
    return set()

def save_seen(seen: set):
    data = {}
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
    data["tx_ids"] = list(seen)
    data["updated_at"] = datetime.now().isoformat()
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_seen_key(key: str) -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
            return set(data.get(key, []))
    return set()

def save_seen_key(key: str, seen: set):
    data = {}
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
    data[key] = list(seen)
    data["updated_at"] = datetime.now().isoformat()
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─── SLASH API ────────────────────────────────────────────────────────────────

def get_slash_transactions(entity_id: str) -> list:
    headers = {
        "X-API-Key": SLASH_API_KEY,
        "x-legal-entity": entity_id,
    }
    try:
        resp = requests.get("https://api.joinslash.com/transaction", headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("items", [])
    except Exception as e:
        log.error(f"Slash API error ({entity_id}): {e}")
    return []

def get_slash_balance(entity_id: str) -> list:
    headers = {
        "X-API-Key": SLASH_API_KEY,
        "x-legal-entity": entity_id,
    }
    try:
        resp = requests.get("https://api.joinslash.com/account", headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("items", [])
    except Exception as e:
        log.error(f"Slash balance error ({entity_id}): {e}")
    return []

def get_slash_balance_for_account(account_id: str, entity_id: str) -> list:
    """Fetch balances for a specific account."""
    headers = {
        "X-API-Key": SLASH_API_KEY,
        "x-legal-entity": entity_id,
    }
    try:
        resp = requests.get(
            f"https://api.joinslash.com/account/{account_id}/balance",
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("balances", [])
    except Exception as e:
        log.error(f"Slash balance error ({account_id}): {e}")
    return []

# ─── WHOP API ─────────────────────────────────────────────────────────────────

def get_whop_payments() -> list:
    if not WHOP_API_KEY or not WHOP_COMPANY_ID:
        return []
    try:
        resp = requests.get(
            "https://api.whop.com/api/v1/payments",
            headers={"Authorization": f"Bearer {WHOP_API_KEY}"},
            params={"company_id": WHOP_COMPANY_ID, "per_page": 100},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception as e:
        log.error(f"Whop API error: {e}")
    return []

def get_whop_unpaid_payments(days: int = 30) -> list:
    """Fetch failed payments with no successful payment from same user (last N days)."""
    if not WHOP_API_KEY or not WHOP_COMPANY_ID:
        return []
    try:
        from datetime import timedelta
        cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        all_payments = []
        page = 1
        while page <= 5:
            resp = requests.get(
                "https://api.whop.com/api/v1/payments",
                headers={"Authorization": f"Bearer {WHOP_API_KEY}"},
                params={"company_id": WHOP_COMPANY_ID, "per_page": 100, "page": page},
                timeout=10
            )
            if resp.status_code != 200:
                break
            data  = resp.json()
            items = data.get("data", [])
            if not items:
                break
            recent = [p for p in items if str(p.get("created_at", "")) >= cutoff_str]
            all_payments.extend(recent)
            if len(recent) < len(items):
                break
            if not data.get("page_info", {}).get("has_next_page", False):
                break
            page += 1
        paid_user_ids = set(
            (p.get("user") or {}).get("id")
            for p in all_payments
            if p.get("status") == "paid" and p.get("total", 0) > 0
        )
        paid_user_ids.discard(None)
        failed = [p for p in all_payments if p.get("payments_failed", 0) > 0]
        return [p for p in failed if (p.get("user") or {}).get("id") not in paid_user_ids]
    except Exception as e:
        log.error(f"Whop unpaid error: {e}")
    return []

def get_whop_user(user_id: str) -> dict:
    """Fetch Whop user details (name, email) from user_id via v5."""
    if not user_id:
        return {}
    try:
        resp = requests.get(
            f"https://api.whop.com/v5/app/users/{user_id}",
            headers={"Authorization": f"Bearer {WHOP_API_KEY}"},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.error(f"Whop user error ({user_id}): {e}")
    return {}

def get_whop_failed_payments(days: int = 7) -> list:
    """Fetch Whop failed payments from last N days."""
    if not WHOP_API_KEY or not WHOP_COMPANY_ID:
        return []
    try:
        from datetime import timedelta
        cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://api.whop.com/api/v1/payments",
            headers={"Authorization": f"Bearer {WHOP_API_KEY}"},
            params={"company_id": WHOP_COMPANY_ID, "status": "open", "per_page": 100},
            timeout=10
        )
        if resp.status_code == 200:
            payments = resp.json().get("data", [])
            return [
                p for p in payments
                if p.get("payments_failed", 0) > 0
                and str(p.get("created_at", ""))[:10] >= cutoff_str
            ]
    except Exception as e:
        log.error(f"Whop failed payments error: {e}")
    return []

# ─── FORMATAGE MESSAGES ───────────────────────────────────────────────────────

def fmt_amount(cents: int) -> str:
    amount = abs(cents) / 100
    return f"${amount:,.2f}"

def fmt_date(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except:
        return date_str[:10]

def source_tag(entity_name: str) -> str:
    if "whop" in entity_name.lower():
        return "🛍️ *Whop*"
    return f"🏦 *Slash* — {entity_name}"

def fmt_transaction(t: dict, entity_name: str) -> str:
    is_whop = "amountCents" not in t
    cents   = t.get("amountCents") if not is_whop else None
    if cents is None:
        cents = int(t.get("total", 0) * 100)
    emoji  = "💰" if cents > 0 else "📤"
    sign   = "+" if cents > 0 else "-"
    amount = fmt_amount(cents)
    status = t.get("status", "")
    source = source_tag(entity_name)
    tx_id  = t.get("id", "")
    id_str = f"`{tx_id}`" if tx_id else ""

    if is_whop:
        # Récupérer infos user Whop
        embedded = t.get("user") or {}
        user_id  = embedded.get("id", "") or t.get("user_id", "")
        user_v5  = get_whop_user(user_id) if user_id else {}
        name     = embedded.get("name") or embedded.get("username") or "—"
        email    = user_v5.get("email", "")
        date    = fmt_date(str(t.get("paid_at", "")))
        product = t.get("product_id", "—")
        user_line = f"👤 {name}"
        if email:
            user_line += f" | 📧 {email}"
        return (
            f"{emoji} *{sign}{amount}*\n"
            f"{user_line}\n"
            f"🔗 {source}\n"
            f"📅 {date} | `{status}`\n"
            f"🆔 {id_str}"
        )
    else:
        desc = t.get("description", "—")
        date = fmt_date(t.get("date", ""))
        return (
            f"{emoji} *{sign}{amount}*\n"
            f"📋 {desc}\n"
            f"🔗 {source}\n"
            f"📅 {date} | `{status}`\n"
            f"🆔 {id_str}"
        )

# ─── COMMANDES BOT ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    name = update.effective_chat.title or update.effective_user.first_name

    msg = (
        f"👋 *Finance Monitor is live!*\n\n"
        f"📍 Chat: *{name}*\n"
        f"🆔 Chat ID: `{chat_id}`\n"
        f"📂 Type: {chat_type}\n\n"
        f"ℹ️ Copie ce Chat ID et mets-le dans ton `.env`:\n"
        f"`TELEGRAM_CHAT_ID={chat_id}`\n\n"
        f"*Available commands:*\n"
        f"/balance — Account balances\n"
        f"/tx [n] — Latest transactions (default 5)\n"
        f"/in [n] — Latest incoming payments\n"
        f"/out [n] — Latest outgoing payments\n"
        f"/today — Today's incoming payments\n"
        f"/check — Force an immediate check\n"
        f"/info — Help & commands list\n"
    )
    await send_safe(context.bot, update.effective_chat.id, msg)


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Finance Monitor — NERO*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "I monitor your Slash & Whop accounts in real-time "
        "and alert this group whenever new payments come in.\n\n"
        "⏱️ *Auto-check:* every hour\n"
        "🔒 *Secured:* restricted to this group only\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *Commands*\n\n"
        "💳 `/balance` — Current balances for all accounts\n\n"
        "💰 `/in [n]` — Last n incoming payments\n"
        "_(e.g. /in 10 → last 10 payments received)_\n\n"
        "📤 `/out [n]` — Last n outgoing payments\n"
        "_(e.g. /out 5 → last 5 payments sent)_\n\n"
        "📊 `/tx [n]` — Last n transactions (all)\n"
        "_(e.g. /tx 7 → last 7 transactions)_\n\n"
        "📅 `/today` — All incoming payments today + daily total\n\n"
        "📅 `/yesterday` — All incoming payments yesterday + total\n\n"
        "🔍 `/check` — Force an immediate check right now\n\n"
        "❌ `/failed` — Current failed payments on Whop\n\n"
        "🚨 `/unpaid` — Failed with no retry success (last 7 days)\n\n"
        "ℹ️ `/info` — Show this help message\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏦 *Sources monitored*\n"
        "• Slash — WCATFM LLC\n"
        "• Slash — DG SOLUTION LLC\n"
        "• Whop\n"
    )
    await send_safe(context.bot, update.effective_chat.id, msg)


@authorized_only
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching balances...", parse_mode="Markdown")

    lines = ["💳 *Account Balances*\n"]
    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        accounts = get_slash_balance(entity_id)
        for acc in accounts:
            acc_id   = acc.get("id", "")
            acc_name = acc.get("name", "—")
            # Récupérer les balances réelles
            balances = get_slash_balance_for_account(acc_id, entity_id)
            lines.append(f"\n🏢 *{entity_name}*")
            lines.append(f"   📄 {acc_name}")
            if balances:
                for b in balances:
                    b_type   = b.get("type", "")
                    b_avail  = b.get("available", {}).get("amountCents", 0) / 100
                    b_posted = b.get("posted", {}).get("amountCents", 0) / 100
                    b_emoji  = "💵" if b_type == "cash" else "💳"
                    lines.append(f"   {b_emoji} `{b_type}` — Available: *${b_avail:,.2f}* | Posted: *${b_posted:,.2f}*")
            else:
                lines.append(f"   ⚠️ Balance unavailable")

    if WHOP_COMPANY_ID:
        lines.append("\n🛍️ *Whop* — configured ✅")
    else:
        lines.append("\n🛍️ *Whop* — not configured")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@authorized_only
async def cmd_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Nombre de transactions à afficher (défaut 5, max 10)
    try:
        n = min(int(context.args[0]), 10) if context.args else 5
    except:
        n = 5

    await update.message.reply_text(f"⏳ Fetching last {n} transactions...", parse_mode="Markdown")

    all_txs = []
    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            all_txs.append((t, entity_name))

    # Trier par date décroissante
    all_txs.sort(key=lambda x: x[0].get("date", ""), reverse=True)

    if not all_txs:
        await update.message.reply_text("❌ No transactions found.")
        return

    for t, entity_name in all_txs[:n]:
        msg = fmt_transaction(t, entity_name)
        await send_safe(context.bot, update.effective_chat.id, msg)
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching today's incoming payments...", parse_mode="Markdown")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    found = []

    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            if t.get("amountCents", 0) > 0 and t.get("date", "").startswith(today):
                found.append((t, entity_name))

    # Whop
    whop_payments = get_whop_payments()
    for p in whop_payments:
        paid_at = p.get("paid_at") or p.get("created_at", 0)
        try:
            if isinstance(paid_at, str):
                paid_date = paid_at[:10]
            elif isinstance(paid_at, (int, float)) and paid_at > 0:
                paid_date = datetime.fromtimestamp(paid_at, tz=timezone.utc).strftime("%Y-%m-%d")
            else:
                paid_date = ""
        except Exception:
            paid_date = ""
        if paid_date == today and p.get("total", 0) > 0 and p.get("status") == "paid":
            found.append((p, "Whop"))

    if not found:
        await update.message.reply_text(f"📭 No incoming payments today ({today}).")
        return

    total = sum(
        t.get("amountCents", 0) if "amountCents" in t
        else int(t.get("total", 0) * 100)
        for t, _ in found
    )
    await update.message.reply_text(
        f"📊 *{len(found)} incoming payment(s) today* — Total: *+{fmt_amount(total)}*",
        parse_mode="Markdown"
    )
    for t, entity_name in found:
        await update.message.reply_text(fmt_transaction(t, entity_name), parse_mode="Markdown")


@authorized_only
async def cmd_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Last n incoming payments across all accounts."""
    try:
        n = min(int(context.args[0]), 20) if context.args else 5
    except:
        n = 5

    await update.message.reply_text(f"⏳ Fetching last {n} incoming payments...", parse_mode="Markdown")

    all_txs = []
    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            if t.get("amountCents", 0) > 0:
                all_txs.append((t, entity_name))

    # Whop
    for p in get_whop_payments():
        all_txs.append((p, "Whop"))

    all_txs.sort(key=lambda x: x[0].get("date", "") or x[0].get("created_at", ""), reverse=True)

    if not all_txs:
        await update.message.reply_text("📭 No incoming payments found.")
        return

    total = sum(t.get("amountCents", 0) for t, _ in all_txs[:n])
    await update.message.reply_text(
        f"💰 *Last {min(n, len(all_txs))} incoming payments* — Total: *+${total/100:,.2f}*",
        parse_mode="Markdown"
    )
    for t, entity_name in all_txs[:n]:
        await update.message.reply_text(fmt_transaction(t, entity_name), parse_mode="Markdown")
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Last n outgoing payments across all accounts."""
    try:
        n = min(int(context.args[0]), 20) if context.args else 5
    except:
        n = 5

    await update.message.reply_text(f"⏳ Fetching last {n} outgoing payments...", parse_mode="Markdown")

    all_txs = []
    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            if t.get("amountCents", 0) < 0:
                all_txs.append((t, entity_name))

    all_txs.sort(key=lambda x: x[0].get("date", ""), reverse=True)

    if not all_txs:
        await update.message.reply_text("📭 No outgoing payments found.")
        return

    total = sum(abs(t.get("amountCents", 0)) for t, _ in all_txs[:n])
    await update.message.reply_text(
        f"📤 *Last {min(n, len(all_txs))} outgoing payments* — Total: *-${total/100:,.2f}*",
        parse_mode="Markdown"
    )
    for t, entity_name in all_txs[:n]:
        await update.message.reply_text(fmt_transaction(t, entity_name), parse_mode="Markdown")
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching yesterday's incoming payments...", parse_mode="Markdown")

    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    found = []

    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            if t.get("amountCents", 0) > 0 and t.get("date", "").startswith(yesterday):
                found.append((t, entity_name))

    for p in get_whop_payments():
        paid_at = p.get("paid_at") or p.get("created_at", 0)
        try:
            if isinstance(paid_at, str):
                paid_date = paid_at[:10]
            elif isinstance(paid_at, (int, float)) and paid_at > 0:
                paid_date = datetime.fromtimestamp(paid_at, tz=timezone.utc).strftime("%Y-%m-%d")
            else:
                paid_date = ""
        except Exception:
            paid_date = ""
        if paid_date == yesterday and p.get("total", 0) > 0 and p.get("status") == "paid":
            found.append((p, "Whop"))

    if not found:
        await update.message.reply_text(f"📭 No incoming payments yesterday ({yesterday}).")
        return

    total = sum(
        t.get("amountCents", 0) if "amountCents" in t
        else int(t.get("total", 0) * 100)
        for t, _ in found
    )
    await update.message.reply_text(
        f"📊 *{len(found)} incoming payment(s) yesterday* ({yesterday}) — Total: *+${total/100:,.2f}*",
        parse_mode="Markdown"
    )
    for t, entity_name in found:
        await update.message.reply_text(fmt_transaction(t, entity_name), parse_mode="Markdown")
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_unpaid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show failed payments with no successful payment (last 30 days)."""
    await update.message.reply_text("⏳ Fetching unpaid payments (last 7 days)...", parse_mode="Markdown")

    unpaid = get_whop_unpaid_payments(days=7)

    if not unpaid:
        await update.message.reply_text("✅ No unpaid payments in the last 7 days.")
        return

    total_at_risk = sum(p.get("total", 0) for p in unpaid)
    await update.message.reply_text(
        f"🚨 *{len(unpaid)} unpaid payment(s) — last 7 days*\n"
        f"💸 Total at risk: *${total_at_risk:,.2f}*",
        parse_mode="Markdown"
    )
    for p in unpaid:
        embedded  = p.get("user") or {}
        user_id   = embedded.get("id", "")
        user_v5   = get_whop_user(user_id) if user_id else {}
        name      = embedded.get("name") or embedded.get("username") or "—"
        email     = user_v5.get("email", "")
        amount    = p.get("total", 0)
        pid       = p.get("id", "")
        fails     = p.get("payments_failed", 0)
        failure   = p.get("failure_message", "—")
        user_line = f"👤 {name}"
        if email:
            user_line += f" | 📧 {email}"
        msg = (
            f"🚨 *Unpaid — ${amount:.2f}*\n"
            f"{user_line}\n"
            f"🔁 Attempts: {fails}\n"
            f"⚡ {failure}\n"
            f"🆔 `{pid}`"
        )
        await send_safe(context.bot, update.effective_chat.id, msg)
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_failed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current failed payments on Whop."""
    await update.message.reply_text("⏳ Fetching failed payments...", parse_mode="Markdown")

    failed = get_whop_failed_payments()
    if not failed:
        await update.message.reply_text("✅ No failed payments on Whop.")
        return

    total = sum(p.get("total", 0) for p in failed)
    await update.message.reply_text(
        f"⚠️ *{len(failed)} failed payment(s)* — Total at risk: *${total:,.2f}*",
        parse_mode="Markdown"
    )
    for p in failed:
        embedded  = p.get("user") or {}
        user_id   = embedded.get("id", "")
        user_v5   = get_whop_user(user_id) if user_id else {}
        name      = embedded.get("name") or embedded.get("username") or "—"
        email     = user_v5.get("email", "")
        amount    = p.get("total", 0)
        pid       = p.get("id", "")
        fails     = p.get("payments_failed", 0)
        failure   = p.get("failure_message", "—")
        user_line = f"👤 {name}"
        if email:
            user_line += f" | 📧 {email}"
        msg = (
            f"❌ *Failed — ${amount:.2f}*\n"
            f"{user_line}\n"
            f"🔁 Attempts: {fails}\n"
            f"⚡ {failure}\n"
            f"🆔 `{pid}`"
        )
        await send_safe(context.bot, update.effective_chat.id, msg)
        await asyncio.sleep(1.0)


@authorized_only
async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Checking now...", parse_mode="Markdown")
    count = await do_check(context, chat_id=update.effective_chat.id)
    if count == 0:
        await update.message.reply_text("✅ No new transactions since last check.")


# ─── POLLING AUTOMATIQUE ──────────────────────────────────────────────────────

async def do_check(context: ContextTypes.DEFAULT_TYPE, chat_id: int = None) -> int:
    """Check for new transactions and notify. Returns count of new ones."""
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not target_chat:
        log.warning("TELEGRAM_CHAT_ID not set, cannot send notifications")
        return 0

    seen = load_seen()
    new_txs = []

    for entity_id, entity_name in SLASH_ENTITIES:
        if not entity_id:
            continue
        txs = get_slash_transactions(entity_id)
        for t in txs:
            tx_id = t.get("id")
            if tx_id and tx_id not in seen and t.get("amountCents", 0) > 0:
                new_txs.append((t, entity_name))
                seen.add(tx_id)

    # Whop - paiements réussis
    whop_payments = get_whop_payments()
    for p in whop_payments:
        pid = p.get("id")
        if pid and pid not in seen and p.get("total", 0) > 0:
            new_txs.append((p, "Whop"))
            seen.add(pid)

    # Whop - paiements échoués
    failed_key = "whop_failed_seen"
    seen_failed = load_seen_key(failed_key)
    new_failed = []
    for p in get_whop_failed_payments():
        pid = p.get("id")
        if pid and pid not in seen_failed:
            new_failed.append(p)
            seen_failed.add(pid)
    if new_failed:
        save_seen_key(failed_key, seen_failed)
        await context.bot.send_message(
            chat_id=target_chat,
            text=f"⚠️ *{len(new_failed)} failed payment(s) on Whop!*",
            parse_mode="Markdown"
        )
        for p in new_failed:
            embedded  = p.get("user") or {}
            user_id   = embedded.get("id", "")
            user_v5   = get_whop_user(user_id) if user_id else {}
            name      = embedded.get("name") or embedded.get("username") or "—"
            email     = user_v5.get("email", "")
            amount    = p.get("total", 0)
            pid       = p.get("id", "")
            fails     = p.get("payments_failed", 0)
            failure   = p.get("failure_message", "—")
            user_line = f"👤 {name}"
            if email:
                user_line += f" | 📧 {email}"
            msg = (
                f"❌ *Failed payment — ${amount:.2f}*\n"
                f"{user_line}\n"
                f"🔁 Attempts: {fails}\n"
                f"⚡ {failure}\n"
                f"🆔 `{pid}`"
            )
            await send_safe(context.bot, target_chat, msg)
            await asyncio.sleep(1.0)

    if new_txs:
        save_seen(seen)
        header = f"🔔 *{len(new_txs)} new transaction(s)!*"
        await send_safe(context.bot, target_chat, header)
        for t, entity_name in new_txs:
            msg = fmt_transaction(t, entity_name)
            await send_safe(context.bot, target_chat, msg)
            await asyncio.sleep(1.0)
    else:
        save_seen(seen)

    log.info(f"Check done — {len(new_txs)} new transaction(s)")
    return len(new_txs)


async def polling_job(context: ContextTypes.DEFAULT_TYPE):
    log.info("Automatic polling started...")
    await do_check(context)


# ─── INITIALISATION ──────────────────────────────────────────────────────────

async def post_init(application: Application):
    """Initialise le fichier seen avec les transactions existantes au premier démarrage."""
    seen = load_seen()
    if not seen:
        log.info("First run — initializing seen_transactions.json...")
        for entity_id, entity_name in SLASH_ENTITIES:
            if not entity_id:
                continue
            txs = get_slash_transactions(entity_id)
            for t in txs:
                tx_id = t.get("id")
                if tx_id:
                    seen.add(tx_id)
        whop_payments = get_whop_payments()
        for p in whop_payments:
            pid = p.get("id")
            if pid:
                seen.add(pid)
        save_seen(seen)
        log.info(f"{len(seen)} existing transactions marked as seen.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing from .env")
        return

    log.info("Starting NERO — Finance Monitor...")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    # Commandes
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("info",         cmd_info))
    app.add_handler(CommandHandler("balance",      cmd_balance))
    app.add_handler(CommandHandler("tx",           cmd_tx))
    app.add_handler(CommandHandler("today",        cmd_today))
    app.add_handler(CommandHandler("yesterday",    cmd_yesterday))
    app.add_handler(CommandHandler("in",           cmd_in))
    app.add_handler(CommandHandler("out",          cmd_out))
    app.add_handler(CommandHandler("failed",       cmd_failed))
    app.add_handler(CommandHandler("unpaid",       cmd_unpaid))
    app.add_handler(CommandHandler("check",        cmd_check))

    # Job polling automatique
    app.job_queue.run_repeating(polling_job, interval=POLL_INTERVAL_SEC, first=10)

    log.info(f"Bot started — polling every {POLL_INTERVAL_SEC//60} minutes")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()