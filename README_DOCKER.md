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
