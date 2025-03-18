import requests
import base64
import re
import json
import os
from datetime import datetime, timedelta
import fcntl  # For Unix-based systems
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("exchange_rate_script.log"),  # Log to a file
        logging.StreamHandler()  # Log to console
    ]
)
logger = logging.getLogger(__name__)

class ExchangeRateStorage:
    def __init__(self, file_path="exchange_rates.json"):
        self.file_path = file_path
        # Create the file if it doesn't exist
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w') as file:
                json.dump({}, file)
            logger.info(f"Created new file: {self.file_path}")

    def _acquire_lock(self, file):
        """Acquire an exclusive lock on the file."""
        fcntl.flock(file, fcntl.LOCK_EX)  # Exclusive lock for writing
        logger.debug("File lock acquired.")

    def _release_lock(self, file):
        """Release the lock on the file."""
        fcntl.flock(file, fcntl.LOCK_UN)  # Unlock the file
        logger.debug("File lock released.")

    def load_data(self):
        """Load data from the file."""
        logger.info("Loading data from file...")
        with open(self.file_path, 'r') as file:
            try:
                data = json.load(file)
                logger.info("Data loaded successfully.")
            except json.JSONDecodeError:
                logger.warning("File is empty or corrupted. Starting with an empty dataset.")
                data = {}
        return data

    def save_data(self, data):
        """Save data to the file, ensuring only one process writes at a time."""
        logger.info("Saving data to file...")
        with open(self.file_path, 'w') as file:
            self._acquire_lock(file)  # Lock the file for writing
            try:
                json.dump(data, file, indent=4)
                logger.info(f"Data saved successfully to {self.file_path}.")
            finally:
                self._release_lock(file)  # Release the lock

    def update_or_add_record(self, new_record):
        """Update the record for the current day or add a new record."""
        data = self.load_data()

        # Get today's date in ISO format (e.g., "2023-10-25")
        today = datetime.now().date().isoformat()
        logger.info(f"Updating or adding record for date: {today}")

        # Update or add the record for today
        data[today] = new_record

        # Remove entries older than 14 days
        cutoff_date = datetime.now() - timedelta(days=14)
        data = {k: v for k, v in data.items() if datetime.fromisoformat(k).date() >= cutoff_date.date()}

        self.save_data(data)


class SuperrichAPI:
    def __init__(self, js_url, api_url):
        self.js_url = js_url
        self.api_url = api_url
        self.username = None
        self.password = None
        self.data = None

    def fetch_js_file(self):
        """Fetch the JavaScript file from the provided URL."""
        logger.info("Fetching JavaScript file...")
        response = requests.get(self.js_url)
        if response.status_code != 200:
            logger.error(f"Failed to fetch JavaScript file. Status code: {response.status_code}")
            raise Exception(f"Failed to fetch JavaScript file. Status code: {response.status_code}")
        logger.info("JavaScript file fetched successfully.")
        return response.text

    def extract_basic_auth(self, js_content):
        """Extract the Basic authorization string from the JavaScript content."""
        logger.info("Extracting Basic authorization string...")
        basic_auth_pattern = r'Authorization:\s*"Basic\s*([^"]+)"'
        match = re.search(basic_auth_pattern, js_content)
        if not match:
            logger.error("Failed to extract Basic authorization string from the JavaScript file.")
            raise Exception("Failed to extract Basic authorization string from the JavaScript file.")
        logger.info("Basic authorization string extracted successfully.")
        return match.group(1)

    def decode_basic_auth(self, encoded_auth):
        """Decode the Base64-encoded Basic authorization string."""
        logger.info("Decoding Basic authorization string...")
        decoded_auth = base64.b64decode(encoded_auth).decode('utf-8')
        self.username, self.password = decoded_auth.split(':')
        logger.info("Basic authorization string decoded successfully.")

    def make_api_request(self):
        """Make an API request using the extracted Basic authorization."""
        if not self.username or not self.password:
            logger.error("Username and password are not set. Call `decode_basic_auth` first.")
            raise Exception("Username and password are not set. Call `decode_basic_auth` first.")

        auth = (self.username, self.password)
        headers = {
            "Content-Type": "application/json"
        }

        logger.info("Making API request to fetch exchange rates...")
        response = requests.get(self.api_url, auth=auth, headers=headers)
        if response.status_code == 200:
            self.data = response.json()
            logger.info("API request successful. Exchange rates fetched.")
        else:
            logger.error(f"API request failed. Status code: {response.status_code}\nResponse: {response.text}")
            raise Exception(f"API request failed. Status code: {response.status_code}\nResponse: {response.text}")

    def extract_all_rates(self):
        """Extract exchange rates for all currencies."""
        if not self.data:
            logger.error("No data available. Call `make_api_request` first.")
            raise Exception("No data available. Call `make_api_request` first.")

        logger.info("Extracting exchange rates for all currencies...")
        rates = {}
        for item in self.data['data']['exchangeRate']:
            currency = item['cUnit']
            rates[currency] = {
                'countryName': item['countryName'],
                'buyingRate': item['rate'][0]['cBuying'],
                'sellingRate': item['rate'][0]['cSelling']
            }
        logger.info("Exchange rates extracted successfully.")
        return rates

    def store_results(self, rates):
        """Store the results in a file."""
        logger.info("Storing results in file...")
        storage = ExchangeRateStorage()
        storage.update_or_add_record({
            "timestamp": datetime.now().isoformat(),  # Add a timestamp
            "rates": rates
        })
        logger.info("Results stored successfully.")

    def run(self):
        """Run the entire process: fetch JS, extract auth, decode, make API request, and store results."""
        try:
            logger.info("Starting script...")

            # Step 1: Fetch the JavaScript file
            js_content = self.fetch_js_file()

            # Step 2: Extract the Basic authorization string
            encoded_auth = self.extract_basic_auth(js_content)

            # Step 3: Decode the Basic authorization string
            self.decode_basic_auth(encoded_auth)

            # Step 4: Make the API request
            self.make_api_request()

            # Step 5: Extract rates for all currencies
            rates = self.extract_all_rates()

            # Step 6: Store the results
            self.store_results(rates)

            logger.info("Script completed successfully.")

        except Exception as e:
            logger.exception(f"Script failed with error: {e}")


# Example usage
if __name__ == "__main__":
    # URLs
    js_url = "https://www.superrichthailand.com/app.min.js"
    api_url = "https://www.superrichthailand.com/api/v1/rates"

    # Create an instance of the SuperrichAPI class
    superrich_api = SuperrichAPI(js_url, api_url)

    # Run the entire process
    superrich_api.run()
