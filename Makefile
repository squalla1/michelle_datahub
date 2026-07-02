.PHONY: install init ingest serve schedule run refresh test

install:
	pip install -e ".[dev]"

init:
	datahub init-db

ingest:
	datahub ingest

serve:
	datahub serve

schedule:
	datahub schedule

# Fetch all P1 news sources once (smoke test of the live pipeline)
run:
	datahub run --module news --priority P1 --limit 5

# Fetch ALL enabled sources once (manual twin of the scheduled 2h refresh)
refresh:
	datahub refresh

test:
	pytest -q
