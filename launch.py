"""Run the local dashboard and open it in the default browser."""
import threading
import webbrowser

import uvicorn
from server import PORT, app

if __name__ == "__main__":
    opener = threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}"))
    opener.daemon = True
    opener.start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)
