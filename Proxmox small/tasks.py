import time
import subprocess
import urllib.parse
import config
from shared import JOBS
from proxmox_utils import get_proxmox_api, delete_vm, find_vms_by_tag

def run_create_template_task(job_id, vmid, name, image_path, storage):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)
    vm_created = False

    try:
        JOBS[job_id]["status"] = "running"
        
        JOBS[job_id]["message"] = f"Customizing image {image_path}..."
        subprocess.run(["virt-customize", "-a", image_path, "--install", "qemu-guest-agent"], check=True, capture_output=True, text=True)

        JOBS[job_id]["message"] = f"Creating VM {vmid}..."
        node.qemu.post(
            vmid=vmid, 
            name=name, 
            memory=2048, 
            net0=f"virtio,bridge={config.NAT_BRIDGE}", 
            scsihw="virtio-scsi-pci", 
            ostype="l26", 
            agent=1
        )
        vm_created = True
        time.sleep(3)

        JOBS[job_id]["message"] = "Importing disk..."
        node.qemu(vmid).config.post(scsi0=f"{storage}:0,import-from={image_path}")
        time.sleep(30)

        JOBS[job_id]["message"] = "Configuring Cloud-Init..."
        node.qemu(vmid).config.post(ide2=f"{storage}:cloudinit", boot="order=scsi0")
        time.sleep(2)

        JOBS[job_id]["message"] = "Converting to template..."
        node.qemu(vmid).template.post()

        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = f"Template {vmid} created."

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)
        if vm_created:
            JOBS[job_id]["message"] += "\n(Rolling back: Deleting incomplete Template)"
            delete_vm(node, vmid)

def run_clone_task(job_id, template_vmid, new_vm_name, cores, memory, disk_size, start_order, tag, user, password, ssh_key, ip_cidr, gateway, storage):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)
    
    final_user = user if user else config.DEFAULT_USER
    final_pass = password if password else config.DEFAULT_PASS
    encoded_key = urllib.parse.quote(ssh_key, safe="") if ssh_key else ""

    if ip_cidr: ip_cidr = ip_cidr.strip()
    if gateway: gateway = gateway.strip()

    if ip_cidr and gateway:
        if "/" not in ip_cidr: ip_cidr += "/24"
        ip_config = f"ip={ip_cidr},gw={gateway},ip6=dhcp"
    else:
        ip_config = "ip=dhcp,ip6=dhcp"

    new_vmid = None 

    try:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["message"] = "Finding VMID..."
        new_vmid = proxmox.cluster.nextid.get()
        JOBS[job_id]["vmid"] = new_vmid
        
        target_storage_msg = storage if storage else "default storage"
        JOBS[job_id]["message"] = f"Cloning {template_vmid} to {new_vmid} on {target_storage_msg}..."
        
        clone_params = {
            "newid": new_vmid,
            "name": new_vm_name
        }
        
        if storage:
            clone_params["storage"] = storage
            clone_params["full"] = 1 
        
        node.qemu(template_vmid).clone.post(**clone_params)
        time.sleep(20)
        
        if disk_size:
            try:
                size_gb = int(disk_size)
                JOBS[job_id]["message"] = f"Resizing disk to {size_gb}GB..."
                node.qemu(new_vmid).resize.put(disk="scsi0", size=f"{size_gb}G")
                time.sleep(3)
            except Exception as resize_err:
                print(f"Resize warning: {resize_err}")
                JOBS[job_id]["message"] += f" (Resize warning: {resize_err})"

        JOBS[job_id]["message"] = "Configuring hardware..."
        
        hw_config = {"memory": memory, "cores": cores}
        if start_order:
             hw_config["startup"] = f"order={start_order}"
        
        node.qemu(new_vmid).config.post(**hw_config)
        time.sleep(3)
        
        JOBS[job_id]["message"] = f"Setting Cloud-Init ({ip_config})..."
        
        config_payload = {
            "ciuser": final_user,
            "cipassword": final_pass,
            "ipconfig0": ip_config,
            "tags": tag,
            "net0": f"virtio,bridge={config.NAT_BRIDGE}"
        }
        if encoded_key:
            config_payload["sshkeys"] = encoded_key

        node.qemu(new_vmid).config.post(**config_payload)
        time.sleep(3)
        
        JOBS[job_id]["message"] = "Starting VM..."
        node.qemu(new_vmid).status.start.post()
        
        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = f"VM {new_vm_name} ({new_vmid}) ready ({disk_size}GB, Order: {start_order})."

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = f"Error: {str(e)}"
        if new_vmid:
            JOBS[job_id]["message"] += "\n(Rolling back: Deleting failed VM)"
            delete_vm(node, new_vmid)

def run_redeploy_task(job_id, old_tag, new_template_id, new_tag):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)
    
    try:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["message"] = f"Scanning tag '{old_tag}'..."
        vms = find_vms_by_tag(proxmox, old_tag)
        
        if not vms:
            JOBS[job_id]["status"] = "success"
            JOBS[job_id]["message"] = "No VMs found to redeploy."
            return
            
        log_msg = []
        for vm in vms:
            old_id = vm['vmid']
            original_name = vm['name']
            new_id = None

            try:
                log_msg.append(f"> Processing {original_name} ({old_id})")
                JOBS[job_id]["message"] = "\n".join(log_msg)
                
                # 1. READ OLD CONFIG
                old_conf = node.qemu(old_id).config.get()
                
                copy_user = old_conf.get('ciuser', config.DEFAULT_USER)
                copy_keys = old_conf.get('sshkeys', "") 
                copy_ip = old_conf.get('ipconfig0', "ip=dhcp,ip6=dhcp")
                copy_mem = old_conf.get('memory', 1024)
                copy_cores = old_conf.get('cores', 1)
                copy_startup = old_conf.get('startup', None) # Backup startup order
                
                # --- DETERMINE STORAGE & DISK SIZE ---
                old_disk_size_gb = None
                target_storage_id = None
                
                disk_config = old_conf.get('scsi0', '')
                
                if ':' in disk_config:
                    target_storage_id = disk_config.split(':')[0]
                    log_msg.append(f"  + Detected Storage: {target_storage_id}")
                
                if 'size=' in disk_config:
                    try:
                        parts = disk_config.split(',')
                        for p in parts:
                            if p.startswith('size='):
                                size_str = p.split('=')[1]
                                if size_str.upper().endswith('G'):
                                    old_disk_size_gb = int(float(size_str[:-1]))
                                    log_msg.append(f"  + Detected Size: {old_disk_size_gb}GB")
                    except Exception as parse_e:
                        print(f"Could not parse disk size: {parse_e}")

                # 2. DELETE OLD VM
                log_msg.append(f"  - Deleting old VM {old_id}...")
                JOBS[job_id]["message"] = "\n".join(log_msg)
                
                if not delete_vm(node, old_id):
                     raise Exception("Failed to delete old VM. Aborting to save state.")
                
                # 3. CREATE NEW VM
                new_id = proxmox.cluster.nextid.get()
                log_msg.append(f"  + Cloning Template to {new_id}...")
                JOBS[job_id]["message"] = "\n".join(log_msg)
                
                clone_params = {
                    "newid": new_id,
                    "name": original_name
                }
                
                if target_storage_id:
                    clone_params['storage'] = target_storage_id
                    clone_params['full'] = 1 
                
                node.qemu(new_template_id).clone.post(**clone_params)
                time.sleep(15)
                
                # 4. RESIZE (Restore)
                if old_disk_size_gb:
                    try:
                        log_msg.append(f"  + Restoring Disk Size: {old_disk_size_gb}GB")
                        JOBS[job_id]["message"] = "\n".join(log_msg)
                        node.qemu(new_id).resize.put(disk="scsi0", size=f"{old_disk_size_gb}G")
                        time.sleep(3)
                    except Exception as resize_e:
                        log_msg.append(f"  ! Resize Failed: {resize_e}")

                # 5. CONFIG & START
                config_payload = {
                    "memory": copy_mem,
                    "cores": copy_cores,
                    "ciuser": copy_user,
                    "cipassword": config.DEFAULT_PASS, 
                    "ipconfig0": copy_ip,
                    "tags": new_tag,
                    "net0": f"virtio,bridge={config.NAT_BRIDGE}"
                }
                if copy_keys:
                    config_payload["sshkeys"] = copy_keys
                
                if copy_startup:
                    config_payload["startup"] = copy_startup

                node.qemu(new_id).config.post(**config_payload)
                time.sleep(3)
                
                node.qemu(new_id).status.start.post()
                log_msg.append(f"  + New VM {new_id} started")
                JOBS[job_id]["message"] = "\n".join(log_msg)

            except Exception as inner_e:
                log_msg.append(f"  ! CRITICAL ERROR: {str(inner_e)}")
                JOBS[job_id]["message"] = "\n".join(log_msg)
                raise inner_e 
            
        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = "Redeploy complete."

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)