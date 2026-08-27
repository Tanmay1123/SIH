CodeNova - Dataset Lab, every preset generated to disk
========================================================

Each subfolder is one of the Dataset Lab's presets, generated with the
exact seed and knob values the lab UI uses for that preset - regenerating
from the lab with the same preset reproduces these files exactly.

Every file is fabricated. No real GSTIN, company, or invoice appears
anywhere in this folder.

FOLDERS
-------
  balanced   Even spread             282 companies,  4936 invoices (high 12, medium 31, low 41, clean 198)
  quick      Quick demo              119 companies,  2035 invoices (high 12, medium 8, low 11, clean 88)
  haystack   Needle in a haystack    901 companies, 15368 invoices (high 9, medium 25, low 46, clean 821)
  no_loops   Fraud without loops     240 companies,  3920 invoices (high 6, medium 4, low 23, clean 207)
  grey       All grey zone           304 companies,  4843 invoices (high 0, medium 42, low 33, clean 229)

Each folder contains:
  companies.csv    upload this as the companies file
  invoices.csv     upload this as the invoices file
  answer_key.csv   what each company was planted as - NOT an upload file,
                   keep it out of the console, it is for checking results
  README.txt       the same note the lab's own zip download includes

TO USE
------
Detections -> Upload dataset -> pick companies.csv and invoices.csv from
one of these folders -> Run detection.

Generated 27 Aug 2026 at 10:44 directly from fraud_engine.dataset_lab - the
same generator the Dataset Lab page in the app calls.
