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
        self.application.add_handler(CommandHandler("rates", self.send_rates))  # Add /rates handler

        # Initialize the database
        self.init_db()

        # Initialize the scheduler
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Bangkok"))

        # Load exchange rates initially
        self.exchange_rates = self.load_exchange_rates()

    async def post_init(self, application: Application):
        """Set up bot commands using set_my_commands."""
        await application.bot.set_my_commands([
            ("start", "Start the bot and subscribe to daily rates"),
            ("rates", "Get the latest exchange rates"),
        ])
        logger.info("Bot commands have been set up.")

    def init_db(self):
        """Initialize the SQLite database to store user chat IDs."""
        try:
            self.conn = sqlite3.connect("users.db")
            self.cursor = self.conn.cursor()
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY
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
            "Welcome! You will now receive daily exchange rates for USD, RUB, and EUR at 10 AM Bangkok time.\n\n"
            "Use /rates to get the latest exchange rates at any time."
        )

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

    async def reload_exchange_rates(self, *args):
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

    async def send_daily_rates(self, *args):
        """Send the daily exchange rates to all registered users."""
        try:
            latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend = self.get_latest_rates()
            message = self.format_rates_message(latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend)

            self.cursor.execute("SELECT chat_id FROM users")
            users = self.cursor.fetchall()
            for user in users:
                chat_id = user[0]
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML"  # Enable HTML formatting
                )
            logger.info(f"Daily rates sent to {len(users)} users.")
        except Exception as e:
            logger.error(f"Failed to send daily rates: {e}")

    def start_scheduler(self):
        """Start the scheduler after the bot is running."""
        self.application.job_queue.run_repeating(self.send_daily_rates, interval=600, first=10)
        self.application.job_queue.run_repeating(self.reload_exchange_rates, interval=1800, first=5)
        logger.info("Scheduler started.")

    def run(self):
        self.start_scheduler()
        self.application.run_polling()

if __name__ == "__main__":
    bot = ExchangeRateBot()
    bot.run()
