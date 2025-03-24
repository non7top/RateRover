import json
import os
import sqlite3
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
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


class DatabaseHandler:
    """Handles all database operations."""

    def __init__(self, db_name: str = "users.db"):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self.init_db()

    def init_db(self):
        """Initialize the SQLite database to store user chat IDs, timezones, and currencies."""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.cursor = self.conn.cursor()

            # Create the users table if it doesn't exist
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    timezone TEXT DEFAULT 'Asia/Bangkok',
                    currencies TEXT DEFAULT 'USD,RUB,EUR',
                    timezone_offset INTEGER
                )
            """)
            self.conn.commit()
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.exception("Failed to initialize database.")
            raise


    def add_user(self, chat_id: int):
        """Add a user to the database if they don't already exist."""
        try:
            self.cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
            self.conn.commit()
            logger.info(f"User {chat_id} added to the database.")
        except Exception as e:
            logger.exception(f"Failed to add user {chat_id} to the database.")
            raise

    def update_timezone(self, chat_id: int, timezone: str):
        """Update the user's timezone."""
        try:
            self.cursor.execute("UPDATE users SET timezone = ? WHERE chat_id = ?", (timezone, chat_id))
            self.conn.commit()
            logger.info(f"User {chat_id} updated timezone to {timezone}.")
        except Exception as e:
            logger.exception(f"Failed to update timezone for user {chat_id}.")
            raise

    def update_currencies(self, chat_id: int, currencies: str):
        """Update the user's preferred currencies."""
        try:
            self.cursor.execute("UPDATE users SET currencies = ? WHERE chat_id = ?", (currencies, chat_id))
            self.conn.commit()
            logger.info(f"User {chat_id} updated currencies to {currencies}.")
        except Exception as e:
            logger.exception(f"Failed to update currencies for user {chat_id}.")
            raise

    def delete_user(self, chat_id: int):
        """Delete a user from the database."""
        try:
            self.cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
            self.conn.commit()
            logger.info(f"User {chat_id} deleted from the database.")
        except Exception as e:
            logger.exception(f"Failed to delete user {chat_id}.")
            raise

    def get_user(self, chat_id: int):
        """Get a user's data from the database."""
        try:
            self.cursor.execute("SELECT timezone, currencies FROM users WHERE chat_id = ?", (chat_id,))
            return self.cursor.fetchone()
        except Exception as e:
            logger.exception(f"Failed to fetch user {chat_id}.")
            raise

    def get_all_users(self):
        """Get all users from the database."""
        try:
            self.cursor.execute("SELECT chat_id, timezone, currencies, timezone_offset FROM users")
            return self.cursor.fetchall()
        except Exception as e:
            logger.exception("Failed to fetch all users.")
            raise


    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")


class ExchangeRateBot:
    def __init__(self):
        # Get the bot token from the environment variable
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            logger.error("TELEGRAM_BOT_TOKEN environment variable is not set.")
            raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable in the .env file.")

        # Initialize the bot application
        self.application = Application.builder().token(self.bot_token).post_init(self.post_init).build()

        # Initialize the database handler
        self.db_handler = DatabaseHandler()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("rates", self.send_rates))
        self.application.add_handler(CommandHandler("settimezone", self.set_timezone))
        self.application.add_handler(CommandHandler("unsubscribe", self.unsubscribe))
        self.application.add_handler(CommandHandler("listtimezones", self.list_timezones))
        self.application.add_handler(CommandHandler("setcurrencies", self.set_currencies))
        self.application.add_handler(CommandHandler("currencyrates", self.currency_rates))

        # Add a reply handler for the currency prompt
        self.application.add_handler(
            MessageHandler(filters.TEXT & filters.REPLY, self.handle_currency_reply)
        )

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
            ("currencyrates", "Get historical rates for a specific currency (e.g., /currencyrates USD)"),
        ])
        logger.info("Bot commands have been set up.")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /start command."""
        chat_id = update.message.chat_id

        # Save the user's chat ID to the database if not already present
        try:
            self.db_handler.add_user(chat_id)
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
            "Use /listtimezones to see all available timezones.\n"
            "Use /currencyrates to get historical rates for a specific currency (e.g., /currencyrates USD)."
        )

    async def set_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /settimezone command."""
        chat_id = update.message.chat_id
        timezone = context.args[0] if context.args else None

        if timezone and timezone in pytz.all_timezones:
            try:
                # Calculate the offset in hours (rounded to the nearest integer)
                tz = pytz.timezone(timezone)
                now = datetime.now(tz)
                offset = now.utcoffset().total_seconds() / 3600  # Convert to hours
                offset_int = int(round(offset))  # Round to the nearest integer

                # Update the database with the timezone and offset
                self.db_handler.update_timezone(chat_id, timezone)
                self.db_handler.cursor.execute(
                    "UPDATE users SET timezone_offset = ? WHERE chat_id = ?",
                    (offset_int, chat_id)
                )
                self.db_handler.conn.commit()

                await update.message.reply_text(f"Your timezone has been set to {timezone} (offset: UTC{offset_int:+d}).")
                logger.info(f"User {chat_id} set timezone to {timezone} (offset: UTC{offset_int:+d}).")
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
                self.db_handler.update_currencies(chat_id, currencies)
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
            self.db_handler.delete_user(chat_id)
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
            user = self.db_handler.get_user(chat_id)
            if not user:
                await update.message.reply_text("You are not subscribed. Use /start to subscribe.")
                return
            _, currencies = user

            latest_date, latest_rates, previous_rates = self.get_latest_rates()
            message = self.format_rates_message(latest_date, latest_rates, previous_rates, currencies)
            await update.message.reply_text(message, parse_mode="HTML")
            logger.info(f"Rates sent to user {chat_id}.")
        except Exception as e:
            logger.exception(f"Failed to send rates to user {chat_id}.")
            await update.message.reply_text("An error occurred. Please try again later.")

    async def currency_rates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /currencyrates command."""
        chat_id = update.message.chat_id
        currency = context.args[0].upper() if context.args else None

        if not currency:
            # Use force reply to prompt the user for a currency code
            await update.message.reply_text(
                "Please provide a currency code (e.g., USD, EUR, RUB):",
                reply_markup={"force_reply": True}  # Enable force reply
            )
            return

        # Process the currency code
        await self.process_currency_rates(update, context, currency)

    async def handle_currency_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the user's reply to the currency prompt."""
        chat_id = update.message.chat_id
        currency = update.message.text.upper()

        # Process the currency code
        await self.process_currency_rates(update, context, currency)

    async def process_currency_rates(self, update: Update, context: ContextTypes.DEFAULT_TYPE, currency: str):
        """Process the currency rates for the given currency."""
        chat_id = update.message.chat_id  # Extract chat_id from the update object

        try:
            # Get the last 10 records, spaced every two days
            sorted_dates = sorted(self.exchange_rates.keys(), reverse=True)
            selected_dates = []
            current_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d")

            for date in sorted_dates:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                if (current_date - date_obj).days % 2 == 0:
                    selected_dates.append(date)
                    if len(selected_dates) >= 10:
                        break

            # Extract buying rates for the selected dates
            buying_rates = []
            for date in selected_dates:
                rates = self.exchange_rates[date]["rates"]
                if currency in rates:
                    buying_rate = rates[currency].get("buyingRate", 0)
                    buying_rates.append((date, buying_rate))
                else:
                    buying_rates.append((date, None))  # Add None for missing data

            if not buying_rates:
                await update.message.reply_text(f"No data found for currency {currency}.")
                return

            # Filter out None values for min/max calculation
            valid_rates = [rate for _, rate in buying_rates if rate is not None]
            if not valid_rates:
                await update.message.reply_text(f"No valid rates found for currency {currency}.")
                return

            # Find the minimum and maximum buying rates
            min_rate = min(valid_rates)
            max_rate = max(valid_rates)

            # Prepare the bar graph
            message = f"📊 Historical rates for <b>{currency}</b> (last 10 records, every 2 days):\n\n"
            for date, rate in buying_rates:
                if rate is not None:
                    # Normalize the rate relative to the minimum rate
                    normalized_rate = rate - min_rate
                    max_normalized = max_rate - min_rate

                    # Scale the bar to a fixed width (e.g., 20 characters)
                    bar_length = int((normalized_rate / max_normalized) * 20) if max_normalized != 0 else 0
                    bar = "▉" * bar_length  # Use block character for the bar
                    message += f"📅 <b>{date}</b>\n  Buying Rate: {rate}\n  {bar}\n\n"
                else:
                    message += f"📅 <b>{date}</b>\n  No data for {currency}\n\n"

            await update.message.reply_text(message, parse_mode="HTML")
            logger.info(f"Currency rates sent to user {chat_id} for {currency}.")
        except Exception as e:
            logger.exception(f"Failed to send currency rates to user {chat_id}.")
            await update.message.reply_text("An error occurred. Please try again later.")

    async def send_daily_rates(self, context: ContextTypes.DEFAULT_TYPE):
        """Send the daily exchange rates to users whose local time is 10:00 AM."""
        try:
            latest_date, latest_rates, previous_rates = self.get_latest_rates()

            # Fetch all users
            users = self.db_handler.get_all_users()
            for user in users:
                chat_id, timezone, currencies, offset = user  # Include offset in the query
                try:
                    # Calculate the user's local time based on their integer offset
                    now_utc = datetime.utcnow()
                    user_local_time = now_utc + timedelta(hours=offset)

                    # Check if it's 10:00 AM in the user's local time
                    if user_local_time.hour == 10 and user_local_time.minute == 0:
                        message = self.format_rates_message(latest_date, latest_rates, previous_rates, currencies)
                        await self.application.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
                        logger.info(f"Daily rates sent to user {chat_id} in timezone {timezone} (offset: UTC{offset:+d}).")
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

    def __del__(self):
        """Clean up resources when the bot is shut down."""
        self.db_handler.close()
        logger.info("Bot shut down and resources cleaned up.")


if __name__ == "__main__":
    bot = ExchangeRateBot()
    bot.run()
