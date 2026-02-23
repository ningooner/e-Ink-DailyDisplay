# PaperDeck Firmware Configuration
# Copy this file to config.py and fill in your values.
# config.py is gitignored — never commit real credentials.

WIFI_SSID     = "YourNetworkName"
WIFI_PASSWORD = "YourPassword"

# cribbbserver LAN IP (use this when on home network)
API_BASE = "http://192.168.1.220:8765"

# How often (seconds) to poll /status for changes
POLL_INTERVAL_S = 2

# Force a full display refresh every N seconds to clear greyscale ghosting
FORCE_FULL_INTERVAL_S = 3600  # 60 minutes
