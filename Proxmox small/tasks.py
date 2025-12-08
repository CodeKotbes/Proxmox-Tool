import time
import base64
import urllib.parse
import functools
import traceback
import config
import database
from shared import JOBS
from proxmox_utils import get_proxmox_api, delete_vm, find_vms_by_tag

def task_wrapper(func):
    @functools.wraps(func)
    def wrapper(job_id, *args, **kwargs):
        try:
            return func(job_id, *args, **kwargs)
        except Exception as e:
            print(f"CRITICAL TASK ERROR in {job_id}: {e}")
            traceback.print_exc()
            if job_id in JOBS:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["message"] = f"Internal Error: {str(e)}"
    return wrapper

def combine_scripts(script_ids):
    if not script_ids:
        return None
    combined_content = "#!/bin/bash\n# --- MASTER SETUP SCRIPT ---\n\n"
    for sid in script_ids:
        try:
            content = database.get_script_content(sid)
            if content:
                clean_content = content.replace("#!/bin/bash", "")
                combined_content += f"\n# --- START SCRIPT ID {sid} ---\n{clean_content}\n# --- END SCRIPT ID {sid} ---\n"
        except Exception as e:
            print(f"Error loading script {sid}: {e}")
    return combined_content

def generate_persistence_script(mount_path):
    device = "/dev/sdb"
    script = f"""#!/bin/bash
# --- DYNAMIC PERSISTENCE SETUP ---
DEVICE="{device}"
TARGET="{mount_path}"
echo "Configuring persistent storage for $TARGET on $DEVICE..."
for i in {{1..10}}; do [ -b "$DEVICE" ] && break; sleep 1; done
if [ ! -b "$DEVICE" ]; then echo "Error: Device $DEVICE not found"; exit 0; fi

IS_NEW=0
if blkid "$DEVICE" > /dev/null; then
    echo "Disk is already formatted."
else
    echo "Disk is empty. Formatting ext4..."
    mkfs.ext4 -F "$DEVICE"
    IS_NEW=1
fi

if [ "$IS_NEW" -eq 1 ]; then
    mkdir -p /mnt/tmp_migrate
    mount "$DEVICE" /mnt/tmp_migrate
    if [ -d "$TARGET" ] && [ "$(ls -A $TARGET)" ]; then
        echo "Migrating existing data from $TARGET to new disk..."
        rsync -a "$TARGET/" /mnt/tmp_migrate/
    fi
    umount /mnt/tmp_migrate
    rmdir /mnt/tmp_migrate
fi

mkdir -p "$TARGET"
mount "$DEVICE" "$TARGET"
if [ "$TARGET" != "/home" ]; then chmod 777 "$TARGET"; fi

if ! grep -qs "$TARGET" /etc/fstab; then
    UUID=$(blkid -s UUID -o value "$DEVICE")
    echo "UUID=$UUID $TARGET ext4 defaults 0 2" >> /etc/fstab
fi
echo "Persistence setup complete."
"""
    return script

def run_guest_script(node, vmid, script_content):
    if not script_content: return
    print(f"[VM {vmid}] Waiting for Guest Agent...")
    agent_up = False
    for i in range(300):
        try:
            res = node.qemu(vmid).agent.info.get()
            if res: 
                agent_up = True
                break
        except:
            time.sleep(2)
            
    if not agent_up:
        print(f"[VM {vmid}] Agent Timeout - Script skipped.")
        return

    time.sleep(10)
    print(f"[VM {vmid}] Uploading script in chunks...")

    try:
        clean_content = script_content.replace("\r\n", "\n")
        b64_full = base64.b64encode(clean_content.encode('utf-8')).decode('utf-8')
        node.qemu(vmid).agent.exec.post(command=["/bin/bash", "-c", "echo -n '' > /tmp/upload.b64"])
        
        chunk_size = 1000
        total_len = len(b64_full)
        for i in range(0, total_len, chunk_size):
            chunk = b64_full[i:i+chunk_size]
            cmd_append = ["/bin/bash", "-c", f"echo -n '{chunk}' >> /tmp/upload.b64"]
            node.qemu(vmid).agent.exec.post(command=cmd_append)
            time.sleep(0.1)
            
        print(f"[VM {vmid}] Upload complete. Executing...")
        final_cmd = (
            "base64 -d /tmp/upload.b64 > /tmp/setup.sh && "
            "chmod +x /tmp/setup.sh && "
            "nohup /tmp/setup.sh > /tmp/setup.log 2>&1 &"
        )
        node.qemu(vmid).agent.exec.post(command=["/bin/bash", "-c", final_cmd])
        print(f"[VM {vmid}] Script started successfully.")
    except Exception as e:
        print(f"[VM {vmid}] Script Error (Non-Fatal): {e}")

@task_wrapper
def run_create_template_task(job_id, vmid, name, image_path, storage):
    proxmox = get_proxmox_api()
    if not proxmox: return
    node = proxmox.nodes(config.NODE_NAME)

    JOBS[job_id]["status"] = "running"
    JOBS[job_id]["message"] = f"Creating VM {vmid}..."
    node.qemu.post(vmid=vmid, name=name, memory=2048, net0=f"virtio,bridge={config.NAT_BRIDGE}", scsihw="virtio-scsi-pci", ostype="l26", agent=1)
    time.sleep(3)
    JOBS[job_id]["message"] = "Importing disk..."
    node.qemu(vmid).config.post(scsi0=f"{storage}:0,import-from={image_path}")
    time.sleep(45)
    JOBS[job_id]["message"] = "Configuring Cloud-Init..."
    node.qemu(vmid).config.post(ide2=f"{storage}:cloudinit", boot="order=scsi0")
    time.sleep(5)
    JOBS[job_id]["message"] = "Converting to template..."
    node.qemu(vmid).template.post()
    JOBS[job_id]["status"] = "success"
    JOBS[job_id]["message"] = f"Template {vmid} created."

@task_wrapper
def run_clone_task(job_id, template_vmid, new_vm_name, cores, memory, disk_size, start_order, tag, user, password, ssh_key, ip_cidr, gateway, storage, script_ids=[], data_disk_gb=0, mount_path=None):
    proxmox = get_proxmox_api()
    if not proxmox: return
    node = proxmox.nodes(config.NODE_NAME)

    full_script_content = ""
    if data_disk_gb and int(data_disk_gb) > 0 and mount_path:
        full_script_content += generate_persistence_script(mount_path)
        full_script_content += "\n\n"
    
    user_scripts = combine_scripts(script_ids)
    if user_scripts: full_script_content += user_scripts
    
    final_user = user if user else config.DEFAULT_USER
    final_pass = password if password else config.DEFAULT_PASS
    encoded_key = urllib.parse.quote(ssh_key, safe="") if ssh_key else ""
    ip_config = f"ip={ip_cidr},gw={gateway},ip6=dhcp" if (ip_cidr and gateway) else "ip=dhcp,ip6=dhcp"

    JOBS[job_id]["status"] = "running"
    new_vmid = proxmox.cluster.nextid.get()
    JOBS[job_id]["vmid"] = new_vmid
    target_storage = storage if storage else "local"
    
    JOBS[job_id]["message"] = f"Cloning {template_vmid} to {new_vmid} on {target_storage}..."
    
    clone_params = {"newid": new_vmid, "name": new_vm_name, "full": 1, "format": "qcow2"}
    if storage: clone_params["storage"] = storage
    
    node.qemu(template_vmid).clone.post(**clone_params)
    time.sleep(20)

    if disk_size:
        try: node.qemu(new_vmid).resize.put(disk="scsi0", size=f"{int(disk_size)}G")
        except: pass

    if data_disk_gb and int(data_disk_gb) > 0:
        JOBS[job_id]["message"] = f"Creating Data Disk ({data_disk_gb} GB)..."
        try:
            disk_conf = f"{target_storage}:{data_disk_gb},format=qcow2"
            node.qemu(new_vmid).config.post(scsi1=disk_conf)
            time.sleep(5)
        except Exception as e:
            print(f"Error creating data disk: {e}")

    hw_config = {"memory": memory, "cores": cores}
    if start_order: hw_config["startup"] = f"order={start_order}"
    node.qemu(new_vmid).config.post(**hw_config)

    config_payload = {
        "ciuser": final_user, "cipassword": final_pass, "ipconfig0": ip_config,
        "tags": tag, "net0": f"virtio,bridge={config.NAT_BRIDGE}"
    }
    if encoded_key: config_payload["sshkeys"] = encoded_key
    node.qemu(new_vmid).config.post(**config_payload)
    time.sleep(2)
    
    JOBS[job_id]["message"] = "Starting VM..."
    node.qemu(new_vmid).status.start.post()

    if full_script_content:
        JOBS[job_id]["message"] = "Running setup scripts..."
        try:
            run_guest_script(node, new_vmid, full_script_content)
            JOBS[job_id]["message"] = "VM ready & Scripts executed."
        except Exception as e:
            JOBS[job_id]["message"] += f" (Script Error: {e})"
    else:
        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = f"VM {new_vm_name} ready."

@task_wrapper
def run_redeploy_task(job_id, old_tag, new_template_id, new_tag, script_ids=[], mount_path=None):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)

    JOBS[job_id]["status"] = "running"
    vms = find_vms_by_tag(proxmox, old_tag)
    
    if not vms:
        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = "No VMs found."
        return

    log_msg = []
    for vm in vms:
        old_id = vm['vmid']
        original_name = vm['name']
        log_msg.append(f"> Processing {original_name} ({old_id})")
        JOBS[job_id]["message"] = "\n".join(log_msg)

        snap_name = f"autobackup_{int(time.time())}"
        try:
            node.qemu(old_id).snapshot.post(snapname=snap_name, description="Pre-Redeploy", vmstate=0)
            time.sleep(3)
        except Exception as e:
            log_msg.append(f"  ! Snapshot skipped (likely RAW Disk): {e}")

        try:
            old_conf = node.qemu(old_id).config.get()
            data_vol = old_conf.get('scsi1') 
            os_vol = old_conf.get('scsi0') 
            
            disk_storage = "local"
            if data_vol and ":" in data_vol: disk_storage = data_vol.split(":")[0]

            old_os_size_gb = 0
            if os_vol and "size=" in os_vol:
                try:
                    size_part = os_vol.split("size=")[1].split(",")[0]
                    if "G" in size_part: old_os_size_gb = int(float(size_part.replace("G", "")))
                except: pass

            copy_mem = old_conf.get('memory', 2048)
            copy_cores = old_conf.get('cores', 2)
            copy_ip = old_conf.get('ipconfig0', "ip=dhcp,ip6=dhcp")
            
            copy_sshkeys = old_conf.get('sshkeys') 
            copy_startup = old_conf.get('startup') 

        except Exception as e:
            log_msg.append(f"  ! Config Error: {e}")
            continue

        new_id = proxmox.cluster.nextid.get()
        clone_params = {"newid": new_id, "name": original_name, "full": 1, "format": "qcow2"}
        if disk_storage: clone_params["storage"] = disk_storage
        try:
            node.qemu(new_template_id).clone.post(**clone_params)
            time.sleep(20)
        except Exception as e:
            log_msg.append(f"  ! Clone failed: {e}")
            continue

        if old_os_size_gb > 0:
            try:
                node.qemu(new_id).resize.put(disk="scsi0", size=f"{old_os_size_gb}G")
                time.sleep(3)
            except: pass

        if data_vol:
            try:
                node.qemu(old_id).config.put(delete="scsi1")
                time.sleep(3)
            except Exception as e:
                log_msg.append(f"  ! Detach Error: {e}")
                continue 

        config_payload = {
            "memory": copy_mem, "cores": copy_cores, "ipconfig0": copy_ip,
            "tags": new_tag, "net0": f"virtio,bridge={config.NAT_BRIDGE}",
            "ciuser": config.DEFAULT_USER, 
            "cipassword": config.DEFAULT_PASS
        }

        if copy_sshkeys:
            config_payload["sshkeys"] = copy_sshkeys

        if copy_startup:
            config_payload["startup"] = copy_startup

        if data_vol: config_payload["scsi1"] = data_vol

        node.qemu(new_id).config.post(**config_payload)
        time.sleep(2)

        delete_old_vm = True
        if data_vol:
            log_msg.append(f"  + Moving disk (enforcing QCOW2)...")
            JOBS[job_id]["message"] = "\n".join(log_msg)
            
            is_qcow2 = "qcow2" in data_vol
            
            try:
                if not is_qcow2:
                    log_msg.append("  + Converting RAW -> QCOW2...")
                    node.qemu(new_id).move_disk.post(
                        disk="scsi1", storage=disk_storage, format="qcow2", delete=1
                    )
                    time.sleep(15)
                else:
                    log_msg.append("  + Step 1/2: Temp RAW conversion...")
                    node.qemu(new_id).move_disk.post(
                        disk="scsi1", storage=disk_storage, format="raw", delete=1
                    )
                    time.sleep(15) 
                    log_msg.append("  + Step 2/2: Final QCOW2 conversion...")
                    node.qemu(new_id).move_disk.post(
                        disk="scsi1", storage=disk_storage, format="qcow2", delete=1
                    )
                    time.sleep(15)

            except Exception as move_err:
                log_msg.append(f"  ! MOVE FAILED: {move_err}")
                log_msg.append("  ! ZOMBIE MODE: Renaming Old VM to protect data.")
                delete_old_vm = False
                try:
                    new_zombie_name = f"ZOMBIE-{old_id}-{original_name}"
                    node.qemu(old_id).config.post(name=new_zombie_name)
                    old_tags = old_conf.get("tags", "")
                    node.qemu(old_id).config.post(tags=f"{old_tags},move-failed,do-not-delete")
                except: pass

        if delete_old_vm:
            try: delete_vm(node, old_id)
            except: log_msg.append("  ! Delete failed (minor)")
        else:
            log_msg.append(f"  ! SKIPPED DELETION of {old_id}")

        node.qemu(new_id).status.start.post()
        
        full_script_content = ""
        if data_vol and mount_path:
            full_script_content += generate_persistence_script(mount_path)
            full_script_content += "\n\n"
            
        user_scripts = combine_scripts(script_ids)
        if user_scripts: full_script_content += user_scripts
            
        if full_script_content:
            try: run_guest_script(node, new_id, full_script_content)
            except Exception as se: log_msg.append(f"  ! Script Warning: {se}")

    JOBS[job_id]["status"] = "success"
    JOBS[job_id]["message"] = "Redeploy complete.\n" + "\n".join(log_msg)

@task_wrapper
def run_snapshot_task(job_id, vmid, snap_name, description):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)

    JOBS[job_id]["status"] = "running"
    JOBS[job_id]["message"] = f"Checking VM {vmid} capability..."

    try:
        conf = node.qemu(vmid).config.get()
        disk_config = conf.get("scsi0", "")
        
        if "media=cdrom" not in disk_config:
            if ".raw" in disk_config or "format=raw" in disk_config:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["message"] = (
                    "Snapshot failed: Disk is in RAW format.\n"
                    "Please execute a Redeploy to convert it back to QCOW2."
                )
                return

        JOBS[job_id]["message"] = f"Creating snapshot '{snap_name}'..."
        node.qemu(vmid).snapshot.post(snapname=snap_name, description=description, vmstate=0)
        
        for _ in range(30):
            task_status = node.qemu(vmid).snapshot.get()
            time.sleep(1)

        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = f"Snapshot '{snap_name}' created."
        
    except Exception as e:
        err_msg = str(e)
        if "feature not available" in err_msg:
            JOBS[job_id]["message"] = "Error: Snapshots not supported on this Disk type (RAW)."
        else:
            JOBS[job_id]["message"] = f"Proxmox Error: {err_msg}"
        JOBS[job_id]["status"] = "error"

@task_wrapper
def run_rollback_task(job_id, vmid, snapname):
    proxmox = get_proxmox_api()
    if not proxmox: return
    node = proxmox.nodes(config.NODE_NAME)

    JOBS[job_id]["status"] = "running"
    JOBS[job_id]["message"] = f"Stopping VM {vmid}..."
    try:
        node.qemu(vmid).status.stop.post()
        time.sleep(5)
    except: pass

    JOBS[job_id]["message"] = f"Rolling back to '{snapname}'..."
    node.qemu(vmid).snapshot(snapname).rollback.post()
    time.sleep(5)
    
    JOBS[job_id]["message"] = "Starting VM..."
    node.qemu(vmid).status.start.post()
    
    JOBS[job_id]["status"] = "success"
    JOBS[job_id]["message"] = f"Rollback complete."