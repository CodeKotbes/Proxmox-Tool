# 🚀 Proxmox Automation & Redeployment Portal

![Python](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.0+-green?style=for-the-badge&logo=flask&logoColor=white)
![Proxmox](https://img.shields.io/badge/Proxmox-VE-E57000?style=for-the-badge&logo=proxmox&logoColor=white)

A lightweight yet powerful **Infrastructure-as-Code (IaC) Portal** for Proxmox VE.
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

## 📘 Functional Description & System Architecture

This application consists of a **Python Flask Backend**, a **SQLite Database** for script/job management, and a modern **Web Frontend**.

### 1. Core Workflows

#### A. Template Creation (Image Builder)
Before provisioning, the system needs a standardized "Golden Image".
* **Prerequisite:** A Cloud-Image (e.g., `ubuntu-22.04-cloud-image.qcow2`) on the Proxmox storage.
* **Process:**
    1.  **VM Shell:** Creates a VM with optimized hardware settings (VirtIO Network & SCSI).
    2.  **Disk Import:** Imports the image file as the system disk (`scsi0`).
    3.  **Cloud-Init:** Automatically attaches a Cloud-Init drive (`ide2`) to allow parameter injection later.
    4.  **Conversion:** Converts the VM into a Proxmox Template.

#### B. VM Provisioning (Clone)
Creates a new VM based on a template.
* **Process:**
    1.  User selects a template and resources (CPU, RAM).
    2.  **Network Config:** Sets Cloud-Init parameters (IP, SSH Keys, User).
    3.  **Persistent Storage (Optional):**
        * If requested, a **second empty disk** (`scsi1`) is created.
        * A dynamic setup script is generated to format and mount this disk on the first boot (e.g., to `/home`).
    4.  **Setup Scripts:** Selected Bash scripts are injected and executed via QEMU Guest Agent.

#### C. VM Redeployment (Update & Data Persistence)
The heart of the application. Allows replacing the OS while keeping data.
* **The Fail-Safe Process:**
    1.  **Identification:** Finds all VMs matching the provided `old_tag`.
    2.  **Safety Snapshot:** Automatically takes a snapshot of the old VM.
    3.  **Clone:** Creates a new VM from the (potentially updated) template.
    4.  **OS Restore:** Detects the size of the old OS disk and resizes the new VM's disk to match.
    5.  **Hardware Transfer:** Detaches the Data Disk (`scsi1`) from the old VM and attaches it to the new one.
    6.  **Fail-Safe Move:** Physically moves the disk file to the new VM's folder (`move_disk`).
        * *Technical Trick:* Toggles the format (`raw` <-> `qcow2`) to force Proxmox to move the file even on local storage.
        * *Safety:* If this fails, the process aborts, and the old VM remains as a "ZOMBIE".
    7.  **Smart Mounting:** A dynamic script mounts the rescued disk. It auto-detects existing data and syncs it if necessary.
    8.  **Cleanup:** The old VM is only deleted if all steps succeed.

#### D. Maintenance & Self-Healing
* **Manual Snapshots:** Create restore points via API.
* **Rollback:** Revert a VM to a previous snapshot state.
* **Garbage Collection:** A specific task searches for failed deployments (marked by tags like `move-failed` and names like `ZOMBIE-...`) and safely deletes them if they are stopped.

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

| Location | Description |
| :--- | :--- |
| **[`Proxmox-Tool/`](./ProxmoxTool/)** | This folder contains the **Bruno Collection**. Import it into the [Bruno API Client](https://usebruno.com/) for instant testing. |
| **[`Proxmox small/Befehle.txt`](./Proxmox%20small/Befehle.txt)** | A text file containing all **Curl commands** for terminal usage. |

---

## ⚙️ Installation & Setup

It is recommended to run the application within a Python virtual environment to keep dependencies clean.

### 1. Clone & Prepare Environment
```bash
# Repository klonen
git clone [https://github.com/CodeKotbes/Proxmox-Tool.git](https://github.com/CodeKotbes/Proxmox-Tool.git)
cd Proxmox-Tool

# Create Virtual Environment
python3 -m venv venv

# Activate Environment
# On Linux/MacOS:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate
