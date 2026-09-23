# Synthetic demonstration notices

The five fictional Korean notices are defined in `backend/app/services/demos.py` so their source text, structured interpretation, evidence, critical-fact IDs, faithful translation, and comprehension questions remain versioned together.

They cover visa/residence procedures, tuition, scholarships, dormitories, and course registration. They are not policies of Sogang University or any other real institution. Researchers can add a `DemoNotice` entry following the existing pattern.

`images/` contains seven generated raster fixtures covering a clean printout, an angled photograph, a conditional table, mixed Korean/English terminology, two pages of one notice, and a QR code. Regenerate them with `python generate_image_demos.py`. Every page visibly says that it is synthetic and is not a real policy.
