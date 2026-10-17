# Research notebooks

## Primary notebook: 7,300-day experiment

[`thesis_7300day_notebook_organized_plain_text.ipynb`](thesis_7300day_notebook_organized_plain_text.ipynb) is the primary organized notebook associated with the thesis. It contains 114 cells in 10 numbered sections:

1. environment setup and source-data loading;
2. data validation and structural checks;
3. demand structure and seasonality exploration;
4. forecasting dataset and feature preparation;
5. forecasting experiments (including Seasonal Naïve, ETS and LightGBM for Normal);
6. inventory decision experiment — Normal;
7. Demand Disruption experiment;
8. Supply Disruption experiment;
9. Combined Disruption experiment; and
10. locked master results and forecast rechecks.

The notebook is preserved as a research record; its cells and saved outputs have not been rewritten as part of repository packaging. It is **not a clean-room reproducibility guarantee**. It references local Windows files under `D:\ISOMORPH\...`, depends on external simulation data, contains five empty placeholder cells, and contains three saved error cells in the Combined Disruption section (cells 93, 100, 103) alongside later passing assembly and inventory cells (104–106). The locked master table (cell 109) is hardcoded literals with no file reads, and its MASE values do not match any in-notebook calculation from the Combined file. Two cells run `!pip install` (matplotlib, LightGBM) at execution time. Review [the validation notes](../docs/reproducibility_and_validation.md) before relying on a saved result.

## Historical notebook

An earlier working copy is kept under [`archive/`](archive/README.md) for traceability. It should not be confused with the organized primary notebook.

## Running notebooks

Install the packages in the root `requirements.txt`, open the notebook in Jupyter, and adapt data paths only after placing the required source data in an explicitly configured local environment. Do not commit private, raw or generated daily simulation histories. A successful notebook open or cell execution is not equivalent to verification of every downstream result.
