.PHONY: bootstrap test test-integration run proto hooks

bootstrap: proto hooks
	uv pip install -e ".[dev]"

proto:
	python -m grpc_tools.protoc -I proto \
		--python_out=src/contoso_payments/_proto \
		proto/settlement.proto

hooks:
	cp scripts/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit

test:
	pytest tests/unit -q

test-integration:
	pytest tests/integration -q

run:
	uvicorn contoso_payments.app:app --reload --port 8123
