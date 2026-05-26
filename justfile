set dotenv-load

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
@update:
    uv sync --upgrade

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
    ENVIRONMENT=test uv run pytest -n auto --dist loadscope --exitfirst --cov=. --cov-report html:htmlcov --cov-report term:skip-covered --cov-fail-under 100 {{ args }}

# Run linter / pre-commit hooks
[group('utility')]
lint:
    uvx pre-commit run --all-files


##########################################################################
# Codeberg
##########################################################################

# List issues (state: open|closed|all)
[group('codeberg')]
issues state="open":
    ./bin/codeberg list {{ state }}

# Show issue details
[group('codeberg')]
issue number:
    ./bin/codeberg show {{ number }}

# Add comment to issue
[group('codeberg')]
issue-comment number text:
    ./bin/codeberg comment {{ number }} "{{ text }}"

# Mark a checkbox step as done in issue body
[group('codeberg')]
issue-check number step:
    ./bin/codeberg check {{ number }} "{{ step }}"

# Close issue
[group('codeberg')]
issue-close number:
    ./bin/codeberg close {{ number }}

# Reopen issue
[group('codeberg')]
issue-reopen number:
    ./bin/codeberg reopen {{ number }}

# Add labels to issue (space-separated)
[group('codeberg')]
issue-label number *labels:
    ./bin/codeberg label {{ number }} {{ labels }}

# Create new issue
[group('codeberg')]
issue-create title body="":
    ./bin/codeberg create "{{ title }}" "{{ body }}"
