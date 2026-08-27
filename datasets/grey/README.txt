CodeNova - generated test dataset
=================================
Generated 27 Aug 2026 at 10:44 by the Dataset Lab.

THIS IS FABRICATED DATA. Every GSTIN, company name, director, address, amount
and date in these files was made up by a random number generator seeded with
88. No real taxpayer information was used to produce it and none is
contained in it.

FILES
-----
companies.csv    304 rows. Upload this as the companies file.
invoices.csv     4843 rows. Upload this as the invoices file.
answer_key.csv   What each company was planted as. NOT an input - keep it out
                 of the console, it is for checking results afterwards.

WHAT WAS PLANTED
----------------
     0 companies  high risk    - 0 circular-trade rings, 0 invoice mills
    42 companies  grey zone    - 8 ambiguous loops, 6 borderline sellers
    33 companies  honest loops - 12 genuine two-way traders
   229 companies  ordinary trade

The band is what the company was BUILT as, not what the detector scored it.
Comparing the two is the point of the exercise.

TO USE
------
Detections -> Upload dataset -> companies.csv and invoices.csv -> Run detection.

Regenerating with seed 88 and the same settings produces these exact
files again.
