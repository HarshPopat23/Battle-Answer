import json
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

class BookingFixtureHandler(BaseHTTPRequestHandler):
    bookings = []
    logs = []
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        msg = f"{self.command} {self.path} - {format % args}"
        self.logs.append({"time": time.time(), "msg": msg})

    def send_data(self, status, content, mime="text/html; charset=utf-8"):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        self.logs.append({"time": time.time(), "method": "GET", "path": self.path})
        if self.path in ("/", "/index.html"):
            html = """<!DOCTYPE html>
<html>
<head><title>Booking Form</title></head>
<body>
  <h1>Booking Form</h1>
  <form id="booking-form" onsubmit="return false;">
    <label for="name">Name:</label>
    <input type="text" id="name" name="name" aria-label="Name" placeholder="Enter name">
    <br><br>
    <label for="slot">Slot:</label>
    <input type="text" id="slot" name="slot" aria-label="Slot" placeholder="Enter slot">
    <br><br>
    <button type="button" id="save" aria-label="Save booking" onclick="saveBooking()">Save booking</button>
  </form>
  <div id="status" style="margin-top:20px; font-weight:bold;">Initial Status: Ready</div>
  <script>
    async function saveBooking() {
      const name = document.getElementById('name').value;
      const slot = document.getElementById('slot').value;
      const resp = await fetch('/bookings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, slot: slot})
      });
      if (resp.ok) {
        document.getElementById('status').textContent = 'Booking Confirmed: ' + name + ' for ' + slot;
      } else {
        document.getElementById('status').textContent = 'Submission Failed';
      }
    }
  </script>
</body>
</html>"""
            self.send_data(200, html)
        elif self.path == "/state":
            data = {"bookings": self.bookings, "count": len(self.bookings)}
            self.send_data(200, json.dumps(data), "application/json; charset=utf-8")
        elif self.path == "/logs":
            self.send_data(200, json.dumps(self.logs), "application/json; charset=utf-8")
        else:
            self.send_data(404, "Not Found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self.logs.append({"time": time.time(), "method": "POST", "path": self.path, "body": body.decode("utf-8", errors="replace")})
        if self.path == "/bookings":
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {"raw": body.decode("utf-8", errors="replace")}
            self.bookings.append(data)
            self.send_data(200, json.dumps({"ok": True, "booking": data, "count": len(self.bookings)}), "application/json; charset=utf-8")
        else:
            self.send_data(404, "Not Found", "text/plain")

if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8910), BookingFixtureHandler)
    print("Fixture running on http://127.0.0.1:8910", flush=True)
    server.serve_forever()
