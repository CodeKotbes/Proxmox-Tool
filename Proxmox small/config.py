# --- PROXMOX CONNECTION CONFIG ---
PVE_HOST = "localhost"
PVE_PORT = 8006
PVE_USER = "root@pam"
PVE_PASSWORD = "proxmox"
NODE_NAME = "server-proxmox"

# --- NETWORKING CONFIG ---
NAT_BRIDGE = "vmbr1"

# --- FALLBACK CREDENTIALS FOR VMS ---
DEFAULT_USER = "ubuntu"
DEFAULT_PASS = "ubuntu" 
DEFAULT_SSH_KEY = ""