import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta

# Fix UTF-8 encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# نصب خودکار pg8000 در صورت عدم وجود (pure Python - بدون نیاز به libpq)
try:
    import pg8000
    import pg8000.native
    DB_AVAILABLE = True
except ImportError:
    print("pg8000 یافت نشد. در حال نصب خودکار...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pg8000", "-q"])
    import pg8000
    import pg8000.native
    DB_AVAILABLE = True
    print("pg8000 با موفقیت نصب شد.")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ====== تنظیمات اولیه ======
TOKEN = os.getenv("BOT_TOKEN")
STATE_FILE = "support_state.json"
MEDIA_DIR = "media"
DEFAULT_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_ID")
RESTART_LABEL = "شروع مجدد"

# ====== تنظیمات دیتابیس PostgreSQL ======
# این متغیر به صورت خودکار توسط Railway تنظیم می‌شود
DATABASE_URL = os.environ.get("DATABASE_URL")

# ====== شناسه ادمین‌ها (Telegram user ID) ======
ADMIN_IDS = [
    162879965,   # <-- ID خودت رو اینجا بنویس
    # 987654321, # ادمین دوم (اختیاری)
]

os.makedirs(MEDIA_DIR, exist_ok=True)

# ====== لیست کامل دوره‌ها ======
COURSES = [
    "نقشه خوانی",
    "نتظیم موتور",
    "پارامتر خوانی",
    "مالتی پلکس ایران خودرو",
    "مالتی پلکس فرانسه",
    "مالتی پلکس سایپا",
    "کولر و تهویه مطبوع",
    "استارت و دینام",
    "هیوندا و کیا",
    "ایسیو ۱",
    "ایسیو ۲",
    "تعمیرات نود مالتی پلکس",
    "جک و لیفان",
    "ریمپ با TNM",
    "کاربری TNM",
    "ایمو بلایزر و تعریف ریموت",
    "وینولز",
]

MESSAGES = {
    "welcome": (
        "🔧 به ربات پشتیبانی آموزشی آکادمی SKP خوش آمدید\n\n"
        "این سامانه با هدف ارائه پشتیبانی تخصصی و پاسخگویی به سوالات کارآموزان دوره‌های آموزشی مکانیک و برق خودرو راه‌اندازی شده است.\n\n"
        "📚 نحوه استفاده از ربات:\n\n"
        "1️⃣ ابتدا شماره تلفن خود را ثبت نمایید.\n\n"
        "2️⃣ سپس دوره آموزشی مورد نظر خود را از لیست دوره‌ها انتخاب کنید.\n\n"
        "3️⃣ سوال فنی، آموزشی یا تخصصی خود را به صورت کامل و دقیق ارسال نمایید.\n"
        "   (می‌توانید متن، عکس، ویدیو یا ویس ارسال کنید)\n\n"
        "4️⃣ سوال شما برای استاد مربوطه ارسال خواهد شد.\n\n"
        "5️⃣ پس از بررسی و پاسخگویی، جواب استاد از طریق همین ربات برای شما ارسال می‌شود.\n\n"
        "💡 برای دریافت پاسخ دقیق‌تر، لطفاً هنگام ثبت سوال مواردی مانند مدل خودرو، سال ساخت، نوع سیستم، کد خطا (در صورت وجود) و توضیحات کامل مشکل را ذکر نمایید.\n\n"
        "⏱ زمان پاسخگویی بسته به نوع سوال، حجم درخواست‌ها و زمان حضور اساتید ممکن است از چند دقیقه تا حداکثر ۲۴ ساعت کاری متغیر باشد.\n\n"
        "☎️ تلفن شرکت:\n021-63002000\n\n"
        "🌐 وب‌سایت:\nhttps://skppart.com/\n\n"
        "از اعتماد شما به آکادمی SKP سپاسگزاریم.\n\n"
    ),
    "group_set": "گروه پشتیبانی ثبت شد.\nID گروه: {group_id}",
    "setgroup_private": "این دستور را داخل گروه پشتیبانی اجرا کنید.",
    "course_selected": (
        "دوره انتخاب شده: {course}\n\n"
        "📩 حالا سوال خود را ارسال کنید.\n"
        "می‌توانید چند پیام (متن، عکس، ویدیو، ویس، فایل) ارسال کنید.\n"
        "وقتی آماده شدید دکمه 📤 ارسال سوال را بزنید تا همه پیام‌ها یکجا ارسال شوند."
    ),
    "need_course": "ابتدا باید دوره را انتخاب کنید. /start را ارسال کنید.",
    "group_not_set": "گروه پشتیبانی تنظیم نشده است. ابتدا /setgroup را در گروه پشتیبانی اجرا کنید.",
    "question_sent": "سوال شما ثبت شد و به گروه اساتید ارسال شد. به زودی پاسخ دریافت می‌کنید.",
    "question_send_failed": "ارسال سوال به گروه موفق نبود.",
    "selected_answer": "✅ این سوال توسط {teacher} انتخاب شد. لطفاً جواب را در چت خصوصی با ربات ارسال کنید.",
    "teacher_private_question": (
        "شما سوال را برای پاسخ انتخاب کردید:\n"
        "👨‍🎓 دانشجو: {student_name}\n"
        "📚 دوره: {course}\n"
        "سوال: {question}\n\n"
        "لطفاً پاسخ خود را هم‌اکنون در این چت ارسال کنید.\n"
        "تمام پیام‌های شما تا زمان زدن دکمه ارسال پاسخ در صف می‌مانند."
    ),
    "teacher_private_error": "خطا: ربات نمی‌تواند به استاد پیام خصوصی ارسال کند.",
    "not_related_post": "❌ این سوال مربوط به دوره انتخاب‌شده نیست.",
    "student_not_related": "سلام! یکی از اساتید اعلام کرده این سوال مربوط به دوره انتخاب‌شده نیست.",
    "no_pending_question": "شما سوالی برای پاسخ دادن ندارید. ابتدا در گروه سوال را انتخاب کنید.",
    "question_not_found": "سوال پیدا نشد یا قبلاً بسته شده است.",
    "answer_sent": "پاسخ شما با موفقیت به دانشجو ارسال شد.",
    "answer_send_failed": "خطا در ارسال پاسخ به دانشجو.",
    "unknown": "لطفاً از دستور /start برای شروع استفاده کنید.",
    "question_answered_group": "✅ این سوال توسط {teacher} پاسخ داده شد.",
    "not_authorized": (
        "⛔️ شما مجاز به استفاده از این سامانه نیستید.\n\n"
        "شماره‌ی ثبت شده شما در سیستم یافت نشد.\n"
        "برای اطلاعات بیشتر با آکادمی SKP تماس بگیرید:\n"
        "☎️ 021-63002000"
    ),
    "not_admin": "⛔️ شما دسترسی ادمین ندارید.",
    "admin_help": (
        "🛠 دستورات ادمین:\n\n"
        "/adduser 09xxxxxxxxx نام|نام‌خانوادگی دوره۱|دوره۲\n"
        "   ➕ افزودن یا ویرایش کاراموز\n\n"
        "   مثال:\n"
        "   /adduser 09121234567 علی|محمدی نقشه خوانی|ایسیو ۱\n\n"
        "/removeuser 09xxxxxxxxx\n"
        "   ➖ حذف کاراموز\n\n"
        "/listusers\n"
        "   📋 نمایش همه کاراموزان\n\n"
        "/searchuser 09xxxxxxxxx\n"
        "   🔍 جستجوی کاراموز با شماره\n\n"
        "/dbstatus\n"
        "   🗄 وضعیت دیتابیس"
    ),
}

STUDENT_PHONE, STUDENT_COURSE, STUDENT_QUESTION = range(3)

# ====== state های پنل ادمین ======
(
    ADMIN_MENU,
    ADMIN_ADD_PHONE,
    ADMIN_ADD_FIRSTNAME,
    ADMIN_ADD_LASTNAME,
    ADMIN_ADD_COURSES,
    ADMIN_CONFIRM_ADD,
    ADMIN_SEARCH_PHONE,
    ADMIN_EDIT_MENU,
    ADMIN_EDIT_COURSES,
    ADMIN_DELETE_CONFIRM,
    ADMIN_LIST_PAGE,
) = range(10, 21)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

status = {
    "start_time": None,
    "connected": False,
    "disconnect_count": 0,
    "last_check": None,
    "last_error": None,
}

# =====================================================
# ====== توابع مدیریت دیتابیس PostgreSQL (pg8000) ======
# =====================================================

def get_db_connection():
    """اتصال به دیتابیس PostgreSQL با pg8000"""
    # اولویت: استفاده از متغیرهای جداگانه Railway (مطمئن‌تر)
    pg_host = os.environ.get("PGHOST")
    pg_user = os.environ.get("PGUSER")
    pg_password = os.environ.get("PGPASSWORD")
    pg_database = os.environ.get("PGDATABASE")
    pg_port = int(os.environ.get("PGPORT", 5432))

    if pg_host and pg_user and pg_database:
        logger.info("اتصال با متغیرهای PG...")
        return pg8000.native.Connection(
            host=pg_host,
            user=pg_user,
            password=pg_password,
            database=pg_database,
            port=pg_port,
            ssl_context=True,
        )

    # fallback: پارس DATABASE_URL
    if not DATABASE_URL:
        raise Exception("متغیر DATABASE_URL یا PGHOST تنظیم نشده است")

    from urllib.parse import urlparse, unquote
    url = DATABASE_URL.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    parsed = urlparse(url)
    logger.info("اتصال با DATABASE_URL - host=%s user=%s", parsed.hostname, parsed.username)
    return pg8000.native.Connection(
        host=parsed.hostname,
        user=parsed.username,
        password=unquote(parsed.password) if parsed.password else None,
        database=parsed.path.lstrip("/").split("?")[0],
        port=parsed.port or 5432,
        ssl_context=True,
    )


def _row_to_dict(columns: list, row: tuple) -> dict:
    """تبدیل ردیف به دیکشنری با استفاده از نام ستون‌ها"""
    if row is None:
        return None
    return dict(zip(columns, row))


def _rows_to_dicts(columns: list, rows: list) -> list:
    return [dict(zip(columns, r)) for r in rows]


def init_db():
    """
    ساخت جدول‌های دیتابیس در صورت عدم وجود.
    این تابع یک بار هنگام راه‌اندازی ربات اجرا می‌شود.
    """
    try:
        conn = get_db_connection()

        # جدول کاراموزان
        conn.run("""
            CREATE TABLE IF NOT EXISTS interns (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) UNIQUE NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                courses TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # جدول تنظیمات ربات
        conn.run("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # جدول سوالات
        conn.run("""
            CREATE TABLE IF NOT EXISTS questions (
                id VARCHAR(100) PRIMARY KEY,
                student_id BIGINT,
                student_name VARCHAR(200),
                student_phone VARCHAR(20),
                course VARCHAR(200),
                question TEXT,
                status VARCHAR(50) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT NOW(),
                group_message_id BIGINT,
                assigned_teacher_id BIGINT,
                assigned_teacher_name VARCHAR(200),
                answer TEXT,
                media_file_id VARCHAR(500),
                media_type VARCHAR(50),
                answer_media_file_id VARCHAR(500),
                answer_media_type VARCHAR(50)
            )
        """)

        # جدول استادهای در انتظار پاسخ
        conn.run("""
            CREATE TABLE IF NOT EXISTS teacher_pending (
                teacher_id BIGINT PRIMARY KEY,
                question_id VARCHAR(100),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.close()
        logger.info("✅ دیتابیس با موفقیت راه‌اندازی شد")
    except Exception as e:
        logger.error("❌ خطا در راه‌اندازی دیتابیس: %s", e)
        raise


def normalize_phone(phone: str) -> str:
    """نرمال‌سازی شماره تلفن به فرمت 09XXXXXXXXX"""
    phone = str(phone).strip().replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]
    if phone.startswith("9") and len(phone) == 10:
        phone = "0" + phone
    return phone


def db_get_intern(phone: str) -> dict | None:
    """دریافت اطلاعات یک کاراموز از دیتابیس"""
    try:
        conn = get_db_connection()
        rows = conn.run(
            "SELECT id, phone, first_name, last_name, courses, created_at, updated_at FROM interns WHERE phone = :p",
            p=normalize_phone(phone)
        )
        columns = ["id", "phone", "first_name", "last_name", "courses", "created_at", "updated_at"]
        conn.close()
        return _row_to_dict(columns, rows[0] if rows else None)
    except Exception as e:
        logger.error("خطا در دریافت کاراموز: %s", e)
        return None


def db_get_allowed_courses(phone: str) -> list | None:
    """برگرداندن لیست دوره‌های مجاز کاراموز."""
    intern = db_get_intern(phone)
    if intern is None:
        return None
    courses_str = intern.get("courses") or ""
    return [c.strip() for c in courses_str.split("|") if c.strip()]


def db_add_intern(phone: str, first_name: str, last_name: str, courses: list) -> bool:
    """افزودن یا ویرایش کاراموز در دیتابیس"""
    try:
        conn = get_db_connection()
        courses_str = "|".join(courses)
        conn.run("""
            INSERT INTO interns (phone, first_name, last_name, courses, updated_at)
            VALUES (:phone, :fn, :ln, :courses, NOW())
            ON CONFLICT (phone) DO UPDATE
            SET first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                courses = EXCLUDED.courses,
                updated_at = NOW()
        """, phone=normalize_phone(phone), fn=first_name, ln=last_name, courses=courses_str)
        conn.close()
        logger.info("کاراموز ثبت/ویرایش شد: %s", phone)
        return True
    except Exception as e:
        logger.error("خطا در افزودن کاراموز: %s", e)
        return False


def db_remove_intern(phone: str) -> bool:
    """حذف کاراموز از دیتابیس"""
    try:
        conn = get_db_connection()
        conn.run("DELETE FROM interns WHERE phone = :p", p=normalize_phone(phone))
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا در حذف کاراموز: %s", e)
        return False


def db_list_interns() -> list:
    """لیست همه کاراموزان"""
    try:
        conn = get_db_connection()
        rows = conn.run("SELECT phone, first_name, last_name, courses, created_at FROM interns ORDER BY created_at DESC")
        columns = ["phone", "first_name", "last_name", "courses", "created_at"]
        conn.close()
        return _rows_to_dicts(columns, rows)
    except Exception as e:
        logger.error("خطا در دریافت لیست: %s", e)
        return []


def db_count_interns() -> int:
    """تعداد کاراموزان"""
    try:
        conn = get_db_connection()
        rows = conn.run("SELECT COUNT(*) FROM interns")
        conn.close()
        return rows[0][0] if rows else 0
    except Exception as e:
        logger.error("خطا: %s", e)
        return 0


# ====== توابع تنظیمات ربات ======

def db_get_setting(key: str) -> str | None:
    try:
        conn = get_db_connection()
        rows = conn.run("SELECT value FROM bot_settings WHERE key = :k", k=key)
        conn.close()
        return rows[0][0] if rows else None
    except Exception as e:
        logger.error("خطا در دریافت تنظیمات: %s", e)
        return None


def db_set_setting(key: str, value: str) -> bool:
    try:
        conn = get_db_connection()
        conn.run("""
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, k=key, v=value)
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا در ذخیره تنظیمات: %s", e)
        return False


# ====== توابع سوالات ======

_QUESTION_COLS = [
    "id", "student_id", "student_name", "student_phone", "course", "question",
    "status", "created_at", "group_message_id", "assigned_teacher_id",
    "assigned_teacher_name", "answer", "media_file_id", "media_type",
    "answer_media_file_id", "answer_media_type"
]

def db_save_question(question_id: str, data: dict) -> bool:
    try:
        conn = get_db_connection()
        conn.run("""
            INSERT INTO questions (
                id, student_id, student_name, student_phone, course, question,
                status, group_message_id, assigned_teacher_id, assigned_teacher_name,
                answer, media_file_id, media_type, answer_media_file_id, answer_media_type
            ) VALUES (:id,:sid,:sname,:sphone,:course,:question,:status,:gmid,:atid,:atname,:answer,:mfid,:mtype,:amfid,:amtype)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                group_message_id = EXCLUDED.group_message_id,
                assigned_teacher_id = EXCLUDED.assigned_teacher_id,
                assigned_teacher_name = EXCLUDED.assigned_teacher_name,
                answer = EXCLUDED.answer,
                answer_media_file_id = EXCLUDED.answer_media_file_id,
                answer_media_type = EXCLUDED.answer_media_type
        """,
            id=question_id,
            sid=data.get("student_id"),
            sname=data.get("student_name"),
            sphone=data.get("student_phone"),
            course=data.get("course"),
            question=data.get("question"),
            status=data.get("status", "open"),
            gmid=data.get("group_message_id"),
            atid=data.get("assigned_teacher_id"),
            atname=data.get("assigned_teacher_name"),
            answer=data.get("answer"),
            mfid=data.get("media_file_id"),
            mtype=data.get("media_type"),
            amfid=data.get("answer_media_file_id"),
            amtype=data.get("answer_media_type"),
        )
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا در ذخیره سوال: %s", e)
        return False


def db_get_question(question_id: str) -> dict | None:
    try:
        conn = get_db_connection()
        rows = conn.run(
            "SELECT id,student_id,student_name,student_phone,course,question,status,created_at,group_message_id,assigned_teacher_id,assigned_teacher_name,answer,media_file_id,media_type,answer_media_file_id,answer_media_type FROM questions WHERE id = :qid",
            qid=question_id
        )
        conn.close()
        return _row_to_dict(_QUESTION_COLS, rows[0] if rows else None)
    except Exception as e:
        logger.error("خطا در دریافت سوال: %s", e)
        return None


def db_update_question_status(question_id: str, status: str, **kwargs) -> bool:
    try:
        conn = get_db_connection()
        # ساخت دینامیک query با named params
        set_parts = ["status = :status"]
        params = {"status": status, "qid": question_id}
        for k, v in kwargs.items():
            set_parts.append(f"{k} = :{k}")
            params[k] = v
        sql = f"UPDATE questions SET {', '.join(set_parts)} WHERE id = :qid"
        conn.run(sql, **params)
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا در آپدیت سوال: %s", e)
        return False


def db_set_teacher_pending(teacher_id: int, question_id: str) -> bool:
    try:
        conn = get_db_connection()
        conn.run("""
            INSERT INTO teacher_pending (teacher_id, question_id, updated_at)
            VALUES (:tid, :qid, NOW())
            ON CONFLICT (teacher_id) DO UPDATE SET question_id = EXCLUDED.question_id, updated_at = NOW()
        """, tid=teacher_id, qid=question_id)
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا در ذخیره teacher_pending: %s", e)
        return False


def db_get_teacher_pending(teacher_id: int) -> str | None:
    try:
        conn = get_db_connection()
        rows = conn.run("SELECT question_id FROM teacher_pending WHERE teacher_id = :tid", tid=teacher_id)
        conn.close()
        return rows[0][0] if rows else None
    except Exception as e:
        logger.error("خطا: %s", e)
        return None


def db_remove_teacher_pending(teacher_id: int) -> bool:
    try:
        conn = get_db_connection()
        conn.run("DELETE FROM teacher_pending WHERE teacher_id = :tid", tid=teacher_id)
        conn.close()
        return True
    except Exception as e:
        logger.error("خطا: %s", e)
        return False


def db_get_group_chat_id() -> str | None:
    val = db_get_setting("group_chat_id")
    return val or DEFAULT_GROUP_CHAT_ID



# =====================================================
# ====== توابع کمکی ======
# =====================================================

def format_timedelta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def clear_console() -> None:
    if os.name == "nt":
        os.system("cls")
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def get_connection_status():
    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        return bool(data.get("ok")), None
    except Exception as e:
        return False, str(e)


def display_status(final: bool = False) -> None:
    clear_console()
    now = datetime.now()
    uptime = format_timedelta(now - (status["start_time"] or now))
    print("============================================")
    print("    Telegram Support Bot - وضعیت اتصال")
    print("============================================")
    print(f"وضعیت: {'✅ متصل' if status['connected'] else '❌ قطع'}")
    print(f"زمان اجرا: {uptime}")
    print(f"تعداد قطعی‌ها: {status['disconnect_count']}")
    print(f"آخرین بررسی: {status['last_check'].strftime('%Y-%m-%d %H:%M:%S') if status['last_check'] else '-'}")
    if status["last_error"]:
        print(f"خطای آخر: {status['last_error']}")
    print("--------------------------------------------")
    print("برای توقف: Ctrl+C")
    if final:
        print("ربات متوقف شده است.")
    sys.stdout.flush()


def status_monitor(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        connected, error = get_connection_status()
        now = datetime.now()
        if status["start_time"] is None:
            status["start_time"] = now
        if status["connected"] and not connected:
            status["disconnect_count"] += 1
        status["connected"] = connected
        status["last_check"] = now
        status["last_error"] = error
        display_status()
        if stop_event.wait(5):
            break
    display_status(final=True)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_course_keyboard(allowed_courses=None) -> list:
    courses = allowed_courses if allowed_courses is not None else COURSES
    return [[InlineKeyboardButton(c, callback_data=f"course:{c}")] for c in courses]


# =====================================================
# ====== دستورات ادمین ======
# =====================================================

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return
    await update.message.reply_text(MESSAGES["admin_help"])


async def admin_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    فرمت: /adduser 09121234567 علی|محمدی نقشه خوانی|ایسیو ۱
    آرگومان اول: شماره موبایل
    آرگومان دوم: نام|نام‌خانوادگی
    آرگومان سوم به بعد: دوره‌ها با | جدا شده
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "⚠️ فرمت اشتباه!\n\n"
            "فرمت صحیح:\n"
            "/adduser شماره نام|نام‌خانوادگی دوره‌ها\n\n"
            "مثال:\n"
            "/adduser 09121234567 علی|محمدی نقشه خوانی|ایسیو ۱\n\n"
            "📌 دوره‌ها را با | از هم جدا کنید."
        )
        return

    phone = normalize_phone(args[0])

    # آرگومان دوم: نام|نام‌خانوادگی
    name_parts = args[1].split("|")
    if len(name_parts) < 2:
        await update.message.reply_text(
            "⚠️ فرمت نام اشتباه است!\n"
            "نام و نام‌خانوادگی را با | جدا کنید.\n"
            "مثال: علی|محمدی"
        )
        return
    first_name = name_parts[0].strip()
    last_name = name_parts[1].strip()

    # آرگومان سوم به بعد: دوره‌ها
    courses_str = " ".join(args[2:])
    courses = [c.strip() for c in courses_str.split("|") if c.strip()]

    if not courses:
        await update.message.reply_text("⚠️ حداقل یک دوره باید وارد شود.")
        return

    invalid = [c for c in courses if c not in COURSES]
    if invalid:
        courses_list = "\n".join(f"• {c}" for c in COURSES)
        await update.message.reply_text(
            f"⚠️ دوره‌های نامعتبر:\n{', '.join(invalid)}\n\nدوره‌های مجاز:\n{courses_list}"
        )
        return

    if db_add_intern(phone, first_name, last_name, courses):
        await update.message.reply_text(
            f"✅ کاراموز ثبت/ویرایش شد:\n"
            f"📞 شماره: {phone}\n"
            f"👤 نام: {first_name} {last_name}\n"
            f"📚 دوره‌ها:\n" +
            "\n".join(f"  ✅ {c}" for c in courses)
        )
    else:
        await update.message.reply_text("❌ خطا در ثبت. لطفاً دوباره امتحان کنید.")


async def admin_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/removeuser 09121234567"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return
    args = context.args
    if not args:
        await update.message.reply_text("فرمت: /removeuser 09121234567")
        return
    phone = normalize_phone(args[0])
    if db_remove_intern(phone):
        await update.message.reply_text(f"✅ کاراموز {phone} حذف شد.")
    else:
        await update.message.reply_text(f"⚠️ شماره {phone} در سیستم یافت نشد.")


async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listusers"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return
    interns = db_list_interns()
    if not interns:
        await update.message.reply_text("📋 هیچ کاراموزی ثبت نشده است.")
        return
    lines = [f"📋 لیست کاراموزان ({len(interns)} نفر):\n"]
    for intern in interns:
        name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()
        courses = intern.get("courses") or ""
        lines.append(
            f"📞 {intern['phone']}\n"
            f"   👤 {name}\n"
            f"   📚 {courses.replace('|', ' | ') if courses else 'بدون دوره'}\n"
        )
    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await update.message.reply_text(chunk)


async def admin_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/searchuser 09121234567"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return
    args = context.args
    if not args:
        await update.message.reply_text("فرمت: /searchuser 09121234567")
        return
    intern = db_get_intern(args[0])
    if not intern:
        await update.message.reply_text(f"⚠️ کاراموزی با شماره {args[0]} یافت نشد.")
        return
    name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()
    courses = (intern.get("courses") or "").replace("|", "\n   • ")
    await update.message.reply_text(
        f"🔍 نتیجه جستجو:\n\n"
        f"📞 شماره: {intern['phone']}\n"
        f"👤 نام: {name}\n"
        f"📚 دوره‌ها:\n   • {courses}\n"
        f"🗓 تاریخ ثبت: {intern.get('created_at','')}"
    )


async def admin_db_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dbstatus"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return
    try:
        count = db_count_interns()
        conn = get_db_connection()
        q_rows = conn.run("SELECT COUNT(*) FROM questions")
        open_rows = conn.run("SELECT COUNT(*) FROM questions WHERE status = 'open'")
        conn.close()
        q_count = q_rows[0][0] if q_rows else 0
        open_q = open_rows[0][0] if open_rows else 0
        await update.message.reply_text(
            f"🗄 وضعیت دیتابیس:\n\n"
            f"👥 تعداد کاراموزان: {count}\n"
            f"❓ کل سوالات: {q_count}\n"
            f"🟡 سوالات باز: {open_q}\n"
            f"✅ دیتابیس متصل است"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در اتصال به دیتابیس:\n{e}")


# =====================================================
# ====== هندلرهای اصلی ربات ======
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("لطفاً در چت خصوصی با من /start را ارسال کنید.")
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton("شروع ثبت درخواست", callback_data="start_register")]]
    if is_admin(update.effective_user.id):
        buttons.append([InlineKeyboardButton("پنل ادمین", callback_data="ap:open")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(MESSAGES["welcome"], reply_markup=keyboard)
    # Send a persistent reply keyboard with a quick restart button so users can
    # re-open the bot without typing /start
    try:
        restart_kb = ReplyKeyboardMarkup([[KeyboardButton(RESTART_LABEL)]], resize_keyboard=True, one_time_keyboard=False)
        await context.bot.send_message(chat_id=update.effective_user.id, text="برای شروع سریع دکمه را بزنید:", reply_markup=restart_kb)
    except Exception:
        pass
    return STUDENT_PHONE


async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        db_set_setting("group_chat_id", str(update.effective_chat.id))
        await update.message.reply_text(MESSAGES["group_set"].format(group_id=update.effective_chat.id))
    else:
        await update.message.reply_text(MESSAGES["setgroup_private"])


async def course_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    course = query.data.split(":", 1)[1]
    context.user_data["selected_course"] = course
    # پاک‌سازی صف پیام‌های قبلی
    context.user_data["pending_messages"] = []
    send_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال سوال", callback_data="submit_question")],
        [InlineKeyboardButton("🗑 پاک کردن پیام‌ها", callback_data="clear_question")],
    ])
    await query.message.edit_text(
        MESSAGES["course_selected"].format(course=course),
        reply_markup=send_keyboard,
    )
    return STUDENT_QUESTION


async def ask_again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_course", None)
    allowed_courses = context.user_data.get("allowed_courses")
    try:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="دوره مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(build_course_keyboard(allowed_courses)),
        )
    except Exception:
        try:
            await query.message.edit_text(
                "دوره مورد نظر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(build_course_keyboard(allowed_courses)),
            )
        except Exception:
            pass
    return STUDENT_COURSE


async def start_register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    kb = ReplyKeyboardMarkup([[KeyboardButton("ارسال شماره", request_contact=True)]], one_time_keyboard=True, resize_keyboard=True)
    try:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="لطفاً شماره تلفن خود را ارسال کنید (از طریق دکمه یا تایپ شماره).",
            reply_markup=kb
        )
    except Exception:
        pass
    return STUDENT_PHONE


async def receive_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    phone = None
    if update.message.contact and update.message.contact.phone_number:
        phone = update.message.contact.phone_number
    elif update.message.text:
        txt = update.message.text.strip()
        if any(ch.isdigit() for ch in txt):
            phone = txt
    if not phone:
        await update.message.reply_text("شماره تلفن نامعتبر است. لطفاً مجدداً امتحان کنید.")
        return STUDENT_PHONE

    allowed_courses = db_get_allowed_courses(phone)
    if allowed_courses is None:
        logger.info("شماره %s مجاز نیست", phone)
        await update.message.reply_text(MESSAGES["not_authorized"], reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    normalized = normalize_phone(phone)
    intern = db_get_intern(phone)
    intern_name = ""
    if intern:
        intern_name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()

    context.user_data["phone"] = normalized
    context.user_data["allowed_courses"] = allowed_courses

    try:
        greeting = f"✅ شماره شما تأیید شد: {normalized}"
        if intern_name:
            greeting = f"✅ خوش آمدید {intern_name}!\nشماره شما تأیید شد: {normalized}"
        await context.bot.send_message(
            chat_id=user.id,
            text=f"{greeting}\n\n📚 دوره‌های در دسترس شما:",
            reply_markup=ReplyKeyboardRemove()
        )
        await context.bot.send_message(
            chat_id=user.id,
            text="لطفاً دوره مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(build_course_keyboard(allowed_courses))
        )
    except Exception:
        pass
    return STUDENT_COURSE


def _extract_message_data(message) -> dict | None:
    """استخراج داده پیام و تبدیل به دیکشنری برای ذخیره در صف"""
    if message.text:
        return {"type": "text", "text": message.text.strip(), "media_file_id": None, "media_type": None}
    elif message.photo:
        return {"type": "photo", "text": message.caption or "", "media_file_id": message.photo[-1].file_id, "media_type": "photo"}
    elif message.video:
        return {"type": "video", "text": message.caption or "", "media_file_id": message.video.file_id, "media_type": "video"}
    elif message.voice:
        return {"type": "voice", "text": message.caption or "", "media_file_id": message.voice.file_id, "media_type": "voice"}
    elif message.document:
        return {"type": "document", "text": message.caption or "", "media_file_id": message.document.file_id, "media_type": "document"}
    elif message.audio:
        return {"type": "audio", "text": message.caption or "", "media_file_id": message.audio.file_id, "media_type": "audio"}
    elif message.animation:
        return {"type": "animation", "text": message.caption or "", "media_file_id": message.animation.file_id, "media_type": "animation"}
    return None


async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پیام‌های کاراموز را در صف ذخیره می‌کند تا با دکمه ارسال شوند"""
    course = context.user_data.get("selected_course")
    if not course:
        await update.message.reply_text(MESSAGES["need_course"])
        return ConversationHandler.END

    msg_data = _extract_message_data(update.message)
    if not msg_data:
        await update.message.reply_text("لطفاً متن، عکس، ویدیو، ویس یا فایل ارسال کنید.")
        return STUDENT_QUESTION

    pending = context.user_data.setdefault("pending_messages", [])
    pending.append(msg_data)
    count = len(pending)

    # نمایش تعداد پیام‌های در صف و دکمه ارسال
    send_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📤 ارسال سوال ({count} پیام)", callback_data="submit_question")],
        [InlineKeyboardButton("🗑 پاک کردن و شروع مجدد", callback_data="clear_question")],
    ])
    await update.message.reply_text(
        f"✅ پیام {count} در صف قرار گرفت.\n"
        "می‌توانید پیام بیشتری اضافه کنید یا دکمه ارسال را بزنید.",
        reply_markup=send_keyboard,
    )
    return STUDENT_QUESTION


async def submit_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ارسال همه پیام‌های صف به گروه اساتید"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    course = context.user_data.get("selected_course")
    pending = context.user_data.get("pending_messages", [])

    if not pending:
        await query.answer("⚠️ هیچ پیامی در صف نیست! ابتدا سوال خود را ارسال کنید.", show_alert=True)
        return STUDENT_QUESTION

    if not course:
        await query.edit_message_text(MESSAGES["need_course"])
        return ConversationHandler.END

    group_chat_id = db_get_group_chat_id()
    if not group_chat_id:
        await query.edit_message_text(MESSAGES["group_not_set"])
        return ConversationHandler.END

    question_id = str(uuid.uuid4())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    phone = context.user_data.get("phone", "")

    # ساخت متن خلاصه سوال از همه پیام‌های متنی
    texts = [m["text"] for m in pending if m.get("text")]
    combined_text = " | ".join(t for t in texts if t) or f"({len(pending)} پیام رسانه‌ای)"

    question_data = {
        "student_id": user.id,
        "student_name": user.full_name,
        "student_phone": phone,
        "course": course,
        "question": combined_text,
        "status": "open",
        "created_at": now,
        "group_message_id": None,
        "assigned_teacher_id": None,
        "assigned_teacher_name": None,
        "answer": None,
        "media_file_id": None,
        "media_type": None,
    }

    group_header = (
        f"📬 سوال جدید ثبت شد:\n"
        f"👨‍🎓 دانشجو: {user.full_name}\n"
        + (f"📞 {phone}\n" if phone else "")
        + f"📚 دوره: {course}\n"
        f"🕒 زمان: {now}\n"
        f"📦 تعداد پیام‌ها: {len(pending)}\n\n"
        f"پیام‌های کاربر در ادامه ارسال می‌شوند."
    )
    keyboard = [
        [InlineKeyboardButton("✅ پاسخ می‌دهم", callback_data=f"answer:{question_id}")],
        [InlineKeyboardButton("❌ مربوط به این دوره نیست", callback_data=f"not_related:{question_id}")],
    ]

    try:
        # ارسال پیام اصلی (header) به گروه
        msg = await context.bot.send_message(
            chat_id=group_chat_id, text=group_header,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        question_data["group_message_id"] = msg.message_id

        # ارسال همه پیام‌ها به گروه به ترتیب
        for i, pm in enumerate(pending, 1):
            msg_text = pm.get("text") or ""
            if pm.get("type") == "text":
                try:
                    await context.bot.send_message(chat_id=group_chat_id, text=f"📩 پیام {i}: {msg_text}" if msg_text else f"📩 پیام {i}")
                except Exception as e:
                    logger.error("خطا ارسال متن %d به گروه: %s", i, e)
            else:
                caption = msg_text or f"پیام {i}"
                try:
                    if pm.get("type") == "photo":
                        await context.bot.send_photo(chat_id=group_chat_id, photo=pm.get("media_file_id"), caption=f"📷 {caption}")
                    elif pm.get("type") == "video":
                        await context.bot.send_video(chat_id=group_chat_id, video=pm.get("media_file_id"), caption=f"🎥 {caption}")
                    elif pm.get("type") == "voice":
                        await context.bot.send_voice(chat_id=group_chat_id, voice=pm.get("media_file_id"), caption=f"🎙️ {caption}")
                    elif pm.get("type") == "document":
                        await context.bot.send_document(chat_id=group_chat_id, document=pm.get("media_file_id"), caption=f"📎 {caption}")
                    elif pm.get("type") == "audio":
                        await context.bot.send_audio(chat_id=group_chat_id, audio=pm.get("media_file_id"), caption=f"🎵 {caption}")
                    elif pm.get("type") == "animation":
                        await context.bot.send_animation(chat_id=group_chat_id, animation=pm.get("media_file_id"), caption=f"🎬 {caption}")
                except Exception as e:
                    logger.error("خطا ارسال رسانه %d به گروه: %s", i, e)

        db_save_question(question_id, question_data)

        # پاک‌سازی صف
        context.user_data["pending_messages"] = []

        await query.edit_message_text(MESSAGES["question_sent"])
        try:
            await context.bot.send_message(
                chat_id=user.id, text="در صورت داشتن سوال مجدد:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ارسال سوال جدید", callback_data="ask_again")]]),
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("خطا ارسال سوال: %s", e)
        await query.edit_message_text(MESSAGES["question_send_failed"])

    return ConversationHandler.END


async def clear_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پاک کردن صف پیام‌ها"""
    query = update.callback_query
    await query.answer()
    context.user_data["pending_messages"] = []
    course = context.user_data.get("selected_course", "")
    send_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال سوال", callback_data="submit_question")],
        [InlineKeyboardButton("🗑 پاک کردن پیام‌ها", callback_data="clear_question")],
    ])
    await query.edit_message_text(
        f"🗑 صف پیام‌ها پاک شد.\n\n"
        f"دوره: {course}\n"
        "می‌توانید سوال جدیدی ارسال کنید.",
        reply_markup=send_keyboard,
    )
    return STUDENT_QUESTION


async def group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, question_id = query.data.split(":", 1)
    question = db_get_question(question_id)
    if not question:
        await query.edit_message_text("این سوال موجود نیست.")
        return
    if question["status"] != "open":
        await query.answer("این سوال قبلاً بررسی شده است.", show_alert=True)
        return
    if action == "answer":
        teacher = update.effective_user
        db_update_question_status(
            question_id, "assigned",
            assigned_teacher_id=teacher.id,
            assigned_teacher_name=teacher.full_name
        )
        db_set_teacher_pending(teacher.id, question_id)
        await query.edit_message_text(
            query.message.text + "\n\n" + MESSAGES["selected_answer"].format(teacher=teacher.full_name)
        )
        try:
            await context.bot.send_message(
                chat_id=teacher.id,
                text=MESSAGES["teacher_private_question"].format(
                    student_name=question["student_name"],
                    course=question["course"],
                    question=question["question"],
                ),
            )
            if question.get("media_file_id") and question.get("media_type"):
                mt, fid = question["media_type"], question["media_file_id"]
                if mt == "photo":
                    await context.bot.send_photo(chat_id=teacher.id, photo=fid, caption="📷 عکس سوال")
                elif mt == "video":
                    await context.bot.send_video(chat_id=teacher.id, video=fid, caption="🎥 ویدیو سوال")
                elif mt == "voice":
                    await context.bot.send_voice(chat_id=teacher.id, voice=fid, caption="🎙️ ویس سوال")
                elif mt == "document":
                    await context.bot.send_document(chat_id=teacher.id, document=fid, caption="📎 فایل سوال")
                elif mt == "audio":
                    await context.bot.send_audio(chat_id=teacher.id, audio=fid, caption="🎵 آهنگ سوال")
                elif mt == "animation":
                    await context.bot.send_animation(chat_id=teacher.id, animation=fid, caption="🎬 GIF سوال")
        except Exception as e:
            logger.error("خطا ارسال به استاد: %s", e)
            await query.message.reply_text(MESSAGES["teacher_private_error"])
    elif action == "not_related":
        db_update_question_status(question_id, "not_related")
        await query.edit_message_text(query.message.text + "\n\n" + MESSAGES["not_related_post"])
        try:
            await context.bot.send_message(chat_id=question["student_id"], text=MESSAGES["student_not_related"])
        except Exception as e:
            logger.error("خطا not_related: %s", e)


async def teacher_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    teacher_id = update.effective_user.id
    pending_question = db_get_teacher_pending(teacher_id)
    if not pending_question:
        await update.message.reply_text(MESSAGES["no_pending_question"])
        return

    msg_data = _extract_message_data(update.message)
    if not msg_data:
        await update.message.reply_text("لطفاً متن یا رسانه‌ای برای پاسخ ارسال کنید.")
        return

    teacher_pending = context.user_data.setdefault("teacher_pending_messages", [])
    teacher_pending.append(msg_data)
    context.user_data["teacher_pending_question"] = pending_question

    count = len(teacher_pending)
    await update.message.reply_text(
        f"✅ پیام شما در صف قرار گرفت.\n"
        f"تعداد پیام‌های پاسخ: {count}.\n"
        "وقتی آماده بودید دکمه ارسال پاسخ را بزنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 ارسال پاسخ", callback_data="submit_answer")],
            [InlineKeyboardButton("🗑 پاک کردن پاسخ‌ها", callback_data="clear_answer")],
        ]),
    )
    return
async def submit_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    teacher_id = query.from_user.id
    pending_question = context.user_data.get("teacher_pending_question") or db_get_teacher_pending(teacher_id)
    teacher_pending = context.user_data.get("teacher_pending_messages", [])

    if not pending_question or not teacher_pending:
        await query.edit_message_text("⚠️ هیچ پاسخی در صف نیست یا سوالی برای پاسخ دادن ندارید.")
        return

    question = db_get_question(pending_question)
    if not question:
        await query.edit_message_text("⚠️ سوال یافت نشد.")
        return

    text_parts = [m["text"] for m in teacher_pending if m.get("text")]
    combined_text = "\n".join(text_parts).strip() or "(بدون متن)"
    answer_media = next((m for m in teacher_pending if m.get("media_file_id")), None)
    answer_media_file_id = answer_media["media_file_id"] if answer_media else None
    answer_media_type = answer_media["media_type"] if answer_media else None

    if not db_update_question_status(
        pending_question, "answered",
        answer=combined_text,
        answer_media_file_id=answer_media_file_id,
        answer_media_type=answer_media_type
    ):
        await query.edit_message_text("❌ خطا در ثبت پاسخ. لطفاً دوباره تلاش کنید.")
        return

    db_remove_teacher_pending(teacher_id)
    context.user_data.pop("teacher_pending_messages", None)
    context.user_data.pop("teacher_pending_question", None)

    student_id = question["student_id"]
    try:
        await context.bot.send_message(
            chat_id=student_id,
            text=(
                f"✅ پاسخ استاد:\n📚 دوره: {question['course']}\n"
                f"👨‍🏫 استاد: {question['assigned_teacher_name']}\n\n"
                f"{combined_text}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("سوالی ندارم", callback_data=f"no_more:{pending_question}")],
                [InlineKeyboardButton("باز سوال دارم", callback_data=f"ask_more:{pending_question}")],
            ])
        )
        if answer_media_file_id and answer_media_type:
            if answer_media_type == "photo":
                await context.bot.send_photo(chat_id=student_id, photo=answer_media_file_id, caption="📷 عکس پاسخ")
            elif answer_media_type == "video":
                await context.bot.send_video(chat_id=student_id, video=answer_media_file_id, caption="🎥 ویدیو پاسخ")
            elif answer_media_type == "voice":
                await context.bot.send_voice(chat_id=student_id, voice=answer_media_file_id, caption="🎙️ وِیس پاسخ")
            elif answer_media_type == "audio":
                await context.bot.send_audio(chat_id=student_id, audio=answer_media_file_id, caption="🎵 آهنگ پاسخ")
            elif answer_media_type == "document":
                await context.bot.send_document(chat_id=student_id, document=answer_media_file_id, caption="📎 فایل پاسخ")
            elif answer_media_type == "animation":
                await context.bot.send_animation(chat_id=student_id, animation=answer_media_file_id, caption="🎬 GIF پاسخ")
        await query.edit_message_text(MESSAGES["answer_sent"])
    except Exception as e:
        logger.error("خطا ارسال پاسخ: %s", e)
        await query.edit_message_text(MESSAGES["answer_send_failed"])
        return

    group_chat_id = db_get_group_chat_id()
    if group_chat_id and question.get("group_message_id"):
        try:
            await context.bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=question["group_message_id"],
                text=f"{question['question']}\n\n" + MESSAGES["question_answered_group"].format(
                    teacher=question["assigned_teacher_name"]
                ),
            )
        except Exception as e:
            logger.warning("خطا update گروه: %s", e)


async def clear_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("teacher_pending_messages", None)
    context.user_data.pop("teacher_pending_question", None)
    await query.edit_message_text(
        "🗑️ صف پاسخ‌ها پاک شد.\n"
        "اگر می‌خواهید دوباره پاسخ ارسال کنید، پیام‌های جدید را ارسال کنید."
    )


async def post_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action, question_id = query.data.split(":", 1)
    question = db_get_question(question_id)
    if not question:
        try:
            await query.edit_message_text("خطا: سوال یافت نشد.")
        except Exception:
            pass
        return ConversationHandler.END
    if action == "no_more":
        try:
            await context.bot.send_poll(
                chat_id=question["student_id"],
                question="نظرسنجی: کیفیت پاسخ پشتیبانی؟",
                options=["خیلی خوب", "خوب", "متوسط", "ضعیف"],
                is_anonymous=False,
            )
            await context.bot.send_message(
                chat_id=question["student_id"], text="اگر می‌خواهید دوباره استفاده کنید:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("استارت مجدد", callback_data="restart_bot")]]),
            )
        except Exception as e:
            logger.error("خطا نظرسنجی: %s", e)
        return ConversationHandler.END
    elif action == "ask_more":
        allowed_courses = context.user_data.get("allowed_courses")
        if not allowed_courses:
            phone = context.user_data.get("phone", "")
            allowed_courses = db_get_allowed_courses(phone) if phone else None
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id, text="دوره مورد نظر رو انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(build_course_keyboard(allowed_courses))
            )
        except Exception:
            pass
        return STUDENT_COURSE


async def restart_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    buttons = [[InlineKeyboardButton("شروع ثبت درخواست", callback_data="start_register")]]
    if is_admin(query.from_user.id):
        buttons.append([InlineKeyboardButton("پنل ادمین", callback_data="ap:open")])
    try:
        await query.message.reply_text(
            MESSAGES["welcome"],
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        # also send the persistent restart reply keyboard
        restart_kb = ReplyKeyboardMarkup([[KeyboardButton(RESTART_LABEL)]], resize_keyboard=True, one_time_keyboard=False)
        await context.bot.send_message(chat_id=query.from_user.id, text="برای شروع سریع دکمه را بزنید:", reply_markup=restart_kb)
    except Exception:
        pass


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MESSAGES["unknown"])


# =====================================================
# ====== پنل ادمین (مرحله به مرحله با InlineKeyboard) ======
# =====================================================

def _admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن کاراموز جدید", callback_data="ap:add")],
        [InlineKeyboardButton("🔍 جستجو / ویرایش کاراموز", callback_data="ap:search")],
        [InlineKeyboardButton("📋 لیست همه کاراموزان", callback_data="ap:list:0")],
        [InlineKeyboardButton("🗄 وضعیت دیتابیس", callback_data="ap:dbstatus")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="ap:close")],
    ])


def _courses_keyboard(selected: list) -> InlineKeyboardMarkup:
    """کیبورد انتخاب دوره با تیک برای دوره‌های انتخاب‌شده"""
    rows = []
    for c in COURSES:
        tick = "✅ " if c in selected else "⬜ "
        rows.append([InlineKeyboardButton(tick + c, callback_data=f"apc:{c}")])
    rows.append([
        InlineKeyboardButton("✔️ تأیید انتخاب‌ها", callback_data="apc:__done__"),
        InlineKeyboardButton("🔙 بازگشت", callback_data="apc:__back__"),
    ])
    return InlineKeyboardMarkup(rows)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ورودی پنل ادمین — دستور /panel"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MESSAGES["not_admin"])
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["admin_mode"] = True

    await update.message.reply_text(
        "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=_admin_main_keyboard(),
    )
    return ADMIN_MENU


async def admin_panel_callback_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ورودی پنل ادمین از طریق callback button"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔️ دسترسی ندارید.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["admin_mode"] = True

    await query.edit_message_text(
        "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=_admin_main_keyboard(),
    )
    return ADMIN_MENU


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """هندل همه callback های پنل ادمین با prefix ap:"""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔️ دسترسی ندارید.")
        return ConversationHandler.END

    data = query.data  # ap:xxx

    # ---- بستن پنل ----
    if data == "ap:close":
        await query.edit_message_text("✅ پنل ادمین بسته شد.")
        context.user_data.clear()
        return ConversationHandler.END

    # ---- وضعیت دیتابیس ----
    if data == "ap:dbstatus":
        try:
            count = db_count_interns()
            conn = get_db_connection()
            q_rows = conn.run("SELECT COUNT(*) FROM questions")
            open_rows = conn.run("SELECT COUNT(*) FROM questions WHERE status = 'open'")
            conn.close()
            q_count = q_rows[0][0] if q_rows else 0
            open_q = open_rows[0][0] if open_rows else 0
            text = (
                f"🗄 *وضعیت دیتابیس*\n\n"
                f"👥 تعداد کاراموزان: {count}\n"
                f"❓ کل سوالات: {q_count}\n"
                f"🟡 سوالات باز: {open_q}\n"
                f"✅ دیتابیس متصل است"
            )
        except Exception as e:
            text = f"❌ خطا در اتصال:\n{e}"
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")]]),
        )
        return ADMIN_MENU

    # ---- بازگشت به منو اصلی ----
    if data == "ap:home":
        context.user_data.pop("new_intern", None)
        await query.edit_message_text(
            "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=_admin_main_keyboard(),
        )
        return ADMIN_MENU

    # ---- باز کردن پنل از دکمه شروع ----
    if data == "ap:open":
        context.user_data.clear()
        context.user_data["admin_mode"] = True
        await query.edit_message_text(
            "🛠 *پنل مدیریت ادمین*\n\n"
            "یک گزینه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=_admin_main_keyboard(),
        )
        return ADMIN_MENU

    # ---- شروع افزودن ----
    if data == "ap:add":
        context.user_data["new_intern"] = {}
        await query.edit_message_text(
            "➕ *افزودن کاراموز جدید*\n\n"
            "📞 *مرحله ۱ از ۴:* شماره موبایل کاراموز را وارد کنید:\n"
            "_(مثال: 09121234567)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")]]),
        )
        return ADMIN_ADD_PHONE

    # ---- جستجو ----
    if data == "ap:search":
        await query.edit_message_text(
            "🔍 *جستجوی کاراموز*\n\n"
            "شماره موبایل کاراموز را وارد کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="ap:home")]]),
        )
        return ADMIN_SEARCH_PHONE

    # ---- لیست کاراموزان با صفحه‌بندی ----
    if data.startswith("ap:list:"):
        page = int(data.split(":")[-1])
        PAGE_SIZE = 8
        interns = db_list_interns()
        total = len(interns)
        if total == 0:
            await query.edit_message_text(
                "📋 هیچ کاراموزی ثبت نشده است.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="ap:home")]]),
            )
            return ADMIN_MENU
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        chunk = interns[start:end]
        lines = [f"📋 *لیست کاراموزان* — صفحه {page+1} از {((total-1)//PAGE_SIZE)+1} ({total} نفر)\n"]
        for i, intern in enumerate(chunk, start=start+1):
            name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()
            courses = (intern.get("courses") or "").replace("|", " | ")
            lines.append(f"*{i}.* {name}\n   📞 `{intern['phone']}`\n   📚 {courses or '—'}\n")
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"ap:list:{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"ap:list:{page+1}"))
        kb = []
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")])
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return ADMIN_MENU

    # ---- منوی ویرایش/حذف یک کاراموز ----
    if data.startswith("ap:edit:"):
        phone = data[len("ap:edit:"):]
        intern = db_get_intern(phone)
        if not intern:
            await query.edit_message_text("⚠️ کاراموز یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="ap:home")]]))
            return ADMIN_MENU
        name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()
        courses_str = (intern.get("courses") or "").replace("|", "\n   • ")
        context.user_data["edit_phone"] = phone
        await query.edit_message_text(
            f"✏️ *ویرایش کاراموز*\n\n"
            f"👤 نام: {name}\n"
            f"📞 شماره: `{phone}`\n"
            f"📚 دوره‌های فعلی:\n   • {courses_str or '—'}\n\n"
            f"چه کاری انجام دهید؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ ویرایش دوره‌ها", callback_data=f"ap:editcourses:{phone}")],
                [InlineKeyboardButton("🗑 حذف کاراموز", callback_data=f"ap:askdelete:{phone}")],
                [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")],
            ]),
        )
        return ADMIN_EDIT_MENU

    # ---- شروع ویرایش دوره‌ها ----
    if data.startswith("ap:editcourses:"):
        phone = data[len("ap:editcourses:"):]
        intern = db_get_intern(phone)
        existing = [c.strip() for c in (intern.get("courses") or "").split("|") if c.strip()] if intern else []
        context.user_data["edit_phone"] = phone
        context.user_data["edit_courses"] = existing.copy()
        await query.edit_message_text(
            f"📚 *ویرایش دوره‌های کاراموز*\n"
            f"شماره: `{phone}`\n\n"
            "دوره‌های مورد نظر را انتخاب یا حذف کنید:",
            parse_mode="Markdown",
            reply_markup=_courses_keyboard(existing),
        )
        return ADMIN_EDIT_COURSES

    # ---- تأیید حذف ----
    if data.startswith("ap:askdelete:"):
        phone = data[len("ap:askdelete:"):]
        intern = db_get_intern(phone)
        name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip() if intern else phone
        await query.edit_message_text(
            f"⚠️ *آیا مطمئن هستید؟*\n\n"
            f"کاراموز *{name}* (`{phone}`) حذف شود؟\n\n"
            "این عمل قابل بازگشت نیست!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، حذف شود", callback_data=f"ap:doDelete:{phone}")],
                [InlineKeyboardButton("❌ انصراف", callback_data=f"ap:edit:{phone}")],
            ]),
        )
        return ADMIN_DELETE_CONFIRM

    # ---- اجرای حذف ----
    if data.startswith("ap:doDelete:"):
        phone = data[len("ap:doDelete:"):]
        if db_remove_intern(phone):
            msg = f"✅ کاراموز `{phone}` با موفقیت حذف شد."
        else:
            msg = f"⚠️ شماره `{phone}` در سیستم یافت نشد."
        await query.edit_message_text(
            msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")]]),
        )
        return ADMIN_MENU

    return ADMIN_MENU


async def admin_add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت شماره کاراموز جدید"""
    phone_raw = update.message.text.strip()
    phone = normalize_phone(phone_raw)
    if not (phone.startswith("09") and len(phone) == 11 and phone.isdigit()):
        await update.message.reply_text(
            "⚠️ شماره وارد شده معتبر نیست!\n"
            "شماره باید ۱۱ رقم و با ۰۹ شروع شود.\n\nمجدداً وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")]]),
        )
        return ADMIN_ADD_PHONE

    context.user_data["new_intern"]["phone"] = phone
    # بررسی وجود قبلی
    existing = db_get_intern(phone)
    if existing:
        name = f"{existing.get('first_name','')} {existing.get('last_name','')}".strip()
        courses_str = (existing.get("courses") or "").replace("|", " | ")
        await update.message.reply_text(
            f"⚠️ این شماره قبلاً ثبت شده است:\n\n"
            f"👤 نام: {name}\n"
            f"📞 شماره: `{phone}`\n"
            f"📚 دوره‌ها: {courses_str or '—'}\n\n"
            "اگر ادامه دهید، اطلاعات *بازنویسی* می‌شود.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ادامه و بازنویسی", callback_data="ap:continue_add")],
                [InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")],
            ]),
        )
        return ADMIN_ADD_PHONE  # منتظر callback می‌مانیم

    await update.message.reply_text(
        f"✅ شماره: `{phone}`\n\n"
        "👤 *مرحله ۲ از ۴:* نام *کوچک* کاراموز را وارد کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")]]),
    )
    return ADMIN_ADD_FIRSTNAME


async def admin_continue_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه افزودن پس از تأیید بازنویسی"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"✅ شماره: `{context.user_data['new_intern']['phone']}`\n\n"
        "👤 *مرحله ۲ از ۴:* نام *کوچک* کاراموز را وارد کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")]]),
    )
    return ADMIN_ADD_FIRSTNAME


async def admin_add_firstname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام کوچک"""
    first_name = update.message.text.strip()
    if len(first_name) < 2:
        await update.message.reply_text("⚠️ نام خیلی کوتاه است. مجدداً وارد کنید:")
        return ADMIN_ADD_FIRSTNAME
    context.user_data["new_intern"]["first_name"] = first_name
    await update.message.reply_text(
        f"✅ نام: *{first_name}*\n\n"
        "👤 *مرحله ۳ از ۴:* نام *خانوادگی* کاراموز را وارد کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")]]),
    )
    return ADMIN_ADD_LASTNAME


async def admin_add_lastname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام خانوادگی"""
    last_name = update.message.text.strip()
    if len(last_name) < 2:
        await update.message.reply_text("⚠️ نام خانوادگی خیلی کوتاه است. مجدداً وارد کنید:")
        return ADMIN_ADD_LASTNAME
    context.user_data["new_intern"]["last_name"] = last_name
    intern = context.user_data["new_intern"]
    await update.message.reply_text(
        f"✅ نام کامل: *{intern['first_name']} {last_name}*\n\n"
        "📚 *مرحله ۴ از ۴:* دوره‌های مجاز را انتخاب کنید:\n"
        "_(می‌توانید چند دوره انتخاب کنید)_",
        parse_mode="Markdown",
        reply_markup=_courses_keyboard([]),
    )
    context.user_data["new_intern"]["last_name"] = last_name
    context.user_data["new_intern"]["courses"] = []
    return ADMIN_ADD_COURSES


async def admin_add_courses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """toggle انتخاب دوره در مرحله افزودن"""
    query = update.callback_query
    await query.answer()
    course = query.data[len("apc:"):]
    intern = context.user_data.get("new_intern", {})
    selected = intern.get("courses", [])

    if course == "__back__":
        await query.edit_message_text(
            "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=_admin_main_keyboard(),
        )
        return ADMIN_MENU

    if course == "__done__":
        if not selected:
            await query.answer("⚠️ حداقل یک دوره انتخاب کنید!", show_alert=True)
            return ADMIN_ADD_COURSES
        # نمایش خلاصه و تأیید
        courses_list = "\n".join(f"   ✅ {c}" for c in selected)
        await query.edit_message_text(
            f"📋 *تأیید اطلاعات کاراموز جدید*\n\n"
            f"📞 شماره: `{intern['phone']}`\n"
            f"👤 نام: *{intern['first_name']} {intern['last_name']}*\n"
            f"📚 دوره‌ها:\n{courses_list}\n\n"
            "آیا اطلاعات صحیح است؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ثبت نهایی", callback_data="ap:doAdd")],
                [InlineKeyboardButton("✏️ ویرایش دوره‌ها", callback_data="ap:redo_courses")],
                [InlineKeyboardButton("🔙 انصراف", callback_data="ap:home")],
            ]),
        )
        return ADMIN_CONFIRM_ADD

    # toggle
    if course in selected:
        selected.remove(course)
    else:
        selected.append(course)
    context.user_data["new_intern"]["courses"] = selected
    await query.edit_message_text(
        f"📚 *مرحله ۴ از ۴:* دوره‌های مجاز را انتخاب کنید:\n"
        f"_(انتخاب شده: {len(selected)} دوره)_",
        parse_mode="Markdown",
        reply_markup=_courses_keyboard(selected),
    )
    return ADMIN_ADD_COURSES


async def admin_confirm_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback های صفحه تأیید افزودن"""
    query = update.callback_query
    await query.answer()
    data = query.data
    intern = context.user_data.get("new_intern", {})

    if data == "ap:redo_courses":
        selected = intern.get("courses", [])
        await query.edit_message_text(
            "📚 دوره‌ها را مجدداً انتخاب کنید:",
            reply_markup=_courses_keyboard(selected),
        )
        return ADMIN_ADD_COURSES

    if data == "ap:doAdd":
        phone = intern.get("phone", "")
        first_name = intern.get("first_name", "")
        last_name = intern.get("last_name", "")
        courses = intern.get("courses", [])
        if db_add_intern(phone, first_name, last_name, courses):
            courses_list = "\n".join(f"   ✅ {c}" for c in courses)
            await query.edit_message_text(
                f"🎉 *کاراموز با موفقیت ثبت شد!*\n\n"
                f"📞 شماره: `{phone}`\n"
                f"👤 نام: *{first_name} {last_name}*\n"
                f"📚 دوره‌ها:\n{courses_list}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ افزودن کاراموز دیگر", callback_data="ap:add")],
                    [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")],
                ]),
            )
            context.user_data.pop("new_intern", None)
        else:
            await query.edit_message_text(
                "❌ خطا در ثبت. لطفاً مجدداً امتحان کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")]]),
            )
        return ADMIN_MENU

    if data == "ap:home":
        context.user_data.pop("new_intern", None)
        await query.edit_message_text(
            "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=_admin_main_keyboard(),
        )
        return ADMIN_MENU

    return ADMIN_CONFIRM_ADD


async def admin_search_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت شماره برای جستجو"""
    phone_raw = update.message.text.strip()
    phone = normalize_phone(phone_raw)
    intern = db_get_intern(phone)
    if not intern:
        await update.message.reply_text(
            f"⚠️ کاراموزی با شماره `{phone}` یافت نشد.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 جستجوی مجدد", callback_data="ap:search")],
                [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")],
            ]),
        )
        return ADMIN_MENU
    name = f"{intern.get('first_name','')} {intern.get('last_name','')}".strip()
    courses_str = (intern.get("courses") or "").replace("|", "\n   • ")
    created = str(intern.get("created_at", ""))[:19]
    await update.message.reply_text(
        f"🔍 *نتیجه جستجو*\n\n"
        f"👤 نام: *{name}*\n"
        f"📞 شماره: `{phone}`\n"
        f"📚 دوره‌ها:\n   • {courses_str or '—'}\n"
        f"🗓 تاریخ ثبت: {created}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ ویرایش / حذف", callback_data=f"ap:edit:{phone}")],
            [InlineKeyboardButton("🔍 جستجوی دیگر", callback_data="ap:search")],
            [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")],
        ]),
    )
    return ADMIN_MENU


async def admin_edit_courses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """toggle دوره‌ها در حالت ویرایش"""
    query = update.callback_query
    await query.answer()
    course = query.data[len("apc:"):]
    phone = context.user_data.get("edit_phone", "")
    selected = context.user_data.get("edit_courses", [])

    if course == "__back__":
        await query.edit_message_text(
            "🛠 *پنل مدیریت ادمین*\n\nیک گزینه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=_admin_main_keyboard(),
        )
        return ADMIN_MENU

    if course == "__done__":
        if not selected:
            await query.answer("⚠️ حداقل یک دوره انتخاب کنید!", show_alert=True)
            return ADMIN_EDIT_COURSES
        intern = db_get_intern(phone)
        first_name = intern.get("first_name", "") if intern else ""
        last_name = intern.get("last_name", "") if intern else ""
        if db_add_intern(phone, first_name, last_name, selected):
            courses_list = "\n".join(f"   ✅ {c}" for c in selected)
            await query.edit_message_text(
                f"✅ *دوره‌های کاراموز بروزرسانی شد!*\n\n"
                f"👤 نام: *{first_name} {last_name}*\n"
                f"📞 شماره: `{phone}`\n"
                f"📚 دوره‌های جدید:\n{courses_list}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ ویرایش مجدد", callback_data=f"ap:edit:{phone}")],
                    [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="ap:home")],
                ]),
            )
        else:
            await query.edit_message_text(
                "❌ خطا در بروزرسانی.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="ap:home")]]),
            )
        return ADMIN_MENU

    # toggle
    if course in selected:
        selected.remove(course)
    else:
        selected.append(course)
    context.user_data["edit_courses"] = selected
    await query.edit_message_text(
        f"📚 دوره‌های کاراموز را ویرایش کنید:\n_(انتخاب شده: {len(selected)} دوره)_",
        parse_mode="Markdown",
        reply_markup=_courses_keyboard(selected),
    )
    return ADMIN_EDIT_COURSES


# =====================================================
# ====== main ======
# =====================================================

def main() -> None:
    # راه‌اندازی دیتابیس
    logger.info("در حال راه‌اندازی دیتابیس...")
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    # دستورات ادمین (متنی — قدیمی، هنوز کار می‌کنند)
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("adduser", admin_add_user))
    app.add_handler(CommandHandler("removeuser", admin_remove_user))
    app.add_handler(CommandHandler("listusers", admin_list_users))
    app.add_handler(CommandHandler("searchuser", admin_search_user))
    app.add_handler(CommandHandler("dbstatus", admin_db_status))

    # ====== پنل ادمین گرافیکی (مرحله به مرحله) ======
    admin_panel_conv = ConversationHandler(
        entry_points=[
            CommandHandler("panel", admin_panel),
            CallbackQueryHandler(admin_panel_callback_entry, pattern=r"^ap:open$"),
        ],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:"),
            ],
            ADMIN_ADD_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_phone),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:home$"),
                CallbackQueryHandler(admin_continue_add_callback, pattern=r"^ap:continue_add$"),
            ],
            ADMIN_ADD_FIRSTNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_firstname),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:home$"),
            ],
            ADMIN_ADD_LASTNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_lastname),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:home$"),
            ],
            ADMIN_ADD_COURSES: [
                CallbackQueryHandler(admin_add_courses_callback, pattern=r"^apc:"),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:home$"),
            ],
            ADMIN_CONFIRM_ADD: [
                CallbackQueryHandler(admin_confirm_add_callback, pattern=r"^ap:(doAdd|redo_courses|home)$"),
            ],
            ADMIN_SEARCH_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_phone),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:"),
            ],
            ADMIN_EDIT_MENU: [
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:"),
            ],
            ADMIN_EDIT_COURSES: [
                CallbackQueryHandler(admin_edit_courses_callback, pattern=r"^apc:"),
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:home$"),
            ],
            ADMIN_DELETE_CONFIRM: [
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:"),
            ],
            ADMIN_LIST_PAGE: [
                CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:"),
            ],
        },
        fallbacks=[
            CommandHandler("panel", admin_panel),
            CallbackQueryHandler(admin_panel_callback, pattern=r"^ap:close$"),
        ],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(admin_panel_conv)
    # Allow pressing a persistent 'شروع مجدد' reply-button to trigger /start without typing
    app.add_handler(MessageHandler(filters.Regex(r"^" + RESTART_LABEL + r"$"), start))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(post_answer_callback, pattern=r"^ask_more:"),
        ],
        states={
            STUDENT_PHONE: [
                CallbackQueryHandler(start_register_callback, pattern=r"^start_register$"),
                MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), receive_contact),
            ],
            STUDENT_COURSE: [CallbackQueryHandler(course_selected, pattern=r"^course:")],
            STUDENT_QUESTION: [
                CallbackQueryHandler(submit_question_callback, pattern=r"^submit_question$"),
                CallbackQueryHandler(clear_question_callback, pattern=r"^clear_question$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question),
                MessageHandler(filters.PHOTO, receive_question),
                MessageHandler(filters.VIDEO, receive_question),
                MessageHandler(filters.VOICE, receive_question),
                MessageHandler(filters.Document.ALL, receive_question),
                MessageHandler(filters.AUDIO, receive_question),
                MessageHandler(filters.ANIMATION, receive_question),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(submit_answer_callback, pattern=r"^submit_answer$"))
    app.add_handler(CallbackQueryHandler(clear_answer_callback, pattern=r"^clear_answer$"))
    app.add_handler(CallbackQueryHandler(post_answer_callback, pattern=r"^(no_more|ask_more):"))
    app.add_handler(CallbackQueryHandler(restart_bot_callback, pattern=r"^restart_bot$"))
    app.add_handler(CommandHandler("setgroup", set_group))
    app.add_handler(CallbackQueryHandler(group_callback, pattern=r"^(answer|not_related):"))
    app.add_handler(CallbackQueryHandler(course_selected, pattern=r"^course:"))
    app.add_handler(CallbackQueryHandler(ask_again_callback, pattern=r"^ask_again$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_reply))
    app.add_handler(MessageHandler(filters.PHOTO, teacher_reply))
    app.add_handler(MessageHandler(filters.VIDEO, teacher_reply))
    app.add_handler(MessageHandler(filters.VOICE, teacher_reply))
    app.add_handler(MessageHandler(filters.AUDIO, teacher_reply))
    app.add_handler(MessageHandler(filters.Document.ALL, teacher_reply))
    app.add_handler(MessageHandler(filters.ANIMATION, teacher_reply))
    app.add_handler(MessageHandler(filters.ALL, unknown))

    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=status_monitor, args=(stop_event,), daemon=True)
    monitor_thread.start()

    logger.info("ربات شروع به کار کرد...")
    try:
        app.run_polling()
    finally:
        stop_event.set()
        monitor_thread.join(timeout=5)


if __name__ == "__main__":
    main()
