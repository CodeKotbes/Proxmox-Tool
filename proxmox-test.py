from proxmoxer import ProxmoxAPI

PVE_HOST = "localhost" 
PVE_USER = "python-script@pve"
PVE_TOKEN_ID = "template-script" 
PVE_TOKEN_SECRET = "53d30c31-7ae6-49bb-8793-436ee9793dea" 

try:
    proxmox = ProxmoxAPI(
        PVE_HOST,
        port=8080,
        user=PVE_USER,
        token_name=PVE_TOKEN_ID,
        token_value=PVE_TOKEN_SECRET,
        verify_ssl=False  
    )

    print(f"Successfully connected to {PVE_HOST}!")

    nodes = proxmox.nodes.get()
    
    print("Available Nodes in Cluster:")
    for node in nodes:
        print(f"- Node: {node['node']}, Status: {node['status']}")

except Exception as e:
    print(f"Connection failed: {e}")