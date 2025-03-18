import json
import os
import sqlite3
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

class ExchangeRateBot:
    def __init__(self):
        # Get the bot token from the environment variable
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            logger.error("TELEGRAM_BOT_TOKEN environment variable is not set.")
            raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable in the .env file.")

        # Initialize the bot application
        self.application = Application.builder().token(self.bot_token).post_init(self.post_init).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("rates", self.send_rates))
        self.application.add_handler(CommandHandler("settimezone", self.set_timezone))
        self.application.add_handler(CommandHandler("unsubscribe", self.unsubscribe))
        self.application.add_handler(CommandHandler("listtimezones", self.list_timezones))

        # Initialize the database
        self.init_db()

        # Initialize the scheduler
        self.scheduler = AsyncIOScheduler()

        # Load exchange rates initially
        self.exchange_rates = self.load_exchange_rates()

    async def post_init(self, application: Application):
        """Set up bot commands using set_my_commands."""
        await application.bot.set_my_commands([
            ("start", "Start the bot and subscribe to daily rates"),
            ("rates", "Get the latest exchange rates"),
            ("settimezone", "Set your preferred timezone (e.g., /settimezone Asia/Bangkok)"),
            ("unsubscribe", "Unsubscribe from daily updates"),
            ("listtimezones", "List all available timezones"),
        ])
        logger.info("Bot commands have been set up.")

    def init_db(self):
        """Initialize the SQLite database to store user chat IDs and timezones."""
        try:
            self.conn = sqlite3.connect("users.db")
            self.cursor = self.conn.cursor()

            # Check if the `timezone` column exists
            self.cursor.execute("PRAGMA table_info(users)")
            columns = self.cursor.fetchall()
            column_names = [column[1] for column in columns]

            if "timezone" not in column_names:
                # Add the `timezone` column if it doesn't exist
                self.cursor.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Bangkok'")
                self.conn.commit()
                logger.info("Added 'timezone' column to the users table.")

            # Create the users table if it doesn't exist
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    timezone TEXT DEFAULT 'Asia/Bangkok'
                )
            """)
            self.conn.commit()
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /start command."""
        chat_id = update.message.chat_id

        # Save the user's chat ID to the database if not already present
        try:
            self.cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
            self.conn.commit()
            logger.info(f"User {chat_id} started the bot.")
        except Exception as e:
            logger.error(f"Failed to save user {chat_id} to the database: {e}")
            await update.message.reply_text("An error occurred. Please try again later.")
            return

        await update.message.reply_text(
            "Welcome! You will now receive daily exchange rates for USD, RUB, and EUR at 10 AM in your preferred timezone.\n\n"
            "Use /settimezone to set your timezone (e.g., /settimezone Asia/Bangkok).\n"
            "Use /rates to get the latest exchange rates at any time.\n"
            "Use /unsubscribe to stop receiving daily updates.\n"
            "Use /listtimezones to see all available timezones."
        )

    async def set_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /settimezone command."""
        chat_id = update.message.chat_id
        timezone = context.args[0] if context.args else None

        if timezone and timezone in pytz.all_timezones:
            try:
                self.cursor.execute("UPDATE users SET timezone = ? WHERE chat_id = ?", (timezone, chat_id))
                self.conn.commit()
                await update.message.reply_text(f"Your timezone has been set to {timezone}.")
                logger.info(f"User {chat_id} set timezone to {timezone}.")
            except Exception as e:
                logger.error(f"Failed to update timezone for user {chat_id}: {e}")
                await update.message.reply_text("An error occurred. Please try again later.")
        else:
            await update.message.reply_text("Invalid timezone. Please provide a valid timezone (e.g., /settimezone Asia/Bangkok).")

    async def unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /unsubscribe command."""
        chat_id = update.message.chat_id

        try:
            self.cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
            self.conn.commit()
            await update.message.reply_text("You have been unsubscribed from daily updates.")
            logger.info(f"User {chat_id} unsubscribed.")
        except Exception as e:
            logger.error(f"Failed to unsubscribe user {chat_id}: {e}")
            await update.message.reply_text("An error occurred. Please try again later.")

    async def list_timezones(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /listtimezones command."""
        timezones = "\n".join(pytz.all_timezones)
        await update.message.reply_text(f"Available timezones:\n\n{timezones}")

    def load_exchange_rates(self):
        """Load the exchange rates from the JSON file."""
        try:
            with open("exchange_rates.json", "r") as file:
                data = json.load(file)
            logger.info("Exchange rates loaded successfully.")
            return data
        except Exception as e:
            logger.error(f"Failed to load exchange rates: {e}")
            raise

    async def reload_exchange_rates(self, context: ContextTypes.DEFAULT_TYPE):
        """Reload the exchange rates from the JSON file."""
        try:
            self.exchange_rates = self.load_exchange_rates()
            logger.info(f"Exchange rates reloaded at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            logger.error(f"Failed to reload exchange rates: {e}")

    def get_latest_rates(self):
        """Get the latest date and rates for USD, RUB, and EUR."""
        try:
            # Get the latest date (assuming the JSON is sorted by date)
            sorted_dates = sorted(self.exchange_rates.keys(), reverse=True)
            latest_date = sorted_dates[0]
            previous_date = sorted_dates[1] if len(sorted_dates) > 1 else None

            latest_rates = self.exchange_rates[latest_date]["rates"]
            previous_rates = self.exchange_rates[previous_date]["rates"] if previous_date else None

            # Extract USD, RUB, and EUR rates
            usd = latest_rates.get("USD", {})
            rub = latest_rates.get("RUB", {})
            eur = latest_rates.get("EUR", {})

            # Compare with previous rates
            def get_trend(current, previous, key):
                if not previous or key not in previous:
                    return ""
                current_rate = current.get(key, 0)
                previous_rate = previous.get(key, {})
                if current_rate > previous_rate:
                    return '↑ 💹'  # Green up arrow
                elif current_rate < previous_rate:
                    return '↓ ❌'  # Red down arrow
                return ""

            usd_trend = get_trend(usd, previous_rates.get("USD") if previous_rates else None, "buyingRate")
            rub_trend = get_trend(rub, previous_rates.get("RUB") if previous_rates else None, "buyingRate")
            eur_trend = get_trend(eur, previous_rates.get("EUR") if previous_rates else None, "buyingRate")

            return latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend
        except Exception as e:
            logger.exception(f"Failed to get latest rates: {e}")
            raise

    def format_rates_message(self, latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend):
        """Format the exchange rates into a message."""
        return (
            f"📅 Latest rates as of <b>{latest_date}</b>:\n\n"
            f"🇺🇸 <b>USD (United States)</b>\n"
            f"  Buying: {usd.get('buyingRate', 'N/A')} {usd_trend}\n"
            f"  Selling: {usd.get('sellingRate', 'N/A')}\n\n"
            f"🇷🇺 <b>RUB (Russia)</b>\n"
            f"  Buying: {rub.get('buyingRate', 'N/A')} {rub_trend}\n"
            f"  Selling: {rub.get('sellingRate', 'N/A')}\n\n"
            f"🇪🇺 <b>EUR (European Union)</b>\n"
            f"  Buying: {eur.get('buyingRate', 'N/A')} {eur_trend}\n"
            f"  Selling: {eur.get('sellingRate', 'N/A')}\n"
        )

    async def send_rates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /rates command."""
        try:
            latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend = self.get_latest_rates()
            message = self.format_rates_message(latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend)
            await update.message.reply_text(message, parse_mode="HTML")
            logger.info(f"Rates sent to user {update.message.chat_id}.")
        except Exception as e:
            logger.exception(f"Failed to send rates to user {update.message.chat_id}: {e}")
            await update.message.reply_text("An error occurred. Please try again later.")

    async def send_hourly_rates(self, context: ContextTypes.DEFAULT_TYPE):
        """Send the hourly exchange rates to users whose timezone matches the current hour."""
        try:
            latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend = self.get_latest_rates()
            message = self.format_rates_message(latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend)

            # Get the current time in UTC
            now_utc = datetime.now(pytz.utc)

            # Fetch users whose timezone matches the current hour
            self.cursor.execute("SELECT chat_id, timezone FROM users")
            users = self.cursor.fetchall()
            for user in users:
                chat_id, timezone = user
                try:
                    tz = pytz.timezone(timezone)
                    now_local = now_utc.astimezone(tz)
                    if now_local.hour == 10 and now_local.minute == 0:  # Send at 10:00 in the user's timezone
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode="HTML"
                        )
                except Exception as e:
                    logger.error(f"Failed to send hourly rates to user {chat_id}: {e}")
            logger.info(f"Hourly rates sent to users.")
        except Exception as e:
            logger.error(f"Failed to send hourly rates: {e}")

    def start_scheduler(self):
        """Start the scheduler after the bot is running."""
        # Schedule send_hourly_rates to run every hour at the 10th minute
        self.application.job_queue.run_repeating(self.send_hourly_rates, interval=3600, first=10)

        # Schedule reload_exchange_rates to run every hour at the 5th minute
        self.application.job_queue.run_repeating(self.reload_exchange_rates, interval=3600, first=5)

        logger.info("Scheduler started.")

    def run(self):
        self.start_scheduler()
        self.application.run_polling()

if __name__ == "__main__":
    bot = ExchangeRateBot()
    bot.run()
