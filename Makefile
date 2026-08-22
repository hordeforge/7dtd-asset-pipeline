.PHONY: check test

check:
	python3 -m compileall -q src tests
	bash -n scripts/bootstrap scripts/setup-unity

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
