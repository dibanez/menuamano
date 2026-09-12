.PHONY: up down demo test test-local migrate shell logs

up:            ## Build and start the local stack on http://localhost:8010
	docker compose up --build -d

down:
	docker compose down

migrate:
	docker compose exec web python manage.py migrate

demo:          ## Load (or rebuild) the demo household
	docker compose exec web python manage.py load_demo --reset

test:          ## Run the test suite inside the container (no paid API calls)
	docker compose run --rm web pytest

test-local:    ## Run tests from a local virtualenv against the compose database (port 5433)
	.venv/bin/python -m pytest

shell:
	docker compose exec web python manage.py shell

logs:
	docker compose logs -f web
