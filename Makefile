.PHONY: test run seed

test:
	python -m pytest -q

run:
	python -m uvicorn backend.app.main:app --reload

seed:
	python scripts/seed_demo.py
