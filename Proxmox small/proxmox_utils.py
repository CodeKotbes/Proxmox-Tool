import time
from proxmoxer import ProxmoxAPI
import config

def get_proxmox_api():
    """Establishes connection to Proxmox API."""
    try:
        return ProxmoxAPI(
            config.PVE_HOST, 
            port=config.PVE_PORT, 
            user=config.PVE_USER, 
            password=config.PVE_PASSWORD, 
            verify_ssl=False
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        return None

def delete_vm(node, vmid):
    """Attempts to delete a VM, catches errors if it doesn't exist."""
    try:
        try:
            node.qemu(vmid).status.stop.post()
            time.sleep(8) 
        except:
            pass 
        node.qemu(vmid).delete()
        return True
    except:
        return False

def find_vms_by_tag(proxmox, tag):
    """Returns a list of VMs that contain the specified tag."""
    vms = []
    for vm in proxmox.cluster.resources.get(type='vm'):
        if tag in vm.get('tags', '').split(';'):
            vms.append(vm)
    return vms