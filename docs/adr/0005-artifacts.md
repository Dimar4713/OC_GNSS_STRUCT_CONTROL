# ADR-0005: Parquet + JSON manifest are canonical run artifacts

Status: accepted.

Decision: persist dense tabular results as Parquet, portable inspection copies as CSV, identity/provenance as JSON manifest/summary and human reports as Markdown/HTML.

Rationale: this combination supports reproducibility, analytics and long-term engineering audit without binding the domain to a database.

Consequence: scenario/config/code/force-model/seed identity travels with every run directory.
