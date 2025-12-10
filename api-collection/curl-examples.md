# API Curl Examples

Here are manual `curl` commands to test the API.

**Base URL:** `http://188.34.81.134:5000`

---

## 🟢 GET Requests (Retrieve Data)

### Get Storage Info (Disk Size)
```bash
curl -X GET http://188.34.81.134:5000/api/storages
````

### List Snapshots of a VM

*Replace `{vm_id}` with the actual ID.*

```bash
curl -X GET http://188.34.81.134:5000/api/vms/{vm_id}/snapshots
```

### List All Jobs

```bash
curl -X GET http://188.34.81.134:5000/api/jobs
```

### List Available Scripts

```bash
curl -X GET http://188.34.81.134:5000/api/scripts
```

### List All VMs

```bash
curl -X GET http://188.34.81.134:5000/api/vms
```

-----

## 🟡 POST Requests (Create & Actions)

### Create Template

Creates a new template from a Cloud-Init image.

```bash
curl -X POST http://188.34.81.134:5000/api/template \
  -H "Content-Type: application/json" \
  -d '{
    "vmid": 9000,
    "name": "ubuntu-2204",
    "image": "/var/lib/vz/template/iso/ubuntu-22.04-cloud.qcow2",
    "storage": "data-zfs"
  }'
```

### Clone VM (Full Clone)

Clones a VM from a template and configures Cloud-Init.

```bash
curl -X POST http://188.34.81.134:5000/api/clone \
  -H "Content-Type: application/json" \
  -d '{
    "template_vmid": 9000,
    "vm_name": "webserver-01",
    "cores": 1,
    "memory": 1024,
    "disk_size": 3,
    "tag": "webserver",
    "storage": "local",
    "ci_user": "ubuntu",
    "ci_password": "ubuntu",
    "ssh_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCywGwdfsM6zvdvvl0e6Z6YTXO19O3L8kQlnYObwbxFr25FOJIlNZutgFgWyQ1HnQrtZxpwpE3pWGRJ3SG1O2E/kY+R8B8TfTq+Hk7nSiWu1XHcSS9iVImSc1WueFo32Q5kyOIPWk7BZPsXOaIEBKZAVZgHpKcEAdTr9buO2JYwv/77ZHDSwBH4NL9wILDA9Lrn7VzDTd7trARTuUAq05S4/0vljNpzXSukWGvxAGtqyoWr35ntdvImoCzb1UAAyFkADu6B1T6pO4bpzRW2zt92nIJGMe2BvvgDwdsTFOUBz0VoTHgvha1uDv74vWyWytAasuWYCP3F7EinLD3AaU9H3Zd7VfwELqfL67zxEQTsxxl4KXNBifACANViPizaNojI8AdfDcnV5umYyAg5PLdsSoUWL/woUc5Zwi0LshuudI0IxmUejsfLm1nJ7hlKFdXu6ofI37NEVHYGq39VJlTVjovmdMJBwJgMw2rNXrJdR24C2VWlrkyz2IgjtnqlZQs= lehmbergs@SIT-SMBP-P9RKDY",
    "ip_cidr": "10.10.10.50/24",
    "gateway": "10.10.10.1",
    "data_disk_gb": 3,
    "mount_path": "/home",
    "script_id": [1, 2]
  }'
```

### Redeploy VM

Deletes VMs based on tags and recreates them.

```bash
curl -X POST http://188.34.81.134:5000/api/redeploy \
  -H "Content-Type: application/json" \
  -d '{
    "old_tag": "webserver",
    "new_template_id": 9000,
    "new_tag": "webserver-v2",
    "mount_path": "/home",
    "script_ids": [1, 2]
  }'
```

### Create Scripts

Uploads new setup scripts to the database.

```bash
curl -X POST http://188.34.81.134:5000/api/scripts \
  -H "Content-Type: application/json" \
  -d '[
    {
      "name": "01_Install_Docker",
      "description": "Installs Docker & Compose",
      "content": "#!/bin/bash\ncurl -fsSL [https://get.docker.com](https://get.docker.com) | sh"
    },
    {
      "name": "02_Hello_World",
      "description": "Creates a test file in home dir",
      "content": "#!/bin/bash\necho \"Hello\" > /home/ubuntu/test.txt"
    }
  ]'
```

### Create Snapshot

```bash
curl -X POST http://188.34.81.134:5000/api/snapshot \
  -H "Content-Type: application/json" \
  -d '{
    "vmid": 100,
    "name": "backup",
    "description": "Backup via API"
  }'
```

### Rollback (Restore Snapshot)

```bash
curl -X POST http://188.34.81.134:5000/api/rollback \
  -H "Content-Type: application/json" \
  -d '{
    "vmid": 100,
    "snapname": "backup"
  }'
```

### Cleanup Zombie Processes

```bash
curl -X POST http://188.34.81.134:5000/api/cleanup/zombies
```

-----

## 🔴 DELETE Requests (Remove Data)

### Delete Script

*Replace `{script_id}` with the actual script ID.*

```bash
curl -X DELETE http://188.34.81.134:5000/api/scripts/{script_id}
```
