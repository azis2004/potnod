from flask import Flask
import threading
import subprocess
import time
import sys
import os

app = Flask(__name__)

def run_bot():
    while True:
        try:
            print("Running vsphone_autoreff.py...")
            subprocess.run([sys.executable, "vsphone_autoreff.py"])
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(10)

@app.route('/')
def home():
    return "VSPhone Bot is RUNNING!"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
