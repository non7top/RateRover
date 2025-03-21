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
        self.application.add_handler(CommandHandler("setcurrencies", self.set_currencies))

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
            ("setcurrencies", "Set your preferred currencies (e.g., /setcurrencies USD,RUB,EUR)"),
        ])
        logger.info("Bot commands have been set up.")

    def init_db(self):
        """Initialize the SQLite database to store user chat IDs, timezones, and currencies."""
        try:
            self.conn = sqlite3.connect("users.db")
            self.cursor = self.conn.cursor()

            # Create the users table if it doesn't exist
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    timezone TEXT DEFAULT 'Asia/Bangkok',
                    currencies TEXT DEFAULT 'USD,RUB,EUR'
                )
            """)
            self.conn.commit()
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.exception("Failed to initialize database.")
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
            logger.exception(f"Failed to save user {chat_id} to the database.")
            await update.message.reply_text("An error occurred. Please try again later.")
            return

        await update.message.reply_text(
            "Welcome! You will now receive daily exchange rates for your preferred currencies at 10 AM in your preferred timezone.\n\n"
            "Use /settimezone to set your timezone (e.g., /settimezone Asia/Bangkok).\n"
            "Use /setcurrencies to set your preferred currencies (e.g., /setcurrencies USD,RUB,EUR).\n"
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
                logger.exception(f"Failed to update timezone for user {chat_id}.")
                await update.message.reply_text("An error occurred. Please try again later.")
        else:
            await update.message.reply_text("Invalid timezone. Please provide a valid timezone (e.g., /settimezone Asia/Bangkok).")

    async def set_currencies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /setcurrencies command."""
        chat_id = update.message.chat_id
        currencies = context.args[0] if context.args else None

        if currencies:
            try:
                # Validate currencies (e.g., check if they exist in the rates data)
                self.cursor.execute("UPDATE users SET currencies = ? WHERE chat_id = ?", (currencies, chat_id))
                self.conn.commit()
                await update.message.reply_text(f"Your preferred currencies have been set to {currencies}.")
                logger.info(f"User {chat_id} set currencies to {currencies}.")
            except Exception as e:
                logger.exception(f"Failed to update currencies for user {chat_id}.")
                await update.message.reply_text("An error occurred. Please try again later.")
        else:
            await update.message.reply_text("Invalid currencies. Please provide a comma-separated list (e.g., /setcurrencies USD,RUB,EUR).")

    async def unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /unsubscribe command."""
        chat_id = update.message.chat_id

        try:
            # Delete the user from the database
            self.cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
            self.conn.commit()
            await update.message.reply_text("You have been unsubscribed from daily updates.")
            logger.info(f"User {chat_id} unsubscribed and removed from the database.")
        except Exception as e:
            logger.exception(f"Failed to unsubscribe user {chat_id}.")
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
            logger.exception("Failed to load exchange rates.")
            raise

    async def reload_exchange_rates(self, context: ContextTypes.DEFAULT_TYPE):
        """Reload the exchange rates from the JSON file."""
        try:
            self.exchange_rates = self.load_exchange_rates()
            logger.info(f"Exchange rates reloaded at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            logger.exception("Failed to reload exchange rates.")

    def get_latest_rates(self):
        """Get the latest date and rates for USD, RUB, and EUR."""
        try:
            # Get the latest date (assuming the JSON is sorted by date)
            sorted_dates = sorted(self.exchange_rates.keys(), reverse=True)
            latest_date = sorted_dates[0]
            previous_date = sorted_dates[1] if len(sorted_dates) > 1 else None

            latest_rates = self.exchange_rates[latest_date]["rates"]
            previous_rates = self.exchange_rates[previous_date]["rates"] if previous_date else None

            return latest_date, latest_rates, previous_rates
        except Exception as e:
            logger.exception("Failed to get latest rates.")
            raise

    def format_rates_message(self, latest_date, latest_rates, previous_rates, currencies):
        """Format the exchange rates into a message."""
        message = f"📅 Latest rates as of <b>{latest_date}</b>:\n\n"
        for currency in currencies.split(","):
            if currency in latest_rates:
                current_rate = latest_rates[currency].get("buyingRate", "N/A")
                previous_rate = previous_rates.get(currency, {}).get("buyingRate", "N/A") if previous_rates else "N/A"
                trend = ""
                if previous_rate != "N/A":
                    if current_rate > previous_rate:
                        trend = '↑ 💹'
                    elif current_rate < previous_rate:
                        trend = '↓ ❌'
                message += (
                    f"🇺🇸 <b>{currency}</b>\n"
                    f"  Buying: {current_rate} {trend}\n"
                    f"  Selling: {latest_rates[currency].get('sellingRate', 'N/A')}\n\n"
                )
        return message

    async def send_rates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /rates command."""
        chat_id = update.message.chat_id
        try:
            # Get user's preferred currencies
            self.cursor.execute("SELECT currencies FROM users WHERE chat_id = ?", (chat_id,))
            user = self.cursor.fetchone()
            if not user:
                await update.message.reply_text("You are not subscribed. Use /start to subscribe.")
                return
            currencies = user[0]

            latest_date, latest_rates, previous_rates = self.get_latest_rates()
            message = self.format_rates_message(latest_date, latest_rates, previous_rates, currencies)
            await update.message.reply_text(message, parse_mode="HTML")
            logger.info(f"Rates sent to user {chat_id}.")
        except Exception as e:
            logger.exception(f"Failed to send rates to user {chat_id}.")
            await update.message.reply_text("An error occurred. Please try again later.")

    async def send_daily_rates(self, context: ContextTypes.DEFAULT_TYPE):
        """Send the daily exchange rates to users whose local time is 10:00 AM."""
        try:
            latest_date, latest_rates, previous_rates = self.get_latest_rates()

            # Fetch all users
            self.cursor.execute("SELECT chat_id, timezone, currencies FROM users")
            users = self.cursor.fetchall()
            for user in users:
                chat_id, timezone, currencies = user
                try:
                    # Get the current time in the user's timezone
                    user_tz = pytz.timezone(timezone)
                    now_local = datetime.now(user_tz)

                    # Check if it's 10:00 AM in the user's timezone
                    if now_local.hour == 10 and now_local.minute == 0:
                        message = self.format_rates_message(latest_date, latest_rates, previous_rates, currencies)
                        await self.application.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
                        logger.info(f"Daily rates sent to user {chat_id} in timezone {timezone}.")
                except Exception as e:
                    logger.exception(f"Failed to send daily rates to user {chat_id}.")
        except Exception as e:
            logger.exception("Failed to send daily rates.")

    def start_scheduler(self):
        """Start the scheduler after the bot is running."""
        # Schedule send_daily_rates to run every hour
        self.application.job_queue.run_repeating(self.send_daily_rates, interval=3600)

        # Schedule reload_exchange_rates to run every hour at the 5th minute
        self.application.job_queue.run_repeating(self.reload_exchange_rates, interval=3600, first=300)

        logger.info("Scheduler started.")

    def run(self):
        self.start_scheduler()
        self.application.run_polling()

if __name__ == "__main__":
    bot = ExchangeRateBot()
    bot.run()
