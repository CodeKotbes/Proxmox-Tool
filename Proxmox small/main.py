import threading
import uuid
from flask import Flask, jsonify, request, send_file
import config
import database
from shared import JOBS
from proxmox_utils import get_proxmox_api, delete_vm
import tasks

app = Flask(__name__)

@app.route("/")
def serve_index():
    try: return send_file("index.html")
    except: return "index.html missing", 404

@app.route("/api/storages", methods=["GET"])
def api_get_storages():
    proxmox = get_proxmox_api()
    if not proxmox: return jsonify({"error": "No connection"}), 500
    node = proxmox.nodes(config.NODE_NAME)
    storages = []
    try:
        for s in node.storage.get(content="images"): 
            if s.get("active") == 1:
                storages.append({
                    "id": s.get("storage"), "type": s.get("type"),
                    "total": s.get("total"), "used": s.get("used"), "avail": s.get("avail")
                })
        return jsonify(storages)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/scripts", methods=["GET"])
def api_list_scripts():
    return jsonify(database.get_all_scripts())

@app.route("/api/scripts", methods=["POST"])
def api_add_script():
    data = request.json
    if isinstance(data, list):
        created_ids = []
        errors = 0
        for item in data:
            if not item.get("name") or not item.get("content"):
                errors += 1
                continue
            nid = database.add_script(item.get("name"), item.get("description", ""), item.get("content"))
            created_ids.append(nid)
        return jsonify({"status": "batch_created", "ids": created_ids, "count": len(created_ids), "failed": errors})
    else:
        if not data.get("name") or not data.get("content"):
            return jsonify({"error": "Name and content required"}), 400
        new_id = database.add_script(data.get("name"), data.get("description", ""), data.get("content"))
        return jsonify({"status": "created", "id": new_id})

@app.route("/api/scripts/<int:script_id>", methods=["DELETE"])
def api_delete_script(script_id):
    database.delete_script(script_id)
    return jsonify({"status": "deleted"})

@app.route("/api/template", methods=["POST"])
def api_create_template():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "TEMPLATE", "message": "Queued..."}
    threading.Thread(target=tasks.run_create_template_task, args=(
        jid, d.get("vmid"), d.get("name"), d.get("image"), d.get("storage")
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/clone", methods=["POST"])
def api_clone_vm():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "CLONE", "message": "Queued..."}
    s_ids = d.get("script_ids", [])
    if not s_ids and d.get("script_id"): s_ids = [d.get("script_id")]

    threading.Thread(target=tasks.run_clone_task, args=(
        jid, d.get("template_vmid"), d.get("vm_name"), 
        d.get("cores"), d.get("memory"), d.get("disk_size"), d.get("start_order"),
        d.get("tag"), d.get("ci_user"), d.get("ci_password"), d.get("ssh_key"),
        d.get("ip_cidr"), d.get("gateway"), d.get("storage"),
        s_ids, d.get("data_disk_gb", 0), d.get("mount_path", None)
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/redeploy", methods=["POST"])
def api_redeploy_vms():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "REDEPLOY", "message": "Queued..."}
    s_ids = d.get("script_ids", [])
    if not s_ids and d.get("script_id"): s_ids = [d.get("script_id")]

    threading.Thread(target=tasks.run_redeploy_task, args=(
        jid, d.get("old_tag"), d.get("new_template_id"), d.get("new_tag"),
        s_ids, d.get("mount_path", None)
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/snapshot", methods=["POST"])
def api_create_snapshot():
    d = request.json
    if not d.get("vmid"): return jsonify({"error": "vmid required"}), 400
    snap_name = d.get("name") if d.get("name") else f"manual_{uuid.uuid4().hex[:8]}"

    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "SNAPSHOT", "message": "Queued..."}
    threading.Thread(target=tasks.run_snapshot_task, args=(
        jid, d.get("vmid"), snap_name, d.get("description", "")
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/vms/<int:vmid>/snapshots", methods=["GET"])
def api_get_snapshots(vmid):
    proxmox = get_proxmox_api()
    if not proxmox: return jsonify({"error": "No connection"}), 500
    node = proxmox.nodes(config.NODE_NAME)
    try:
        snaps = node.qemu(vmid).snapshot.get()
        result = []
        for s in snaps:
            if s.get("name") != "current":
                result.append({"name": s.get("name"), "description": s.get("description", ""), "time": s.get("snaptime")})
        return jsonify(result)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/rollback", methods=["POST"])
def api_rollback_vm():
    d = request.json
    if not d.get("vmid") or not d.get("snapname"): return jsonify({"error": "vmid and snapname required"}), 400
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "ROLLBACK", "message": "Queued..."}
    threading.Thread(target=tasks.run_rollback_task, args=(
        jid, d.get("vmid"), d.get("snapname")
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/cleanup/zombies", methods=["POST"])
def api_cleanup_zombies():
    proxmox = get_proxmox_api()
    node = proxmox.nodes(config.NODE_NAME)
    deleted = []
    try:
        for vm in node.qemu.get():
            tags = vm.get("tags", "")
            name = vm.get("name", "")
            if "move-failed" in tags and "ZOMBIE" in name:
                if vm.get("status") == "stopped":
                    delete_vm(node, vm.get("vmid"))
                    deleted.append(name)
        return jsonify({"status": "cleaned", "deleted": deleted})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/jobs", methods=["GET"])
def api_jobs(): return jsonify(JOBS)

if __name__ == "__main__":
    database.init_db() 
    print("Server running on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)