CodeNova - generated test dataset
=================================
Generated 27 Aug 2026 at 10:44 by the Dataset Lab.

THIS IS FABRICATED DATA. Every GSTIN, company name, director, address, amount
and date in these files was made up by a random number generator seeded with
21. No real taxpayer information was used to produce it and none is
contained in it.

FILES
-----
companies.csv    119 rows. Upload this as the companies file.
invoices.csv     2035 rows. Upload this as the invoices file.
answer_key.csv   What each company was planted as. NOT an input - keep it out
                 of the console, it is for checking results afterwards.

WHAT WAS PLANTED
----------------
    12 companies  high risk    - 2 circular-trade rings, 2 invoice mills
     8 companies  grey zone    - 2 ambiguous loops, 1 borderline sellers
    11 companies  honest loops - 4 genuine two-way traders
    88 companies  ordinary trade

The band is what the company was BUILT as, not what the detector scored it.
Comparing the two is the point of the exercise.

TO USE
------
Detections -> Upload dataset -> companies.csv and invoices.csv -> Run detection.

Regenerating with seed 21 and the same settings produces these exact
files again.
