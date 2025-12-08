# 🚀 Proxmox Automation & Redeployment Portal

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![Flask](https://img.shields.io/badge/Framework-Flask-green) ![Proxmox](https://img.shields.io/badge/Platform-Proxmox_VE-orange) 

**A lightweight yet powerful Infrastructure-as-Code (IaC) Portal for Proxmox VE.**

This tool facilitates automated VM provisioning, script management, and—as its core feature—**VM redeployment while preserving persistent data** (Immutable Infrastructure Pattern). It effectively separates the Operating System (Ephemeral) from User Data (Persistent).

---

## 🔥 Key Features

### 🖥️ Smart Provisioning
* **Cloud-Init Integration:** Clone templates with full network configuration (User, SSH Keys, IP, Gateway) in seconds.
* **Custom Script Injection:** Inject post-install Bash scripts automatically via QEMU Guest Agent.

### 💾 Persistent Storage Engine
* **Auto-Data-Disk:** Automatically creates, formats, and mounts a secondary hard disk (`scsi1`) for data.
* **Immutable Redeployment:**
    * The OS disk (`scsi0`) is wiped/replaced with a fresh template.
    * The Data Disk (`scsi1`) is detached, saved, attached to the new VM, and physically moved.
    * Data is remounted automatically to the desired path (e.g., `/home` or `/var/www`).

### 🛡️ Fail-Safe Architecture ("Zombie Mode")
* **Atomic Operations:** If a disk move or cloning operation fails, the system halts.
* **Zombie State:** The old VM is renamed to `ZOMBIE-...` rather than deleted.
* **No Data Loss:** This ensures your data disk is never deleted accidentally if the migration fails.

### ⚡ Optimized Script Injection
* **Reliable Uploads:** Uses a chunking algorithm to upload large scripts via the QEMU Guest Agent, preventing timeouts and buffer overflows.
* **Batch Processing:** Support for uploading and assigning multiple scripts simultaneously.

---

## 📘 System Architecture & Workflows

This application consists of a **Python Flask Backend**, a **SQLite Database** for job management, and a web-based frontend.

### 1. Template Creation (Image Builder)
Before provisioning, a "Golden Image" is required.
1.  **Create VM:** Setup with VirtIO Network & SCSI Controller.
2.  **Import Disk:** Import a Cloud-Image (e.g., `ubuntu-22.04-cloud-image.qcow2`).
3.  **Cloud-Init:** Attach a Cloud-Init drive (`ide2`).
4.  **Convert:** Convert the VM into a Proxmox Template.

### 2. VM Provisioning (The Clone)
1.  User selects template and resources (CPU/RAM).
2.  **Network Config:** Injects IP/SSH keys via Cloud-Init.
3.  **Storage Setup:** Creates a secondary empty disk (`scsi1`) and generates a dynamic setup script to format/mount it on first boot.
4.  **Scripting:** Injects user-selected Bash scripts via QEMU Agent.

### 3. VM Redeployment (The Core Mechanism)
This allows replacing the OS while keeping data intact.

1.  **Snapshot:** Takes a safety snapshot of the old VM.
2.  **Clone:** Spins up a new VM from the updated template.
3.  **Resize:** Detects old OS disk size and adjusts the new VM to match.
4.  **Hardware Transfer:** Detaches `scsi1` (Data) from the Old VM -> Attaches to New VM.
5.  **Physical Move:** Moves the virtual disk file to the new VM's storage path.
    * *Strategy:* Toggles format (raw <-> qcow2) if necessary to force Proxmox to move files on local storage.
6.  **Smart Mount:** Auto-detects existing data and mounts it.
7.  **Cleanup:** The old VM is deleted **only** if all steps succeed. If not, it remains as a "ZOMBIE".

---

## ⚠️ Critical Warnings & Constraints

> [!WARNING]
> **Please read carefully before deploying in production.**

### 1. Storage Format (QCOW2 Required)
To utilize the Snapshot and Redeploy features effectively, your virtual machine disks must be in `.qcow2` format (especially when using directory-based storage like `local`).
* **Raw files (.raw):** Do not support internal snapshots efficiently.
* **ZFS/LVM-Thin:** Supported, but the redeploy logic is currently optimized for qcow2 file-based operations.

### 2. Snapshot Lifecycle
Snapshots are tied to the specific VM ID.
* **The Risk:** When you Redeploy, a **new VM ID** is created.
* **The Result:** History (Snapshots) of the old VM is lost. Only the current data on the persistent disk is carried over.

### 3. IP Management (No Validation)
Currently, there is no IP Address Management (IPAM) validation.
* **Risk:** You can assign an IP that is already in use (e.g., by a "Zombie" VM).
* **Result:** SSH Host Key Verification failures and routing issues.
* **Advice:** Use the "Cleanup" feature to remove Zombie VMs before reusing IPs.

### 4. CIDR Notation Mandatory
When defining IPs via API or Frontend, you **must** use CIDR notation.
* ❌ Wrong: `192.168.1.50`
* ✅ Right: `192.168.1.50/24`

---

## 📂 API Documentation

Detailed API requests and collections are located in the repository:

| Location | Description |
| :--- | :--- |
| `Proxmox-Tool/` | **Bruno Collection**: Import into [Bruno](https://www.usebruno.com/) for instant testing. |
| `Proxmox small/Befehle.txt` | **Curl Commands**: A raw text file with Curl examples. |

---

## ⚙️ Installation & Setup

It is recommended to use a Python Virtual Environment.

### 1. Clone & Prepare
```bash
git clone [https://github.com/CodeKotbes/Proxmox-Tool.git](https://github.com/CodeKotbes/Proxmox-Tool.git)
cd Proxmox-Tool

# Create Virtual Environment
python3 -m venv venv

# Activate (Linux/MacOS)
source venv/bin/activate
# Activate (Windows)
# venv\Scripts\activate
```

### 2. Install Dependencies 
```bash
pip install flask proxmoxer requests
```

### 3.Configuration 
```python
PROXMOX_HOST = "192.168.1.100"
PROXMOX_USER = "root@pam"
PROXMOX_PASSWORD = "your-password"
NODE_NAME = "pve"        # Name of your Proxmox Node
NAT_BRIDGE = "vmbr0"     # Your Network Bridge
```

### 4. Run
```bash
python3 main.py
```

The portal will be available at: http://(Your-Ip):5000
