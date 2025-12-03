import time
import subprocess
import urllib.parse
import config
import database
import base64
from shared import JOBS
from proxmox_utils import get_proxmox_api, delete_vm, find_vms_by_tag

# --- HELPER: Scripte kombinieren ---
def combine_scripts(script_ids):
    if not script_ids:
        return None
    
    combined_content = "#!/bin/bash\n# --- MASTER SETUP SCRIPT ---\n\n"
    
    for sid in script_ids:
        try:
            content = database.get_script_content(sid)
            if content:
                # Shebang entfernen (#/bin/bash), damit es mitten im File keine Fehler gibt
                clean_content = content.replace("#!/bin/bash", "")
                combined_content += f"\n# --- START SCRIPT ID {sid} ---\n"
                combined_content += clean_content + "\n"
                combined_content += f"\n# --- END SCRIPT ID {sid} ---\n"
        except Exception as e:
            print(f"Error loading script {sid}: {e}")
            
    return combined_content

# --- HELPER: Script in VM ausführen (NFS OPTIMIZED) ---
def run_guest_script(node, vmid, script_content):
    if not script_content: return

    print(f"[VM {vmid}] Waiting for Guest Agent...")
    
    # 1. Warten bis Agent da ist
    for i in range(60): # 2 Minuten reichen bei lokalem Storage locker
        try:
            res = node.qemu(vmid).agent.info.get()
            if res: break
        except:
            time.sleep(2)
            
    # Kurze Pause, damit Linux Zeit hat, Dateisysteme fertig zu mounten
    time.sleep(5)

    print(f"[VM {vmid}] Uploading script in chunks...")

    try:
        # 1. Script vorbereiten (Base64 + Windows-Zeilenumbrüche entfernen)
        clean_content = script_content.replace("\r\n", "\n")
        b64_full = base64.b64encode(clean_content.encode('utf-8')).decode('utf-8')
        
        # 2. Datei in VM leeren (Startpunkt)
        node.qemu(vmid).agent.exec.post(command=["/bin/bash", "-c", "echo -n '' > /tmp/upload.b64"])
        
        # 3. CHUNKING LOOP (Das verhindert den Absturz!)
        # Wir senden immer nur 1000 Zeichen. Das verkraftet der Agent ohne Absturz.
        chunk_size = 1000
        total_len = len(b64_full)
        
        for i in range(0, total_len, chunk_size):
            chunk = b64_full[i:i+chunk_size]
            
            # Wir hängen den Chunk an die Datei an (>>).
            cmd_append = ["/bin/bash", "-c", f"echo -n '{chunk}' >> /tmp/upload.b64"]
            
            node.qemu(vmid).agent.exec.post(command=cmd_append)
            # WICHTIG: Winzige Pause, damit der serielle Buffer sich leeren kann
            time.sleep(0.1)
            
        print(f"[VM {vmid}] Upload complete. Executing...")

        # 4. Decoden und Ausführen (Fire & Forget)
        # Jetzt setzen wir alles zusammen und starten es im Hintergrund.
        final_cmd = (
            "base64 -d /tmp/upload.b64 > /tmp/setup.sh && "
            "chmod +x /tmp/setup.sh && "
            "nohup /tmp/setup.sh > /tmp/setup.log 2>&1 &"
        )
        
        node.qemu(vmid).agent.exec.post(command=["/bin/bash", "-c", final_cmd])
        
        print(f"[VM {vmid}] Script started successfully.")

    except Exception as e:
        print(f"[VM {vmid}] Script Error: {e}")
# --- TASKS ---

def run_create_template_task(job_id, vmid, name, image_path, storage):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)
    vm_created = False

    try:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["message"] = f"Injecting Agent & Drivers into {image_path}..."
        
        # WICHTIG: Wir erzwingen das Aktivieren des Services!
        subprocess.run([
            "virt-customize", "-a", image_path, 
            "--install", "qemu-guest-agent,net-tools,curl",
            "--run-command", "systemctl enable qemu-guest-agent", 
            "--run-command", "systemctl unmask qemu-guest-agent"
        ], check=True)

        JOBS[job_id]["message"] = f"Creating VM {vmid}..."
        node.qemu.post(vmid=vmid, name=name, memory=2048, net0=f"virtio,bridge={config.NAT_BRIDGE}", scsihw="virtio-scsi-pci", ostype="l26", agent=1)
        vm_created = True
        time.sleep(3)

        JOBS[job_id]["message"] = "Importing disk..."
        node.qemu(vmid).config.post(scsi0=f"{storage}:0,import-from={image_path}")
        # Wir geben dem Import Zeit
        time.sleep(45)

        JOBS[job_id]["message"] = "Configuring Cloud-Init..."
        node.qemu(vmid).config.post(ide2=f"{storage}:cloudinit", boot="order=scsi0")
        time.sleep(5)

        JOBS[job_id]["message"] = "Converting to template..."
        node.qemu(vmid).template.post()

        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = f"Template {vmid} created."

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)
        if vm_created:
            delete_vm(node, vmid)


def run_clone_task(job_id, template_vmid, new_vm_name, cores, memory, disk_size, start_order, tag, user, password, ssh_key, ip_cidr, gateway, storage, script_ids=[], data_disk_gb=3):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)

    master_script = combine_scripts(script_ids)
    
    # Cloud-Init Vorbereitung
    final_user = user if user else config.DEFAULT_USER
    final_pass = password if password else config.DEFAULT_PASS
    encoded_key = urllib.parse.quote(ssh_key, safe="") if ssh_key else ""
    
    if ip_cidr: ip_cidr = ip_cidr.strip()
    if gateway: gateway = gateway.strip()
    ip_config = f"ip={ip_cidr},gw={gateway},ip6=dhcp" if (ip_cidr and gateway) else "ip=dhcp,ip6=dhcp"

    new_vmid = None

    try:
        JOBS[job_id]["status"] = "running"
        new_vmid = proxmox.cluster.nextid.get()
        JOBS[job_id]["vmid"] = new_vmid
        
        # Welcher Storage? Wenn keiner angegeben, nehmen wir 'local' als Fallback
        target_storage = storage if storage else "local"
        
        JOBS[job_id]["message"] = f"Cloning {template_vmid} to {new_vmid} on {target_storage}..."
        
        # 1. OS KLONEN (scsi0)
        clone_params = {"newid": new_vmid, "name": new_vm_name}
        if storage: 
            clone_params["storage"] = storage
            clone_params["full"] = 1
        
        node.qemu(template_vmid).clone.post(**clone_params)
        time.sleep(20) # Warten auf Clone

        # 2. OS DISK RESIZE (Optional)
        if disk_size:
            try:
                node.qemu(new_vmid).resize.put(disk="scsi0", size=f"{int(disk_size)}G")
            except: pass

        # 3. DATEN DISK ERSTELLEN (scsi1) - DAS IST NEU
        # Wir erstellen eine leere Raw/Qcow2 Disk auf dem gleichen Storage
        if data_disk_gb and int(data_disk_gb) > 0:
            JOBS[job_id]["message"] = f"Creating Data Disk ({data_disk_gb} GB)..."
            try:
                # Syntax: STORAGE:SIZE_IN_GB
                disk_conf = f"{target_storage}:{data_disk_gb}"
                node.qemu(new_vmid).config.post(scsi1=disk_conf)
                time.sleep(5) # Warten bis Disk erstellt ist
            except Exception as e:
                print(f"Error creating data disk: {e}")
                # Wir machen weiter, auch wenn das fehlschlägt, aber loggen es

        # 4. HARDWARE CONFIG
        hw_config = {"memory": memory, "cores": cores}
        if start_order: hw_config["startup"] = f"order={start_order}"
        node.qemu(new_vmid).config.post(**hw_config)

        # 5. CLOUD INIT & NETZWERK
        config_payload = {
            "ciuser": final_user, "cipassword": final_pass, "ipconfig0": ip_config,
            "tags": tag, "net0": f"virtio,bridge={config.NAT_BRIDGE}"
        }
        if encoded_key: config_payload["sshkeys"] = encoded_key
        node.qemu(new_vmid).config.post(**config_payload)
        
        time.sleep(2)
        
        # 6. STARTEN
        JOBS[job_id]["message"] = "Starting VM..."
        node.qemu(new_vmid).status.start.post()

        # 7. SCRIPTE LAUFEN LASSEN
        # Hier wird das Script laufen, das die NEUE Disk formatiert und mountet!
        if master_script:
            JOBS[job_id]["message"] = "Running setup scripts..."
            try:
                # WICHTIG: Nutze hier die NEUE run_guest_script Funktion mit Chunking!
                run_guest_script(node, new_vmid, master_script)
                JOBS[job_id]["message"] = "VM ready & Scripts executed."
            except Exception as e:
                JOBS[job_id]["message"] += f" (Script Error: {e})"
        else:
            JOBS[job_id]["status"] = "success"
            JOBS[job_id]["message"] = f"VM {new_vm_name} ready."

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)
        # Bei Fehler beim Erstellen löschen wir die Leiche
        if new_vmid:
            try: delete_vm(node, new_vmid)
            except: pass


def run_redeploy_task(job_id, old_tag, new_template_id, new_tag, script_ids=[]):
    proxmox = get_proxmox_api()
    if not proxmox:
        JOBS[job_id] = {"status": "error", "message": "API connection failed"}
        return
    node = proxmox.nodes(config.NODE_NAME)

    master_script = combine_scripts(script_ids)

    try:
        JOBS[job_id]["status"] = "running"
        vms = find_vms_by_tag(proxmox, old_tag)
        
        if not vms:
            JOBS[job_id]["status"] = "success"
            return

        log_msg = []
        for vm in vms:
            old_id = vm['vmid']
            original_name = vm['name']
            
            log_msg.append(f"> Processing {original_name} ({old_id})")
            
            # --- 1. CONFIG LESEN ---
            try:
                old_conf = node.qemu(old_id).config.get()
                data_vol = old_conf.get('scsi1') 
                
                disk_storage = "local"
                if data_vol and ":" in data_vol:
                    disk_storage = data_vol.split(":")[0]

                copy_mem = old_conf.get('memory', 2048)
                copy_cores = old_conf.get('cores', 2)
                copy_ip = old_conf.get('ipconfig0', "ip=dhcp,ip6=dhcp")
            except Exception as e:
                log_msg.append(f"  ! Config Error: {e}")
                continue

            # --- 2. NEUE VM ERSTELLEN ---
            new_id = proxmox.cluster.nextid.get()
            log_msg.append(f"  + Cloning to {new_id}...")
            JOBS[job_id]["message"] = "\n".join(log_msg)
            
            clone_params = {"newid": new_id, "name": original_name, "full": 1}
            if disk_storage: clone_params["storage"] = disk_storage
            node.qemu(new_template_id).clone.post(**clone_params)
            time.sleep(20) 

            # --- 3. DISK DETACHEN ---
            if data_vol:
                log_msg.append(f"  + Detaching disk from Old VM...")
                try:
                    node.qemu(old_id).config.put(delete="scsi1")
                    time.sleep(3)
                except Exception as e:
                    log_msg.append(f"  ! Detach Error: {e}")
                    raise e # Abbruch, wenn wir sie nicht lösen können

            # --- 4. DISK ATTACHEN ---
            config_payload = {
                "memory": copy_mem, "cores": copy_cores,
                "ipconfig0": copy_ip, "tags": new_tag,
                "net0": f"virtio,bridge={config.NAT_BRIDGE}",
                "ciuser": config.DEFAULT_USER, "cipassword": config.DEFAULT_PASS
            }
            if data_vol:
                config_payload["scsi1"] = data_vol

            node.qemu(new_id).config.post(**config_payload)
            time.sleep(2)

            # --- 5. DISK MOVE (FAIL-SAFE MODE) ---
            delete_old_vm = True # Standard: Wir löschen die alte VM
            
            if data_vol:
                # Format Toggle Logik
                current_fmt = "raw"
                if "qcow2" in data_vol: current_fmt = "qcow2"
                target_fmt = "qcow2" if current_fmt == "raw" else "raw"

                log_msg.append(f"  + Moving disk ownership...")
                JOBS[job_id]["message"] = "\n".join(log_msg)
                
                try:
                    node.qemu(new_id).move_disk.post(
                        disk="scsi1", storage=disk_storage, format=target_fmt, delete=1
                    )
                    time.sleep(15)
                except Exception as move_err:
                    # HIER IST DER RETTER:
                    log_msg.append(f"  ! MOVE FAILED: {move_err}")
                    log_msg.append("  ! SAFETY MODE: Keeping Old VM to protect data!")
                    JOBS[job_id]["message"] = "\n".join(log_msg)
                    
                    # WICHTIG: Wenn Move fehlschlägt, liegt die Disk noch im Ordner der alten VM.
                    # Wenn wir die alte VM jetzt löschen, löscht Proxmox auch die Disk!
                    # Also verbieten wir das Löschen:
                    delete_old_vm = False

            # --- 6. ALTE VM LÖSCHEN (NUR WENN SICHER) ---
            if delete_old_vm:
                log_msg.append(f"  - Deleting old VM {old_id}...")
                try: delete_vm(node, old_id)
                except: log_msg.append("  ! Delete failed (minor)")
            else:
                log_msg.append(f"  ! SKIPPED DELETION of {old_id} (Manual cleanup required)")

            # --- 7. STARTEN & SCRIPTE ---
            node.qemu(new_id).status.start.post()
            
            if master_script:
                try:
                    run_guest_script(node, new_id, master_script)
                except Exception as se:
                    log_msg.append(f"  ! Script Warning: {se}")

        JOBS[job_id]["status"] = "success"
        JOBS[job_id]["message"] = "Redeploy complete.\n" + "\n".join(log_msg)

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)