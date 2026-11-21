#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv is not installed. Install it from https://docs.astral.sh/uv/"
command -v psql >/dev/null 2>&1 || fail "PostgreSQL client tools are not installed."
pg_isready -q || fail "PostgreSQL is not running. Start it and try again."

database_exists() {
    psql -X -At -d postgres -c "select 1 from pg_database where datname = '$1'" | grep -q 1
}

database_exists harborstone || fail "The harborstone database is missing. Run: createdb harborstone && psql -d harborstone -f ../source_data.sql"

if ! database_exists harborstone_recon; then
    printf 'Creating the harborstone_recon database...\n'
    createdb harborstone_recon
fi

if [[ ! -f .env ]]; then
    [[ -f .env.example ]] || fail "Missing both .env and .env.example."
    printf 'Creating .env from .env.example...\n'
    cp .env.example .env
fi

# The AI features need an OpenAI key. Ask once, when there is none and someone is at the terminal.
if ! grep -qE '^OPENAI_API_KEY=.+' .env && [[ -t 0 ]]; then
    printf 'No OpenAI key is set, so the AI features are off.\n'
    read -r -s -p 'Paste an OpenAI API key to turn them on, or press Enter to skip: ' key
    printf '\n'
    if [[ -n "$key" ]]; then
        # Replace a commented or empty line if there is one; otherwise add the key at the end.
        if grep -qE '^#? ?OPENAI_API_KEY=' .env; then
            sed -i.bak -E "s|^#? ?OPENAI_API_KEY=.*|OPENAI_API_KEY=${key}|" .env && rm -f .env.bak
        else
            printf 'OPENAI_API_KEY=%s\n' "$key" >> .env
        fi
        printf 'Saved to backend/.env. It stays on this machine; git ignores that file.\n'
    fi
fi

printf 'Syncing Python environment...\n'
uv sync

printf 'Starting API at http://localhost:8000/docs\n'
exec uv run uvicorn app.server:app --reload
