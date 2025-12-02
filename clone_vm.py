import time
import urllib.parse
from proxmoxer import ProxmoxAPI

PVE_HOST = "localhost"
PVE_PORT = 8080
PVE_USER = "root@pam"
PVE_PASSWORD = "proxmox"
NODE_NAME = "server-proxmox" 
TEMPLATE_VMID = 9000         
NEW_VM_ID = 105
NEW_VM_NAME = "clone5"
NEW_VM_MEMORY = 1024 
NEW_VM_CORES = 1     
SSH_PUBLIC_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCywGwdfsM6zvdvvl0e6Z6YTXO19O3L8kQlnYObwbxFr25FOJIlNZutgFgWyQ1HnQrtZxpwpE3pWGRJ3SG1O2E/kY+R8B8TfTq+Hk7nSiWu1XHcSS9iVImSc1WueFo32Q5kyOIPWk7BZPsXOaIEBKZAVZgHpKcEAdTr9buO2JYwv/77ZHDSwBH4NL9wILDA9Lrn7VzDTd7trARTuUAq05S4/0vljNpzXSukWGvxAGtqyoWr35ntdvImoCzb1UAAyFkADu6B1T6pO4bpzRW2zt92nIJGMe2BvvgDwdsTFOUBz0VoTHgvha1uDv74vWyWytAasuWYCP3F7EinLD3AaU9H3Zd7VfwELqfL67zxEQTsxxl4KXNBifACANViPizaNojI8AdfDcnV5umYyAg5PLdsSoUWL/woUc5Zwi0LshuudI0IxmUejsfLm1nJ7hlKFdXu6ofI37NEVHYGq39VJlTVjovmdMJBwJgMw2rNXrJdR24C2VWlrkyz2IgjtnqlZQs= lehmbergs@SIT-SMBP-P9RKDY"
SSH_PUBLIC_KEY_ENCODED = urllib.parse.quote(SSH_PUBLIC_KEY, safe="")
CI_USER = "ubuntu" 
CI_PASSWORD = "ubuntu"
CURRENT_TEMPLATE_TAG = "template-ubuntu-2204-v1"

print(f"Connecting to Proxmox at {PVE_HOST}:{PVE_PORT}...")
proxmox = ProxmoxAPI(
    PVE_HOST, port=PVE_PORT, user=PVE_USER,
    password=PVE_PASSWORD, verify_ssl=False
)
print("Connection successful.")
node = proxmox.nodes(NODE_NAME)

try:
    node.qemu(TEMPLATE_VMID).clone.post(newid=NEW_VM_ID, name=NEW_VM_NAME)
    time.sleep(15) 
except Exception as e:
    print(f"Error during clone: {e}")
    exit(1)

node.qemu(NEW_VM_ID).config.post(memory=NEW_VM_MEMORY, cores=NEW_VM_CORES)
time.sleep(3)

print(f"Configuring Cloud-Init for user '{CI_USER}'...")
try:
    node.qemu(NEW_VM_ID).config.post(
        ciuser=CI_USER,
        cipassword=CI_PASSWORD, 
        sshkeys=SSH_PUBLIC_KEY_ENCODED,   
        ipconfig0="ip=dhcp,ip6=dhcp",
        tags=CURRENT_TEMPLATE_TAG,
        net0="virtio,bridge=vmbr1"
    )
    time.sleep(3)
except Exception as e:
    print(f"Error configuring Cloud-Init: {e}")

try:
    node.qemu(NEW_VM_ID).status.start.post()
except Exception as e:
    print(f"Error starting VM: {e}")