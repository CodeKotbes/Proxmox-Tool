import time
import subprocess
import argparse
import sys
from proxmoxer import ProxmoxAPI

PVE_HOST = "localhost"
PVE_PORT = 8006
PVE_USER = "root@pam"
PVE_PASSWORD = "proxmox"
NODE_NAME = "server-proxmox" 

def connect_pve():
    print(f"Connecting to Proxmox at {PVE_HOST}:{PVE_PORT}...")
    try:
        proxmox = ProxmoxAPI(
            PVE_HOST, port=PVE_PORT, user=PVE_USER,
            password=PVE_PASSWORD, verify_ssl=False
        )
        print("Connection successful.")
        return proxmox
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

def customize_image(image_path):
    try:
        command = [
            "virt-customize",
            "-a", image_path,
            "--install", "qemu-guest-agent"
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print("Error: 'virt-customize' not found.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error during virt-customize: {e.stderr}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Proxmox Template Creator")
    parser.add_argument("--vmid", required=True, type=int, help="The VMID for the new template (e.g., 9000)")
    parser.add_argument("--name", required=True, help="The name for the new template (e.g., 'ubuntu-2204-v1')")
    parser.add_argument("--image", required=True, help="Path to the .qcow2 image (e.g., '/var/lib/vz/template/iso/ubuntu-22.04-cloud.qcow2')")
    parser.add_argument("--storage", default="local", help="The storage pool (default: 'local')")
    args = parser.parse_args()

    TEMPLATE_VMID = args.vmid
    TEMPLATE_NAME = args.name
    UBUNTU_IMAGE_PATH = args.image
    STORAGE_POOL = args.storage

    print(f"--- Creating Template {TEMPLATE_NAME} (VMID {TEMPLATE_VMID}) ---")
    
    customize_image(UBUNTU_IMAGE_PATH)

    proxmox = connect_pve()
    node = proxmox.nodes(NODE_NAME)

    try:
        node.qemu.post(
            vmid=TEMPLATE_VMID,
            name=TEMPLATE_NAME,
            memory=2048, 
            net0="virtio,bridge=vmbr0", 
            scsihw="virtio-scsi-pci", 
            ostype="l26", 
            agent=1
        )
        time.sleep(3) 
    except Exception as e:
        print(f"Error creating VM: {e}")
        sys.exit(1)

    print(f"Importing {UBUNTU_IMAGE_PATH} to {STORAGE_POOL} as scsi0...")
    try:
        node.qemu(TEMPLATE_VMID).config.post(
            scsi0=f"{STORAGE_POOL}:0,import-from={UBUNTU_IMAGE_PATH}"
        )
        time.sleep(30) 
    except Exception as e:
        print(f"Error importing disk: {e}")
        node.qemu(TEMPLATE_VMID).delete()
        print("Cleaning up: VM deleted.")
        sys.exit(1)

    try:
        node.qemu(TEMPLATE_VMID).config.post(
            ide2=f"{STORAGE_POOL}:cloudinit"
        )
        time.sleep(2)
        node.qemu(TEMPLATE_VMID).config.post(
            boot="order=scsi0"
        )
        time.sleep(2)
    except Exception as e:
        print(f"Error configuring Cloud-Init: {e}")
        sys.exit(1)

    try:
        node.qemu(TEMPLATE_VMID).template.post()
    except Exception as e:
        print(f"Error converting to template: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()