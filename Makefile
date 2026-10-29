.PHONY: test test-browser lint run seed

test:
	python -m pytest -q

test-browser:
	python -m pytest -q tests/test_web_ui.py --run-browser

lint:
	python -m ruff check .

run:
	python scripts/run_web.py --reload

seed:
	python scripts/seed_demo.py
