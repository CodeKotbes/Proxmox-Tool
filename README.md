# 🚀 Proxmox Automation & Redeployment Portal

![Python](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.0+-green?style=for-the-badge&logo=flask&logoColor=white)
![Proxmox](https://img.shields.io/badge/Proxmox-VE-E57000?style=for-the-badge&logo=proxmox&logoColor=white)

A **Infrastructure-as-Code (IaC) Portal** for Proxmox VE.
It enables automated VM provisioning, script management, and—as its core feature—**VM redeployment while preserving persistent data** (Immutable Infrastructure Pattern).

---

## 🔥 Key Features

### 🖥️ Smart Provisioning
* **Cloud-Init Integration:** Clone templates with full network configuration (User, SSH Keys, IP, Gateway) in seconds.
* **Custom Scripts:** Inject post-install scripts (Bash) automatically via QEMU Guest Agent.

### 💾 Persistent Storage Engine
* **Auto-Data-Disk:** Automatically creates and formats a secondary hard disk (`scsi1`) for data.
* **Redeploy Mechanism:**
    1.  The OS disk (`scsi0`) is wiped and replaced with a fresh template.
    2.  The **Data Disk is detached**, saved, attached to the new VM, and physically moved.
    3.  Data is remounted automatically to the desired path (e.g., `/home` or `/var/www`).

### 🛡️ Fail-Safe Architecture
* **Zombie Mode:** If a disk move or cloning operation fails, the system **stops** the process and renames the old VM to `ZOMBIE-...`.
* **No Data Loss:** The old VM is kept alive to ensure your data disk is never deleted accidentally.

### ⚡ Script Injection
* **Reliable Upload:** Uses a chunking algorithm to upload large scripts via the QEMU Guest Agent without timeouts or buffer overflows.
* **Batch Processing:** Upload and assign multiple scripts at once.

---

## ⚠️ Critical Warnings & Constraints

> [!WARNING]
> Please read these points carefully before deploying in a production environment.

### 1. 🛑 Duplicate IPs & No Validation
Currently, there is **no validation** to check if an IP address is already assigned to another active VM.
* **The Risk:** You can accidentally assign the same static IP to multiple VMs (e.g., a "Zombie" VM and a new live VM).
* **The Consequence:** **SSH connections will fail** ("Host key verification failed") because the network router cannot distinguish between the VMs.
* **Advice:** Always ensure old/zombie VMs are stopped or deleted via the "Cleanup" feature before starting a new one with the same IP.

### 2. 🌐 Subnet Mask (CIDR)
When defining the IP address (Frontend or API), the **subnet mask is mandatory**.
* ❌ Wrong: `192.168.1.50`
* ✅ Right: `192.168.1.50/24`
* *Without the CIDR suffix, Cloud-Init will fail to configure the network interface.*

### 3. 🔙 Rollback Function (Beta)
The **Rollback** feature (`/api/rollback`) is currently experimental. Depending on your storage backend (especially `local` storage with `.raw` files), snapshots might not work reliably.

---

## 📂 API Documentation

To keep this README clean, the detailed API requests are provided in separate files within this repository.

---

## ⚙️ Installation & Setup

### 1. Clone & Install
```bash
git clone [https://github.com/YourRepo/Proxmox-Portal.git](https://github.com/YourRepo/Proxmox-Portal.git)
cd Proxmox-Portal
pip install flask proxmoxer requests