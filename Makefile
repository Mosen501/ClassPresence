PYTHON ?= python3

.PHONY: install run test

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	streamlit run app.py

test:
	$(PYTHON) -m unittest discover -s tests

