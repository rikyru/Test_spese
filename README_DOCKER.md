# 🐳 Docker Deployment Guide (GitHub Workflow)

This guide explains how to deploy using GitHub. This is the best way to keep your server updated.

## 1. Setup on Local PC
1.  **Git Ignore**: A `.gitignore` file has been created to exclude your private data (`finance_data/`, `finance.duckdb`, etc.) from being uploaded.
2.  **Push to GitHub**:
    ```bash
    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/<YOUR_USER>/<REPO_NAME>.git
    git push -u origin main
    ```

## 2. Setup on Home Server
1.  **Clone the Repo**:
    ```bash
    git clone https://github.com/<YOUR_USER>/<REPO_NAME>.git finance_app
    cd finance_app
    ```

2.  **Setup Data Folder**:
    Create the data folder (since it's ignored by Git, you must create it manually):
    ```bash
    mkdir finance_data
    ```
    *Copy your existing `finance.duckdb` and `rules.yaml` into this `finance_data` folder via SCP, USB, or network share.*

3.  **Run Docker**:
    ```bash
    docker-compose up -d --build
    ```

## 3. How to Update
When you make changes on your PC and verify they work:
1.  **PC**: `git push` your changes.
2.  **Server**: Run this command inside the `finance_app` folder:
    ```bash
    git pull && docker-compose up -d --build
    ```
    This will download the new code and rebuild the container. Your data remains safe in `finance_data`.


## 4. Pagina rapida mobile dietro Cloudflare Tunnel

La pagina `/quick` è servita da `finance_api` (porta 8000 nel container), mentre
il dominio punta al dashboard. Serve una ingress rule **prima** del catch-all:

```yaml
ingress:
  # /quick e /quick/* -> API (pagina mobile). Deve stare PRIMA della regola generica.
  - hostname: finance.rikyru.ovh
    path: ^/quick
    service: http://finance_api:8000

  # tutto il resto -> dashboard Streamlit
  - hostname: finance.rikyru.ovh
    service: http://finance_app:8501

  - service: http_status:404
```

Se `cloudflared` gira in un container sulla stessa rete Docker, i nomi
`finance_api` / `finance_app` si risolvono da soli; altrimenti usa
`http://localhost:8502` e `http://localhost:8501`.

Dopo la modifica: `docker restart cloudflared` (o riavvia il servizio) e
`docker compose up -d --build` per l'app.

**Autenticazione**: con Cloudflare Access davanti al dominio, la pagina rapida
eredita la stessa sessione del dashboard e non serve nessun token — la scrittura
è protetta dal login. Se un giorno togli Access, l'endpoint `POST
/quick/api/transaction` resta aperto a chiunque conosca l'URL: in quel caso va
aggiunto un token prima di esporlo.
