# Push This Project to GitLab

Run these commands in your terminal from the project directory (`~/fraud-detection`).

## 1. Initialize Git and commit (if not already done)

```bash
cd ~/fraud-detection

# Initialize repository
git init

# Stage all files (respects .gitignore)
git add -A
git status   # optional: verify what will be committed

# Initial commit
git commit -m "Initial commit: affiliate fraud detection system"
```

## 2. Create a GitLab repository

1. In GitLab: **New project** → **Create blank project**
2. Set project name (e.g. `fraud-detection`), visibility, and **do not** initialize with a README (you already have one)
3. Copy the project URL, e.g.:
   - HTTPS: `https://gitlab.com/your-username/fraud-detection.git`
   - SSH: `git@gitlab.com:your-username/fraud-detection.git`

## 3. Add GitLab as remote and push

```bash
# Replace with your actual GitLab project URL
git remote add origin https://gitlab.com/YOUR_USERNAME/fraud-detection.git

# Or with SSH:
# git remote add origin git@gitlab.com:YOUR_USERNAME/fraud-detection.git

# Push (first time)
git branch -M main
git push -u origin main
```

## Notes

- **`config.json`** is in `.gitignore` (it contains your API key). New clones should copy `config.example.json` to `config.json` and add their own API key.
- **`*.db`** and **`*.log`** are ignored; they are local/sensitive.
- **`data/*.csv`** and **`reports/*.csv`** are ignored to avoid committing customer data.
