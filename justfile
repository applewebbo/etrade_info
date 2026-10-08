set dotenv-load

github_repo := "applewebbo/etrade_info"

default:
    @just --list


##########################################################################
# Setup
##########################################################################

# Sync virtualenv
[group('setup')]
@install:
    uv sync

# Update all dependencies
[group('setup')]
@update: update-assets
    uv sync --upgrade

# Re-download vendored CSS/JS libraries (htmx, Alpine.js, Blades CSS, Inter font)
[group('setup')]
update-assets:
    curl -fsSL https://cdn.jsdelivr.net/npm/htmx.org/dist/htmx.min.js -o static/htmx.min.js
    curl -fsSL https://cdn.jsdelivr.net/npm/alpinejs/dist/cdn.min.js -o static/alpine.min.js
    curl -fsSL https://cdn.jsdelivr.net/npm/@anyblades/blades@3/css/blades.min.css -o static/blades.min.css
    curl -fsSL https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.colors.min.css -o static/pico.colors.min.css
    curl -fsSL https://cdn.jsdelivr.net/npm/@fontsource/inter@5/files/inter-latin-400-normal.woff2 -o static/fonts/inter-400.woff2
    curl -fsSL https://cdn.jsdelivr.net/npm/@fontsource/inter@5/files/inter-latin-600-normal.woff2 -o static/fonts/inter-600.woff2
    curl -fsSL https://cdn.jsdelivr.net/npm/@fontsource/inter@5/files/inter-latin-700-normal.woff2 -o static/fonts/inter-700.woff2
    echo "✓ Librerie statiche (htmx, Alpine.js, Blades CSS, Inter) aggiornate in static/"

# Rebuild lock file
[group('setup')]
@lock:
    uv lock --upgrade

# Remove temp files and venv
[group('setup')]
clean:
    rm -rf .venv .pytest_cache .ruff_cache .coverage htmlcov
    find . -type d -name "__pycache__" -exec rm -r {} +

# Recreate venv from scratch
[group('setup')]
fresh: clean install


##########################################################################
# Development
##########################################################################

# Run the local development server
[group('development')]
@run:
    uv run python app.py runserver

# Run database migrations
[group('development')]
@migrate:
    uv run python app.py migrate --run-syncdb


##########################################################################
# Utility
##########################################################################

# Run tests
[group('utility')]
test *args:
    ENVIRONMENT=test uv run pytest -s -x {{ args }}

# Run fast tests
[group('utility')]
ftest *args:
    ENVIRONMENT=test uv run pytest --exitfirst {{ args }}

# Run tests with coverage (must reach 100%)
[group('utility')]
cov *args:
    ENVIRONMENT=test uv run pytest --exitfirst --cov=. --cov-report html:htmlcov --cov-report term:skip-covered --cov-fail-under 100 {{ args }}

# Run linter / pre-commit hooks
[group('utility')]
lint:
    uvx pre-commit run --all-files


##########################################################################
# GitHub
##########################################################################

# List issues (state: open|closed|all)
[group('github')]
issues state="open":
    gh issue list -R {{ github_repo }} --state {{ state }}

# Show issue details
[group('github')]
issue number:
    gh issue view {{ number }} -R {{ github_repo }} --comments

# Add comment to issue
[group('github')]
issue-comment number text:
    gh issue comment {{ number }} -R {{ github_repo }} --body {{ quote(text) }}

# Close issue
[group('github')]
issue-close number:
    gh issue close {{ number }} -R {{ github_repo }}

# Reopen issue
[group('github')]
issue-reopen number:
    gh issue reopen {{ number }} -R {{ github_repo }}

# Add labels to issue (space-separated, labels must already exist)
[group('github')]
issue-label number *labels:
    #!/usr/bin/env bash
    set -euo pipefail
    for label in {{ labels }}; do
        gh issue edit {{ number }} -R {{ github_repo }} --add-label "$label"
        echo "✓ Label '$label' added to issue #{{ number }}"
    done

# Create new issue
[group('github')]
issue-create title body="":
    gh issue create -R {{ github_repo }} --title {{ quote(title) }} --body {{ quote(body) }}


##########################################################################
# Distribution
##########################################################################

# Build minimal distribution zip for end users
[group('distribution')]
dist:
    #!/usr/bin/env bash
    set -e
    ROOT="$(pwd)"
    rm -rf "dist/Etrade Portfolio" "dist/Etrade Portfolio.zip"
    mkdir -p "dist/Etrade Portfolio"
    cp start.command uninstall.command \
       app.py prices.py tax_engine.py xlsx_parser.py \
       bdi_rates.py ivafe_engine.py \
       pyproject.toml uv.lock ISTRUZIONI.txt \
       "dist/Etrade Portfolio/"
    cp -r templates static migrations "dist/Etrade Portfolio/"
    cd "dist"
    zip -r "Etrade Portfolio.zip" "Etrade Portfolio" -x "*/__pycache__/*" -x "*/.DS_Store"
    rm -rf "Etrade Portfolio"
    cd "$ROOT"
    echo "✓ dist/Etrade Portfolio.zip pronto per la distribuzione"
