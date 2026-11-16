# Princeton On Time: common tasks (Python 3.12 with requirements.txt installed)
PY ?= python

sample:        ## run the whole pipeline on the shipped three-day sample (about 1 minute)
	$(PY) run_all.py

test:          ## run the tests (about 1 to 2 minutes)
	$(PY) -m pytest -q

full:          ## rerun on the full log: make full DATA=/path/to/data
	POT_DATA=$(DATA) $(PY) run_all.py && cd results && shasum -a 256 -c MANIFEST.sha256

weekly:        ## weekly page only, into weekly/: make weekly DATA=/path/to/data SINCE=YYYY-MM-DD
	POT_DATA=$(DATA) POT_SINCE=$(SINCE) $(PY) run_all.py --weekly

report:        ## rebuild the report .docx (then open in Google Docs and export PDF)
	$(PY) report/build_doc.py report/report.md -o "report/Princeton On Time - Final Report.docx"

poster:        ## rebuild the poster .pptx (then open in Google Slides and export PDF)
	$(PY) poster/aspect.py && cd poster && npm install && node poster.js

.PHONY: sample test full weekly report poster
