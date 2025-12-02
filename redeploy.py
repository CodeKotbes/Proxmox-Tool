import time
import urllib.parse
import sys
import argparse  
from proxmoxer import ProxmoxAPI

PVE_HOST = "localhost"
PVE_PORT = 8080
PVE_USER = "root@pam"
PVE_PASSWORD = "proxmox"
NODE_NAME = "server-proxmox" 
SSH_PUBLIC_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCywGwdfsM6zvdvvl0e6Z6YTXO19O3L8kQlnYObwbxFr25FOJIlNZutgFgWyQ1HnQrtZxpwpE3pWGRJ3SG1O2E/kY+R8B8TfTq+Hk7nSiWu1XHcSS9iVImSc1WueFo32Q5kyOIPWk7BZPsXOaIEBKZAVZgHpKcEAdTr9buO2JYwv/77ZHDSwBH4NL9wILDA9Lrn7VzDTd7trARTuUAq05S4/0vljNpzXSukWGvxAGtqyoWr35ntdvImoCzb1UAAyFkADu6B1T6pO4bpzRW2zt92nIJGMe2BvvgDwdsTFOUBz0VoTHgvha1uDv74vWyWytAasuWYCP3F7EinLD3AaU9H3Zd7VfwELqfL67zxEQTsxxl4KXNBifACANViPizaNojI8AdfDcnV5umYyAg5PLdsSoUWL/woUc5Zwi0LshuudI0IxmUejsfLm1nJ7hlKFdXu6ofI3TNEVHYGq39VJlTVjovmdMJBwJgMw2rNXrJdR24C2VWlrkyz2IgjtnqlZQs= lehmbergs@SIT-SMBP-P9RKDY"
SSH_PUBLIC_KEY_ENCODED = urllib.parse.quote(SSH_PUBLIC_KEY, safe="")
CI_USER = "ubuntu" 
CI_PASSWORD = "ubuntu"

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

def find_vms_by_tag(proxmox, tag):
    vms_to_redeploy = []
    try:
        resources = proxmox.cluster.resources.get(type='vm')
        for vm in resources:
            vm_tags = vm.get('tags', '')
            if tag in vm_tags.split(';'):
                print(f"  -> Found: {vm['name']} (VMID {vm['vmid']})")
                vms_to_redeploy.append(vm)
        
        if not vms_to_redeploy:
            print("No VMs found with this tag.")
        return vms_to_redeploy
    except Exception as e:
        print(f"Error searching for VMs: {e}")
        return []

def create_replacement_vm(proxmox, node, old_vm_config, new_template_id, new_tag):
    old_name = old_vm_config['name']
    new_name = f"{old_name}-redeployed" 
    
    memory = old_vm_config['memory']
    cores = old_vm_config['cores']

    try:
        new_vmid = proxmox.cluster.nextid.get()
        node.qemu(new_template_id).clone.post(newid=new_vmid, name=new_name)
        time.sleep(15)

        node.qemu(new_vmid).config.post(memory=memory, cores=cores)
        time.sleep(3)

        print(f"Configuring Cloud-Init with new tag: '{new_tag}'...")
        node.qemu(new_vmid).config.post(
            ciuser=CI_USER,
            cipassword=CI_PASSWORD, 
            sshkeys=SSH_PUBLIC_KEY_ENCODED,
            ipconfig0="ip=dhcp,ip6=dhcp",
            tags=new_tag,  
            net0="virtio,bridge=vmbr1"
        )
        time.sleep(3)
    
        node.qemu(new_vmid).status.start.post()
        
        return new_vmid

    except Exception as e:
        print(f"ERROR creating replacement VM for '{old_name}': {e}")
        return None

def delete_vm(node, vmid):
    try:
        node.qemu(vmid).status.stop.post()
        time.sleep(10) 

        node.qemu(vmid).delete()
        return True
    except Exception as e:
        print(f"ERROR deleting VM {vmid}: {e}")

        try:
            node.qemu(vmid).delete()
            return True
        except Exception as e2:
            print(f"  -> Final deletion failed: {e2}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Proxmox VM Redeployment Tool")
    parser.add_argument("--old-tag", required=True, help="The tag of the VMs to be replaced (e.g., 'template-v1')")
    parser.add_argument("--new-template-id", required=True, type=int, help="The VMID of the NEW template (e.g., 9001)")
    parser.add_argument("--new-tag", required=True, help="The tag that the new VMs will receive (e.g., 'template-v2')")
    
    args = parser.parse_args()
    
    proxmox = connect_pve()
    node = proxmox.nodes(NODE_NAME)
    
    vms_to_replace = find_vms_by_tag(proxmox, args.old_tag)
    
    if not vms_to_replace:
        print("No VMs found for replacement. Everything is up to date.")
        sys.exit(0)
    
    for vm in vms_to_replace:
        vmid = vm['vmid']
        name = vm['name']
        
        try:
            old_config = node.qemu(vmid).config.get()
            
            new_vmid = create_replacement_vm(
                proxmox,
                node, 
                old_config, 
                args.new_template_id, 
                args.new_tag
            )
            
            if new_vmid is None:
                print(f"Skipping deletion of {name}, creation failed.")
                continue

            delete_vm(node, vmid)
            
            print(f"--- Redeployment for {name} COMPLETE ---")
            
        except Exception as e:
            print(f"A critical error occurred during redeploy of {name}: {e}")
            print("Continuing with the next VM...")

    print("\nAll redeployments finished.")

if __name__ == "__main__":
    main()